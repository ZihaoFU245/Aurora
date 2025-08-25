import sys
from pathlib import Path
from typing import List, Dict, Any, Union, Literal, Optional

# Add project root to path to allow imports from other directories
project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from core.engine import Engine
from CurrentTimeTools.Tools import getCurrentTime
from WebSearchTools import ddg_html_search, ddg_html_search_enrich, visit_website, crawl_website
from WriteFileTools import create_file, write_file, replace_in_file, read_file
from EmailTools import getAll # Use the old MCP server tools
#from MCPEmailTools import its_friday_tools
import json, uuid, datetime

app = FastAPI()

# --- Pydantic Models ---
# Base model for message content
class MessageContent(BaseModel):
    content: str
    type: str

# Pydantic models for each message type to handle serialization
class HumanMessageModel(MessageContent):
    type: Literal["human"] = "human"

class AIMessageModel(MessageContent):
    type: Literal["ai"] = "ai"

class ToolMessageModel(MessageContent):
    type: Literal["tool"] = "tool"
    tool_call_id: str

class SystemMessageModel(MessageContent):
    type: Literal["system"] = "system"

# A union type for deserializing messages
MessageModel = Union[HumanMessageModel, AIMessageModel, ToolMessageModel, SystemMessageModel]

class ChatRequest(BaseModel):
    text: str
    history: List[Dict[str, Any]] = []  # kept for backward compatibility (frontend will be simplified)
    chat_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    history_delta: List[Dict[str, Any]]
    chat_id: str

class NewChatRequest(BaseModel):
    title: Optional[str] = None

class TruncateRequest(BaseModel):
    keep: int  # number of messages to keep (truncate from keep onwards)

# --- Engine Initialization ---
def get_engine():
    tools = [
        getCurrentTime,
        ddg_html_search,
        ddg_html_search_enrich,
        visit_website,
        crawl_website,
        create_file,
        write_file,
        replace_in_file,
        read_file,
    ]
    tools += getAll()
    return Engine(tools=tools)

engine = get_engine()

# --- Static Files and Templates ---
# Use absolute paths to be safe
web_dir = Path(__file__).parent
app.mount("/static", StaticFiles(directory=web_dir / "static"), name="static")
templates = Jinja2Templates(directory=web_dir / "templates")

# --- Chat Persistence ---
CHATS_DIR = web_dir / "chats"
CHATS_DIR.mkdir(exist_ok=True)

CHAT_FILE_SUFFIX = ".json"


def _now_iso():
    return datetime.datetime.utcnow().isoformat() + "Z"


def _chat_path(chat_id: str) -> Path:
    return CHATS_DIR / f"{chat_id}{CHAT_FILE_SUFFIX}"


def _load_chat(chat_id: str) -> Dict[str, Any]:
    path = _chat_path(chat_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chat not found")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_chat(chat: Dict[str, Any]):
    chat_id = chat["id"]
    path = _chat_path(chat_id)
    chat["updated_at"] = _now_iso()
    with path.open("w", encoding="utf-8") as f:
        json.dump(chat, f, ensure_ascii=False, indent=2)


def _list_chats() -> List[Dict[str, Any]]:
    items = []
    for file in CHATS_DIR.glob(f"*{CHAT_FILE_SUFFIX}"):
        try:
            with file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            items.append({
                "id": data.get("id"),
                "title": data.get("title") or data.get("id"),
                "updated_at": data.get("updated_at"),
                "created_at": data.get("created_at"),
                "message_count": len(data.get("messages", [])),
            })
        except Exception:
            continue
    items.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return items


def _last_ai_text(messages: List[AnyMessage]) -> str:
    for m in reversed(messages or []):
        if isinstance(m, AIMessage):
            return str(m.content)
    return ""

def deserialize_history(history_data: List[Dict[str, Any]]) -> List[AnyMessage]:
    messages = []
    for msg_data in history_data:
        msg_type = msg_data.get("type")
        content = msg_data.get("content", "")
        if msg_type == "human":
            messages.append(HumanMessage(content=content))
        elif msg_type == "ai":
            messages.append(AIMessage(content=content))
        # extend for other types if needed
    return messages

def serialize_history(history: List[AnyMessage]) -> List[Dict[str, Any]]:
    serialized = []
    for msg in history:
        try:
            serialized.append(msg.dict())
        except Exception:
            serialized.append({"type": getattr(msg, "type", msg.__class__.__name__.lower()), "content": getattr(msg, "content", "")})
    return serialized


# --- API Endpoints ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

# DevTools/Chrome 探测路由，避免日志刷 404
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def _devtools_probe():
    return JSONResponse(content={"status": "ok"})

# Chat CRUD
@app.get("/chats")
async def list_chats():
    return _list_chats()

@app.post("/chats")
async def new_chat(req: NewChatRequest):
    chat_id = uuid.uuid4().hex[:12]
    chat = {
        "id": chat_id,
        "title": req.title or "New Chat",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "messages": []
    }
    _save_chat(chat)
    return {"id": chat_id}

@app.get("/chats/{chat_id}")
async def get_chat(chat_id: str):
    chat = _load_chat(chat_id)
    return {"id": chat["id"], "title": chat.get("title"), "messages": chat.get("messages", [])}

@app.post("/chats/{chat_id}/truncate")
async def truncate_chat(chat_id: str, req: TruncateRequest):
    chat = _load_chat(chat_id)
    keep = max(0, min(req.keep, len(chat.get("messages", []))))
    chat["messages"] = chat.get("messages", [])[:keep]
    _save_chat(chat)
    return {"id": chat_id, "messages": chat["messages"]}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # Determine chat
    if request.chat_id:
        try:
            existing = _load_chat(request.chat_id)
            history = deserialize_history(existing.get("messages", []))
            chat_id = request.chat_id
        except HTTPException:
            # treat as new if not found
            history = []
            chat_id = uuid.uuid4().hex[:12]
    else:
        chat_id = uuid.uuid4().hex[:12]
        history = []

    history_len_before = len(history)
    result = engine.run(request.text, history=history)
    updated_history = result.get("messages", [])
    response_text = _last_ai_text(updated_history)
    history_delta_msgs = updated_history[history_len_before:]

    # Persist chat
    serialized_full = serialize_history(updated_history)
    # Derive title from first human message if not set
    first_human = next((m for m in serialized_full if m.get("type") == "human"), None)
    title = existing.get("title") if request.chat_id and 'existing' in locals() else None
    if not title and first_human:
        title = first_human.get("content", "New Chat").strip().splitlines()[0][:40]
    chat_record = {
        "id": chat_id,
        "title": title or "New Chat",
        "created_at": existing.get("created_at") if request.chat_id and 'existing' in locals() else _now_iso(),
        "updated_at": _now_iso(),
        "messages": serialized_full,
    }
    _save_chat(chat_record)

    return ChatResponse(
        response=response_text,
        history_delta=serialize_history(history_delta_msgs),
        chat_id=chat_id,
    )

if __name__ == "__main__":
    import uvicorn
    # Run from the project root: python -m Web.main
    uvicorn.run("Web.main:app", host="0.0.0.0", port=8000, reload=True)

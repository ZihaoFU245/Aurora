# A multi-node agent continued on "its-friday" project.

> Agent application that enable easy plugin with more tools.

Aurora combines LangChain, LangGraph, and OpenRouter to drive large models, blending conversational abilities with tool usage. It supports both a CLI and a Web UI, and includes built-in tools for web search/scraping, time, file writing, and Gmail (OAuth). The project also provides structured trace logging.

- Language/runtime: Python >= 3.13
- Core dependencies: langchain, langgraph, langchain-openai (used via OpenRouter), fastapi, aiohttp, google-api-python-client, bs4, python-dotenv
- Interfaces:
  - CLI: interactive command-line agent (`python -m CLI.main`)
  - Web: FastAPI + Jinja (`python -m Web.main` or `uvicorn Web.main:app`)

## Features

- Multi-node agent graph (LangGraph):
  - router: decides whether to answer directly, call a tool, plan, or send to the critic
  - planner: produces an action plan and steps
  - executor: executes tool calls (DuckDuckGo search/enrichment, website visit/crawl, time, file write, Gmail tools, etc.)
  - critic: final review and answer composition
- Toolset (LangChain Tools):
  - Time: `getCurrentTime`
  - Web search & browsing: `ddg_html_search`, `ddg_html_search_enrich`, `visit_website`, `visit_websites_batch`, `crawl_website`
  - File operations: `create_file`, `write_file`, `replace_in_file`, `read_file`, `pwd`, `ls`, `cp`
  - Gmail (OAuth): `add_account`, `list_email_accounts`, `email_fetch_unread`, `email_send`, draft APIs, etc.
- Observability: Trace log (default `aurora_trace.log`)
- Persistence (Web): conversation histories stored in `Web/chats/*.json`

## Quick start

1) Install dependencies (recommended: `uv` tool)

 ```powershell
uv sync           # installs dependencies from pyproject.toml / uv.lock
```

2) Configure environment variables

Copy `.env.sample` to `.env` and set the required values:

- OpenRouter (required):
  - `OPENROUTER_API_KEY` — your OpenRouter API key
  - `OPENAI_BASE_URL` — e.g. `https://openrouter.ai/api/v1`
- Models (required):
  - `ROUTER_MODEL`, `PLANNER_MODEL`, `EXECUTOR_MODEL`, `CRITIC_MODEL`
    (these are model identifiers used via OpenRouter or another compatible gateway)
- Optional:
  - Temperature controls: `ROUTER_TEMP`, `PLANNER_TEMP`, `EXECUTOR_TEMP`, `CRITIC_TEMP` (default `0.0`)
  - Prompts: `SYSTEM_PROMPT`, `ROUTER_SYSTEM_PROMPT`, `PLANNER_SYSTEM_PROMPT`, `EXECUTOR_SYSTEM_PROMPT`, `CRITIC_SYSTEM_PROMPT`
  - Router behavior switches: `ROUTER_FORCE_PLANNER`, `ROUTER_FORCE_CRITIC` (set to truthy values like `1`, `true`, `yes`)
  - Trace log file: `TRACE_LOG_FILE` (default `aurora_trace.log`)
  - Gmail-related settings (if using Gmail tools): `GOOGLE_CREDENTIALS_PATH`, `TOKEN_PATH`, `EMAIL_ACCOUNTS_PATH`

  Note: the model initialization will validate required environment variables and exit with the missing key name if any are absent.

  3) Run

- CLI mode:

  ```powershell
  python -m CLI.main
  ```

  Example: "Search for three articles about LangGraph and summarize them." The agent will call search/visit tools when needed.

- Web mode:

  ```powershell
  # Option A
  python -m Web.main
  # Option B (using uvicorn)
  uvicorn Web.main:app --host 0.0.0.0 --port 8000 --reload
  ```

  Open <http://localhost:8000>. Conversation history is saved under `Web/chats/*.json`.

## Environment variables

  Required:

- `OPENROUTER_API_KEY` — OpenRouter API key
- `OPENAI_BASE_URL` — e.g. `https://openrouter.ai/api/v1`
- `ROUTER_MODEL`, `PLANNER_MODEL`, `EXECUTOR_MODEL`, `CRITIC_MODEL` — model names/IDs

  Optional:

- `ROUTER_TEMP`, `PLANNER_TEMP`, `EXECUTOR_TEMP`, `CRITIC_TEMP` — float temperatures (default `0.0`)
- Prompt variables: `SYSTEM_PROMPT`, `ROUTER_SYSTEM_PROMPT`, `PLANNER_SYSTEM_PROMPT`, `EXECUTOR_SYSTEM_PROMPT`, `CRITIC_SYSTEM_PROMPT`
- `TRACE_LOG_FILE` — trace log file path (default `aurora_trace.log`)
- Router overrides: `ROUTER_FORCE_PLANNER`, `ROUTER_FORCE_CRITIC`
- Gmail: `GOOGLE_CREDENTIALS_PATH`, `TOKEN_PATH`, `EMAIL_ACCOUNTS_PATH`

## Gmail (OAuth) configuration

  1. In Google Cloud Console create an OAuth client (Desktop app) and download the client credentials JSON (e.g. `client_secrets.json`).
  2. Set `GOOGLE_CREDENTIALS_PATH` to the credentials file path and `TOKEN_PATH` to a directory where tokens will be stored. The first authorization will open a browser for login.
  3. You can register and use accounts via CLI or Web tools, for example:

  `add_account(provider="gmail", name="me", email="you@example.com")`

  Token files are saved using the convention `{account_name}_gmail.json` (for example `me_gmail.json`).

## Tools and contracts

  All tools are exposed as LangChain Tools and aim for stable, readable return structures.

- Time: `getCurrentTime()` -> str
- Web:
  - `ddg_html_search(query, max_results=10, country="us-en", site=None)` -> List[dict]
  - `ddg_html_search_enrich(query, max_results=10, country="us-en", enrich_limit=5, site=None)` -> List[dict]
  - `visit_website(url, max_chars=8000, timeout_sec=20)` -> dict
  - `visit_websites_batch(urls, max_chars=8000, timeout_sec=20, concurrency=10)` -> List[dict]
  - `crawl_website(start_url, max_pages=5, same_domain=True, max_depth=2, max_chars=2000, timeout_sec=20)` -> List[dict]
- Files: `create_file`, `write_file`, `replace_in_file`, `read_file`, `pwd`, `ls`, `cp`
- Gmail: add/list accounts, fetch/send emails, manage drafts, mark/read/delete messages

## Architecture overview (LangChain + LangGraph + OpenRouter)

- Model management: `core/models/LLM.py`
  - Uses langchain-openai's ChatOpenAI adapter with OpenRouter `base_url` to support multiple providers.
  - Models are separated by role (router/planner/executor/critic); temperature and prompts are independently configurable.

- Nodes and edges: `core/nodes.py`, `core/edges.py`
  - Nodes produce messages or tool calls using role-specific system prompts + LLM invocation.
  - Executor safely parses and runs tool calls synchronously to avoid event loop nesting issues.
  - Edges use a StateGraph(MessagesState); `router_decision` determines flow (executor/planner/critic/END).

- Engine: `core/engine.py`
  - Assembles LLM, tools, and graph, and provides `Engine.run(user_input, history)`.
  - Recursive depth protection: if LangGraph hits the default 25-layer limit, the engine will prompt whether to continue/pause/stop and logs the event.

- Observability: `core/observability/tracing.py` — JSON-lines structured trace logs (default `aurora_trace.log`).

- Configuration: `core/Config.py` (reads `.env`).

## Development & extension

- Add new tools by following the `@tool` implementations in `CurrentTimeTools`, `WebSearchTools`, `WriteFileTools`, or `EmailTools`. Export tools to the CLI/Web tool list to make them available to the agent.
- Customize prompts, models, and temperatures via `.env` without code changes.
- For debugging, use `ROUTER_FORCE_PLANNER` / `ROUTER_FORCE_CRITIC` to force routing behavior.

## Troubleshooting

- Application exits with "Missing required API config": verify `.env` contains `OPENROUTER_API_KEY`, `OPENAI_BASE_URL`, and the four model names.
- Event loop errors from tool calls: the executor attempts to run calls synchronously; if you still see errors, attach `aurora_trace.log` when reporting.
- Web search timeouts or network errors: retry or increase `timeout_sec`. For certificate issues, check system/root certificates and network settings.
- Gmail OAuth issues: first run opens a browser for authorization. If `GOOGLE_CREDENTIALS_PATH` is incorrect, a FileNotFoundError is raised.
- Recursive depth prompts appear when conversations or tool chains get long — follow the prompt to continue or stop.


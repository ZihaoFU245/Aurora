"""
Write file tools for agents
"""
from langchain_core.tools import tool
from pathlib import Path
import re
from typing import Dict, Optional


def _ensure_parent(path: Path):
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


@tool
def create_file(path: str, content: str = "", overwrite: bool = False, encoding: str = "utf-8") -> Dict:
    """Create a text file.

    Inputs:
    - path: file path to create (relative or absolute)
    - content: initial text content (default empty)
    - overwrite: if False and file exists, fail; if True, overwrite (default False)
    - encoding: text encoding (default utf-8)
    Returns: dict {ok, path, bytes, existed}
    """
    p = Path(path)
    existed = p.exists()
    if existed and not overwrite:
        return {"ok": False, "error": "File exists", "path": str(p), "existed": True}
    _ensure_parent(p)
    data = content.encode(encoding)
    p.write_bytes(data)
    return {"ok": True, "path": str(p), "bytes": len(data), "existed": existed}


@tool
def write_file(path: str, content: str, mode: str = "w", encoding: str = "utf-8") -> Dict:
    """Write text to a file.

    Inputs:
    - path: file path (relative or absolute)
    - content: text to write
    - mode: 'w' to overwrite, 'a' to append (default 'w')
    - encoding: text encoding (default utf-8)
    Returns: dict {ok, path, bytes, mode}
    """
    if mode not in ("w", "a"):
        return {"ok": False, "error": "mode must be 'w' or 'a'", "path": path}
    p = Path(path)
    _ensure_parent(p)
    data = content.encode(encoding)
    if mode == "w":
        p.write_bytes(data)
    else:
        # append in text mode to respect encoding and newlines
        with p.open("a", encoding=encoding, newline="") as f:
            f.write(content)
    return {"ok": True, "path": str(p), "bytes": len(data), "mode": mode}


@tool
def read_file(path: str, encoding: str = "utf-8", max_bytes: Optional[int] = None) -> Dict:
    """Read text from a file.

    Inputs:
    - path: file path to read
    - encoding: text encoding (default utf-8)
    - max_bytes: if provided, limit bytes read; returns truncated=True if file exceeds this size
    Returns: dict {ok, path, bytes, content, truncated, size}
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "file not found", "path": str(p)}

    size = p.stat().st_size
    truncated = False

    if max_bytes is None:
        # Full read as text
        text = p.read_text(encoding=encoding)
        return {"ok": True, "path": str(p), "bytes": size, "content": text, "truncated": False, "size": size}

    if max_bytes < 0:
        return {"ok": False, "error": "max_bytes must be non-negative", "path": str(p)}

    # Partial read in binary then decode safely
    with p.open("rb") as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        truncated = True
        data = data[:max_bytes]
    text = data.decode(encoding, errors="replace")
    return {"ok": True, "path": str(p), "bytes": len(data), "content": text, "truncated": truncated, "size": size}


@tool
def replace_in_file(
    path: str,
    pattern: str,
    replacement: str,
    is_regex: bool = False,
    count: int = 0,
    encoding: str = "utf-8",
) -> Dict:
    """Replace text in a file and save the result.

    Inputs:
    - path: file path to modify
    - pattern: text or regex pattern to replace
    - replacement: replacement text
    - is_regex: treat pattern as regex if True (default False)
    - count: maximum replacements per file (0 means replace all)
    - encoding: text encoding (default utf-8)
    Returns: dict {ok, path, replacements}
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "file not found", "path": str(p)}
    text = p.read_text(encoding=encoding)
    if is_regex:
        new_text, n = re.subn(pattern, replacement, text, count=count if count > 0 else 0, flags=re.MULTILINE)
    else:
        if count > 0:
            new_text = text.replace(pattern, replacement, count)
            # Python's str.replace doesn't return count when limited; compute diff
            n = text.count(pattern) if count == 0 else min(count, text.count(pattern))
        else:
            n = text.count(pattern)
            new_text = text.replace(pattern, replacement)
    if new_text != text:
        p.write_text(new_text, encoding=encoding)
    return {"ok": True, "path": str(p), "replacements": n}

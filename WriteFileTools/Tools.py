"""
Write file tools for agents
"""
from langchain_core.tools import tool
from pathlib import Path
import shutil
import os
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


@tool
def pwd() -> Dict:
    """Return the current working directory.

    Returns: dict {ok, cwd}
    """
    return {"ok": True, "cwd": str(Path.cwd())}


@tool
def ls(path: str = ".", recursive: bool = False, include_hidden: bool = False, max_entries: int = 500) -> Dict:
    """List directory entries.

    Inputs:
    - path: directory path to list (default '.')
    - recursive: if True, walk directory tree (default False)
    - include_hidden: include entries starting with '.' (default False)
    - max_entries: cap number of entries returned to avoid huge outputs (default 500)
    Returns: dict {ok, path, entries:[{name,type,size,mtime,path,rel_path}], truncated}
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "path not found", "path": str(p)}
    if not p.is_dir():
        # If it's a file, just return its info
        stat = p.stat()
        return {
            "ok": True,
            "path": str(p),
            "entries": [
                {
                    "name": p.name,
                    "type": "file",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "path": str(p.resolve()),
                    "rel_path": p.name,
                }
            ],
            "truncated": False,
        }

    entries = []
    truncated = False

    def add_entry(base: Path, entry: Path):
        nonlocal truncated
        if len(entries) >= max_entries:
            truncated = True
            return
        try:
            stat = entry.stat()
            entries.append(
                {
                    "name": entry.name,
                    "type": "dir" if entry.is_dir() else "file",
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                    "path": str(entry.resolve()),
                    "rel_path": str(entry.relative_to(base)),
                }
            )
        except OSError as e:
            entries.append(
                {
                    "name": entry.name,
                    "type": "error",
                    "error": str(e),
                    "path": str(entry),
                    "rel_path": str(entry.relative_to(base)) if entry.exists() else entry.name,
                }
            )

    base = p.resolve()
    if recursive:
        for root, dirs, files in os.walk(base):
            root_path = Path(root)
            # Combine dirs + files for ordering
            names = sorted(dirs) + sorted(files)
            for name in names:
                if not include_hidden and name.startswith('.'):
                    continue
                add_entry(base, root_path / name)
            if truncated:
                break
    else:
        for entry in sorted(p.iterdir(), key=lambda x: x.name):
            if not include_hidden and entry.name.startswith('.'):
                continue
            add_entry(base, entry)
            if truncated:
                break

    return {"ok": True, "path": str(p.resolve()), "entries": entries, "truncated": truncated}


@tool
def cp(src: str, dst: str, overwrite: bool = False) -> Dict:
    """Copy a file (no directory tree copy, no deletion).

    Inputs:
    - src: source file path
    - dst: destination file path (file or directory). If dst is an existing directory, copy inside it retaining filename.
    - overwrite: if False and destination file exists, fail (default False)
    Returns: dict {ok, src, dst, bytes}
    """
    src_path = Path(src)
    if not src_path.exists():
        return {"ok": False, "error": "source not found", "src": str(src_path)}
    if not src_path.is_file():
        return {"ok": False, "error": "only regular file copy supported", "src": str(src_path)}

    dst_path = Path(dst)
    if dst_path.is_dir():
        dst_path = dst_path / src_path.name
    if dst_path.exists() and not overwrite:
        return {"ok": False, "error": "destination exists", "dst": str(dst_path), "src": str(src_path)}
    _ensure_parent(dst_path)
    shutil.copyfile(src_path, dst_path)
    size = dst_path.stat().st_size
    return {"ok": True, "src": str(src_path.resolve()), "dst": str(dst_path.resolve()), "bytes": size}

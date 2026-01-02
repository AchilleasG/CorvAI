import os
from pathlib import Path
from typing import List

from orchestration.registry import register_function

# Predefined directory under project root for file-handling tool functions.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
FILES_DIR = BASE_DIR / "managed_files"
FILES_DIR.mkdir(exist_ok=True)


def _safe_path(file_name: str) -> Path:
    """
    Prevent path traversal by allowing only basename writes/reads within FILES_DIR.
    """
    name = os.path.basename(file_name)
    if not name:
        raise ValueError("file_name cannot be empty")
    if name.startswith("."):
        raise ValueError("file_name cannot start with a dot")
    return FILES_DIR / name


@register_function(
    manifest_id="file_handler.write_text",
    module="file_handler",
    name="file_handler.write_text",
    description="Write plain text content to a file in the managed_files directory.",
    params_schema={
        "type": "object",
        "properties": {
            "file_name": {"type": "string", "description": "Name of the file to write"},
            "content": {"type": "string", "description": "Text content to write"},
        },
        "required": ["file_name", "content"],
    },
    return_schema={"type": "object", "properties": {"path": {"type": "string"}}},
)
def write_text(file_name: str, content: str):
    path = _safe_path(file_name)
    path.write_text(content, encoding="utf-8")
    return {"path": str(path)}


@register_function(
    manifest_id="file_handler.list_files",
    module="file_handler",
    name="file_handler.list_files",
    description="List file names available in the managed_files directory.",
    params_schema={"type": "object", "properties": {}},
    return_schema={
        "type": "object",
        "properties": {"files": {"type": "array", "items": {"type": "string"}}},
    },
)
def list_files() -> dict:
    files: List[str] = []
    for entry in FILES_DIR.iterdir():
        if entry.is_file():
            files.append(entry.name)
    return {"files": sorted(files)}


@register_function(
    manifest_id="file_handler.read_file",
    module="file_handler",
    name="file_handler.read_file",
    description="Read text content from a file in the managed_files directory.",
    params_schema={
        "type": "object",
        "properties": {
            "file_name": {"type": "string", "description": "Name of the file to read"},
        },
        "required": ["file_name"],
    },
    return_schema={"type": "object", "properties": {"content": {"type": "string"}}},
)
def read_file(file_name: str):
    path = _safe_path(file_name)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"{file_name} not found in managed_files")
    return {"content": path.read_text(encoding="utf-8")}

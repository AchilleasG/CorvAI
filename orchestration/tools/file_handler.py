import hashlib
import json
from pathlib import Path
from typing import Optional

from django.core.files.base import ContentFile

from coding.models import ManagedFile
from orchestration.registry import register_function


def _tags(value) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
        raise ValueError("tags must be a list of strings")
    return list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))


def _payload(item: ManagedFile) -> dict:
    return {
        "id": str(item.id),
        "managed_file_id": str(item.id),
        "filename": item.filename,
        "content_type": item.content_type,
        "size": item.size,
        "checksum_sha256": item.checksum_sha256,
        "metadata": item.metadata,
        "tags": item.tags,
        "download_url": f"/api/files/{item.id}/content?download=true",
        "preview_url": f"/api/files/{item.id}/content",
        "created_at": item.created_at.isoformat(),
    }


def _get_file(file_id: str = "", file_name: str = "") -> ManagedFile:
    if file_id:
        try:
            return ManagedFile.objects.get(pk=file_id)
        except (ManagedFile.DoesNotExist, ValueError) as exc:
            raise FileNotFoundError(f"Managed file {file_id} was not found") from exc
    name = Path(file_name).name if file_name else ""
    if not name:
        raise ValueError("file_id or file_name is required")
    item = ManagedFile.objects.filter(filename=name).order_by("-created_at").first()
    if not item:
        raise FileNotFoundError(f"Managed file {name} was not found")
    return item


@register_function(
    manifest_id="file_handler.write_text",
    module="file_handler",
    name="file_handler.write_text",
    description="Create a UTF-8 text file (such as TXT, Markdown, CSV, JSON, or source code). Never use this to fabricate PDFs, images, Office documents, archives, audio, video, or other binary formats.",
    params_schema={"type": "object", "properties": {
        "file_name": {"type": "string", "description": "Filename including extension"},
        "content": {"type": "string", "description": "UTF-8 text content"},
        "content_type": {"type": "string", "default": "text/plain"},
        "metadata": {"type": "object", "default": {}},
        "tags": {"type": "array", "items": {"type": "string"}, "default": []},
    }, "required": ["file_name", "content"]},
    return_schema={"type": "object", "properties": {"managed_file_id": {"type": "string"}, "download_url": {"type": "string"}}},
)
def write_text(file_name: str, content: str, content_type: str = "text/plain", metadata: Optional[dict] = None, tags: Optional[list[str]] = None):
    name = Path(file_name).name
    if not name or name in {".", ".."} or name.startswith("."):
        raise ValueError("file_name must be a safe, visible filename")
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    normalized_type = (content_type or "text/plain").lower().split(";", 1)[0].strip()
    text_types = {"application/json", "application/xml", "application/javascript", "application/x-yaml"}
    binary_extensions = {
        ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".doc", ".docx", ".xls",
        ".xlsx", ".ppt", ".pptx", ".zip", ".gz", ".tar", ".mp3", ".wav", ".mp4", ".mov",
    }
    if Path(name).suffix.lower() in binary_extensions or not (
        normalized_type.startswith("text/") or normalized_type in text_types
    ):
        raise ValueError(
            "write_text only creates UTF-8 text files. Use coding/SSH tools to create binary "
            "artifacts, then fetch or upload the finished file."
        )
    data = content.encode("utf-8")
    item = ManagedFile(filename=name, content_type=content_type or "text/plain", size=len(data),
        checksum_sha256=hashlib.sha256(data).hexdigest(), metadata=metadata or {}, tags=_tags(tags))
    item.file.save(name, ContentFile(data), save=False)
    item.save()
    return _payload(item)


@register_function(
    manifest_id="file_handler.list_files", module="file_handler", name="file_handler.list_files",
    description="List and search persistent Corv files, including metadata, tags, and preview/download links.",
    params_schema={"type": "object", "properties": {
        "search": {"type": "string", "description": "Optional filename, tag, or metadata search"},
        "tag": {"type": "string", "description": "Optional exact tag filter"},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
    }},
    return_schema={"type": "object", "properties": {"files": {"type": "array", "items": {"type": "object"}}}},
)
def list_files(search: str = "", tag: str = "", limit: int = 50) -> dict:
    limit = max(1, min(int(limit), 100)); needle = search.strip().lower()
    items = []
    for item in ManagedFile.objects.all():
        if tag and tag not in item.tags:
            continue
        haystack = f"{item.filename} {' '.join(item.tags)} {json.dumps(item.metadata, default=str)}".lower()
        if needle and needle not in haystack:
            continue
        items.append(_payload(item))
        if len(items) >= limit:
            break
    return {"files": items, "count": len(items)}


@register_function(
    manifest_id="file_handler.read_file", module="file_handler", name="file_handler.read_file",
    description="Read UTF-8 text from a persistent Corv file by ID (preferred) or latest matching filename.",
    params_schema={"type": "object", "properties": {"file_id": {"type": "string"}, "file_name": {"type": "string"}, "max_chars": {"type": "integer", "minimum": 1, "maximum": 100000, "default": 20000}}},
    return_schema={"type": "object", "properties": {"content": {"type": "string"}, "file": {"type": "object"}}},
)
def read_file(file_id: str = "", file_name: str = "", max_chars: int = 20000):
    item = _get_file(file_id, file_name); max_chars = max(1, min(int(max_chars), 100000))
    try:
        content = item.file.read().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("This file is binary; use its preview or download URL instead") from exc
    return {"file": _payload(item), "content": content[:max_chars], "truncated": len(content) > max_chars}


@register_function(
    manifest_id="file_handler.update_file", module="file_handler", name="file_handler.update_file",
    description="Update a persistent Corv file's filename, content type, metadata, or tags.",
    params_schema={"type": "object", "properties": {"file_id": {"type": "string"}, "file_name": {"type": "string"}, "content_type": {"type": "string"}, "metadata": {"type": "object"}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["file_id"]},
    return_schema={"type": "object"},
)
def update_file(file_id: str, file_name: str = "", content_type: str = "", metadata: Optional[dict] = None, tags: Optional[list[str]] = None):
    item = _get_file(file_id)
    if file_name:
        name = Path(file_name).name
        if not name or name in {".", ".."}: raise ValueError("file_name is invalid")
        item.filename = name
    if content_type: item.content_type = content_type
    if metadata is not None:
        if not isinstance(metadata, dict): raise ValueError("metadata must be an object")
        item.metadata = metadata
    if tags is not None: item.tags = _tags(tags)
    item.save(); return _payload(item)


@register_function(
    manifest_id="file_handler.delete_file", module="file_handler", name="file_handler.delete_file",
    description="Permanently delete a persistent Corv file and its stored content.",
    params_schema={"type": "object", "properties": {"file_id": {"type": "string"}}, "required": ["file_id"]},
    return_schema={"type": "object", "properties": {"deleted": {"type": "string"}}},
)
def delete_file(file_id: str):
    item = _get_file(file_id); storage = item.file.storage; name = item.file.name; deleted_id = str(item.id)
    item.delete()
    if name: storage.delete(name)
    return {"deleted": deleted_id}

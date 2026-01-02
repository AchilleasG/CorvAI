from typing import Optional, List

from orchestration.registry import register_function
from orchestration.services import UserInfoService


@register_function(
    manifest_id="user_info.get_core",
    module="user_info",
    description="Get the core user profile text (always appended to prompt).",
    params_schema={
        "type": "object",
        "properties": {"user_id": {"type": "string", "description": "User id (optional; defaults to single user)"}},
    },
)
def get_core(user_id: Optional[str] = None):
    profile = UserInfoService.get_core_profile(user_id)
    return {"user_id": user_id or UserInfoService.DEFAULT_USER_ID, "core_text": profile.core_text if profile else ""}


@register_function(
    manifest_id="user_info.set_core",
    module="user_info",
    description="Overwrite the core user profile text.",
    params_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Text to store as core profile"},
            "user_id": {"type": "string", "description": "Optional user id"},
        },
        "required": ["content"],
    },
)
def set_core(content: str, user_id: Optional[str] = None):
    profile = UserInfoService.set_core_profile(content, user_id=user_id)
    return {"user_id": profile.user_id, "core_text": profile.core_text}


@register_function(
    manifest_id="user_info.append_core",
    module="user_info",
    description="Append text to the core user profile.",
    params_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Text to append"},
            "user_id": {"type": "string", "description": "Optional user id"},
            "separator": {"type": "string", "description": "Separator between existing and new content", "default": "\n"},
        },
        "required": ["content"],
    },
)
def append_core(content: str, user_id: Optional[str] = None, separator: str = "\n"):
    profile = UserInfoService.append_core_profile(content, user_id=user_id, separator=separator)
    return {"user_id": profile.user_id, "core_text": profile.core_text}


@register_function(
    manifest_id="user_info.delete_core",
    module="user_info",
    description="Delete the stored core user profile text.",
    params_schema={
        "type": "object",
        "properties": {"user_id": {"type": "string", "description": "Optional user id"}},
    },
)
def delete_core(user_id: Optional[str] = None):
    UserInfoService.delete_core_profile(user_id=user_id)
    return {"user_id": user_id or UserInfoService.DEFAULT_USER_ID, "deleted": True}


@register_function(
    manifest_id="user_info.add_note",
    module="user_info",
    description="Add circumstantial note (embeds for semantic search).",
    params_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Note text"},
            "user_id": {"type": "string", "description": "Optional user id"},
            "source": {"type": "string", "description": "Optional source tag"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional list of tags"},
            "canonicalize": {"type": "boolean", "description": "Normalize text for embedding", "default": True},
        },
        "required": ["content"],
    },
)
def add_note(
    content: str,
    user_id: Optional[str] = None,
    source: str = "",
    tags: Optional[List[str]] = None,
    canonicalize: bool = True,
):
    note = UserInfoService.add_note(
        content=content,
        user_id=user_id,
        source=source,
        tags=tags or [],
        canonicalize=canonicalize,
    )
    return {
        "id": str(note.id),
        "user_id": note.user_id,
        "content": note.content_raw,
        "source": note.source,
        "tags": note.tags,
    }


@register_function(
    manifest_id="user_info.search_notes",
    module="user_info",
    description="Semantic search across circumstantial notes.",
    params_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "user_id": {"type": "string", "description": "Optional user id"},
            "limit": {"type": "integer", "default": 5},
            "source": {"type": "string", "description": "Optional source filter"},
            "tag": {"type": "string", "description": "Optional tag filter"},
        },
        "required": ["query"],
    },
)
def search_notes(
    query: str,
    user_id: Optional[str] = None,
    limit: int = 5,
    source: Optional[str] = None,
    tag: Optional[str] = None,
):
    results = UserInfoService.search_notes(query, user_id=user_id, limit=limit, source=source, tag=tag)
    return {"results": results}


@register_function(
    manifest_id="user_info.update_note",
    module="user_info",
    description="Update a circumstantial note and refresh its embedding.",
    params_schema={
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "Note id"},
            "content": {"type": "string", "description": "Updated content"},
            "user_id": {"type": "string", "description": "Optional user id"},
            "source": {"type": "string", "description": "Optional source"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
            "canonicalize": {"type": "boolean", "description": "Normalize text before embedding", "default": True},
        },
        "required": ["note_id", "content"],
    },
)
def update_note(
    note_id: str,
    content: str,
    user_id: Optional[str] = None,
    source: Optional[str] = None,
    tags: Optional[List[str]] = None,
    canonicalize: bool = True,
):
    note = UserInfoService.update_note(
        note_id,
        content=content,
        user_id=user_id,
        source=source,
        tags=tags,
        canonicalize=canonicalize,
    )
    return {
        "id": str(note.id),
        "user_id": note.user_id,
        "content": note.content_raw,
        "source": note.source,
        "tags": note.tags,
    }


@register_function(
    manifest_id="user_info.delete_note",
    module="user_info",
    description="Soft delete a circumstantial note.",
    params_schema={
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "Note id"},
            "user_id": {"type": "string", "description": "Optional user id"},
        },
        "required": ["note_id"],
    },
)
def delete_note(note_id: str, user_id: Optional[str] = None):
    UserInfoService.delete_note(note_id, user_id=user_id)
    return {"note_id": note_id, "deleted": True}

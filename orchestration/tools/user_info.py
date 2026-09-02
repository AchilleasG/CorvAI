from typing import Optional, List

from orchestration.registry import register_function
from orchestration.services import KnowledgeBaseService, UserInfoService


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
    description="Add a permanent or timed generic note after semantically searching relevant knowledge first. Reuse established tags and store stable dates/birth years instead of relative or changing values.",
    params_schema={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "Note text. All temporal references must use exact calendar dates/times, never relative wording such as today, tomorrow, now, or in X days."},
            "user_id": {"type": "string", "description": "Optional user id"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional list of tags"},
            "canonicalize": {"type": "boolean", "description": "Normalize text for embedding", "default": True},
            "expires_at": {"type": "string", "description": "Optional ISO 8601 expiry date/time. Use for temporary facts; the note stops being recalled after this time and is safely cleaned up."},
        },
        "required": ["content"],
    },
)
def add_note(
    content: str,
    user_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    canonicalize: bool = True,
    expires_at: Optional[str] = None,
):
    note = UserInfoService.add_note(
        content=content,
        user_id=user_id,
        source="corv_action",
        tags=tags or [],
        canonicalize=canonicalize,
        expires_at=expires_at,
    )
    return {
        "id": str(note.id),
        "user_id": note.user_id,
        "content": note.content_raw,
        "source": note.source,
        "tags": note.tags,
        "expires_at": note.expires_at.isoformat() if note.expires_at else None,
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
    description="Update a generic note after semantically searching related knowledge first. Keep tags consistent and express facts in a time-stable form.",
    params_schema={
        "type": "object",
        "properties": {
            "note_id": {"type": "string", "description": "Note id"},
            "content": {"type": "string", "description": "Updated content. Rewrite every temporal reference as an exact date/time; never persist relative wording such as today, tomorrow, now, or in X days."},
            "user_id": {"type": "string", "description": "Optional user id"},
            "source": {"type": "string", "description": "Optional source"},
            "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
            "canonicalize": {"type": "boolean", "description": "Normalize text before embedding", "default": True},
            "expires_at": {"type": ["string", "null"], "description": "Optional ISO 8601 expiry. Pass null to make the note permanent; omit to leave unchanged."},
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
    expires_at=...,
):
    note = UserInfoService.update_note(
        note_id,
        content=content,
        user_id=user_id,
        source=source,
        tags=tags,
        canonicalize=canonicalize,
        expires_at=expires_at,
    )
    return {
        "id": str(note.id),
        "user_id": note.user_id,
        "content": note.content_raw,
        "source": note.source,
        "tags": note.tags,
        "expires_at": note.expires_at.isoformat() if note.expires_at else None,
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


def _location_data(latitude,longitude,extra=None): return {**(extra or {}),"latitude":latitude,"longitude":longitude}
def _person_data(relationship="",facts=None,extra=None): return {**(extra or {}),"relationship":relationship,"facts":facts or []}
def _entity_result(item): return KnowledgeBaseService.payload(item)

@register_function(manifest_id="user_info.create_location",module="user_info",description="Create a structured location with coordinates, description, and unified knowledge tags.",params_schema={"type":"object","properties":{"name":{"type":"string"},"latitude":{"type":"number"},"longitude":{"type":"number"},"description":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}},"attributes":{"type":"object"}},"required":["name","latitude","longitude"]})
def create_location(name:str,latitude:float,longitude:float,description:str="",tags=None,attributes=None): return _entity_result(KnowledgeBaseService.create("location",name=name,description=description,data=_location_data(latitude,longitude,attributes),tags=tags))

@register_function(manifest_id="user_info.update_location",module="user_info",description="Update a location by exact ID, refreshing unified semantic-search content.",params_schema={"type":"object","properties":{"location_id":{"type":"string"},"name":{"type":"string"},"latitude":{"type":"number"},"longitude":{"type":"number"},"description":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}},"attributes":{"type":"object"}},"required":["location_id"]})
def update_location(location_id:str,name=None,latitude=None,longitude=None,description=None,tags=None,attributes=None):
    data=dict(attributes or {});
    if latitude is not None: data["latitude"]=latitude
    if longitude is not None: data["longitude"]=longitude
    return _entity_result(KnowledgeBaseService.update(location_id,entity_type="location",name=name,description=description,data=data,tags=tags))

@register_function(manifest_id="user_info.delete_location",module="user_info",description="Delete a structured location by exact ID after listing/searching to identify it.",params_schema={"type":"object","properties":{"location_id":{"type":"string"}},"required":["location_id"]})
def delete_location(location_id:str): KnowledgeBaseService.delete(location_id,entity_type="location"); return {"id":location_id,"deleted":True}

@register_function(manifest_id="user_info.list_locations",module="user_info",description="List locations or semantically search locations only. Returns coordinates, descriptions, attributes, and tags.",params_schema={"type":"object","properties":{"query":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}},"limit":{"type":"integer"}}})
def list_locations(query:str="",tags=None,limit:int=100): return {"locations":KnowledgeBaseService.list_type("location",query=query,tags=tags,limit=limit)}

@register_function(manifest_id="user_info.create_person",module="user_info",description="Create a structured person with name, relationship, description, facts array, and unified knowledge tags.",params_schema={"type":"object","properties":{"name":{"type":"string"},"relationship":{"type":"string"},"description":{"type":"string"},"facts":{"type":"array","items":{"type":"string"}},"tags":{"type":"array","items":{"type":"string"}},"attributes":{"type":"object"}},"required":["name"]})
def create_person(name:str,relationship:str="",description:str="",facts=None,tags=None,attributes=None): return _entity_result(KnowledgeBaseService.create("person",name=name,description=description,data=_person_data(relationship,facts,attributes),tags=tags))

@register_function(manifest_id="user_info.update_person",module="user_info",description="Update a person by exact ID, including relationship, description, facts, tags, or extensible attributes.",params_schema={"type":"object","properties":{"person_id":{"type":"string"},"name":{"type":"string"},"relationship":{"type":"string"},"description":{"type":"string"},"facts":{"type":"array","items":{"type":"string"}},"tags":{"type":"array","items":{"type":"string"}},"attributes":{"type":"object"}},"required":["person_id"]})
def update_person(person_id:str,name=None,relationship=None,description=None,facts=None,tags=None,attributes=None):
    data=dict(attributes or {});
    if relationship is not None: data["relationship"]=relationship
    if facts is not None: data["facts"]=facts
    return _entity_result(KnowledgeBaseService.update(person_id,entity_type="person",name=name,description=description,data=data,tags=tags))

@register_function(manifest_id="user_info.delete_person",module="user_info",description="Delete a structured person by exact ID after listing/searching to identify them.",params_schema={"type":"object","properties":{"person_id":{"type":"string"}},"required":["person_id"]})
def delete_person(person_id:str): KnowledgeBaseService.delete(person_id,entity_type="person"); return {"id":person_id,"deleted":True}

@register_function(manifest_id="user_info.list_people",module="user_info",description="List people or semantically search people only. Returns relationship, description, facts, attributes, and tags.",params_schema={"type":"object","properties":{"query":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}},"limit":{"type":"integer"}}})
def list_people(query:str="",tags=None,limit:int=100): return {"people":KnowledgeBaseService.list_type("person",query=query,tags=tags,limit=limit)}

@register_function(manifest_id="user_info.get_entity",module="user_info",description="Read one structured knowledge entity by exact ID.",params_schema={"type":"object","properties":{"entity_id":{"type":"string"}},"required":["entity_id"]})
def get_entity(entity_id:str): return _entity_result(KnowledgeBaseService.get(entity_id))

@register_function(manifest_id="user_info.search_knowledge",module="user_info",description="Preferred personal-memory retrieval: broad semantic search across generic notes, locations, people, and future note types. Pass the natural-language query without deterministic filters unless the user explicitly asks for a tag constraint. Returns top-ranked result payloads for reasoning, prioritizing likely entity classes before broadening.",params_schema={"type":"object","properties":{"query":{"type":"string","description":"Natural-language semantic query"},"tags":{"type":"array","items":{"type":"string"},"description":"Hard tag filter; omit unless the user explicitly requested these tags"},"limit":{"type":"integer","default":10,"description":"Number of top relevant payloads to fetch into context; normally 10"}},"required":["query"]})
def search_knowledge(query:str,tags=None,limit:int=10): return KnowledgeBaseService.search(query,tags=tags,limit=limit)

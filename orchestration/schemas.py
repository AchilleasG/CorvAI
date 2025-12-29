from __future__ import annotations

import uuid
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


class MessageEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: str = ""
    role: Literal["user", "frontman", "caller", "runner"]
    type: Literal["user_visible", "tool_only", "system_note", "error"]
    audience: Literal["user", "ai_stack"] = "ai_stack"
    content: str
    call_id: Optional[str] = None
    job_id: Optional[str] = None
    module_id: Optional[str] = None
    function_id: Optional[str] = None
    metadata: Dict = Field(default_factory=dict)


class FunctionCallPayload(BaseModel):
    trace_id: str
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    function_id: str
    params: Dict = Field(default_factory=dict)
    rationale: Optional[str] = None
    plan_step: Optional[str] = None
    job_id: Optional[str] = None


class FunctionResultPayload(BaseModel):
    trace_id: str
    call_id: str
    status: Literal["ok", "error"]
    data: Optional[Dict] = None
    error_summary: Optional[str] = None
    logs: Optional[Dict] = None
    job_id: Optional[str] = None

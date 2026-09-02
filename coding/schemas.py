from typing import Any, Literal, Optional

from ninja import Schema


class CodingSessionIn(Schema):
    name: str
    machine_id: str
    remote_working_directory: str = "~"


class CodingTaskIn(Schema):
    prompt: str
    source: Literal["corv", "ui", "decision"] = "ui"
    file_ids: list[str] = []


class CodingTerminalInput(Schema):
    text: str = ""
    key: Optional[Literal["Enter", "Up", "Down", "Left", "Right", "Tab", "Escape", "C-c", "C-d"]] = None


class FeatureDelegationIn(Schema):
    title: str
    description: str
    acceptance_criteria: list[str]
    qa_enabled: bool = True
    max_iterations: int = 6
    file_ids: list[str] = []


class FeatureDelegationResumeIn(Schema):
    decision: str = ""
    mode: Literal["auto", "qa", "coding"] = "auto"


class ManagedFileCreateIn(Schema):
    filename: str
    content: str = ""
    encoding: Literal["utf-8", "base64"] = "utf-8"
    content_type: str = "text/plain"
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    metadata: dict[str, Any] = {}
    tags: list[str] = []


class ManagedFileUpdateIn(Schema):
    filename: Optional[str] = None
    content_type: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    tags: Optional[list[str]] = None


class ManagedFileAttachIn(Schema):
    message_id: str

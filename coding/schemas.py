from typing import Literal, Optional

from ninja import Schema


class CodingSessionIn(Schema):
    name: str
    machine_id: str
    remote_working_directory: str = "~"


class CodingTaskIn(Schema):
    prompt: str
    source: Literal["corv", "ui", "decision"] = "ui"


class CodingTerminalInput(Schema):
    text: str = ""
    key: Optional[Literal["Enter", "Up", "Down", "Left", "Right", "Tab", "Escape", "C-c", "C-d"]] = None


class FeatureDelegationIn(Schema):
    title: str
    description: str
    acceptance_criteria: list[str]
    qa_enabled: bool = True
    max_iterations: int = 6


class FeatureDelegationResumeIn(Schema):
    decision: str = ""

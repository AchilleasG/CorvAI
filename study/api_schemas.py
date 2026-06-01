from __future__ import annotations

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from ninja import Schema


class StudyAssignmentChecklistItem(Schema):
    step_number: int
    title: str
    description: str


class StudyAssignmentOut(Schema):
    id: UUID
    course_id: UUID
    objective_id: Optional[UUID] = None
    title: str
    description: str
    due_at: datetime
    material_text: Optional[str] = None
    plan: Optional[str] = None
    checklist: List[StudyAssignmentChecklistItem]
    session_count: int
    soft_event_refs: List[str]
    has_uploaded_file: bool = False
    uploaded_file_name: Optional[str] = None
    status: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @staticmethod
    def from_model(assignment) -> StudyAssignmentOut:
        checklist_items = [
            StudyAssignmentChecklistItem(
                step_number=item.get("step_number", i + 1),
                title=item.get("title", ""),
                description=item.get("description", ""),
            )
            for i, item in enumerate(assignment.checklist or [])
        ]
        return StudyAssignmentOut(
            id=assignment.id,
            course_id=assignment.course_id,
            objective_id=assignment.objective_id,
            title=assignment.title,
            description=assignment.description,
            due_at=assignment.due_at,
            material_text=assignment.material_text,
            plan=assignment.plan,
            checklist=checklist_items,
            session_count=assignment.session_count,
            soft_event_refs=assignment.soft_event_refs or [],
            has_uploaded_file=bool(getattr(assignment, "uploaded_file", None) or (assignment.metadata or {}).get("uploaded_file_path")),
            uploaded_file_name=(
                (getattr(assignment.uploaded_file, "name", "") if getattr(assignment, "uploaded_file", None) else "")
                or (assignment.metadata or {}).get("uploaded_file_name")
                or None
            ),
            status=assignment.status,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )


class CreateStudyAssignmentIn(Schema):
    course_id: str
    title: str
    description: Optional[str] = None
    due_at: str
    material_text: Optional[str] = None
    session_count: Optional[int] = None

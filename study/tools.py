from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone

from orchestration.objectives import ObjectiveService
from orchestration.registry import register_function
from study.models import StudyCourse, StudyExam, StudyMaterial, StudyPlan, StudySessionTarget, StudyTopic
from study.services import StudyIngestionService, StudyPlannerService


def _material_payload(material: StudyMaterial) -> dict:
    return {
        "id": str(material.id),
        "course_id": str(material.course_id),
        "topic_id": str(material.topic_id) if material.topic_id else None,
        "exam_id": str(material.exam_id) if material.exam_id else None,
        "kind": material.kind,
        "title": material.title,
        "source_url": material.source_url,
        "file_path": material.file_path,
        "raw_text": material.raw_text,
        "parsed_text": material.parsed_text,
        "ingestion_status": material.ingestion_status,
        "notes": material.notes,
        "metadata": material.metadata,
        "created_at": material.created_at.isoformat() if material.created_at else None,
        "updated_at": material.updated_at.isoformat() if material.updated_at else None,
    }


def _normalize_material_kind(kind: Optional[str]) -> str:
    if kind == StudyMaterial.KIND_LECTURE_PDF:
        return StudyMaterial.KIND_LECTURE
    return kind or StudyMaterial.KIND_OTHER


def _topic_payload(topic: StudyTopic) -> dict:
    return {
        "id": str(topic.id),
        "course_id": str(topic.course_id),
        "name": topic.name,
        "description": topic.description,
        "summary": topic.summary,
        "order_index": topic.order_index,
        "estimated_effort_minutes": topic.estimated_effort_minutes,
        "weight": topic.weight,
        "status": topic.status,
        "passed": topic.passed,
        "passed_at": topic.passed_at.isoformat() if topic.passed_at else None,
        "grade": topic.grade,
    }


def _exam_payload(exam: StudyExam) -> dict:
    return {
        "id": str(exam.id),
        "course_id": str(exam.course_id),
        "course_title": exam.course.title if exam.course_id and exam.course else None,
        "title": exam.title,
        "kind": exam.kind,
        "scheduled_at": exam.scheduled_at.isoformat() if exam.scheduled_at else None,
        "weight": exam.weight,
        "notes": exam.notes,
    }


@register_function(
    manifest_id="study.create_course",
    module="study",
    name="study.create_course",
    description="Create a study course container for one subject or class.",
    params_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "code": {"type": "string"},
            "description": {"type": "string"},
            "term_start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "term_end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "status": {"type": "string", "description": "active|completed|archived"},
            "chat_id": {"type": "string"},
        },
        "required": ["title"],
    },
)
def create_course(
    title: str,
    code: str = "",
    description: str = "",
    term_start_date: Optional[str] = None,
    term_end_date: Optional[str] = None,
    status: str = StudyCourse.STATUS_ACTIVE,
    chat_id: Optional[str] = None,
):
    chat = None
    if chat_id:
        from chat.models import Chat

        chat = Chat.objects.filter(id=chat_id).first()

    course = StudyCourse.objects.create(
        objective=ObjectiveService.create_course_objective(
            title=code or title,
            description=description or "",
            chat=chat,
        ),
        title=title,
        code=code or "",
        description=description or "",
        term_start_date=parse_date(term_start_date) if term_start_date else None,
        term_end_date=parse_date(term_end_date) if term_end_date else None,
        status=status or StudyCourse.STATUS_ACTIVE,
        chat=chat,
    )
    ObjectiveService.ensure_course_objective(course)
    return {"id": str(course.id), "title": course.title, "code": course.code, "status": course.status}


@register_function(
    manifest_id="study.list_courses",
    module="study",
    name="study.list_courses",
    description="List study courses.",
    params_schema={"type": "object", "properties": {"status": {"type": "string"}}},
)
def list_courses(status: Optional[str] = None):
    qs = StudyCourse.objects.all().order_by("title")
    if status:
        qs = qs.filter(status=status)
    return {
        "courses": [
            {
                "id": str(course.id),
                "title": course.title,
                "code": course.code,
                "status": course.status,
                "term_start_date": course.term_start_date.isoformat() if course.term_start_date else None,
                "term_end_date": course.term_end_date.isoformat() if course.term_end_date else None,
            }
            for course in qs
        ]
    }


@register_function(
    manifest_id="study.create_exam",
    module="study",
    name="study.create_exam",
    description="Create an exam checkpoint for a study course.",
    params_schema={
        "type": "object",
        "properties": {
            "course_id": {"type": "string"},
            "title": {"type": "string"},
            "kind": {"type": "string"},
            "scheduled_at": {"type": "string", "description": "ISO datetime"},
            "weight": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["course_id", "title"],
    },
)
def create_exam(
    course_id: str,
    title: str,
    kind: str = StudyExam.KIND_OTHER,
    scheduled_at: Optional[str] = None,
    weight: float = 1.0,
    notes: str = "",
):
    course = StudyCourse.objects.get(id=course_id)
    exam = StudyExam.objects.create(
        course=course,
        title=title,
        kind=kind or StudyExam.KIND_OTHER,
        scheduled_at=parse_datetime(scheduled_at) if scheduled_at else None,
        weight=weight or 1.0,
        notes=notes or "",
    )
    return {"id": str(exam.id), "title": exam.title, "kind": exam.kind, "course_id": str(course.id)}


@register_function(
    manifest_id="study.create_topic",
    module="study",
    name="study.create_topic",
    description="Create a topic for a course.",
    params_schema={
        "type": "object",
        "properties": {
            "course_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "order_index": {"type": "integer"},
            "estimated_effort_minutes": {"type": "integer"},
            "weight": {"type": "number"},
        },
        "required": ["course_id", "name"],
    },
)
def create_topic(
    course_id: str,
    name: str,
    description: str = "",
    order_index: int = 0,
    estimated_effort_minutes: int = 60,
    weight: float = 1.0,
):
    course = StudyCourse.objects.get(id=course_id)
    topic = StudyTopic.objects.create(
        course=course,
        objective=ObjectiveService.create_child_objective(
            parent=course.objective,
            title=f"Study {name}",
            description=description or "",
            deadline_at=course.objective.deadline_at,
            estimated_effort_minutes=max(estimated_effort_minutes or 1, 1),
            remaining_effort_minutes=max(estimated_effort_minutes or 1, 1),
            priority=int(round((weight or 1.0) * 10)),
            metadata={"source": "study_topic"},
        ),
        name=name,
        description=description or "",
        order_index=order_index or 0,
        estimated_effort_minutes=max(estimated_effort_minutes or 1, 1),
        weight=weight or 1.0,
    )
    ObjectiveService.ensure_topic_objective(topic)
    return {"id": str(topic.id), "course_id": str(course.id), "name": topic.name}


@register_function(
    manifest_id="study.create_lesson",
    module="study",
    name="study.create_lesson",
    description="Create a lesson entry for a course. This is an alias for creating a topic.",
    params_schema={
        "type": "object",
        "properties": {
            "course_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "order_index": {"type": "integer"},
            "estimated_effort_minutes": {"type": "integer"},
            "weight": {"type": "number"},
        },
        "required": ["course_id", "name"],
    },
)
def create_lesson(
    course_id: str,
    name: str,
    description: str = "",
    order_index: int = 0,
    estimated_effort_minutes: int = 60,
    weight: float = 1.0,
):
    return create_topic(
        course_id=course_id,
        name=name,
        description=description,
        order_index=order_index,
        estimated_effort_minutes=estimated_effort_minutes,
        weight=weight,
    )


@register_function(
    manifest_id="study.list_topics",
    module="study",
    name="study.list_topics",
    description="List topics for a study course.",
    params_schema={
        "type": "object",
        "properties": {"course_id": {"type": "string"}},
        "required": ["course_id"],
    },
)
def list_topics(course_id: str):
    return {"topics": [_topic_payload(topic) for topic in StudyTopic.objects.filter(course_id=course_id).order_by("order_index", "name")]}


@register_function(
    manifest_id="study.update_topic",
    module="study",
    name="study.update_topic",
    description="Update a topic or lesson, including pass state and grade.",
    params_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "string"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "order_index": {"type": "integer"},
            "estimated_effort_minutes": {"type": "integer"},
            "weight": {"type": "number"},
            "status": {"type": "string"},
            "passed": {"type": "boolean"},
            "grade": {"type": "number"},
        },
        "required": ["topic_id"],
    },
)
def update_topic(
    topic_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    order_index: Optional[int] = None,
    estimated_effort_minutes: Optional[int] = None,
    weight: Optional[float] = None,
    status: Optional[str] = None,
    passed: Optional[bool] = None,
    grade: Optional[float] = None,
):
    topic = StudyTopic.objects.get(id=topic_id)
    fields = []
    if name is not None:
        topic.name = name
        fields.append("name")
    if description is not None:
        topic.description = description
        fields.append("description")
    if order_index is not None:
        topic.order_index = max(order_index, 0)
        fields.append("order_index")
    if estimated_effort_minutes is not None:
        topic.estimated_effort_minutes = max(estimated_effort_minutes, 1)
        fields.append("estimated_effort_minutes")
    if weight is not None:
        topic.weight = weight
        fields.append("weight")
    if status is not None:
        topic.status = status
        fields.append("status")
    if passed is not None:
        topic.passed = passed
        fields.append("passed")
        topic.passed_at = timezone.now() if passed else None
        fields.append("passed_at")
    if grade is not None:
        topic.grade = grade
        fields.append("grade")
    if fields:
        topic.save(update_fields=fields + ["updated_at"])
    return _topic_payload(topic)


@register_function(
    manifest_id="study.list_lessons",
    module="study",
    name="study.list_lessons",
    description="List lessons for a study course. This is an alias for listing topics.",
    params_schema={
        "type": "object",
        "properties": {"course_id": {"type": "string"}},
        "required": ["course_id"],
    },
)
def list_lessons(course_id: str):
    return list_topics(course_id=course_id)


@register_function(
    manifest_id="study.create_material",
    module="study",
    name="study.create_material",
    description="Create a study material record for a course.",
    params_schema={
        "type": "object",
        "properties": {
            "course_id": {"type": "string"},
            "title": {"type": "string"},
            "kind": {"type": "string"},
            "topic_id": {"type": "string"},
            "exam_id": {"type": "string"},
            "source_url": {"type": "string"},
            "file_path": {"type": "string"},
            "notes": {"type": "string"},
        },
        "required": ["course_id", "title"],
    },
)
def create_material(
    course_id: str,
    title: str,
    kind: str = StudyMaterial.KIND_OTHER,
    topic_id: Optional[str] = None,
    exam_id: Optional[str] = None,
    source_url: str = "",
    file_path: str = "",
    notes: str = "",
):
    course = StudyCourse.objects.get(id=course_id)
    topic = StudyTopic.objects.filter(id=topic_id).first() if topic_id else None
    exam = StudyExam.objects.filter(id=exam_id).first() if exam_id else None
    material = StudyMaterial.objects.create(
        course=course,
        topic=topic,
        exam=exam,
        kind=_normalize_material_kind(kind),
        title=title,
        source_url=source_url or "",
        file_path=file_path or "",
        notes=notes or "",
        ingestion_status=StudyMaterial.INGESTION_PENDING,
    )
    return _material_payload(material)


@register_function(
    manifest_id="study.list_materials",
    module="study",
    name="study.list_materials",
    description="List study materials for a course.",
    params_schema={
        "type": "object",
        "properties": {
            "course_id": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["course_id"],
    },
)
def list_materials(course_id: str, status: Optional[str] = None):
    qs = StudyMaterial.objects.filter(course_id=course_id).order_by("-created_at")
    if status:
        qs = qs.filter(ingestion_status=status)
    return {"materials": [_material_payload(material) for material in qs]}


@register_function(
    manifest_id="study.list_exams",
    module="study",
    name="study.list_exams",
    description="List exams for a study course.",
    params_schema={
        "type": "object",
        "properties": {"course_id": {"type": "string"}},
        "required": ["course_id"],
    },
)
def list_exams(course_id: str):
    return {"exams": [_exam_payload(exam) for exam in StudyExam.objects.filter(course_id=course_id).order_by("scheduled_at", "title")]}


@register_function(
    manifest_id="study.ingest_directory",
    module="study",
    name="study.ingest_directory",
    description="Ingest a directory of study materials and convert them to markdown and theory notes.",
    params_schema={
        "type": "object",
        "properties": {
            "course_id": {"type": "string"},
            "directory": {"type": "string"},
            "recursive": {"type": "boolean", "default": True},
            "max_pages": {"type": "integer"},
        },
        "required": ["course_id", "directory"],
    },
)
def ingest_directory(course_id: str, directory: str, recursive: bool = True, max_pages: Optional[int] = None):
    course = StudyCourse.objects.get(id=course_id)
    return StudyIngestionService.ingest_directory(
        course=course,
        directory=directory,
        recursive=recursive,
        max_pages=max_pages,
    )


@register_function(
    manifest_id="study.process_material",
    module="study",
    name="study.process_material",
    description="Process one study material into markdown, solved work, and extracted theory.",
    params_schema={
        "type": "object",
        "properties": {
            "material_id": {"type": "string"},
            "max_pages": {"type": "integer"},
        },
        "required": ["material_id"],
    },
)
def process_material(material_id: str, max_pages: Optional[int] = None):
    material = StudyMaterial.objects.get(id=material_id)
    StudyIngestionService.process_material(material, max_pages=max_pages)
    return {
        "id": str(material.id),
        "status": material.ingestion_status,
        "page_count": material.page_count,
    }


@register_function(
    manifest_id="study.create_active_plan",
    module="study",
    name="study.create_active_plan",
    description="Create a new active study plan for a course and supersede the old one.",
    params_schema={
        "type": "object",
        "properties": {"course_id": {"type": "string"}, "name": {"type": "string"}},
        "required": ["course_id"],
    },
)
def create_active_plan(course_id: str, name: str = ""):
    course = StudyCourse.objects.get(id=course_id)
    plan = StudyPlannerService.create_or_replace_active_plan(course, name=name or None)
    return {"id": str(plan.id), "course_id": str(course.id), "status": plan.status, "name": plan.name}


@register_function(
    manifest_id="study.build_session_targets",
    module="study",
    name="study.build_session_targets",
    description="Build study session targets from the active plan and topic list.",
    params_schema={
        "type": "object",
        "properties": {
            "plan_id": {"type": "string"},
            "start_date": {"type": "string", "description": "YYYY-MM-DD"},
            "end_date": {"type": "string", "description": "YYYY-MM-DD"},
            "preferred_minutes": {"type": "integer", "default": 60},
            "min_minutes": {"type": "integer", "default": 30},
        },
        "required": ["plan_id", "start_date", "end_date"],
    },
)
def build_session_targets(plan_id: str, start_date: str, end_date: str, preferred_minutes: int = 60, min_minutes: int = 30):
    plan = StudyPlan.objects.get(id=plan_id)
    targets = StudyPlannerService.build_session_targets_from_topics(
        plan,
        start_date=date.fromisoformat(start_date),
        end_date=date.fromisoformat(end_date),
        preferred_minutes=preferred_minutes,
        min_minutes=min_minutes,
    )
    return {"plan_id": str(plan.id), "created": len(targets)}

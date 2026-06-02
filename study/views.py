from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional
from datetime import timedelta

from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile
from django.http import FileResponse, HttpResponse, QueryDict
from django.http.multipartparser import MultiPartParser, MultiPartParserError

from orchestration.objectives import ObjectiveService
from orchestration.models import Job, ToolModule
from orchestration.services import JobService
from study.models import (
    StudyAssignment,
    StudyCourse,
    StudyExam,
    StudyMaterial,
    StudyPlan,
    StudySessionTarget,
    StudyTopic,
    StudyTopicAudiobookVersion,
)
from study.services import (
    AssignmentService,
    StudyIngestionService,
    StudyPlannerService,
    StudyTopicAudiobookService,
    _normalize_topic_summary,
)
from study.tasks import (
    process_study_material_job,
    process_study_assignment_job,
    generate_study_topic_audiobook_job,
)
from study.api_schemas import StudyAssignmentOut, CreateStudyAssignmentIn

router = Router(tags=["Study"])

logger = logging.getLogger(__name__)


def _request_json_dict(request) -> dict:
    try:
        raw = request.body.decode("utf-8") if getattr(request, "body", None) else ""
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _request_form_dict(request) -> dict:
    content_type = str(request.META.get("CONTENT_TYPE") or "").lower()

    if "multipart/form-data" in content_type:
        try:
            parser = MultiPartParser(request.META, request, request.upload_handlers, request.encoding)
            data, _files = parser.parse()
            return {key: data.get(key) for key in data.keys()}
        except (MultiPartParserError, ValueError, AttributeError):
            return {}

    if "application/x-www-form-urlencoded" in content_type:
        try:
            charset = request.encoding or "utf-8"
            decoded = request.body.decode(charset) if getattr(request, "body", None) else ""
            data = QueryDict(decoded)
            return {key: data.get(key) for key in data.keys()}
        except Exception:
            return {}

    return {}


def _normalize_material_kind(kind: Optional[str]) -> str:
    normalized = str(kind or "").strip().lower()
    if normalized == StudyMaterial.KIND_LECTURE_PDF:
        return StudyMaterial.KIND_LECTURE
    # Frontend historically sent "exam" for past papers; keep it mapped.
    if normalized == "exam":
        return StudyMaterial.KIND_PAST_EXAM
    return normalized or StudyMaterial.KIND_OTHER


def _course_payload(course: StudyCourse) -> dict:
    return {
        "id": str(course.id),
        "objective_id": str(course.objective_id) if course.objective_id else None,
        "title": course.title,
        "code": course.code,
        "description": course.description,
        "term_start_date": course.term_start_date.isoformat() if course.term_start_date else None,
        "term_end_date": course.term_end_date.isoformat() if course.term_end_date else None,
        "status": course.status,
        "chat_id": str(course.chat_id) if course.chat_id else None,
        "metadata": course.metadata,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
    }


def _material_payload(material: StudyMaterial) -> dict:
    return {
        "id": str(material.id),
        "course_id": str(material.course_id),
        "topic_id": str(material.topic_id) if material.topic_id else None,
        "exam_id": str(material.exam_id) if material.exam_id else None,
        "kind": material.kind,
        "title": material.title,
        "source_url": material.source_url,
        "uploaded_file_url": material.uploaded_file.url if material.uploaded_file else None,
        "uploaded_file_name": material.uploaded_file.name if material.uploaded_file else None,
        "file_path": material.file_path,
        "raw_text": material.raw_text,
        "parsed_text": material.parsed_text,
        "ingestion_status": material.ingestion_status,
        "page_count": material.page_count,
        "converted_markdown": material.converted_markdown,
        "solved_markdown": material.solved_markdown,
        "theory_markdown": material.theory_markdown,
        "extracted_data": material.extracted_data,
        "processed_at": material.processed_at.isoformat() if material.processed_at else None,
        "processing_error": material.processing_error,
        "notes": material.notes,
        "metadata": material.metadata,
        "created_at": material.created_at.isoformat() if material.created_at else None,
        "updated_at": material.updated_at.isoformat() if material.updated_at else None,
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
        "metadata": exam.metadata,
        "created_at": exam.created_at.isoformat() if exam.created_at else None,
        "updated_at": exam.updated_at.isoformat() if exam.updated_at else None,
    }


def _topic_payload(topic: StudyTopic) -> dict:
    return {
        "id": str(topic.id),
        "course_id": str(topic.course_id),
        "objective_id": str(topic.objective_id) if topic.objective_id else None,
        "name": topic.name,
        "description": topic.description,
        "summary": _normalize_topic_summary(topic.summary),
        "homework": topic.homework or [],
        "order_index": topic.order_index,
        "estimated_effort_minutes": topic.estimated_effort_minutes,
        "weight": topic.weight,
        "status": topic.status,
        "passed": topic.passed,
        "passed_at": topic.passed_at.isoformat() if topic.passed_at else None,
        "grade": topic.grade,
        "metadata": topic.metadata,
        "created_at": topic.created_at.isoformat() if topic.created_at else None,
        "updated_at": topic.updated_at.isoformat() if topic.updated_at else None,
    }


def _topic_audiobook_payload(version: StudyTopicAudiobookVersion) -> dict:
    return {
        "id": str(version.id),
        "topic_id": str(version.topic_id),
        "version_number": version.version_number,
        "status": version.status,
        "job_id": str(version.job_id) if version.job_id else None,
        "generation_notes": version.generation_notes,
        "script_markdown": version.script_markdown,
        "audio_url": version.audio_file.url if version.audio_file else None,
        "audio_file_name": version.audio_file.name.split("/")[-1] if version.audio_file else None,
        "audio_mime_type": version.audio_mime_type,
        "tts_voice": version.tts_voice,
        "tts_model": version.tts_model,
        "processing_error": version.processing_error,
        "metadata": version.metadata,
        "created_at": version.created_at.isoformat() if version.created_at else None,
        "updated_at": version.updated_at.isoformat() if version.updated_at else None,
    }


def _job_payload(job: Job) -> dict:
    return {
        "id": str(job.id),
        "status": job.status,
        "user_visible_summary": job.user_visible_summary,
        "progress": job.progress,
        "module_slug": job.module.slug if job.module else None,
        "active_function": job.active_function.manifest_id if job.active_function else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "cancel_requested": job.cancel_requested,
        "error_summary": job.error_summary,
    }


def _queue_material_processing_job(material: StudyMaterial, *, max_pages: Optional[int] = None) -> Job:
    module = ToolModule.objects.filter(slug="study").first()
    job = JobService.create_job(
        chat=material.course.chat,
        module=module,
        user_visible_summary=f"Queued study processing for {material.title}",
    )
    job.metadata = {
        "study_material_id": str(material.id),
        "study_course_id": str(material.course_id),
        "study_material_title": material.title,
    }
    job.save(update_fields=["metadata", "updated_at"])
    try:
        process_study_material_job.delay(str(job.id), str(material.id), max_pages=max_pages)
    except Exception as exc:
        JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
        job.user_visible_summary = f"Failed to queue study processing for {material.title}"
        job.save(update_fields=["user_visible_summary", "updated_at"])
    return job


def _queue_assignment_processing_job(
    assignment: StudyAssignment,
    *,
    uploaded_file_path: Optional[str],
    requested_session_count: Optional[int],
) -> Job:
    module = ToolModule.objects.filter(slug="study").first()
    job = JobService.create_job(
        chat=assignment.course.chat,
        module=module,
        user_visible_summary=f"Queued assignment processing for {assignment.title}",
    )
    job.metadata = {
        "assignment_id": str(assignment.id),
        "study_course_id": str(assignment.course_id),
        "assignment_title": assignment.title,
        "assignment_upload_path": uploaded_file_path,
        "requested_session_count": requested_session_count,
        "job_kind": "assignment_processing",
    }
    job.save(update_fields=["metadata", "updated_at"])
    try:
        process_study_assignment_job.delay(
            str(job.id),
            str(assignment.id),
            uploaded_file_path=uploaded_file_path,
            requested_session_count=requested_session_count,
        )
    except Exception as exc:
        JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
        job.user_visible_summary = f"Failed to queue assignment processing for {assignment.title}"
        job.save(update_fields=["user_visible_summary", "updated_at"])
    return job


def _queue_topic_audiobook_job(
    topic: StudyTopic,
    *,
    generation_notes: str = "",
    model: Optional[str] = None,
    voice: str = "alloy",
) -> tuple[StudyTopicAudiobookVersion, Job]:
    module = ToolModule.objects.filter(slug="study").first()
    job = JobService.create_job(
        chat=topic.course.chat,
        module=module,
        user_visible_summary=f"Queued audiobook generation for {topic.name}",
    )
    version = StudyTopicAudiobookService.create_topic_audiobook_version(
        topic,
        generation_notes=generation_notes,
        job=job,
    )
    job.metadata = {
        "study_topic_id": str(topic.id),
        "study_course_id": str(topic.course_id),
        "study_topic_name": topic.name,
        "audiobook_version_id": str(version.id),
        "job_kind": "topic_audiobook_generation",
        "generation_notes": generation_notes,
        "voice": voice,
        "model": model,
    }
    job.save(update_fields=["metadata", "updated_at"])
    try:
        generate_study_topic_audiobook_job.delay(
            str(job.id),
            str(topic.id),
            str(version.id),
            model=model,
            voice=voice,
        )
    except Exception as exc:
        version.status = StudyTopicAudiobookVersion.STATUS_FAILED
        version.processing_error = str(exc)
        version.save(update_fields=["status", "processing_error", "updated_at"])
        JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
        job.user_visible_summary = f"Failed to queue audiobook generation for {topic.name}"
        job.save(update_fields=["user_visible_summary", "updated_at"])
    return version, job


@router.get("/courses")
def list_courses(request, status: Optional[str] = None):
    qs = StudyCourse.objects.all().order_by("title")
    if status:
        qs = qs.filter(status=status)
    return {"courses": [_course_payload(course) for course in qs]}


@router.post("/courses")
def create_course(
    request,
    title: str = Form(...),
    code: str = Form(""),
    description: str = Form(""),
    term_start_date: Optional[str] = Form(None),
    term_end_date: Optional[str] = Form(None),
    status: str = Form(StudyCourse.STATUS_ACTIVE),
):
    objective = ObjectiveService.create_course_objective(
        title=code or title,
        description=description or "",
    )
    course = StudyCourse.objects.create(
        objective=objective,
        title=title,
        code=code or "",
        description=description or "",
        term_start_date=parse_date(term_start_date) if term_start_date else None,
        term_end_date=parse_date(term_end_date) if term_end_date else None,
        status=status or StudyCourse.STATUS_ACTIVE,
    )
    ObjectiveService.ensure_course_objective(course)
    return _course_payload(course)


@router.patch("/courses/{course_id}")
def update_course(
    request,
    course_id: str,
    title: Optional[str] = Form(None),
    code: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    term_start_date: Optional[str] = Form(None),
    term_end_date: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
):
    course = StudyCourse.objects.get(id=course_id)
    fields: List[str] = []
    if title is not None:
        course.title = title
        fields.append("title")
    if code is not None:
        course.code = code
        fields.append("code")
    if description is not None:
        course.description = description
        fields.append("description")
    if term_start_date is not None:
        course.term_start_date = parse_date(term_start_date) if term_start_date else None
        fields.append("term_start_date")
    if term_end_date is not None:
        course.term_end_date = parse_date(term_end_date) if term_end_date else None
        fields.append("term_end_date")
    if status is not None:
        course.status = status
        fields.append("status")
    if fields:
        course.save(update_fields=fields + ["updated_at"])
        ObjectiveService.ensure_course_objective(course)
    return _course_payload(course)


@router.delete("/courses/{course_id}")
def delete_course(request, course_id: str):
    course = StudyCourse.objects.get(id=course_id)
    course.delete()
    return {"ok": True}


@router.get("/materials")
def list_materials(request, course_id: Optional[str] = None):
    qs = StudyMaterial.objects.select_related("course", "topic", "exam").all().order_by("-created_at")
    if course_id:
        qs = qs.filter(course_id=course_id)
    return {"materials": [_material_payload(material) for material in qs]}

@router.get("/materials/{material_id}/original")
def get_material_original_file(request, material_id: str):
    material = StudyMaterial.objects.get(id=material_id)
    if not material.uploaded_file:
        raise HttpError(404, "Material has no uploaded file")
    file_name = (material.uploaded_file.name or "").split("/")[-1] or f"material-{material.id}"
    try:
        return FileResponse(material.uploaded_file.open("rb"), filename=file_name)
    except FileNotFoundError:
        raise HttpError(404, "Uploaded file not found")


@router.post("/materials/upload")
def upload_material(
    request,
    course_id: str = Form(...),
    title: str = Form(...),
    kind: str = Form(StudyMaterial.KIND_OTHER),
    notes: str = Form(""),
    process_now: bool = Form(True),
    file: Optional[UploadedFile] = File(None),
    source_text: str = Form(""),
    topic_id: Optional[str] = Form(None),
    exam_id: Optional[str] = Form(None),
    source_url: str = Form(""),
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
        uploaded_file=file if file else None,
        file_path=file.name if file else "",
        raw_text=source_text or "",
        notes=notes or "",
    )

    if process_now:
        job = _queue_material_processing_job(material)
    else:
        job = None

    return {"material": _material_payload(material), "job": _job_payload(job) if job else None}


@router.get("/materials/{material_id}")
def get_material(request, material_id: str):
    material = StudyMaterial.objects.select_related("course", "topic", "exam").get(id=material_id)
    return _material_payload(material)


@router.post("/materials/{material_id}/process")
def process_material(request, material_id: str):
    material = StudyMaterial.objects.get(id=material_id)
    job = _queue_material_processing_job(material)
    return {"material": _material_payload(material), "job": _job_payload(job)}


@router.post("/jobs/{job_id}/restart")
def restart_processing_job(request, job_id: str, force: bool = Form(False)):
    job = Job.objects.select_related("module").filter(id=job_id).first()
    if not job:
        raise HttpError(404, "Job not found")

    module_slug = job.module.slug if job.module else None
    material_id = (job.metadata or {}).get("study_material_id")
    if module_slug != "study" or not material_id:
        raise HttpError(400, "Only study processing jobs can be restarted")

    active_statuses = {Job.STATUS_PENDING, Job.STATUS_RUNNING, Job.STATUS_WAITING_USER}
    is_active = job.status in active_statuses and not job.cancel_requested
    if is_active and not force:
        stale_cutoff = timezone.now() - timedelta(minutes=2)
        if job.updated_at and job.updated_at > stale_cutoff:
            raise HttpError(409, "Job is still active; pass force=true to restart anyway")

    if is_active:
        JobService.request_cancel(job, reason="Restart requested by user")

    material = StudyMaterial.objects.filter(id=material_id).first()
    if not material:
        raise HttpError(404, "Study material linked to this job no longer exists")

    restarted_job = _queue_material_processing_job(material)
    restarted_job.metadata = {
        **(restarted_job.metadata or {}),
        "restarted_from_job_id": str(job.id),
    }
    restarted_job.save(update_fields=["metadata", "updated_at"])
    return {"job": _job_payload(restarted_job)}


@router.get("/plans/active")
def get_active_plan(request, course_id: str):
    plan = StudyPlan.objects.filter(course_id=course_id, status=StudyPlan.STATUS_ACTIVE).order_by("-created_at").first()
    if not plan:
        return {"found": False}
    return {
        "found": True,
        "plan": {
            "id": str(plan.id),
            "course_id": str(plan.course_id),
            "name": plan.name,
            "status": plan.status,
            "window_start": plan.window_start.isoformat() if plan.window_start else None,
            "window_end": plan.window_end.isoformat() if plan.window_end else None,
            "summary": plan.summary,
            "plan_json": plan.plan_json,
        },
    }


@router.post("/plans/active")
def create_active_plan(request, course_id: str = Form(...), name: str = Form("")):
    course = StudyCourse.objects.get(id=course_id)
    plan = StudyPlannerService.create_or_replace_active_plan(course, name=name or None)
    return {
        "id": str(plan.id),
        "course_id": str(plan.course_id),
        "name": plan.name,
        "status": plan.status,
        "window_start": plan.window_start.isoformat() if plan.window_start else None,
        "window_end": plan.window_end.isoformat() if plan.window_end else None,
        "summary": plan.summary,
        "plan_json": plan.plan_json,
    }


@router.get("/topics")
def list_topics(request, course_id: str):
    qs = StudyTopic.objects.filter(course_id=course_id).order_by("order_index", "name")
    topics = list(qs)

    # Self-heal missing homework assignments for courses that already have processed homework-source materials.
    has_homework = any(isinstance(topic.homework, list) and len(topic.homework) > 0 for topic in topics)
    if topics and not has_homework:
        has_exam_material = StudyMaterial.objects.filter(
            course_id=course_id,
            kind__in=[StudyMaterial.KIND_PAST_EXAM, "exam", "assignment", "worksheet"],
            ingestion_status=StudyMaterial.INGESTION_PROCESSED,
        ).exists()
        if has_exam_material:
            course = StudyCourse.objects.filter(id=course_id).first()
            if course:
                StudyPlannerService.assign_past_exam_homework_to_topics(course)
                topics = list(StudyTopic.objects.filter(course_id=course_id).order_by("order_index", "name"))

    return {
        "topics": [_topic_payload(topic) for topic in topics]
    }


@router.post("/topics")
def create_topic(
    request,
    course_id: str = Form(...),
    name: str = Form(...),
    description: str = Form(""),
    order_index: int = Form(0),
    estimated_effort_minutes: int = Form(60),
    weight: float = Form(1.0),
):
    course = StudyCourse.objects.get(id=course_id)
    objective = ObjectiveService.create_child_objective(
        parent=course.objective,
        title=f"Study {name}",
        description=description or "",
        deadline_at=course.objective.deadline_at,
        estimated_effort_minutes=max(estimated_effort_minutes, 1),
        remaining_effort_minutes=max(estimated_effort_minutes, 1),
        priority=int(round((weight or 1.0) * 10)),
        metadata={"source": "study_topic"},
    )
    topic = StudyTopic.objects.create(
        course=course,
        objective=objective,
        name=name,
        description=description or "",
        order_index=max(order_index, 0),
        estimated_effort_minutes=max(estimated_effort_minutes, 1),
        weight=weight or 1.0,
    )
    ObjectiveService.ensure_topic_objective(topic)
    StudyPlannerService.assign_past_exam_homework_to_topics(course)
    return _topic_payload(topic)


@router.post("/exams")
def create_exam(
    request,
    course_id: str = Form(...),
    title: str = Form(...),
    kind: str = Form(StudyExam.KIND_OTHER),
    scheduled_at: Optional[str] = Form(None),
    weight: float = Form(1.0),
    notes: str = Form(""),
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
    StudyPlannerService.recalculate_plan_for_course(course)
    return _exam_payload(exam)


@router.get("/exams")
def list_exams(request, course_id: str):
    qs = StudyExam.objects.filter(course_id=course_id).order_by("scheduled_at", "title")
    return {"exams": [_exam_payload(exam) for exam in qs]}


@router.patch("/exams/{exam_id}")
def update_exam(
    request,
    exam_id: str,
    title: Optional[str] = Form(None),
    kind: Optional[str] = Form(None),
    scheduled_at: Optional[str] = Form(None),
    weight: Optional[float] = Form(None),
    notes: Optional[str] = Form(None),
):
    exam = StudyExam.objects.get(id=exam_id)
    fields: List[str] = []
    if title is not None:
        exam.title = title
        fields.append("title")
    if kind is not None:
        exam.kind = kind or StudyExam.KIND_OTHER
        fields.append("kind")
    if scheduled_at is not None:
        exam.scheduled_at = parse_datetime(scheduled_at) if scheduled_at else None
        fields.append("scheduled_at")
    if weight is not None:
        exam.weight = weight or 1.0
        fields.append("weight")
    if notes is not None:
        exam.notes = notes
        fields.append("notes")
    if fields:
        exam.save(update_fields=fields + ["updated_at"])
        StudyPlannerService.recalculate_plan_for_course(exam.course)
    return _exam_payload(exam)


@router.delete("/exams/{exam_id}")
def delete_exam(request, exam_id: str):
    exam = StudyExam.objects.get(id=exam_id)
    course = exam.course
    exam.delete()
    StudyPlannerService.recalculate_plan_for_course(course)
    return {"ok": True}


@router.patch("/topics/{topic_id}")
def update_topic(
    request,
    topic_id: str,
    name: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    order_index: Optional[int] = Form(None),
    estimated_effort_minutes: Optional[int] = Form(None),
    weight: Optional[float] = Form(None),
    status: Optional[str] = Form(None),
    passed: Optional[bool] = Form(None),
    grade: Optional[float] = Form(None),
):
    topic = StudyTopic.objects.get(id=topic_id)
    payload = {
        **_request_form_dict(request),
        **_request_json_dict(request),
    }

    if name is None and "name" in payload:
        name = payload.get("name")
    if description is None and "description" in payload:
        description = payload.get("description")
    if order_index is None and "order_index" in payload:
        try:
            order_index = int(payload.get("order_index"))
        except (TypeError, ValueError):
            raise HttpError(400, "order_index must be an integer")
    if estimated_effort_minutes is None and "estimated_effort_minutes" in payload:
        try:
            estimated_effort_minutes = int(payload.get("estimated_effort_minutes"))
        except (TypeError, ValueError):
            raise HttpError(400, "estimated_effort_minutes must be an integer")
    if weight is None and "weight" in payload:
        try:
            weight = float(payload.get("weight"))
        except (TypeError, ValueError):
            raise HttpError(400, "weight must be a number")
    if status is None and "status" in payload:
        status = str(payload.get("status") or "").strip() or None
    if passed is None and "passed" in payload:
        raw_passed = payload.get("passed")
        if isinstance(raw_passed, bool):
            passed = raw_passed
        elif isinstance(raw_passed, str):
            lowered = raw_passed.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                passed = True
            elif lowered in {"false", "0", "no", "off"}:
                passed = False
            else:
                raise HttpError(400, "passed must be a boolean")
        elif raw_passed is None:
            passed = None
        else:
            raise HttpError(400, "passed must be a boolean")
    if grade is None and "grade" in payload:
        raw_grade = payload.get("grade")
        if raw_grade in (None, ""):
            grade = None
        else:
            try:
                grade = float(raw_grade)
            except (TypeError, ValueError):
                raise HttpError(400, "grade must be a number")

    homework_provided = False
    normalized_homework: List[dict[str, Any]] = []
    if "homework" in payload:
        homework_provided = True
        raw_homework = payload.get("homework")
        if isinstance(raw_homework, str):
            try:
                raw_homework = json.loads(raw_homework)
            except Exception:
                raise HttpError(400, "homework must be a JSON array")
        if raw_homework is None:
            raw_homework = []
        if not isinstance(raw_homework, list):
            raise HttpError(400, "homework must be a list")

        for idx, item in enumerate(raw_homework):
            if isinstance(item, str):
                text = item.strip()
                if not text:
                    continue
                normalized_homework.append(
                    {
                        "assignment_id": f"manual:{topic.id}:{idx+1}",
                        "text": text,
                        "done": False,
                    }
                )
                continue
            if not isinstance(item, dict):
                continue

            text = str(item.get("text") or item.get("question") or "").strip()
            if not text:
                continue
            normalized_homework.append(
                {
                    "assignment_id": str(item.get("assignment_id") or f"manual:{topic.id}:{idx+1}"),
                    "source_material_id": item.get("source_material_id"),
                    "source_material_title": item.get("source_material_title"),
                    "source_exercise_label": item.get("source_exercise_label"),
                    "question_index": item.get("question_index"),
                    "text": text,
                    "done": bool(item.get("done")),
                }
            )

    fields: List[str] = []
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
        valid_statuses = {choice[0] for choice in StudyTopic.STATUS_CHOICES}
        if status not in valid_statuses:
            raise HttpError(400, f"Invalid status '{status}'")
        topic.status = status
        fields.append("status")
    if passed is not None:
        topic.passed = passed
        fields.append("passed")
        if passed and not topic.passed_at:
            topic.passed_at = timezone.now()
            fields.append("passed_at")
        elif not passed:
            topic.passed_at = None
            fields.append("passed_at")
    if grade is not None:
        topic.grade = grade
        fields.append("grade")
    if homework_provided:
        topic.homework = normalized_homework
        fields.append("homework")
    topic.save(update_fields=fields + ["updated_at"] if fields else ["updated_at"])
    ObjectiveService.ensure_topic_objective(topic)
    return _topic_payload(topic)


@router.delete("/topics/{topic_id}")
def delete_topic(request, topic_id: str):
    topic = StudyTopic.objects.get(id=topic_id)
    course = topic.course
    cleanup_stats = StudyPlannerService.cleanup_topic_soft_events(topic)
    topic.delete()
    StudyPlannerService.assign_past_exam_homework_to_topics(course)
    return {"ok": True, "cleanup": cleanup_stats}


@router.get("/topics/{topic_id}/audiobooks")
def list_topic_audiobooks(request, topic_id: str):
    topic = StudyTopic.objects.get(id=topic_id)
    versions = topic.audiobook_versions.all().order_by("-version_number", "-created_at")
    return {"versions": [_topic_audiobook_payload(version) for version in versions]}


@router.post("/topics/{topic_id}/audiobooks")
def create_topic_audiobook(
    request,
    topic_id: str,
    generation_notes: str = Form(""),
    voice: str = Form("alloy"),
    model: Optional[str] = Form(None),
):
    topic = StudyTopic.objects.select_related("course").get(id=topic_id)
    version, job = _queue_topic_audiobook_job(
        topic,
        generation_notes=generation_notes,
        model=model,
        voice=voice,
    )
    return {
        "version": _topic_audiobook_payload(version),
        "job": _job_payload(job),
    }


@router.post("/topics/{topic_id}/audiobooks/preview")
def preview_topic_audiobook_voice(
    request,
    topic_id: str,
    voice: str = Form("en-US-EmmaMultilingualNeural"),
    text: str = Form(""),
):
    topic = StudyTopic.objects.get(id=topic_id)
    preview_text = (text or "").strip()
    if not preview_text:
        preview_text = (
            f"Hello, this is a preview for {topic.name}. "
            "If this voice sounds good to you, use it for the full lesson audiobook."
        )
    preview_text = preview_text[:500]

    audio_bytes, mime_type = StudyTopicAudiobookService._render_audio(preview_text, voice=voice)
    extension = "wav" if mime_type == "audio/wav" else "mp3"
    response = HttpResponse(audio_bytes, content_type=mime_type)
    response["Content-Disposition"] = f'inline; filename="voice-preview-{topic.id}.{extension}"'
    return response


@router.get("/topics/{topic_id}/audiobooks/{version_id}/download")
def download_topic_audiobook(request, topic_id: str, version_id: str):
    version = StudyTopicAudiobookVersion.objects.select_related("topic").get(id=version_id, topic_id=topic_id)
    if not version.audio_file:
        raise HttpError(404, "Audiobook file is not ready for this version")
    file_name = version.audio_file.name.split("/")[-1] or f"topic-{topic_id}-v{version.version_number}.mp3"
    try:
        return FileResponse(version.audio_file.open("rb"), filename=file_name)
    except FileNotFoundError:
        raise HttpError(404, "Audiobook file not found")


# ===== ASSIGNMENTS =====


@router.get("/assignments", response=List[StudyAssignmentOut])
def list_assignments(request, course_id: Optional[str] = None, status: Optional[str] = None):
    """List study assignments, optionally filtered by course and status."""
    qs = StudyAssignment.objects.all()
    if course_id:
        qs = qs.filter(course_id=course_id)
    if status:
        qs = qs.filter(status=status)
    return [StudyAssignmentOut.from_model(item) for item in qs.order_by("-created_at")]


@router.get("/assignments/{assignment_id}", response=StudyAssignmentOut)
def get_assignment(request, assignment_id: str):
    """Get a study assignment by ID."""
    return StudyAssignmentOut.from_model(StudyAssignment.objects.get(id=assignment_id))


@router.get("/assignments/{assignment_id}/original")
def get_assignment_original_file(request, assignment_id: str):
    assignment = StudyAssignment.objects.get(id=assignment_id)
    file_path = AssignmentService.uploaded_file_path(assignment)
    if not file_path:
        raise HttpError(404, "Assignment has no uploaded file")
    if not os.path.exists(file_path):
        raise HttpError(404, "Uploaded assignment file not found")
    file_name = AssignmentService.uploaded_file_name(assignment) or os.path.basename(file_path)
    return FileResponse(open(file_path, "rb"), filename=file_name)


@router.post("/assignments", response=StudyAssignmentOut)
def create_assignment(
    request,
    payload: Optional[CreateStudyAssignmentIn] = None,
    course_id: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    due_at: Optional[str] = Form(None),
    material_text: Optional[str] = Form(None),
    session_count: Optional[int] = Form(None),
    file: Optional[UploadedFile] = File(None),
):
    """Create a new study assignment and process material -> plan + checklist."""
    body_payload = _request_json_dict(request)

    if payload is not None:
        resolved_course_id = payload.course_id
        resolved_title = payload.title
        resolved_description = payload.description
        resolved_due_at = payload.due_at
        resolved_material_text = payload.material_text
        resolved_session_count = payload.session_count
    else:
        resolved_course_id = course_id or body_payload.get("course_id")
        resolved_title = title or body_payload.get("title")
        resolved_description = description or body_payload.get("description")
        resolved_due_at = due_at or body_payload.get("due_at")
        resolved_material_text = material_text or body_payload.get("material_text")
        resolved_session_count = session_count if session_count is not None else body_payload.get("session_count")

    if not resolved_course_id:
        raise HttpError(400, "course_id is required")
    if not resolved_title:
        raise HttpError(400, "title is required")
    parsed_due_at = parse_datetime(str(resolved_due_at or ""))
    if not parsed_due_at:
        raise HttpError(400, "due_at must be a valid ISO datetime")
    if timezone.is_naive(parsed_due_at):
        parsed_due_at = timezone.make_aware(parsed_due_at)

    course = StudyCourse.objects.get(id=resolved_course_id)
    combined_material_text = str(resolved_material_text or "").strip()

    try:
        requested_session_count = max(1, int(resolved_session_count or 1))
    except (TypeError, ValueError):
        requested_session_count = 1

    # Create assignment in processing status and queue async processing job.
    assignment = StudyAssignment.objects.create(
        course=course,
        title=str(resolved_title).strip(),
        description=str(resolved_description or ""),
        due_at=parsed_due_at,
        uploaded_file=file,
        material_text=combined_material_text,
        status=StudyAssignment.STATUS_PROCESSING,
        session_count=requested_session_count,
        metadata={
            "uploaded_file_name": (file.name if file else "") or "",
        },
    )

    _queue_assignment_processing_job(
        assignment,
        uploaded_file_path=AssignmentService.uploaded_file_path(assignment) if file else None,
        requested_session_count=resolved_session_count,
    )

    return StudyAssignmentOut.from_model(assignment)


@router.patch("/assignments/{assignment_id}", response=StudyAssignmentOut)
def update_assignment_status(request, assignment_id: str, status: str):
    """Update assignment status."""
    assignment = StudyAssignment.objects.get(id=assignment_id)

    if status == StudyAssignment.STATUS_IN_PROGRESS and assignment.status == StudyAssignment.STATUS_READY:
        assignment.status = status
        assignment.save(update_fields=["status", "updated_at"])
        ObjectiveService.ensure_assignment_objective(assignment)

    elif status in [StudyAssignment.STATUS_SUBMITTED, StudyAssignment.STATUS_GRADED]:
        assignment.status = status
        assignment.save(update_fields=["status", "updated_at"])
        objective = ObjectiveService.ensure_assignment_objective(assignment) if assignment.objective_id else None
        if objective:
            ObjectiveService.archive_objective_soft_events(objective)

    return StudyAssignmentOut.from_model(assignment)


@router.delete("/assignments/{assignment_id}")
def delete_assignment(request, assignment_id: str):
    assignment = StudyAssignment.objects.get(id=assignment_id)
    assignment.delete()
    return {"ok": True}

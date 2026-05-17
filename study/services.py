from __future__ import annotations

import base64
import ast
import json
import logging
import mimetypes
import os
import re
from datetime import date, datetime, time, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
from PIL import Image
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from Corv.config import settings
from openai_integration.services import ChatAIService
from orchestration.model_providers import resolve_provider, get_client
from orchestration.models import Job, JobEvent, SoftEvent, SoftEventSlot, ToolFunction
from orchestration.services import JobService, ModelConfigService, UserInfoService, UsageService
from study.models import (
    StudyCourse,
    StudyExam,
    StudyMaterial,
    StudyPlan,
    StudySessionLog,
    StudySessionTarget,
    StudyTopic,
    TopicMastery,
)

logger = logging.getLogger(__name__)

ALLOWED_MATERIAL_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}

MATERIAL_PAGE_INSTRUCTIONS = (
    "You are converting a study material page into structured notes. "
    "Read the image carefully. Do not use OCR tools or external transcription services. "
    "Use only the image content visible to you. Be faithful to the page. "
    "Return JSON only with keys: converted_markdown, solved_markdown, theory_markdown, extracted_data. "
    "Write ALL output fields in English, even when the source material is in another language. "
    "If needed, translate terms and statements into clear English while preserving meaning. "
    "converted_markdown should be a clean markdown transcription/structuring of all visible content. "
    "solved_markdown must solve ALL visible questions/problems on the page with complete working. "
    "Do not skip exercises for brevity, compactness, or time. "
    "Never write statements like 'the remaining exercises are not solved'. "
    "If any item cannot be fully solved from the visible content, include it under an 'Unresolved Items' section with: question label, what is missing, and the most likely method. "
    "theory_markdown should contain definitions, formulas, rules, and study reminders. "
    "extracted_data should be an object with keys: topics, formulas, definitions, key_points, questions, worked_examples, memory_cards, warnings, needs_followup. "
    "If a problem is not fully solvable from the image alone, explain the missing assumption instead of inventing facts."
)

MATERIAL_TEXT_INSTRUCTIONS = (
    "You are converting a pasted study material into structured notes. "
    "Read the text carefully. Return JSON only with keys: converted_markdown, solved_markdown, theory_markdown, extracted_data. "
    "Write ALL output fields in English, even when the source text is in another language. "
    "If needed, translate terms and statements into clear English while preserving meaning. "
    "converted_markdown should be a clean markdown rewrite/structure of the provided text. "
    "solved_markdown must solve ALL visible questions/problems in the text with complete working. "
    "Do not skip exercises for brevity, compactness, or time. "
    "Never write statements like 'the remaining exercises are not solved'. "
    "If any item cannot be fully solved from the provided text, include it under an 'Unresolved Items' section with: question label, what is missing, and the most likely method. "
    "theory_markdown should contain definitions, formulas, rules, and study reminders. "
    "extracted_data should be an object with keys: topics, formulas, definitions, key_points, questions, worked_examples, memory_cards, warnings, needs_followup. "
    "If the text is incomplete or ambiguous, explain what is missing instead of inventing facts."
)

TOPIC_RECONCILIATION_INSTRUCTIONS = (
    "You are reconciling freshly extracted study concepts against an existing course topic catalog. "
    "You must decide whether each concept should update an existing topic, create a new topic, or do nothing. "
    "Prefer updating an existing topic when the concept is the same topic under a different phrasing. "
    "Avoid duplicates. Do not rename existing topics unless absolutely necessary; use aliases or description updates instead. "
    "Return JSON only with keys: summary, actions. "
    "Each action must contain: action, rationale. "
    "Allowed actions: create, update, noop. "
    "Write all returned strings and list items in English only, regardless of the source material language. "
    "For create include: name, description, summary, estimated_effort_minutes, weight, status, metadata_patch, why_it_matters, what_to_know, mastery_checks, common_pitfalls, prerequisite_assumptions. "
    "For update include: target_topic_id, description, summary, estimated_effort_minutes, weight, status, metadata_patch, aliases, why_it_matters, what_to_know, mastery_checks, common_pitfalls, prerequisite_assumptions. "
    "For noop include: rationale. "
    "Descriptions must be concrete and detailed enough for a student to study directly from them. "
    "Avoid generic one-liners. Include exam-relevant emphasis when possible. "
    "summary must be a SHORT, HUMAN-FRIENDLY bullet-point list (3-6 bullets) of the key learning outcomes or topics covered. "
    "Summary is displayed on the study page as a PREVIEW before students open the full topic. Make it concise and specific. "
    "Example summary: '• Newton\\'s three laws of motion\\n• Force, mass, and acceleration relationships\\n• Free body diagrams\\n• Applications in circular motion' "
    "CRITICAL: Topics must be like chapters in a book—broad, substantial, and self-contained. Do NOT create too many topics. "
    "Each topic should cover a major learning unit equivalent to a full chapter or substantial lesson block (typically 60-180 minutes of study). "
    "A single past exam or practice paper should become roughly 3-6 broad topics at most, NOT one topic per question or line item. "
    "When the material is a past exam, exam paper, or worksheet, infer the underlying syllabus chapters/themes and group all related questions into the same topic if they test the same core concept. "
    "Do NOT split topics by individual formula, individual question, individual worked example, or minor variant—these belong together in ONE broader chapter topic. "
    "If two concepts would naturally be taught in the same class chapter, merge them into one broader topic. "
    "If the course already has a broader topic that covers the concept, update that topic instead of creating a new narrow one. "
    "Before creating a new topic, ask: 'Is this truly a distinct chapter-level concept that would not fit into any existing topic?' If the answer is maybe, then do not create it—update an existing one instead. "
    "WHEN NEW MATERIAL ARRIVES: Strongly prefer merging new content into existing topics over creating new ones. "
    "Use update actions liberally. If concepts are even remotely related to an existing topic (same subject area, same exam/course unit, overlapping skills), merge them with update instead of creating a new topic. "
    "Only create a new topic if it is genuinely orthogonal to all existing topics—i.e., it covers a completely different major theme that no existing topic touches at all. "
    "This keeps the topic catalog lean and consolidated as material accumulates. "
    "For create and update actions, include at least 3 bullets in what_to_know, at least 3 bullets in mastery_checks, and at least 2 bullets in common_pitfalls. "
    "If detail is missing in the material, explicitly state what is unknown rather than fabricating. "
    "Base your decision on the solved material outputs and the full existing topic catalog provided."
)


@dataclass
class RenderedPage:
    index: int
    mime_type: str
    data_url: str


class StudyJobCanceled(Exception):
    pass


def _safe_json_load(text: str) -> Dict[str, Any]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    return {}


def _normalize_topic_summary(value: Any) -> str:
    """Normalize AI summary payloads into readable multi-line bullets.

    Some model outputs arrive as Python/JSON list literals serialized into a string
    (for example: "['item a', 'item b']"). This converts those into stable
    newline bullet text for storage and API responses.
    """
    raw_items: List[str] = []

    if value is None:
        return ""

    if isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        text = str(value).strip()
        if not text:
            return ""

        parsed: Any = None
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except Exception:
                try:
                    parsed = ast.literal_eval(text)
                except Exception:
                    parsed = None

        if isinstance(parsed, (list, tuple, set)):
            raw_items = [str(item) for item in parsed]
        else:
            normalized = text.replace("\\n", "\n")
            raw_items = normalized.splitlines() or [normalized]

    cleaned: List[str] = []
    for item in raw_items:
        line = str(item).strip()
        if not line:
            continue
        line = re.sub(r"^[\-\*•\u2022]+\s*", "", line)
        line = line.strip(" \t\r\n\"'`")
        if line:
            cleaned.append(line)

    if not cleaned:
        return ""

    return "\n".join(f"- {line}" for line in cleaned)


def _file_extension(path: str) -> str:
    return Path(path).suffix.lower()


def _guess_mime_type(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _bytes_to_data_url(data: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _render_image_file(path: str) -> List[RenderedPage]:
    rendered: List[RenderedPage] = []
    with Image.open(path) as img:
        frame_count = getattr(img, "n_frames", 1)
        for index in range(frame_count):
            try:
                img.seek(index)
            except EOFError:
                break
            frame = img.convert("RGB")
            from io import BytesIO

            buffer = BytesIO()
            frame.save(buffer, format="PNG")
            rendered.append(
                RenderedPage(
                    index=index + 1,
                    mime_type="image/png",
                    data_url=_bytes_to_data_url(buffer.getvalue(), "image/png"),
                )
            )
    return rendered


def _render_pdf_pages(path: str, max_pages: Optional[int] = None) -> List[RenderedPage]:
    rendered: List[RenderedPage] = []
    doc = fitz.open(path)
    try:
        page_total = doc.page_count
        if max_pages is not None:
            page_total = min(page_total, max_pages)
        for index in range(page_total):
            page = doc.load_page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            rendered.append(
                RenderedPage(
                    index=index + 1,
                    mime_type="image/png",
                    data_url=_bytes_to_data_url(pix.tobytes("png"), "image/png"),
                )
            )
    finally:
        doc.close()
    return rendered


def _render_material_to_pages(path: str, max_pages: Optional[int] = None) -> List[RenderedPage]:
    ext = _file_extension(path)
    if ext == ".pdf":
        return _render_pdf_pages(path, max_pages=max_pages)
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}:
        return _render_image_file(path)
    raise ValueError(f"Unsupported file type for study ingestion: {ext}")


def _generate_summary_from_description(description: str, metadata: Dict[str, Any] = None) -> str:
    """
    Generate a human-friendly bullet-point summary from topic description and metadata.
    Extracts key learning points for preview on the study page.
    """
    if metadata is None:
        metadata = {}
    
    summary_parts: List[str] = []
    
    # Prefer structured metadata fields first
    what_to_know = metadata.get("what_to_know", [])
    if isinstance(what_to_know, list) and what_to_know:
        summary_parts.extend(str(item).strip() for item in what_to_know if str(item).strip())
    
    # If not enough content, try to extract from description
    if not summary_parts and description:
        # Look for bullet points in the description
        lines = description.split("\n")
        for line in lines:
            line = line.strip()
            if line.startswith("- ") or line.startswith("* "):
                item = line.lstrip("- *").strip()
                if item:
                    summary_parts.append(item)
            elif line and ":" not in line and len(line) < 150:
                # Take short descriptive lines that aren't section headers
                if not any(line.lower().startswith(h) for h in ["###", "##", "what you", "why this", "prerequisite", "mastery", "common", "pitfall"]):
                    if len(summary_parts) < 5:
                        summary_parts.append(line)
    
    # Limit to top 5-6 points for preview
    summary_list = summary_parts[:6]
    if summary_list:
        return "\n".join(f"• {item}" for item in summary_list)
    
    return ""


class StudyIngestionService:
    """
    Converts uploaded study materials into markdown, solves visible questions, and extracts theory.
    """

    logger = logging.getLogger(__name__)

    @staticmethod
    def _ensure_not_canceled(cancel_check: Optional[Callable[[], None]] = None) -> None:
        if cancel_check:
            cancel_check()

    @staticmethod
    def _emit_progress(
        progress_callback: Optional[Callable[[float, str], None]],
        progress: float,
        message: str,
    ) -> None:
        if progress_callback:
            progress_callback(progress, message)

    @staticmethod
    def _material_path(material: StudyMaterial) -> str:
        if material.uploaded_file:
            return material.uploaded_file.path
        if material.file_path:
            return material.file_path
        if material.source_url:
            raise ValueError("Remote source_url ingestion is not implemented yet; upload the file or provide a local file_path")
        raise ValueError("Study material has no file path or uploaded file")

    @staticmethod
    def _extract_text_material(material: StudyMaterial, text: str, model: Optional[str] = None) -> Dict[str, Any]:
        model_name = model or ModelConfigService.get_study_model()
        text_prompt = (
            f"Course: {material.course.title}\n"
            f"Material: {material.title}\n"
            f"Kind: {material.kind}\n\n"
            f"Text:\n{text}\n\n"
            "Return the requested JSON now."
        )
        resp = get_client("openai").with_options(max_retries=0).responses.create(
            model=model_name,
            input=[
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": MATERIAL_TEXT_INSTRUCTIONS}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": text_prompt}],
                },
            ],
            text={"format": {"type": "json_object"}, "verbosity": "medium"},
            reasoning={"effort": "medium"},
            store=False,
            timeout=120,
        )
        usage_obj = getattr(resp, "usage", None)
        if usage_obj:
            UsageService.log_usage(
                source="study_processing_text",
                model=model_name,
                cache_mode=ModelConfigService.get_cache_mode(),
                usage=usage_obj,
                job=None,
            )
        raw = getattr(resp, "output_text", "") or "{}"
        data = _safe_json_load(raw)
        return {
            "converted_markdown": data.get("converted_markdown", "") or "",
            "solved_markdown": data.get("solved_markdown", "") or "",
            "theory_markdown": data.get("theory_markdown", "") or "",
            "extracted_data": data.get("extracted_data", {}) or {},
            "raw_response": raw,
        }

    @staticmethod
    def _extract_page(material: StudyMaterial, page: RenderedPage, model: Optional[str] = None) -> Dict[str, Any]:
        model_name = model or ModelConfigService.get_study_model()
        provider = resolve_provider(model_name)

        page_text = (
            f"Course: {material.course.title}\n"
            f"Material: {material.title}\n"
            f"Kind: {material.kind}\n"
            f"Page: {page.index}\n"
            "Return the requested JSON now."
        )

        if provider != "openai":
            # Still use the same instruction contract; xAI does not currently have a guaranteed multimodal path here.
            # If xAI is the selected provider, fall back to OpenAI for study ingestion.
            provider = "openai"

        input_seq = [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": MATERIAL_PAGE_INSTRUCTIONS}],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": page_text},
                    {"type": "input_image", "image_url": page.data_url},
                ],
            },
        ]

        resp = get_client("openai").with_options(max_retries=0).responses.create(
            model=model_name,
            input=input_seq,
            text={"format": {"type": "json_object"}, "verbosity": "medium"},
            reasoning={"effort": "medium"},
            store=False,
            timeout=180,
        )
        usage_obj = getattr(resp, "usage", None)
        if usage_obj:
            UsageService.log_usage(
                source="study_processing_page",
                model=model_name,
                cache_mode=ModelConfigService.get_cache_mode(),
                usage=usage_obj,
                job=None,
            )
        raw = getattr(resp, "output_text", "") or "{}"
        data = _safe_json_load(raw)
        return {
            "converted_markdown": data.get("converted_markdown", "") or "",
            "solved_markdown": data.get("solved_markdown", "") or "",
            "theory_markdown": data.get("theory_markdown", "") or "",
            "extracted_data": data.get("extracted_data", {}) or {},
            "raw_response": raw,
        }

    @staticmethod
    def _merge_text_blocks(blocks: Sequence[str]) -> str:
        return "\n\n".join(block.strip() for block in blocks if block and block.strip()).strip()

    @staticmethod
    def _ensure_topic_mastery(course: StudyCourse, topic: StudyTopic) -> None:
        TopicMastery.objects.get_or_create(
            course=course,
            topic=topic,
            defaults={
                "mastery_score": 0.0,
                "confidence_score": 0.0,
                "evidence_count": 0,
            },
        )

    @staticmethod
    def _merge_topic_description(existing: str, incoming: str) -> str:
        existing = (existing or "").strip()
        incoming = (incoming or "").strip()
        if not incoming:
            return existing
        if not existing:
            return incoming
        if incoming in existing:
            return existing
        return f"{existing}\n\n{incoming}"

    @staticmethod
    def _coerce_str_list(value: Any) -> List[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            out: List[str] = []
            for item in value:
                txt = str(item).strip()
                if txt:
                    out.append(txt)
            return out
        return []

    @staticmethod
    def _build_rich_topic_description(name: str, action: Dict[str, Any], current_description: str = "") -> str:
        metadata_patch = action.get("metadata_patch") if isinstance(action.get("metadata_patch"), dict) else {}
        base_description = str(action.get("description") or "").strip() or (current_description or "").strip()
        why_it_matters = str(action.get("why_it_matters") or metadata_patch.get("why_it_matters") or "").strip()

        what_to_know = StudyIngestionService._coerce_str_list(action.get("what_to_know"))
        if not what_to_know:
            what_to_know = StudyIngestionService._coerce_str_list(metadata_patch.get("what_to_know"))

        mastery_checks = StudyIngestionService._coerce_str_list(action.get("mastery_checks"))
        if not mastery_checks:
            mastery_checks = StudyIngestionService._coerce_str_list(metadata_patch.get("mastery_checks"))

        common_pitfalls = StudyIngestionService._coerce_str_list(action.get("common_pitfalls"))
        if not common_pitfalls:
            common_pitfalls = StudyIngestionService._coerce_str_list(metadata_patch.get("common_pitfalls"))

        prerequisite_assumptions = StudyIngestionService._coerce_str_list(action.get("prerequisite_assumptions"))
        if not prerequisite_assumptions:
            prerequisite_assumptions = StudyIngestionService._coerce_str_list(metadata_patch.get("prerequisite_assumptions"))

        sections: List[str] = []
        if base_description:
            sections.append(base_description)

        if why_it_matters:
            sections.append(f"### Why This Matters\n{why_it_matters}")

        if prerequisite_assumptions:
            sections.append(
                "### Prerequisites\n" + "\n".join(f"- {item}" for item in prerequisite_assumptions)
            )

        if what_to_know:
            sections.append("### What You Need To Know\n" + "\n".join(f"- {item}" for item in what_to_know))
        if mastery_checks:
            sections.append("### Mastery Checks\n" + "\n".join(f"- {item}" for item in mastery_checks))
        if common_pitfalls:
            sections.append("### Common Pitfalls\n" + "\n".join(f"- {item}" for item in common_pitfalls))

        # No synthetic filler text: return only what came from AI/material context.
        return "\n\n".join(section.strip() for section in sections if section.strip())

    @staticmethod
    def _topic_metadata_from_action(action: Dict[str, Any]) -> Dict[str, Any]:
        metadata = action.get("metadata_patch") if isinstance(action.get("metadata_patch"), dict) else {}
        metadata = dict(metadata)
        for key in (
            "why_it_matters",
            "what_to_know",
            "mastery_checks",
            "common_pitfalls",
            "prerequisite_assumptions",
        ):
            if key in action and action.get(key) is not None:
                metadata[key] = action.get(key)
        return metadata

    @staticmethod
    def _serialize_existing_topics(course: StudyCourse) -> List[Dict[str, Any]]:
        mastery_by_topic = {
            str(entry.topic_id): entry
            for entry in TopicMastery.objects.filter(course=course).select_related("topic")
        }
        topics = []
        for topic in course.topics.all().order_by("order_index", "name"):
            mastery = mastery_by_topic.get(str(topic.id))
            topics.append(
                {
                    "id": str(topic.id),
                    "name": topic.name,
                    "description": topic.description,
                    "order_index": topic.order_index,
                    "estimated_effort_minutes": topic.estimated_effort_minutes,
                    "weight": topic.weight,
                    "status": topic.status,
                    "metadata": topic.metadata,
                    "mastery": {
                        "mastery_score": mastery.mastery_score if mastery else 0.0,
                        "confidence_score": mastery.confidence_score if mastery else 0.0,
                        "evidence_count": mastery.evidence_count if mastery else 0,
                        "last_evidence_at": mastery.last_evidence_at.isoformat() if mastery and mastery.last_evidence_at else None,
                        "notes": mastery.notes if mastery else "",
                    },
                }
            )
        return topics

    @staticmethod
    def _create_topics_from_extraction(course: StudyCourse, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        topic_names: List[str] = []
        for key in ("topics", "key_points", "definitions"):
            value = extracted_data.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.strip():
                        topic_names.append(item.strip())
                    elif isinstance(item, dict):
                        candidate = item.get("name") or item.get("title")
                        if candidate and str(candidate).strip():
                            topic_names.append(str(candidate).strip())
        seen = set()
        topics: List[StudyTopic] = []
        next_index = course.topics.count()
        created_count = 0
        reused_count = 0
        for name in topic_names:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            topic, created = StudyTopic.objects.get_or_create(
                course=course,
                name=name,
                defaults={
                    "order_index": next_index,
                    "description": f"Derived from uploaded material extraction: {name}.",
                    "estimated_effort_minutes": 60,
                    "weight": 1.0,
                },
            )
            if created:
                next_index += 1
                created_count += 1
            else:
                reused_count += 1
            topics.append(topic)
            StudyIngestionService._ensure_topic_mastery(course, topic)
        return {
            "topics": topics,
            "created_count": created_count,
            "reused_count": reused_count,
            "updated_count": 0,
            "noop_count": 0,
            "mode": "fallback_exact_name",
            "summary": "Fallback topic creation by exact name.",
        }

    @staticmethod
    def reconcile_topics_for_material(
        material: StudyMaterial,
        *,
        model: Optional[str] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> Dict[str, Any]:
        StudyIngestionService._ensure_not_canceled(cancel_check)
        course = material.course
        existing_topics = StudyIngestionService._serialize_existing_topics(course)
        material_context = {
            "material_id": str(material.id),
            "title": material.title,
            "kind": material.kind,
            "converted_markdown": material.converted_markdown,
            "solved_markdown": material.solved_markdown,
            "theory_markdown": material.theory_markdown,
            "extracted_data": material.extracted_data,
        }
        model_name = model or ModelConfigService.get_study_model()
        raw = "{}"
        try:
            resp = get_client("openai").with_options(max_retries=0).responses.create(
                model=model_name,
                input=[
                    {
                        "role": "developer",
                        "content": [{"type": "input_text", "text": TOPIC_RECONCILIATION_INSTRUCTIONS}],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": json.dumps(
                                    {
                                        "course": {
                                            "id": str(course.id),
                                            "title": course.title,
                                            "code": course.code,
                                            "description": course.description,
                                            "status": course.status,
                                        },
                                        "existing_topics": existing_topics,
                                        "material": material_context,
                                    },
                                    ensure_ascii=True,
                                ),
                            }
                        ],
                    },
                ],
                text={"format": {"type": "json_object"}, "verbosity": "low"},
                reasoning={"effort": "low"},
                store=False,
                timeout=120,
            )
            usage_obj = getattr(resp, "usage", None)
            if usage_obj:
                UsageService.log_usage(
                    source="study_topic_reconciliation",
                    model=model_name,
                    cache_mode=ModelConfigService.get_cache_mode(),
                    usage=usage_obj,
                    job=None,
                )
            raw = getattr(resp, "output_text", "") or "{}"
            data = _safe_json_load(raw)
            actions = data.get("actions") if isinstance(data.get("actions"), list) else []
        except Exception:
            StudyIngestionService.logger.exception(
                "Topic reconciliation failed for study material %s; falling back to exact-name matching",
                material.id,
            )
            actions = []
            data = {}

        if not actions:
            fallback = StudyIngestionService._create_topics_from_extraction(
                course,
                material.extracted_data if isinstance(material.extracted_data, dict) else {},
            )
            fallback["raw_response"] = raw
            return fallback

        existing_by_id = {str(topic.id): topic for topic in course.topics.all()}
        valid_statuses = {choice[0] for choice in StudyTopic.STATUS_CHOICES}
        created_count = 0
        updated_count = 0
        noop_count = 0
        touched_topics: List[StudyTopic] = []

        for action in actions:
            StudyIngestionService._ensure_not_canceled(cancel_check)
            if not isinstance(action, dict):
                noop_count += 1
                continue
            action_type = str(action.get("action") or "noop").strip().lower()
            if action_type == "create":
                raw_name = str(action.get("name") or "").strip()
                if not raw_name:
                    noop_count += 1
                    continue
                existing = StudyTopic.objects.filter(course=course, name__iexact=raw_name).first()
                if existing:
                    description = StudyIngestionService._build_rich_topic_description(
                        raw_name,
                        action,
                        current_description=existing.description,
                    )
                    merged = StudyIngestionService._merge_topic_description(existing.description, description)
                    update_fields_local = []
                    if merged != existing.description:
                        existing.description = merged
                        update_fields_local.append("description")
                    new_summary = _normalize_topic_summary(action.get("summary"))
                    if new_summary and new_summary != existing.summary:
                        existing.summary = new_summary
                        update_fields_local.append("summary")
                    metadata_patch = StudyIngestionService._topic_metadata_from_action(action)
                    if metadata_patch:
                        existing.metadata = {
                            **(existing.metadata or {}),
                            **metadata_patch,
                        }
                        update_fields_local.append("metadata")
                    if update_fields_local:
                        existing.save(update_fields=update_fields_local + ["updated_at"])
                        updated_count += 1
                    else:
                        noop_count += 1
                    StudyIngestionService._ensure_topic_mastery(course, existing)
                    touched_topics.append(existing)
                    continue
                topic = StudyTopic.objects.create(
                    course=course,
                    name=raw_name,
                    description=StudyIngestionService._build_rich_topic_description(raw_name, action),
                    summary=_normalize_topic_summary(action.get("summary")),
                    order_index=course.topics.count(),
                    estimated_effort_minutes=max(int(action.get("estimated_effort_minutes") or 60), 1),
                    weight=float(action.get("weight") or 1.0),
                    status=(str(action.get("status") or StudyTopic.STATUS_NOT_STARTED).strip() if str(action.get("status") or "").strip() in valid_statuses else StudyTopic.STATUS_NOT_STARTED),
                    metadata=StudyIngestionService._topic_metadata_from_action(action),
                )
                StudyIngestionService._ensure_topic_mastery(course, topic)
                touched_topics.append(topic)
                created_count += 1
                continue
            if action_type == "update":
                target_topic_id = str(action.get("target_topic_id") or "").strip()
                topic = existing_by_id.get(target_topic_id)
                if not topic:
                    noop_count += 1
                    continue
                update_fields: List[str] = []
                description = StudyIngestionService._build_rich_topic_description(
                    topic.name,
                    action,
                    current_description=topic.description,
                )
                merged_description = StudyIngestionService._merge_topic_description(topic.description, description)
                if merged_description != topic.description:
                    topic.description = merged_description
                    update_fields.append("description")
                new_summary = _normalize_topic_summary(action.get("summary"))
                if new_summary and new_summary != topic.summary:
                    topic.summary = new_summary
                    update_fields.append("summary")
                effort = action.get("estimated_effort_minutes")
                if isinstance(effort, int) and effort > 0 and effort != topic.estimated_effort_minutes:
                    topic.estimated_effort_minutes = effort
                    update_fields.append("estimated_effort_minutes")
                weight = action.get("weight")
                if isinstance(weight, (int, float)) and float(weight) > 0 and float(weight) != topic.weight:
                    topic.weight = float(weight)
                    update_fields.append("weight")
                status = str(action.get("status") or "").strip()
                if status in valid_statuses and status != topic.status:
                    topic.status = status
                    update_fields.append("status")
                metadata_patch = StudyIngestionService._topic_metadata_from_action(action)
                aliases = [str(alias).strip() for alias in action.get("aliases", []) if str(alias).strip()]
                if metadata_patch or aliases:
                    metadata = dict(topic.metadata or {})
                    if metadata_patch:
                        metadata.update(metadata_patch)
                    if aliases:
                        current_aliases = [str(alias).strip() for alias in metadata.get("aliases", []) if str(alias).strip()]
                        metadata["aliases"] = sorted({*current_aliases, *aliases})
                    if metadata != topic.metadata:
                        topic.metadata = metadata
                        update_fields.append("metadata")
                if update_fields:
                    topic.save(update_fields=update_fields + ["updated_at"])
                    updated_count += 1
                else:
                    noop_count += 1
                StudyIngestionService._ensure_topic_mastery(course, topic)
                touched_topics.append(topic)
                continue
            noop_count += 1

        return {
            "topics": touched_topics,
            "created_count": created_count,
            "reused_count": 0,
            "updated_count": updated_count,
            "noop_count": noop_count,
            "mode": "ai_reconciled",
            "summary": str(data.get("summary") or "AI topic reconciliation completed."),
            "raw_response": raw,
        }

    @staticmethod
    @transaction.atomic
    def process_material(
        material: StudyMaterial,
        *,
        model: Optional[str] = None,
        max_pages: Optional[int] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
    ) -> StudyMaterial:
        material.ingestion_status = StudyMaterial.INGESTION_PROCESSING
        material.processing_error = ""
        material.save(update_fields=["ingestion_status", "processing_error", "updated_at"])

        try:
            StudyIngestionService._ensure_not_canceled(cancel_check)
            extracted_data: Dict[str, Any] = {
                "topics": [],
                "formulas": [],
                "definitions": [],
                "key_points": [],
                "questions": [],
                "worked_examples": [],
                "memory_cards": [],
                "warnings": [],
                "needs_followup": False,
            }

            if material.uploaded_file or material.file_path or material.source_url:
                StudyIngestionService._emit_progress(progress_callback, 0.05, "Rendering material pages")
                path = StudyIngestionService._material_path(material)
                pages = _render_material_to_pages(path, max_pages=max_pages)
                if not pages:
                    raise ValueError("No pages could be rendered from the material")

                page_results: List[Dict[str, Any]] = []
                converted_blocks: List[str] = []
                solved_blocks: List[str] = []
                theory_blocks: List[str] = []

                page_total = len(pages)
                for page_index, page in enumerate(pages, start=1):
                    StudyIngestionService._ensure_not_canceled(cancel_check)
                    result = StudyIngestionService._extract_page(material, page, model=model)
                    page_results.append(
                        {
                            "page": page.index,
                            "converted_markdown": result["converted_markdown"],
                            "solved_markdown": result["solved_markdown"],
                            "theory_markdown": result["theory_markdown"],
                            "extracted_data": result["extracted_data"],
                        }
                    )
                    if result["converted_markdown"]:
                        converted_blocks.append(f"## Page {page.index}\n\n{result['converted_markdown']}")
                    if result["solved_markdown"]:
                        solved_blocks.append(f"## Page {page.index}\n\n{result['solved_markdown']}")
                    if result["theory_markdown"]:
                        theory_blocks.append(f"## Page {page.index}\n\n{result['theory_markdown']}")

                    page_data = result["extracted_data"] if isinstance(result["extracted_data"], dict) else {}
                    for key in extracted_data.keys():
                        if key in {"needs_followup"}:
                            extracted_data[key] = bool(extracted_data.get(key)) or bool(page_data.get(key))
                            continue
                        if key not in page_data:
                            continue
                        current_value = extracted_data.get(key)
                        incoming = page_data.get(key)
                        if isinstance(current_value, list) and isinstance(incoming, list):
                            current_value.extend(incoming)
                    StudyIngestionService._emit_progress(
                        progress_callback,
                        0.1 + (0.6 * (page_index / max(page_total, 1))),
                        f"Processed page {page_index} of {page_total}",
                    )

                material.page_count = len(pages)
                material.converted_markdown = StudyIngestionService._merge_text_blocks(converted_blocks)
                material.solved_markdown = StudyIngestionService._merge_text_blocks(solved_blocks)
                material.theory_markdown = StudyIngestionService._merge_text_blocks(theory_blocks)
                extracted_data["pages"] = page_results
            elif material.raw_text.strip():
                StudyIngestionService._emit_progress(progress_callback, 0.05, "Processing pasted text")
                result = StudyIngestionService._extract_text_material(material, material.raw_text.strip(), model=model)
                material.page_count = 1
                material.converted_markdown = result["converted_markdown"] or material.raw_text.strip()
                material.solved_markdown = result["solved_markdown"]
                material.theory_markdown = result["theory_markdown"]
                extracted_data.update(result["extracted_data"] if isinstance(result["extracted_data"], dict) else {})
                extracted_data["source"] = "pasted_text"
                extracted_data["text_length"] = len(material.raw_text.strip())
            else:
                raise ValueError("Study material needs either an uploaded file or pasted text")

            source_text = material.raw_text.strip()
            material.extracted_data = extracted_data
            material.raw_text = source_text if source_text else material.converted_markdown
            material.parsed_text = material.converted_markdown
            material.processed_at = timezone.now()
            material.processing_error = ""
            material.ingestion_status = StudyMaterial.INGESTION_PROCESSED

            StudyIngestionService._emit_progress(progress_callback, 0.78, "Reconciling topics")
            topic_result = StudyIngestionService.reconcile_topics_for_material(
                material,
                model=model,
                cancel_check=cancel_check,
            )

            plan_refresh: Dict[str, Any] = {"recalculated": False, "target_count": 0}
            if topic_result.get("created_count", 0) > 0:
                StudyIngestionService._emit_progress(progress_callback, 0.9, "Recalculating study plan")
                plan_refresh = StudyPlannerService.recalculate_plan_for_course(
                    material.course,
                    source_material=material,
                )

            extracted_data["topic_reconciliation"] = {
                "mode": topic_result.get("mode"),
                "summary": topic_result.get("summary"),
                "created_count": topic_result.get("created_count", 0),
                "updated_count": topic_result.get("updated_count", 0),
                "noop_count": topic_result.get("noop_count", 0),
            }
            extracted_data["plan_refresh"] = plan_refresh
            material.save(
                update_fields=[
                    "page_count",
                    "converted_markdown",
                    "solved_markdown",
                    "theory_markdown",
                    "extracted_data",
                    "raw_text",
                    "parsed_text",
                    "processed_at",
                    "processing_error",
                    "ingestion_status",
                    "updated_at",
                ]
            )
            StudyIngestionService._emit_progress(progress_callback, 1.0, "Study material processing complete")
            return material
        except StudyJobCanceled:
            material.ingestion_status = StudyMaterial.INGESTION_PENDING
            material.processing_error = "Processing canceled"
            material.save(update_fields=["ingestion_status", "processing_error", "updated_at"])
            raise
        except Exception as exc:
            material.ingestion_status = StudyMaterial.INGESTION_FAILED
            material.processing_error = str(exc)
            material.processed_at = timezone.now()
            material.save(
                update_fields=["ingestion_status", "processing_error", "processed_at", "updated_at"]
            )
            StudyIngestionService.logger.exception("Failed to process study material %s", material.id)
            raise

    @staticmethod
    @transaction.atomic
    def ingest_directory(
        *,
        course: StudyCourse,
        directory: str,
        recursive: bool = True,
        model: Optional[str] = None,
        max_pages: Optional[int] = None,
        create_missing: bool = True,
    ) -> Dict[str, Any]:
        base = Path(directory).expanduser().resolve()
        if not base.exists() or not base.is_dir():
            raise ValueError(f"Directory does not exist: {directory}")

        pattern = "**/*" if recursive else "*"
        created = processed = failed = skipped = 0
        results: List[Dict[str, Any]] = []

        for path in sorted(base.glob(pattern)):
            if not path.is_file():
                continue
            if path.suffix.lower() not in ALLOWED_MATERIAL_EXTENSIONS:
                continue

            title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
            material = None
            if create_missing:
                material, created_flag = StudyMaterial.objects.update_or_create(
                    course=course,
                    file_path=str(path),
                    defaults={
                        "title": title,
                        "kind": StudyMaterial.KIND_PAST_EXAM if path.suffix.lower() == ".pdf" else StudyMaterial.KIND_LECTURE,
                        "ingestion_status": StudyMaterial.INGESTION_PENDING,
                        "uploaded_file": None,
                    },
                )
                if created_flag:
                    created += 1
            else:
                try:
                    material = StudyMaterial.objects.get(course=course, file_path=str(path))
                except StudyMaterial.DoesNotExist:
                    skipped += 1
                    continue

            if material is None:
                continue

            if not material.uploaded_file and not material.file_path:
                material.file_path = str(path)
                material.save(update_fields=["file_path", "updated_at"])

            try:
                StudyIngestionService.process_material(material, model=model, max_pages=max_pages)
                processed += 1
                results.append({"material_id": str(material.id), "status": "processed", "title": material.title})
            except Exception as exc:
                failed += 1
                results.append({"material_id": str(material.id), "status": "failed", "error": str(exc), "title": material.title})

        return {
            "directory": str(base),
            "created": created,
            "processed": processed,
            "failed": failed,
            "skipped": skipped,
            "results": results,
        }


class StudyPlannerService:
    """
    Minimal plan generator that turns topics into session targets.
    """

    @staticmethod
    @transaction.atomic
    def create_or_replace_active_plan(course: StudyCourse, *, name: Optional[str] = None) -> StudyPlan:
        StudyPlan.objects.filter(course=course, status=StudyPlan.STATUS_ACTIVE).update(status=StudyPlan.STATUS_SUPERSEDED)
        plan = StudyPlan.objects.create(
            course=course,
            name=name or f"{course.title} Study Plan",
            status=StudyPlan.STATUS_ACTIVE,
            plan_json={"generated_by": "system", "version": 1, "notes": "Initial plan scaffold"},
        )
        return plan

    @staticmethod
    @transaction.atomic
    def cleanup_plan_soft_events(plan: StudyPlan) -> Dict[str, int]:
        target_refs = [
            soft_ref
            for soft_ref in plan.session_targets.exclude(soft_event_ref__isnull=True)
            .values_list("soft_event_ref", flat=True)
        ]
        if not target_refs:
            return {"archived_soft_events": 0, "canceled_slots": 0}

        soft_events = SoftEvent.objects.filter(id__in=target_refs)
        soft_event_ids = list(soft_events.values_list("id", flat=True))
        archived_soft_events = soft_events.exclude(status=SoftEvent.STATUS_ARCHIVED).update(
            status=SoftEvent.STATUS_ARCHIVED,
            updated_at=timezone.now(),
        )
        canceled_slots = SoftEventSlot.objects.filter(
            soft_event_id__in=soft_event_ids,
            status__in=[SoftEventSlot.STATUS_PLANNED, SoftEventSlot.STATUS_DEFERRED],
        ).update(
            status=SoftEventSlot.STATUS_CANCELED,
            rationale="Canceled because study plan was superseded.",
            updated_at=timezone.now(),
        )
        return {
            "archived_soft_events": archived_soft_events,
            "canceled_slots": canceled_slots,
        }

    @staticmethod
    @transaction.atomic
    def cleanup_topic_soft_events(topic: StudyTopic) -> Dict[str, int]:
        target_refs = list(
            StudySessionTarget.objects.filter(topic=topic)
            .exclude(soft_event_ref__isnull=True)
            .values_list("soft_event_ref", flat=True)
        )
        target_count = StudySessionTarget.objects.filter(topic=topic).count()
        if not target_refs and not target_count:
            return {
                "archived_soft_events": 0,
                "canceled_slots": 0,
                "deleted_targets": 0,
            }

        soft_events = SoftEvent.objects.filter(id__in=target_refs)
        soft_event_ids = list(soft_events.values_list("id", flat=True))
        archived_soft_events = soft_events.exclude(status=SoftEvent.STATUS_ARCHIVED).update(
            status=SoftEvent.STATUS_ARCHIVED,
            updated_at=timezone.now(),
        )
        canceled_slots = SoftEventSlot.objects.filter(
            soft_event_id__in=soft_event_ids,
            status__in=[SoftEventSlot.STATUS_PLANNED, SoftEventSlot.STATUS_DEFERRED],
        ).update(
            status=SoftEventSlot.STATUS_CANCELED,
            rationale="Canceled because the linked study lesson was deleted.",
            updated_at=timezone.now(),
        )
        deleted_targets = StudySessionTarget.objects.filter(topic=topic).delete()[0]
        return {
            "archived_soft_events": archived_soft_events,
            "canceled_slots": canceled_slots,
            "deleted_targets": deleted_targets,
        }

    @staticmethod
    def _build_study_user_context(course: StudyCourse, target: StudySessionTarget) -> Dict[str, Any]:
        core_text = UserInfoService.format_core_profile_block()
        query_parts = [course.title, course.code, target.focus, target.outcome]
        if target.topic:
            query_parts.append(target.topic.name)
            query_parts.append(target.topic.description)
        query = " ".join(part for part in query_parts if part).strip()
        related_notes = UserInfoService.search_notes(query, limit=3) if query else []
        note_lines = []
        for note in related_notes:
            parts = [note.get("content", "").strip()]
            if note.get("source"):
                parts.append(f"source={note['source']}")
            if note.get("tags"):
                parts.append(f"tags={','.join(note['tags'])}")
            note_lines.append(" | ".join(part for part in parts if part))

        context_lines = []
        if core_text:
            context_lines.append(core_text)
        if note_lines:
            context_lines.append("Relevant user notes:\n- " + "\n- ".join(note_lines))
        return {
            "core_text": core_text,
            "related_notes": related_notes,
            "context_text": "\n\n".join(context_lines).strip(),
        }

    @staticmethod
    def _target_deadlines(course: StudyCourse, target: StudySessionTarget) -> Tuple[Optional[datetime], Optional[datetime]]:
        target_start = datetime.combine(target.target_date, time(hour=6, minute=0))
        target_end = datetime.combine(target.target_date, time(hour=23, minute=59))
        exam_dt = (
            target.exam.scheduled_at
            if target.exam and target.exam.scheduled_at
            else course.exams.exclude(scheduled_at__isnull=True).order_by("scheduled_at").values_list("scheduled_at", flat=True).first()
        )
        if timezone.is_naive(target_start):
            target_start = timezone.make_aware(target_start)
        if timezone.is_naive(target_end):
            target_end = timezone.make_aware(target_end)
        hard_deadline = exam_dt if exam_dt else target_end
        if hard_deadline and timezone.is_naive(hard_deadline):
            hard_deadline = timezone.make_aware(hard_deadline)
        soft_deadline = hard_deadline if hard_deadline else target_end
        return soft_deadline, hard_deadline

    @staticmethod
    @transaction.atomic
    def sync_session_targets_to_soft_events(plan: StudyPlan) -> Dict[str, int]:
        created = 0
        updated = 0
        targets = plan.session_targets.select_related("course", "topic", "exam").order_by("target_date", "created_at")
        for target in targets:
            user_context = StudyPlannerService._build_study_user_context(plan.course, target)

            title_bits = ["Study"]
            if plan.course.code:
                title_bits.append(plan.course.code)
            else:
                title_bits.append(plan.course.title)
            if target.topic:
                title_bits.append(target.topic.name)
            else:
                title_bits.append(target.focus[:40] if target.focus else "Session")
            soft_title = " — ".join(bit for bit in title_bits if bit)

            description_bits = [target.focus.strip() if target.focus else ""]
            if target.outcome:
                description_bits.append(f"Outcome: {target.outcome.strip()}")
            if target.topic and target.topic.description:
                description_bits.append(target.topic.description.strip())
            description = "\n\n".join(bit for bit in description_bits if bit).strip()

            note_parts = []
            if target.topic:
                note_parts.append(f"Topic: {target.topic.name}")
                note_parts.append(f"Topic status: {target.topic.status}")
            note_parts.append(f"Plan: {plan.name}")
            note_parts.append(f"Target date: {target.target_date.isoformat()}")
            if target.target_preferred_minutes:
                note_parts.append(f"Preferred minutes: {target.target_preferred_minutes}")
            if target.target_min_minutes:
                note_parts.append(f"Minimum minutes: {target.target_min_minutes}")
            notes = "\n\n".join(bit for bit in note_parts if bit).strip()

            soft_deadline, hard_deadline = StudyPlannerService._target_deadlines(plan.course, target)
            priority = int(round((target.topic.weight if target.topic else 1.0) * 10))
            if target.topic:
                topic_status = (target.topic.status or StudyTopic.STATUS_NOT_STARTED).strip()
                if topic_status == StudyTopic.STATUS_MASTERED:
                    priority = max(priority - 8, 1)
                elif topic_status == StudyTopic.STATUS_REVIEW:
                    priority = max(priority - 3, 1)
                elif topic_status == StudyTopic.STATUS_IN_PROGRESS:
                    priority = max(priority + 1, 1)
                else:
                    priority = max(priority + 3, 1)
            if target.exam and target.exam.scheduled_at:
                priority += 10

            defaults = {
                "title": soft_title,
                "description": description,
                "notes": notes,
                "preferred_duration_minutes": max(target.target_preferred_minutes or 60, 1),
                "min_duration_minutes": max(min(target.target_min_minutes or 30, target.target_preferred_minutes or 60), 1),
                "soft_deadline": soft_deadline,
                "hard_deadline": hard_deadline,
                "priority": priority,
                "chat": plan.course.chat,
                "status": SoftEvent.STATUS_ACTIVE,
                "metadata": {
                    "study_plan_id": str(plan.id),
                    "study_session_target_id": str(target.id),
                    "study_course_id": str(plan.course_id),
                    "study_topic_id": str(target.topic_id) if target.topic_id else None,
                    "study_topic_status": target.topic.status if target.topic else None,
                    "study_exam_id": str(target.exam_id) if target.exam_id else None,
                    "source": "study_session_target",
                },
            }

            if target.soft_event_ref:
                soft_event = SoftEvent.objects.filter(id=target.soft_event_ref).first()
                if soft_event:
                    soft_event.title = defaults["title"]
                    soft_event.description = defaults["description"]
                    soft_event.notes = defaults["notes"]
                    soft_event.preferred_duration_minutes = defaults["preferred_duration_minutes"]
                    soft_event.min_duration_minutes = defaults["min_duration_minutes"]
                    soft_event.soft_deadline = defaults["soft_deadline"]
                    soft_event.hard_deadline = defaults["hard_deadline"]
                    soft_event.priority = defaults["priority"]
                    soft_event.chat = defaults["chat"]
                    soft_event.status = defaults["status"]
                    soft_event.metadata = defaults["metadata"]
                    soft_event.save(
                        update_fields=[
                            "title",
                            "description",
                            "notes",
                            "preferred_duration_minutes",
                            "min_duration_minutes",
                            "soft_deadline",
                            "hard_deadline",
                            "priority",
                            "chat",
                            "status",
                            "metadata",
                            "updated_at",
                        ]
                    )
                    updated += 1
                else:
                    target.soft_event_ref = None

            if not target.soft_event_ref:
                soft_event = SoftEvent.objects.create(**defaults)
                target.soft_event_ref = soft_event.id
                target.status = StudySessionTarget.STATUS_SCHEDULED
                target.save(update_fields=["soft_event_ref", "status", "updated_at"])
                created += 1

        return {"created_soft_events": created, "updated_soft_events": updated}

    @staticmethod
    def _resolve_plan_window(course: StudyCourse) -> Tuple[date, date]:
        today = timezone.localdate()
        start_date = course.term_start_date or today
        if start_date < today:
            start_date = today
        exam_date = (
            course.exams.exclude(scheduled_at__isnull=True)
            .order_by("scheduled_at")
            .values_list("scheduled_at", flat=True)
            .first()
        )
        end_candidates = [candidate for candidate in [course.term_end_date, exam_date.date() if exam_date else None] if candidate]
        if end_candidates:
            end_date = max(start_date, min(end_candidates))
        else:
            end_date = start_date + timedelta(days=max(14, course.topics.count() * 3))
        return start_date, end_date

    @staticmethod
    @transaction.atomic
    def recalculate_plan_for_course(
        course: StudyCourse,
        *,
        source_material: Optional[StudyMaterial] = None,
    ) -> Dict[str, Any]:
        current_active = (
            StudyPlan.objects.filter(course=course, status=StudyPlan.STATUS_ACTIVE)
            .order_by("-created_at")
            .first()
        )
        cleanup_stats = {"archived_soft_events": 0, "canceled_slots": 0}
        if current_active:
            cleanup_stats = StudyPlannerService.cleanup_plan_soft_events(current_active)
        plan = StudyPlannerService.create_or_replace_active_plan(
            course,
            name=current_active.name if current_active else None,
        )
        start_date, end_date = StudyPlannerService._resolve_plan_window(course)
        plan.window_start = timezone.make_aware(datetime.combine(start_date, time(hour=6, minute=0)))
        plan.window_end = timezone.make_aware(datetime.combine(end_date, time(hour=22, minute=0)))
        targets = StudyPlannerService.build_session_targets_from_topics(
            plan,
            start_date=start_date,
            end_date=end_date,
        )
        soft_event_stats = StudyPlannerService.sync_session_targets_to_soft_events(plan)
        plan.summary = (
            f"Auto-recalculated from {course.topics.count()} topics"
            + (f" after processing {source_material.title}." if source_material else ".")
        )
        plan.plan_json = {
            "generated_by": "study_ingestion",
            "topic_count": course.topics.count(),
            "target_count": len(targets),
            "source_material_id": str(source_material.id) if source_material else None,
            "soft_event_stats": soft_event_stats,
        }
        plan.save(update_fields=["window_start", "window_end", "summary", "plan_json", "updated_at"])
        return {
            "recalculated": True,
            "plan_id": str(plan.id),
            "target_count": len(targets),
            "window_start": plan.window_start.isoformat() if plan.window_start else None,
            "window_end": plan.window_end.isoformat() if plan.window_end else None,
            "archived_soft_events": cleanup_stats["archived_soft_events"],
            "canceled_slots": cleanup_stats["canceled_slots"],
            "created_soft_events": soft_event_stats["created_soft_events"],
            "updated_soft_events": soft_event_stats["updated_soft_events"],
        }

    @staticmethod
    @transaction.atomic
    def build_session_targets_from_topics(
        plan: StudyPlan,
        *,
        start_date,
        end_date,
        preferred_minutes: int = 60,
        min_minutes: int = 30,
    ) -> List[StudySessionTarget]:
        topics = list(plan.course.topics.all().order_by("order_index", "name"))
        if not topics:
            return []
        targets: List[StudySessionTarget] = []
        day_count = max((end_date - start_date).days + 1, 1)
        topic_index = 0
        for day_offset in range(day_count):
            current_date = start_date + timedelta(days=day_offset)
            topic = topics[topic_index % len(topics)]
            topic_status = (topic.status or StudyTopic.STATUS_NOT_STARTED).strip()
            if topic_status == StudyTopic.STATUS_MASTERED:
                focus = f"Light spaced review for {topic.name}."
                outcome = f"Retain mastery in {topic.name} with quick recall and one mixed checkpoint problem."
            elif topic_status == StudyTopic.STATUS_REVIEW:
                focus = f"Review and reinforce {topic.name}, focusing on previous weak spots."
                outcome = f"Restore confidence and fluency for {topic.name} through targeted review practice."
            elif topic_status == StudyTopic.STATUS_IN_PROGRESS:
                focus = f"Continue building depth in {topic.name}."
                outcome = f"Move {topic.name} toward review readiness by solving representative problems independently."
            else:
                focus = f"Cover {topic.name} thoroughly."
                outcome = f"Be able to explain and solve problems for {topic.name}."
            target = StudySessionTarget.objects.create(
                plan=plan,
                course=plan.course,
                exam=plan.course.exams.order_by("scheduled_at").first(),
                topic=topic,
                target_date=current_date,
                target_preferred_minutes=preferred_minutes,
                target_min_minutes=min_minutes,
                focus=focus,
                outcome=outcome,
            )
            targets.append(target)
            topic_index += 1
        return targets


class StudyProcessingJobService:
    @staticmethod
    def _update_job(job: Job, *, progress: Optional[float] = None, summary: Optional[str] = None, message: str = "") -> None:
        update_fields: List[str] = []
        if progress is not None:
            job.progress = progress
            update_fields.append("progress")
        if summary is not None:
            job.user_visible_summary = summary
            update_fields.append("user_visible_summary")
        if update_fields:
            job.save(update_fields=update_fields + ["updated_at"])
        if message:
            JobService.append_event(
                job,
                role="study",
                event_type=JobEvent.EVENT_PROGRESS if progress is not None else JobEvent.EVENT_INFO,
                visibility=JobEvent.VISIBILITY_USER,
                message=message,
            )

    @staticmethod
    def _cancel_check(job: Job) -> None:
        job.refresh_from_db(fields=["cancel_requested", "status"])
        if job.cancel_requested or job.status == Job.STATUS_CANCELED:
            raise StudyJobCanceled("Study processing canceled")

    @staticmethod
    def run_material_processing_job(job_id: str, material_id: str, *, model: Optional[str] = None, max_pages: Optional[int] = None) -> StudyMaterial:
        job = Job.objects.select_related("module", "active_function").get(id=job_id)
        material = StudyMaterial.objects.select_related("course").get(id=material_id)
        process_function = ToolFunction.objects.filter(manifest_id="study.process_material").first()
        job.status = Job.STATUS_RUNNING
        job.active_function = process_function
        job.progress = 0.01
        job.user_visible_summary = f"Processing {material.title}"
        job.save(update_fields=["status", "active_function", "progress", "user_visible_summary", "updated_at"])
        JobService.append_event(
            job,
            role="study",
            event_type=JobEvent.EVENT_STATE,
            visibility=JobEvent.VISIBILITY_USER,
            message=f"Started processing {material.title}",
        )

        try:
            processed = StudyIngestionService.process_material(
                material,
                model=model,
                max_pages=max_pages,
                progress_callback=lambda progress, message: StudyProcessingJobService._update_job(
                    job,
                    progress=progress,
                    summary=message,
                    message=message,
                ),
                cancel_check=lambda: StudyProcessingJobService._cancel_check(job),
            )
            StudyProcessingJobService._update_job(
                job,
                progress=1.0,
                summary=f"Completed processing {processed.title}",
                message=f"Completed processing {processed.title}",
            )
            JobService.mark_status(job, Job.STATUS_COMPLETED, progress=1.0)
            return processed
        except StudyJobCanceled as exc:
            StudyProcessingJobService._update_job(
                job,
                summary=f"Canceled processing {material.title}",
                message=str(exc),
            )
            JobService.mark_status(job, Job.STATUS_CANCELED, progress=job.progress)
            raise
        except Exception as exc:
            StudyProcessingJobService._update_job(
                job,
                summary=f"Failed processing {material.title}",
                message=str(exc),
            )
            JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
            raise

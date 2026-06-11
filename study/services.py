from __future__ import annotations

import base64
import asyncio
import ast
import concurrent.futures
import json
import logging
from math import ceil
import mimetypes
import os
import re
import shutil
import subprocess
import tempfile
import time as time_module
from datetime import date, datetime, time, timedelta
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import fitz  # PyMuPDF
from PIL import Image, ImageOps
from django.core.files.base import ContentFile
from django.db import models, transaction
from django.utils import timezone

from Corv.config import settings
from openai_integration.services import ChatAIService
from orchestration.objectives import ObjectiveService
from orchestration.model_providers import resolve_provider, get_client
from orchestration.models import (
    Job,
    JobEvent,
    ObjectiveTask,
    SoftEvent,
    SoftEventObjective,
    SoftEventSlot,
    SoftEventTask,
    ToolFunction,
)
from orchestration.services import JobService, ModelConfigService, UserInfoService, UsageService
from study.models import (
    StudyAssignment,
    StudyTopicAudiobookVersion,
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
MAX_IMAGE_EDGE_PX = 2000
MAX_IMAGE_UPLOAD_BYTES = 8 * 1024 * 1024
JPEG_QUALITY_HIGH = 88
JPEG_QUALITY_FALLBACK = 72

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
    "For create include: name, description, summary, order_index, estimated_effort_minutes, weight, status, metadata_patch, why_it_matters, what_to_know, mastery_checks, common_pitfalls, prerequisite_assumptions. "
    "For update include: target_topic_id, description, summary, order_index, estimated_effort_minutes, weight, status, metadata_patch, aliases, why_it_matters, what_to_know, mastery_checks, common_pitfalls, prerequisite_assumptions. "
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

HOMEWORK_ASSIGNMENT_INSTRUCTIONS = (
    "You are assigning solved homework questions from past exams and assignments to an existing ordered lesson catalog. "
    "Return JSON only with keys: summary, assignments. "
    "assignments must be an array of objects with keys: assignment_id, topic_id, rationale. "
    "Assign EVERY provided question to exactly one existing topic whenever reasonably possible. "
    "Prefer broad semantic relevance over exact keyword matching. "
    "Use lesson order_index to keep the study plan coherent and sequential: foundational questions should usually go to earlier lessons. "
    "Do not create topics. Do not duplicate questions across topics. Do not omit a question just because the fit is imperfect; choose the best lesson. "
    "Base the assignment on lesson name, summary, description, metadata, the exact question text, and the source material reference. "
    "Write all strings in English."
)


@dataclass
class RenderedPage:
    index: int
    mime_type: str
    data_url: str


class StudyJobCanceled(Exception):
    pass


AUDIOBOOK_SCRIPT_INSTRUCTIONS = (
    "You are creating a complete, audio-first lesson audiobook script for a university student. "
    "The script must be extensive, detailed, and fully sufficient for solving lesson-related exercises. "
    "It should cover the subject thoroughly enough that a student who listens carefully has the knowledge needed to solve the corresponding exercises with confidence. "
    "Use all provided context: lesson description, summary, metadata, homework assignments, and matching past-exam material. "
    "If audience or user profile context is provided, adapt the depth, pacing, wording, and examples to that target student while still covering the lesson completely. "
    "Explain concepts from fundamentals to advanced exam tactics. "
    "Teach all prerequisite ideas, the core theory, the meaning of the formulas, when each method applies, and how to recognize which approach to use. "
    "Include worked examples, common traps, and step-by-step solving heuristics. "
    "Make sure the final script contains all of the practical knowledge, reasoning patterns, and problem-solving methods needed for the exercise types implied by the lesson material. "
    "Do not omit difficult parts. Do not hand-wave. Do not give a short summary when a full explanation is required. "
    "Write clear spoken language suitable for text-to-speech. "
    "Use a conversational, direct, and slightly friendly tone, like a strong one-on-one tutor speaking to the student. "
    "Sound natural and human, not formal, robotic, academic, or overly scripted. "
    "Address the listener directly when helpful using plain spoken phrasing, but stay focused on teaching. "
    "The final result must flow naturally as an audio-only lesson, as if a skilled tutor is teaching aloud. "
    "Prioritize listening clarity over visual organization. "
    "Do not rely on diagrams, tables, written layout, symbols on a page, or phrases like 'as you can see above' or 'look at the figure'. "
    "Avoid long strings of numbers, excessive variable lists, dense notation dumps, or formatting that is hard to follow by ear. "
    "When formulas or steps are necessary, introduce them slowly in spoken form and immediately explain what they mean and how they are used. "
    "This script will be fed directly into a TTS engine, so it must be plain text only. "
    "Do not use markdown, headings, bullet points, numbered lists, tables, code blocks, emojis, symbols, decorative separators, or formatting markup of any kind. "
    "Do not include special characters unless they are standard sentence punctuation needed for natural speech. "
    "Do not wrap words in quotes for emphasis and do not use shorthand notation that sounds unnatural when read aloud. "
    "Organize the lesson naturally in plain paragraphs using simple transitions instead of formatting. "
    "Cover, in order, the lesson overview, the core theory and formulas, how to solve the main exercise types, worked walkthroughs, typical mistakes and how to avoid them, a rapid revision recap, and self-test practice prompts."
)


class StudyTopicAudiobookService:
    """Generate and persist detailed lesson audiobook versions."""

    @staticmethod
    def _normalize_script_for_tts(script: str) -> str:
        text = (script or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"^\s{0,3}(?:[-*•]+|\d+[.)])\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"[*_`#>\[\]\{\}|~]+", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _get_audience_context(topic: StudyTopic) -> dict[str, Any]:
        course = topic.course
        user_scope = str(course.chat_id) if course.chat_id else None
        profile = UserInfoService.get_core_profile(user_scope)
        profile_text = (profile.core_text or "").strip() if profile else ""

        if not profile_text and user_scope:
            fallback_profile = UserInfoService.get_core_profile()
            profile_text = (fallback_profile.core_text or "").strip() if fallback_profile else ""

        return {
            "chat_id": str(course.chat_id) if course.chat_id else None,
            "user_profile": profile_text or None,
        }

    @staticmethod
    def _collect_topic_context(topic: StudyTopic) -> dict[str, Any]:
        course = topic.course
        homework = topic.homework if isinstance(topic.homework, list) else []
        exams = list(course.exams.exclude(scheduled_at__isnull=True).order_by("scheduled_at"))
        topic_materials = list(
            StudyMaterial.objects.filter(course=course)
            .filter(models.Q(topic=topic) | models.Q(kind__in=[StudyMaterial.KIND_PAST_EXAM, "exam", "assignment", "worksheet"]))
            .order_by("-created_at")[:12]
        )

        material_blobs: list[dict[str, Any]] = []
        for material in topic_materials:
            excerpt = "\n\n".join(
                part
                for part in [
                    (material.theory_markdown or "").strip(),
                    (material.solved_markdown or "").strip(),
                    (material.converted_markdown or "").strip(),
                ]
                if part
            )
            if len(excerpt) > 6000:
                excerpt = excerpt[:6000] + "\n\n...[truncated]"
            material_blobs.append(
                {
                    "id": str(material.id),
                    "kind": material.kind,
                    "title": material.title,
                    "excerpt": excerpt,
                    "notes": material.notes,
                }
            )

        return {
            "topic": {
                "id": str(topic.id),
                "name": topic.name,
                "description": topic.description,
                "summary": _normalize_topic_summary(topic.summary),
                "status": topic.status,
                "estimated_effort_minutes": topic.estimated_effort_minutes,
                "weight": topic.weight,
                "metadata": topic.metadata or {},
            },
            "course": {
                "id": str(course.id),
                "title": course.title,
                "code": course.code,
                "description": course.description,
                "term_end_date": course.term_end_date.isoformat() if course.term_end_date else None,
            },
            "homework": homework,
            "upcoming_exams": [
                {
                    "title": exam.title,
                    "kind": exam.kind,
                    "scheduled_at": exam.scheduled_at.isoformat() if exam.scheduled_at else None,
                    "notes": exam.notes,
                }
                for exam in exams
            ],
            "materials": material_blobs,
            "audience_context": StudyTopicAudiobookService._get_audience_context(topic),
        }

    @staticmethod
    def _generate_script(topic: StudyTopic, *, model: Optional[str] = None) -> tuple[str, str]:
        model_name = model or ModelConfigService.get_study_model()
        provider = resolve_provider(model_name)
        context = StudyTopicAudiobookService._collect_topic_context(topic)
        prompt = (
            f"{AUDIOBOOK_SCRIPT_INSTRUCTIONS}\n\n"
            f"Topic audiobook request for lesson: {topic.name}\n"
            f"Data:\n{json.dumps(context, ensure_ascii=True, default=str)}"
        )

        if provider == "openai":
            response = get_client("openai").with_options(max_retries=0).responses.create(
                model=model_name,
                input=[{"role": "developer", "content": [{"type": "input_text", "text": prompt}]}],
                text={"format": {"type": "text"}, "verbosity": "high"},
                reasoning={"effort": "medium"},
                store=False,
                timeout=120,
            )
            usage_obj = getattr(response, "usage", None)
            if usage_obj:
                UsageService.log_usage(
                    source="study_audiobook_script",
                    model=model_name,
                    cache_mode=ModelConfigService.get_cache_mode(),
                    usage=usage_obj,
                    job=None,
                )
            script = StudyTopicAudiobookService._normalize_script_for_tts(
                (getattr(response, "output_text", None) or "").strip()
            )
            return script, model_name

        response = get_client("xai").chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": AUDIOBOOK_SCRIPT_INSTRUCTIONS},
                {"role": "user", "content": f"Data:\n{json.dumps(context, ensure_ascii=True, default=str)}"},
            ],
            timeout=120,
        )
        usage_obj = getattr(response, "usage", None)
        if usage_obj:
            UsageService.log_usage(
                source="study_audiobook_script",
                model=model_name,
                cache_mode=ModelConfigService.get_cache_mode(),
                usage=usage_obj,
                job=None,
            )
        script = ""
        if getattr(response, "choices", None):
            script = StudyTopicAudiobookService._normalize_script_for_tts(
                (response.choices[0].message.content or "").strip()  # type: ignore[assignment]
            )
        return script, model_name

    @staticmethod
    def _render_audio(script: str, *, voice: str = "alloy", model: str = "gpt-4o-mini-tts") -> tuple[bytes, str]:
        if not script.strip():
            raise ValueError("Cannot render empty audiobook script")
        provider = str(os.getenv("AUDIOBOOK_TTS_PROVIDER", "edge")).strip().lower()

        if provider in {"edge", "edge-tts", "ms", "microsoft"}:
            return StudyTopicAudiobookService._render_audio_edge(script, voice=voice)

        if provider in {"open_source", "local", "espeak", "espeak-ng"}:
            return StudyTopicAudiobookService._render_audio_open_source(script, voice=voice)

        response = get_client("openai").audio.speech.create(
            model=model,
            voice=voice,
            input=script,
            response_format="mp3",
        )
        if hasattr(response, "read"):
            audio_bytes = response.read()
        elif isinstance(response, (bytes, bytearray)):
            audio_bytes = bytes(response)
        elif hasattr(response, "content"):
            audio_bytes = bytes(response.content)
        else:
            raise RuntimeError("TTS returned unexpected response payload")
        if not audio_bytes:
            raise RuntimeError("TTS returned empty audio")
        return audio_bytes, "audio/mpeg"

    @staticmethod
    def _split_text_for_tts(text: str, *, max_chars: int = 2400) -> List[str]:
        source = re.sub(r"\s+", " ", text).strip()
        if not source:
            return []
        if len(source) <= max_chars:
            return [source]

        sentences = re.split(r"(?<=[.!?])\s+", source)
        chunks: List[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                for i in range(0, len(sentence), max_chars):
                    chunks.append(sentence[i : i + max_chars])
                continue

            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = sentence

        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _render_audio_edge(script: str, *, voice: str = "alloy") -> tuple[bytes, str]:
        try:
            import edge_tts  # type: ignore
        except Exception as exc:
            # Fallback to local open-source engine if edge-tts is unavailable.
            return StudyTopicAudiobookService._render_audio_open_source(script, voice=voice)

        default_voice = os.getenv("AUDIOBOOK_EDGE_VOICE", "en-US-EmmaMultilingualNeural")
        candidate_voice = (voice or "").strip()
        edge_voice = (
            candidate_voice
            if candidate_voice.endswith("Neural") or "-" in candidate_voice
            else default_voice
        )

        rate = os.getenv("AUDIOBOOK_EDGE_RATE", "+0%")
        pitch = os.getenv("AUDIOBOOK_EDGE_PITCH", "+0Hz")
        volume = os.getenv("AUDIOBOOK_EDGE_VOLUME", "+0%")
        max_chars = int(os.getenv("AUDIOBOOK_EDGE_MAX_CHARS", "2400"))

        chunks = StudyTopicAudiobookService._split_text_for_tts(script, max_chars=max_chars)
        if not chunks:
            raise RuntimeError("No text to synthesize")

        async def synth_once(text_chunk: str) -> bytes:
            comm = edge_tts.Communicate(text_chunk, edge_voice, rate=rate, pitch=pitch, volume=volume)
            data: List[bytes] = []
            async for part in comm.stream():
                if part.get("type") == "audio":
                    chunk_data = part.get("data")
                    if isinstance(chunk_data, (bytes, bytearray)):
                        data.append(bytes(chunk_data))
            return b"".join(data)

        async def synth_all() -> bytes:
            merged: List[bytes] = []
            for item in chunks:
                segment = await synth_once(item)
                if segment:
                    merged.append(segment)
            return b"".join(merged)

        try:
            audio_bytes = asyncio.run(synth_all())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                audio_bytes = loop.run_until_complete(synth_all())
            finally:
                loop.close()

        if not audio_bytes:
            raise RuntimeError("edge-tts returned empty audio")
        return audio_bytes, "audio/mpeg"

    @staticmethod
    def _render_audio_open_source(script: str, *, voice: str = "alloy") -> tuple[bytes, str]:
        exe = shutil.which("espeak-ng") or shutil.which("espeak")
        if not exe:
            raise RuntimeError("Open-source TTS engine not found (missing espeak-ng/espeak)")

        rate = int(os.getenv("AUDIOBOOK_TTS_RATE", "165"))
        pitch = int(os.getenv("AUDIOBOOK_TTS_PITCH", "50"))
        volume = int(os.getenv("AUDIOBOOK_TTS_VOLUME", "100"))
        # espeak voices differ from cloud voice names; map unknown names to english default.
        espeak_voice = voice if voice and voice not in {"alloy", "nova", "shimmer", "echo", "fable", "onyx"} else "en-us"

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = tmp.name

        try:
            proc = subprocess.run(
                [
                    exe,
                    "-v",
                    espeak_voice,
                    "-s",
                    str(rate),
                    "-p",
                    str(pitch),
                    "-a",
                    str(volume),
                    "--stdin",
                    "-w",
                    out_path,
                ],
                input=script.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=True,
            )
            _ = proc
            with open(out_path, "rb") as fh:
                audio_bytes = fh.read()
        except subprocess.CalledProcessError as exc:
            stderr_text = (exc.stderr or b"").decode("utf-8", errors="ignore").strip()
            raise RuntimeError(f"Open-source TTS failed: {stderr_text or exc}") from exc
        finally:
            try:
                os.remove(out_path)
            except Exception:
                pass

        if not audio_bytes:
            raise RuntimeError("Open-source TTS returned empty audio")
        return audio_bytes, "audio/wav"

    @staticmethod
    def create_topic_audiobook_version(
        topic: StudyTopic,
        *,
        generation_notes: str = "",
        job: Optional[Job] = None,
    ) -> StudyTopicAudiobookVersion:
        last_version = (
            StudyTopicAudiobookVersion.objects.filter(topic=topic)
            .order_by("-version_number")
            .first()
        )
        next_version = int(last_version.version_number) + 1 if last_version else 1
        version = StudyTopicAudiobookVersion.objects.create(
            topic=topic,
            version_number=next_version,
            status=StudyTopicAudiobookVersion.STATUS_PENDING,
            generation_notes=(generation_notes or "").strip(),
            job=job,
            metadata={"source": "study_topic_audiobook"},
        )
        return version

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
    def run_audiobook_generation_job(
        job_id: str,
        topic_id: str,
        version_id: str,
        *,
        model: Optional[str] = None,
        voice: str = "alloy",
    ) -> StudyTopicAudiobookVersion:
        job = Job.objects.select_related("module", "active_function").get(id=job_id)
        topic = StudyTopic.objects.select_related("course").get(id=topic_id)
        version = StudyTopicAudiobookVersion.objects.get(id=version_id)

        process_function = ToolFunction.objects.filter(manifest_id="study.generate_topic_audiobook").first()
        job.status = Job.STATUS_RUNNING
        job.active_function = process_function
        job.progress = 0.02
        job.user_visible_summary = f"Generating audiobook for {topic.name}"
        job.save(update_fields=["status", "active_function", "progress", "user_visible_summary", "updated_at"])

        version.status = StudyTopicAudiobookVersion.STATUS_PROCESSING
        version.processing_error = ""
        version.save(update_fields=["status", "processing_error", "updated_at"])

        try:
            StudyTopicAudiobookService._update_job(
                job,
                progress=0.15,
                summary=f"Drafting audiobook script for {topic.name}",
                message=f"Drafting audiobook script for lesson {topic.name}",
            )
            script_markdown, script_model = StudyTopicAudiobookService._generate_script(topic, model=model)
            if not script_markdown.strip():
                raise RuntimeError("Model returned empty audiobook script")

            version.script_markdown = script_markdown
            version.tts_voice = voice
            tts_provider = str(os.getenv("AUDIOBOOK_TTS_PROVIDER", "edge")).strip().lower()
            if tts_provider in {"edge", "edge-tts", "ms", "microsoft"}:
                version.tts_model = "edge-tts"
            elif tts_provider in {"open_source", "local", "espeak", "espeak-ng"}:
                version.tts_model = "espeak-ng"
            else:
                version.tts_model = "gpt-4o-mini-tts"
            version.metadata = {
                **(version.metadata or {}),
                "script_model": script_model,
                "topic_id": str(topic.id),
                "course_id": str(topic.course_id),
                "generated_at": timezone.now().isoformat(),
            }
            version.save(update_fields=["script_markdown", "tts_voice", "tts_model", "metadata", "updated_at"])

            StudyTopicAudiobookService._update_job(
                job,
                progress=0.65,
                summary=f"Rendering audiobook audio for {topic.name}",
                message="Converting script to audio",
            )
            audio_bytes, mime_type = StudyTopicAudiobookService._render_audio(script_markdown, voice=voice)
            extension = "wav" if mime_type == "audio/wav" else "mp3"
            filename = f"topic-{topic.id}-v{version.version_number}.{extension}"
            version.audio_file.save(filename, ContentFile(audio_bytes), save=False)
            version.audio_mime_type = mime_type
            version.status = StudyTopicAudiobookVersion.STATUS_READY
            version.processing_error = ""
            version.save(update_fields=["audio_file", "audio_mime_type", "status", "processing_error", "updated_at"])

            StudyTopicAudiobookService._update_job(
                job,
                progress=1.0,
                summary=f"Audiobook ready for {topic.name}",
                message=f"Audiobook version v{version.version_number} is ready",
            )
            JobService.mark_status(job, Job.STATUS_COMPLETED, progress=1.0)
            return version
        except Exception as exc:
            version.status = StudyTopicAudiobookVersion.STATUS_FAILED
            version.processing_error = str(exc)
            version.save(update_fields=["status", "processing_error", "updated_at"])
            StudyTopicAudiobookService._update_job(
                job,
                summary=f"Audiobook generation failed for {topic.name}",
                message=str(exc),
            )
            JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
            raise


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
            # Normalize orientation and cap dimensions to avoid oversized API payloads.
            frame = ImageOps.exif_transpose(img).convert("RGB")
            width, height = frame.size
            max_edge = max(width, height)
            if max_edge > MAX_IMAGE_EDGE_PX:
                scale = MAX_IMAGE_EDGE_PX / float(max_edge)
                resample = getattr(Image, "Resampling", Image).LANCZOS
                frame = frame.resize(
                    (
                        max(1, int(round(width * scale))),
                        max(1, int(round(height * scale))),
                    ),
                    resample,
                )
            from io import BytesIO

            buffer = BytesIO()
            frame.save(buffer, format="JPEG", quality=JPEG_QUALITY_HIGH, optimize=True)
            data = buffer.getvalue()
            if len(data) > MAX_IMAGE_UPLOAD_BYTES:
                buffer = BytesIO()
                frame.save(buffer, format="JPEG", quality=JPEG_QUALITY_FALLBACK, optimize=True)
                data = buffer.getvalue()

            rendered.append(
                RenderedPage(
                    index=index + 1,
                    mime_type="image/jpeg",
                    data_url=_bytes_to_data_url(data, "image/jpeg"),
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
    def _extract_page_with_heartbeat(
        material: StudyMaterial,
        page: RenderedPage,
        *,
        page_index: int,
        page_total: int,
        model: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None,
        cancel_check: Optional[Callable[[], None]] = None,
        heartbeat_seconds: float = 12.0,
    ) -> Dict[str, Any]:
        start = time_module.monotonic()
        heartbeat_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(StudyIngestionService._extract_page, material, page, model)
            while True:
                StudyIngestionService._ensure_not_canceled(cancel_check)
                try:
                    return future.result(timeout=heartbeat_seconds)
                except concurrent.futures.TimeoutError:
                    heartbeat_count += 1
                    elapsed = int(time_module.monotonic() - start)
                    StudyIngestionService._emit_progress(
                        progress_callback,
                        0.1 + (0.6 * ((page_index - 1) / max(page_total, 1))),
                        (
                            f"Still analyzing page {page_index} of {page_total} "
                            f"({elapsed}s elapsed, heartbeat {heartbeat_count})"
                        ),
                    )
                    continue

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
                    maybe_order_index = action.get("order_index")
                    if isinstance(maybe_order_index, int):
                        next_order = max(int(maybe_order_index), 0)
                        if next_order != existing.order_index:
                            existing.order_index = next_order
                            update_fields_local.append("order_index")
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
                    ObjectiveService.ensure_topic_objective(existing)
                    StudyIngestionService._ensure_topic_mastery(course, existing)
                    touched_topics.append(existing)
                    continue
                course_objective = ObjectiveService.ensure_course_objective(course)
                topic = StudyTopic.objects.create(
                    course=course,
                    objective=ObjectiveService.create_child_objective(
                        parent=course_objective,
                        title=f"Study {raw_name}",
                        description=StudyIngestionService._build_rich_topic_description(raw_name, action),
                        deadline_at=course_objective.deadline_at,
                        estimated_effort_minutes=max(int(action.get("estimated_effort_minutes") or 60), 1),
                        remaining_effort_minutes=max(int(action.get("estimated_effort_minutes") or 60), 1),
                        priority=int(round(float(action.get("weight") or 1.0) * 10)),
                        metadata={"source": "study_topic"},
                    ),
                    name=raw_name,
                    description=StudyIngestionService._build_rich_topic_description(raw_name, action),
                    summary=_normalize_topic_summary(action.get("summary")),
                    order_index=max(int(action.get("order_index") or course.topics.count()), 0),
                    estimated_effort_minutes=max(int(action.get("estimated_effort_minutes") or 60), 1),
                    weight=float(action.get("weight") or 1.0),
                    status=(str(action.get("status") or StudyTopic.STATUS_NOT_STARTED).strip() if str(action.get("status") or "").strip() in valid_statuses else StudyTopic.STATUS_NOT_STARTED),
                    metadata=StudyIngestionService._topic_metadata_from_action(action),
                )
                ObjectiveService.ensure_topic_objective(topic)
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
                maybe_order_index = action.get("order_index")
                if isinstance(maybe_order_index, int):
                    next_order = max(int(maybe_order_index), 0)
                    if next_order != topic.order_index:
                        topic.order_index = next_order
                        update_fields.append("order_index")
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
                ObjectiveService.ensure_topic_objective(topic)
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
                    StudyIngestionService._emit_progress(
                        progress_callback,
                        0.1 + (0.6 * ((page_index - 1) / max(page_total, 1))),
                        f"Analyzing page {page_index} of {page_total}",
                    )
                    try:
                        result = StudyIngestionService._extract_page_with_heartbeat(
                            material,
                            page,
                            page_index=page_index,
                            page_total=page_total,
                            model=model,
                            progress_callback=progress_callback,
                            cancel_check=cancel_check,
                        )
                    except Exception as exc:
                        if "timed out" in str(exc).lower():
                            raise TimeoutError(
                                f"Timed out while analyzing page {page_index} of {page_total}. "
                                "Try a clearer crop or PDF export for this page."
                            ) from exc
                        raise
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

            StudyIngestionService._emit_progress(progress_callback, 0.9, "Recalculating study plan")
            plan_refresh: Dict[str, Any] = StudyPlannerService.recalculate_plan_for_course(
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
    def _past_exam_question_text(raw_question: Any) -> str:
        if isinstance(raw_question, str):
            return raw_question.strip()
        if isinstance(raw_question, dict):
            for key in ("question", "prompt", "text", "task", "title", "body", "label"):
                value = raw_question.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            # Fallback: collect meaningful string fragments from arbitrary model output.
            preferred: List[str] = []
            secondary: List[str] = []

            def collect_strings(value: Any, *, depth: int = 0, key_name: str = "") -> None:
                if depth > 2:
                    return
                if isinstance(value, str):
                    text = value.strip()
                    if not text:
                        return
                    lowered = key_name.lower()
                    if lowered in {"label", "question_number", "number", "exercise"}:
                        preferred.append(text)
                    else:
                        secondary.append(text)
                    return
                if isinstance(value, dict):
                    for child_key, child_value in value.items():
                        collect_strings(child_value, depth=depth + 1, key_name=str(child_key))
                    return
                if isinstance(value, list):
                    for child in value[:6]:
                        collect_strings(child, depth=depth + 1, key_name=key_name)

            collect_strings(raw_question)
            merged = [part for part in [*preferred, *secondary] if part]
            if merged:
                return " — ".join(merged[:3])[:500].strip()
        return ""

    @staticmethod
    def _topic_text_for_homework_scoring(topic: StudyTopic) -> str:
        metadata = topic.metadata if isinstance(topic.metadata, dict) else {}
        metadata_bits: List[str] = []
        for value in metadata.values():
            if isinstance(value, str) and value.strip():
                metadata_bits.append(value.strip())
            elif isinstance(value, list):
                metadata_bits.extend(str(item).strip() for item in value if str(item).strip())
        return "\n".join(
            part for part in [topic.name, topic.summary, topic.description, *metadata_bits] if str(part).strip()
        )

    @staticmethod
    def _tokenize_homework_text(text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(token) >= 3}

    @staticmethod
    def _fallback_topic_for_homework_question(question: Dict[str, Any], topics: List[StudyTopic]) -> StudyTopic:
        question_text = " ".join(
            str(part).strip()
            for part in [
                question.get("text"),
                question.get("source_exercise_label"),
                question.get("source_material_title"),
            ]
            if str(part or "").strip()
        )
        question_tokens = StudyPlannerService._tokenize_homework_text(question_text)
        scored: List[Tuple[int, int, StudyTopic]] = []
        for topic in topics:
            topic_tokens = StudyPlannerService._tokenize_homework_text(
                StudyPlannerService._topic_text_for_homework_scoring(topic)
            )
            overlap = len(question_tokens & topic_tokens)
            score = overlap * 10
            if topic.name and topic.name.lower() in question_text.lower():
                score += 15
            scored.append((score, -int(topic.order_index), topic))
        scored.sort(reverse=True, key=lambda item: (item[0], item[1]))
        return scored[0][2] if scored else topics[0]

    @staticmethod
    def _request_homework_topic_assignments(
        course: StudyCourse,
        topics: List[StudyTopic],
        questions: List[Dict[str, Any]],
        *,
        model: Optional[str] = None,
        source_material: Optional[StudyMaterial] = None,
    ) -> Dict[str, str]:
        if not topics or not questions:
            return {}

        model_name = model or ModelConfigService.get_study_model()
        topic_payload = [
            {
                "id": str(topic.id),
                "name": topic.name,
                "order_index": topic.order_index,
                "summary": topic.summary,
                "description": topic.description,
                "metadata": topic.metadata if isinstance(topic.metadata, dict) else {},
            }
            for topic in topics
        ]
        question_payload = [
            {
                "assignment_id": str(question.get("assignment_id") or ""),
                "text": str(question.get("text") or "").strip(),
                "source_material_title": str(question.get("source_material_title") or "").strip(),
                "source_exercise_label": str(question.get("source_exercise_label") or "").strip(),
                "question_index": question.get("question_index"),
            }
            for question in questions
        ]
        payload = {
            "course": {
                "id": str(course.id),
                "title": course.title,
                "code": course.code,
            },
            "source_material": {
                "id": str(source_material.id),
                "title": source_material.title,
                "kind": source_material.kind,
            }
            if source_material
            else None,
            "topics": topic_payload,
            "questions": question_payload,
        }

        resp = get_client("openai").with_options(max_retries=0).responses.create(
            model=model_name,
            input=[
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": HOMEWORK_ASSIGNMENT_INSTRUCTIONS}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(payload, ensure_ascii=True)}],
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
                source="study_homework_assignment",
                model=model_name,
                cache_mode=ModelConfigService.get_cache_mode(),
                usage=usage_obj,
                job=None,
            )

        raw = getattr(resp, "output_text", "") or "{}"
        data = _safe_json_load(raw)
        assignments = data.get("assignments") if isinstance(data.get("assignments"), list) else []
        valid_topic_ids = {str(topic.id) for topic in topics}
        valid_assignment_ids = {str(question.get("assignment_id") or "") for question in questions}

        mapped: Dict[str, str] = {}
        for item in assignments:
            if not isinstance(item, dict):
                continue
            assignment_id = str(item.get("assignment_id") or "").strip()
            topic_id = str(item.get("topic_id") or "").strip()
            if not assignment_id or not topic_id:
                continue
            if assignment_id not in valid_assignment_ids or topic_id not in valid_topic_ids:
                continue
            if assignment_id in mapped:
                continue
            mapped[assignment_id] = topic_id
        return mapped

    @staticmethod
    def _collect_past_exam_questions(course: StudyCourse) -> List[Dict[str, Any]]:
        questions: List[Dict[str, Any]] = []
        materials = (
            StudyMaterial.objects.filter(
                course=course,
                kind__in=[StudyMaterial.KIND_PAST_EXAM, "exam", "assignment", "worksheet"],
                ingestion_status=StudyMaterial.INGESTION_PROCESSED,
            )
            .order_by("created_at")
        )

        for material in materials:
            extracted = material.extracted_data if isinstance(material.extracted_data, dict) else {}
            raw_questions = extracted.get("questions") if isinstance(extracted, dict) else []
            if not isinstance(raw_questions, list):
                raw_questions = []

            # Fallback: if top-level questions are missing, try page-level extraction blocks.
            if not raw_questions:
                page_blocks = extracted.get("pages") if isinstance(extracted, dict) else []
                if isinstance(page_blocks, list):
                    for page in page_blocks:
                        if not isinstance(page, dict):
                            continue
                        page_data = page.get("extracted_data")
                        if not isinstance(page_data, dict):
                            continue
                        page_questions = page_data.get("questions")
                        if isinstance(page_questions, list):
                            raw_questions.extend(page_questions)

            for idx, raw_question in enumerate(raw_questions, start=1):
                text = StudyPlannerService._past_exam_question_text(raw_question)
                if not text:
                    continue
                questions.append(
                    {
                        "assignment_id": f"{material.id}:{idx}",
                        "source_material_id": str(material.id),
                        "source_material_title": material.title,
                        "source_exercise_label": (
                            str(
                                raw_question.get("label")
                                or raw_question.get("question_number")
                                or raw_question.get("number")
                                or raw_question.get("exercise")
                                or ""
                            ).strip()
                            if isinstance(raw_question, dict)
                            else ""
                        ),
                        "question_index": idx,
                        "text": text,
                        "raw": raw_question if isinstance(raw_question, dict) else {"question": text},
                    }
                )

        return questions

    @staticmethod
    def assign_past_exam_homework_to_topics(
        course: StudyCourse,
        *,
        source_material: Optional[StudyMaterial] = None,
        model: Optional[str] = None,
    ) -> Dict[str, int]:
        topics = list(course.topics.all().order_by("order_index", "name"))
        if not topics:
            return {
                "past_exam_question_count": 0,
                "topics_with_homework": 0,
                "model_assigned_count": 0,
                "fallback_assigned_count": 0,
            }

        questions = StudyPlannerService._collect_past_exam_questions(course)
        existing_done_state: Dict[str, bool] = {}
        for topic in topics:
            if not isinstance(topic.homework, list):
                continue
            for item in topic.homework:
                if not isinstance(item, dict):
                    continue
                assignment_id = str(item.get("assignment_id") or "").strip()
                if assignment_id:
                    existing_done_state[assignment_id] = bool(item.get("done"))

        if not questions:
            for topic in topics:
                if topic.homework:
                    topic.homework = []
                    topic.save(update_fields=["homework", "updated_at"])
            return {
                "past_exam_question_count": 0,
                "topics_with_homework": 0,
                "model_assigned_count": 0,
                "fallback_assigned_count": 0,
            }

        assignment_map: Dict[str, str] = {}
        try:
            assignment_map = StudyPlannerService._request_homework_topic_assignments(
                course,
                topics,
                questions,
                model=model,
                source_material=source_material,
            )
        except Exception:
            StudyIngestionService.logger.exception(
                "Homework assignment model call failed for course %s; using semantic fallback",
                course.id,
            )

        topic_buckets: Dict[str, List[Dict[str, Any]]] = {str(topic.id): [] for topic in topics}
        model_assigned_count = 0
        fallback_assigned_count = 0
        topics_by_id = {str(topic.id): topic for topic in topics}
        for question in questions:
            assignment_id = str(question.get("assignment_id") or "").strip()
            topic_id = assignment_map.get(assignment_id)
            topic = topics_by_id.get(topic_id) if topic_id else None
            if topic is None:
                topic = StudyPlannerService._fallback_topic_for_homework_question(question, topics)
                fallback_assigned_count += 1
            else:
                model_assigned_count += 1

            topic_buckets[str(topic.id)].append(
                {
                    **question,
                    "done": existing_done_state.get(assignment_id, False),
                }
            )

        topics_with_homework = 0
        for topic in topics:
            assigned = topic_buckets[str(topic.id)]
            assigned.sort(
                key=lambda item: (
                    str(item.get("source_material_title") or "").lower(),
                    str(item.get("source_exercise_label") or "").lower(),
                    int(item.get("question_index") or 0),
                )
            )
            topic.homework = assigned
            topic.save(update_fields=["homework", "updated_at"])
            ObjectiveService.ensure_topic_objective(topic)
            if assigned:
                topics_with_homework += 1

        return {
            "past_exam_question_count": len(questions),
            "topics_with_homework": topics_with_homework,
            "model_assigned_count": model_assigned_count,
            "fallback_assigned_count": fallback_assigned_count,
        }

    @staticmethod
    @transaction.atomic
    def sync_session_targets_to_soft_events(plan: StudyPlan) -> Dict[str, int]:
        created = 0
        updated = 0
        targets = plan.session_targets.select_related("course", "topic", "exam").order_by("target_date", "created_at")
        for target in targets:
            user_context = StudyPlannerService._build_study_user_context(plan.course, target)
            topic_objective = None
            topic_task_ids: list[str] = []
            if target.topic_id and target.topic and getattr(target.topic, "objective_id", None):
                topic_objective = ObjectiveService.ensure_topic_objective(target.topic)
                topic_task_ids = [
                    str(task.id)
                    for task in topic_objective.tasks.exclude(
                        status__in=[ObjectiveTask.STATUS_DONE, ObjectiveTask.STATUS_CANCELED]
                    ).order_by("sort_order", "created_at")
                ]

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
            target_homework = []
            if target.topic and isinstance(target.topic.homework, list):
                target_homework = [item for item in target.topic.homework if isinstance(item, dict)]
            if target_homework:
                note_parts.append(
                    f"Lesson homework: {len(target_homework)} past-exam question(s) assigned to this lesson."
                )
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
                    "objective_id": str(topic_objective.id) if topic_objective else None,
                    "study_topic_id": str(target.topic_id) if target.topic_id else None,
                    "study_topic_status": target.topic.status if target.topic else None,
                    "study_exam_id": str(target.exam_id) if target.exam_id else None,
                    "study_topic_homework_count": len(target_homework),
                    "study_topic_homework_required": bool(target_homework),
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
            else:
                soft_event = SoftEvent.objects.filter(id=target.soft_event_ref).first()

            if soft_event and topic_objective:
                SoftEventObjective.objects.update_or_create(
                    soft_event=soft_event,
                    objective=topic_objective,
                    defaults={"role": SoftEventObjective.ROLE_PRIMARY},
                )
                existing_task_ids = set(
                    SoftEventTask.objects.filter(soft_event=soft_event).values_list("task_id", flat=True)
                )
                desired_task_ids = {task_id for task_id in topic_task_ids}
                stale_task_ids = existing_task_ids - desired_task_ids
                if stale_task_ids:
                    SoftEventTask.objects.filter(
                        soft_event=soft_event,
                        task_id__in=stale_task_ids,
                    ).delete()
                for task_id in desired_task_ids - existing_task_ids:
                    SoftEventTask.objects.create(soft_event=soft_event, task_id=task_id)

        return {"created_soft_events": created, "updated_soft_events": updated}

    @staticmethod
    def _resolve_plan_window(course: StudyCourse) -> Tuple[date, date]:
        today = timezone.localdate()
        start_date = course.term_start_date or today
        if start_date < today:
            start_date = today
        # Use the last exam date so the window always covers all pre-exam revision days.
        last_exam_date = (
            course.exams.exclude(scheduled_at__isnull=True)
            .order_by("-scheduled_at")
            .values_list("scheduled_at", flat=True)
            .first()
        )
        end_candidates = [
            candidate
            for candidate in [course.term_end_date, last_exam_date.date() if last_exam_date else None]
            if candidate
        ]
        if end_candidates:
            end_date = max(start_date, max(end_candidates))
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
        ObjectiveService.ensure_course_objective(course)
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
        homework_stats = StudyPlannerService.assign_past_exam_homework_to_topics(
            course,
            source_material=source_material,
        )
        soft_event_stats = ObjectiveService.rebuild_objective_soft_events_for_window(
            plan.window_start,
            plan.window_end,
        )
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
            "homework_stats": homework_stats,
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
            "created_soft_events": soft_event_stats.get("planned_soft_events", 0),
            "updated_soft_events": 0,
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
        topic_sequence: List[StudyTopic] = []
        for topic in topics:
            ObjectiveService.ensure_topic_objective(topic)
            remaining_minutes = (
                topic.objective.remaining_effort_minutes
                or topic.objective.estimated_effort_minutes
                or topic.estimated_effort_minutes
                or preferred_minutes
            )
            topic_status = (topic.status or StudyTopic.STATUS_NOT_STARTED).strip()
            if topic.passed or topic_status == StudyTopic.STATUS_MASTERED:
                sessions_needed = 1
            else:
                sessions_needed = max(int(ceil(max(int(remaining_minutes), 1) / max(preferred_minutes, 1))), 1)
            topic_sequence.extend([topic] * sessions_needed)
        if not topic_sequence:
            topic_sequence = topics

        for index, topic in enumerate(topic_sequence):
            current_date = start_date + timedelta(days=(index % day_count))
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

        # Add a pre-exam revision target for each upcoming exam (the day before).
        exams_in_window = (
            plan.course.exams.exclude(scheduled_at__isnull=True)
            .order_by("scheduled_at")
        )
        for exam in exams_in_window:
            revision_date = (exam.scheduled_at - timedelta(days=1)).date()
            if revision_date < start_date or revision_date > end_date:
                continue
            revision_target = StudySessionTarget.objects.create(
                plan=plan,
                course=plan.course,
                exam=exam,
                target_date=revision_date,
                target_preferred_minutes=90,
                target_min_minutes=45,
                focus=f"Pre-exam revision: consolidate all topics for {exam.title}.",
                outcome=f"Walk into {exam.title} confident across all course topics.",
            )
            targets.append(revision_target)

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


class AssignmentService:
    """Service for study assignment management: PDF processing, planning, and soft event creation."""

    logger = logging.getLogger(__name__)

    @staticmethod
    def uploaded_file_path(assignment: StudyAssignment) -> str:
        uploaded_file = getattr(assignment, "uploaded_file", None)
        if uploaded_file:
            try:
                if getattr(uploaded_file, "path", ""):
                    return str(uploaded_file.path).strip()
            except Exception:
                pass
        return str((assignment.metadata or {}).get("uploaded_file_path") or "").strip()

    @staticmethod
    def uploaded_file_name(assignment: StudyAssignment) -> str:
        uploaded_file = getattr(assignment, "uploaded_file", None)
        if uploaded_file:
            name = str(getattr(uploaded_file, "name", "") or "").strip()
            if name:
                return os.path.basename(name)
        return str((assignment.metadata or {}).get("uploaded_file_name") or "").strip()

    @staticmethod
    def extract_material_text_from_file(
        uploaded_file,
        *,
        course: Optional[StudyCourse] = None,
        title: Optional[str] = None,
        model: Optional[str] = None,
        max_pages: int = 12,
    ) -> str:
        """Extract assignment material text from uploaded content with multimodal PDF support."""
        if not uploaded_file:
            return ""

        file_name = str(getattr(uploaded_file, "name", "") or "").lower()
        try:
            raw = uploaded_file.read()
        finally:
            try:
                uploaded_file.seek(0)
            except Exception:
                pass

        if not raw:
            return ""

        if file_name.endswith(".pdf"):
            # Prefer the same page-vision extraction flow used for study materials.
            if course:
                tmp_path = None
                try:
                    suffix = os.path.splitext(file_name)[1] or ".pdf"
                    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                        tmp.write(raw)
                        tmp_path = tmp.name

                    pages = _render_material_to_pages(tmp_path, max_pages=max_pages)
                    material_kind = getattr(StudyMaterial, "KIND_ASSIGNMENT", "assignment")
                    fake_material = SimpleNamespace(
                        course=course,
                        title=title or "Assignment upload",
                        kind=material_kind,
                    )

                    converted_blocks: List[str] = []
                    for page in pages:
                        extracted = StudyIngestionService._extract_page(
                            fake_material,
                            page,
                            model=model or ModelConfigService.get_study_model(),
                        )
                        block = str(extracted.get("converted_markdown") or "").strip()
                        if block:
                            converted_blocks.append(block)

                    merged = StudyIngestionService._merge_text_blocks(converted_blocks)
                    if merged:
                        return merged
                except Exception:
                    AssignmentService.logger.exception(
                        "Assignment multimodal extraction failed; falling back to direct PDF text extraction"
                    )
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass

            # Fallback: direct text extraction via PDF text layer.
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
                try:
                    parts: List[str] = []
                    for page in doc:
                        text = (page.get_text("text") or "").strip()
                        if text:
                            parts.append(text)
                    return "\n\n".join(parts)
                finally:
                    doc.close()
            except Exception:
                AssignmentService.logger.exception("Failed to extract PDF text for assignment upload")
                return ""

        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw.decode(encoding).strip()
            except Exception:
                continue

        return ""

    @staticmethod
    def extract_material_text_from_path(
        file_path: str,
        *,
        course: Optional[StudyCourse] = None,
        title: Optional[str] = None,
        model: Optional[str] = None,
        max_pages: int = 12,
    ) -> str:
        """Extract assignment material text from a saved file path."""
        if not file_path or not os.path.exists(file_path):
            return ""

        file_name = str(file_path).lower()
        if file_name.endswith(".pdf") and course:
            try:
                pages = _render_material_to_pages(file_path, max_pages=max_pages)
                material_kind = getattr(StudyMaterial, "KIND_ASSIGNMENT", "assignment")
                fake_material = SimpleNamespace(
                    course=course,
                    title=title or "Assignment upload",
                    kind=material_kind,
                )
                converted_blocks: List[str] = []
                for page in pages:
                    extracted = StudyIngestionService._extract_page(
                        fake_material,
                        page,
                        model=model or ModelConfigService.get_study_model(),
                    )
                    block = str(extracted.get("converted_markdown") or "").strip()
                    if block:
                        converted_blocks.append(block)
                merged = StudyIngestionService._merge_text_blocks(converted_blocks)
                if merged:
                    return merged
            except Exception:
                AssignmentService.logger.exception(
                    "Assignment multimodal extraction failed for %s; falling back", file_path
                )

        try:
            with open(file_path, "rb") as fh:
                raw = fh.read()
        except Exception:
            return ""

        if file_name.endswith(".pdf"):
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
                try:
                    parts: List[str] = []
                    for page in doc:
                        text = (page.get_text("text") or "").strip()
                        if text:
                            parts.append(text)
                    return "\n\n".join(parts)
                finally:
                    doc.close()
            except Exception:
                AssignmentService.logger.exception("Failed fallback PDF text extraction for %s", file_path)
                return ""

        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw.decode(encoding).strip()
            except Exception:
                continue
        return ""

    @staticmethod
    def process_assignment_material(material_text: str, title: str, description: str, model: str = None) -> Tuple[str, List[dict], int]:
        """
        Process assignment material and generate plan, checklist, and session count.

        Returns: (plan, checklist, session_count)
        """
        if not model:
            model = ModelConfigService.get_study_model()

        provider = resolve_provider(model)
        client = get_client(provider)

        # Generate plan and checklist
        prompt = f"""You are analyzing a student assignment. Your task is to generate:
1. A high-level approach/strategy (2-3 paragraphs)
2. A detailed checklist of steps the student must complete
3. An estimate of how many study sessions are needed

Assignment: {title}
Description: {description}

Material:
{material_text[:3000]}...

Respond in JSON format:
{{
    "plan": "Here's how to approach this assignment...",
    "checklist": [
        {{"step_number": 1, "title": "Step title", "description": "Detailed description"}},
        ...
    ],
    "estimated_sessions": <integer between 1 and 5>
}}

Be concise but thorough. For a fairly competent student working at a good pace:
- 1-2 hours work = 1 session
- 2-4 hours work = 2 sessions
- 4+ hours work = 3+ sessions
""" 

        try:
            if provider == "openai":
                response = client.responses.create(
                    model=model,
                    input=[
                        {
                            "role": "user",
                            "content": [{"type": "input_text", "text": prompt}],
                        }
                    ],
                    text={"format": {"type": "json_object"}, "verbosity": "low"},
                    reasoning={"effort": "low"},
                    store=False,
                    timeout=60,
                )
                usage_obj = getattr(response, "usage", None)
                if usage_obj:
                    UsageService.log_usage(
                        source="study_assignment_processing",
                        model=model,
                        cache_mode=ModelConfigService.get_cache_mode(),
                        usage=usage_obj,
                        job=None,
                    )
                text = getattr(response, "output_text", "") or "{}"
            else:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                    response_format={"type": "json_object"},
                    timeout=60,
                )
                usage_obj = getattr(response, "usage", None)
                if usage_obj:
                    UsageService.log_usage(
                        source="study_assignment_processing",
                        model=model,
                        cache_mode=ModelConfigService.get_cache_mode(),
                        usage=usage_obj,
                        job=None,
                    )
                text = "{}"
                if getattr(response, "choices", None):
                    text = response.choices[0].message.content or "{}"  # type: ignore[assignment]

            # Extract JSON from response (may be wrapped in markdown code blocks)
            json_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
            if json_match:
                text = json_match.group(1)

            result = json.loads(text)
            plan = str(result.get("plan", "") or "").strip()
            checklist = result.get("checklist", [])
            estimated_sessions = result.get("estimated_sessions", 1)

            # Validate checklist format
            if not isinstance(checklist, list):
                checklist = []
            for i, item in enumerate(checklist):
                if not isinstance(item, dict):
                    checklist[i] = {"step_number": i + 1, "title": "", "description": ""}
                else:
                    item.setdefault("step_number", i + 1)
                    item.setdefault("title", "")
                    item.setdefault("description", "")

            estimated_sessions = max(1, min(int(estimated_sessions), 5))

            return plan, checklist, estimated_sessions
        except Exception as e:
            AssignmentService.logger.exception(f"Failed to generate plan/checklist: {e}")
            raise

    @staticmethod
    def create_soft_events_from_assignment(assignment) -> List[str]:
        """
        Backward-compatible wrapper around objective-based assignment planning.
        """
        return ObjectiveService.plan_assignment_objective(assignment)

    @staticmethod
    def cleanup_assignment_soft_events(assignment: StudyAssignment) -> Dict[str, int]:
        """Delete soft events linked to this assignment, whether or not refs are complete."""
        soft_event_ids = []
        for raw in (assignment.soft_event_refs or []):
            text = str(raw).strip()
            if text:
                soft_event_ids.append(text)
        by_ref_qs = SoftEvent.objects.filter(id__in=soft_event_ids) if soft_event_ids else SoftEvent.objects.none()
        by_meta_qs = SoftEvent.objects.filter(
            metadata__source="study_assignment",
            metadata__assignment_id=str(assignment.id),
        )

        ref_deleted, _ = by_ref_qs.delete()
        meta_deleted, _ = by_meta_qs.delete()
        return {
            "deleted_by_ref": int(ref_deleted),
            "deleted_by_metadata": int(meta_deleted),
        }


class AssignmentProcessingJobService:
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
    def run_assignment_processing_job(
        job_id: str,
        assignment_id: str,
        *,
        uploaded_file_path: Optional[str] = None,
        requested_session_count: Optional[int] = None,
    ) -> StudyAssignment:
        job = Job.objects.select_related("module", "active_function").get(id=job_id)
        assignment = StudyAssignment.objects.select_related("course").get(id=assignment_id)
        process_function = ToolFunction.objects.filter(manifest_id="study.process_material").first()

        job.status = Job.STATUS_RUNNING
        job.active_function = process_function
        job.progress = 0.01
        job.user_visible_summary = f"Processing assignment {assignment.title}"
        job.save(update_fields=["status", "active_function", "progress", "user_visible_summary", "updated_at"])
        JobService.append_event(
            job,
            role="study",
            event_type=JobEvent.EVENT_STATE,
            visibility=JobEvent.VISIBILITY_USER,
            message=f"Started processing assignment {assignment.title}",
        )

        try:
            AssignmentProcessingJobService._update_job(
                job,
                progress=0.2,
                summary=f"Extracting assignment material for {assignment.title}",
                message="Extracting content from uploaded material",
            )

            extracted_text = ""
            if uploaded_file_path:
                if not os.path.exists(uploaded_file_path):
                    raise FileNotFoundError(f"Uploaded assignment file not found: {uploaded_file_path}")
                extracted_text = AssignmentService.extract_material_text_from_path(
                    uploaded_file_path,
                    course=assignment.course,
                    title=assignment.title,
                )

            combined_material = (assignment.material_text or "").strip()
            if extracted_text:
                combined_material = (
                    f"{combined_material}\n\n{extracted_text}".strip() if combined_material else extracted_text
                )
            assignment.material_text = combined_material
            assignment.save(update_fields=["material_text", "updated_at"])

            if not assignment.material_text.strip():
                raise ValueError(
                    "No assignment material could be extracted. The uploaded file may be missing, unreadable, or empty."
                )

            AssignmentProcessingJobService._update_job(
                job,
                progress=0.6,
                summary=f"Generating assignment plan for {assignment.title}",
                message="Generating checklist and session estimate",
            )

            plan, checklist, auto_sessions = AssignmentService.process_assignment_material(
                material_text=assignment.material_text,
                title=assignment.title,
                description=assignment.description,
            )

            if not plan.strip() and not checklist:
                raise ValueError("Assignment processing returned no plan and no checklist.")

            assignment.plan = plan
            assignment.checklist = checklist
            if not requested_session_count:
                assignment.session_count = auto_sessions
            assignment.status = StudyAssignment.STATUS_READY
            assignment.save(update_fields=["plan", "checklist", "session_count", "status", "updated_at"])
            ObjectiveService.ensure_assignment_objective(assignment)

            AssignmentProcessingJobService._update_job(
                job,
                progress=1.0,
                summary=f"Completed assignment processing for {assignment.title}",
                message="Assignment plan ready",
            )
            JobService.mark_status(job, Job.STATUS_COMPLETED, progress=1.0)
            return assignment
        except Exception as exc:
            if assignment.objective_id:
                try:
                    assignment.objective.delete()
                except Exception:
                    AssignmentService.logger.exception(
                        "Failed to delete objective for assignment %s after processing failure",
                        assignment.id,
                    )
                assignment.objective = None
            assignment.status = StudyAssignment.STATUS_DRAFT
            assignment.save(update_fields=["objective", "status", "updated_at"])
            AssignmentProcessingJobService._update_job(
                job,
                summary=f"Failed assignment processing for {assignment.title}",
                message=str(exc),
            )
            JobService.mark_status(job, Job.STATUS_FAILED, error_summary=str(exc), progress=job.progress)
            raise

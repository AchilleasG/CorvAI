import base64
import hashlib
import json
import mimetypes
import shutil
from pathlib import Path
from uuid import UUID

from django.core.files.base import ContentFile
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError

from chat.models import ChatMessage
from coding.models import CodingSession, CodingTurn, FeatureDelegation, ManagedFile
from coding.schemas import ManagedFileAttachIn, ManagedFileCreateIn, ManagedFileUpdateIn

router = Router(tags=["Files"])
MAX_CONTEXT_BYTES = 100_000


def resolve_files(file_ids, *, session=None):
    ids = list(dict.fromkeys(str(value) for value in (file_ids or []) if value))
    items = list(ManagedFile.objects.filter(pk__in=ids))
    if len(items) != len(ids):
        raise ValueError("One or more attached files were not found")
    by_id = {str(item.pk): item for item in items}
    ordered = [by_id[value] for value in ids]
    if session and any(item.session_id and item.session_id != session.pk for item in ordered):
        raise ValueError("An attached file belongs to a different coding session")
    return ordered


def attachment_context(file_ids):
    """Build bounded text context and retain metadata for non-text files."""
    blocks = []
    textual = {".json", ".csv", ".md", ".py", ".js", ".ts", ".tsx", ".html", ".css", ".xml", ".yaml", ".yml", ".log"}
    for item in resolve_files(file_ids):
        heading = f"Attached file: {item.filename} ({item.content_type}, {item.size} bytes)"
        content = ""
        suffix = Path(item.filename).suffix.lower()
        if item.content_type.startswith("text/") or suffix in textual:
            with item.file.open("rb") as handle:
                raw = handle.read(MAX_CONTEXT_BYTES + 1)
            content = raw[:MAX_CONTEXT_BYTES].decode("utf-8", errors="replace")
            if len(raw) > MAX_CONTEXT_BYTES:
                content += "\n[File content truncated]"
        elif item.content_type == "application/pdf" or suffix == ".pdf":
            from pypdf import PdfReader
            with item.file.open("rb") as handle:
                content = "\n".join((page.extract_text() or "") for page in PdfReader(handle).pages)
            content = content[:MAX_CONTEXT_BYTES]
        blocks.append(f"{heading}\n{content}" if content else f"{heading}\n[Binary file attached; content is not inlined]")
    return "\n\n".join(blocks)


def materialize_inputs(session, file_ids):
    from coding.services import CodingSessionService
    items = resolve_files(file_ids, session=session)
    target = CodingSessionService.workspace_dir(session) / "inputs"
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths = []
    for item in items:
        path = target / f"{item.pk}-{Path(item.filename).name}"
        with item.file.open("rb") as source, path.open("wb") as destination:
            shutil.copyfileobj(source, destination)
        item.session = session
        item.save(update_fields=["session", "updated_at"])
        paths.append(path)
    return paths


def _clean_tags(tags):
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise HttpError(400, "tags must be a list of strings")
    return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))


def _relations(session_id=None, turn_id=None):
    session = get_object_or_404(CodingSession, pk=session_id) if session_id else None
    turn = get_object_or_404(CodingTurn.objects.select_related("session"), pk=turn_id) if turn_id else None
    if turn:
        if session and turn.session_id != session.id:
            raise HttpError(400, "turn does not belong to session")
        session = session or turn.session
    return session, turn


def file_payload(request, item):
    return {
        "id": str(item.id), "filename": item.filename, "content_type": item.content_type,
        "size": item.size, "checksum_sha256": item.checksum_sha256,
        "metadata": item.metadata, "tags": item.tags,
        "session_id": str(item.session_id) if item.session_id else None,
        "turn_id": str(item.turn_id) if item.turn_id else None,
        "delegation_id": str(item.delegation_id) if item.delegation_id else None,
        "assistant_message_id": str(item.assistant_message_id) if item.assistant_message_id else None,
        "download_url": request.build_absolute_uri(f"/api/files/{item.id}/content"),
        "created_at": item.created_at.isoformat(), "updated_at": item.updated_at.isoformat(),
    }


def _store(uploaded, filename, content_type, session, turn, metadata, tags, delegation=None):
    digest = hashlib.sha256(); size = 0
    for chunk in uploaded.chunks():
        digest.update(chunk); size += len(chunk)
    uploaded.seek(0)
    item = ManagedFile(filename=filename, content_type=content_type or "application/octet-stream",
        size=size, checksum_sha256=digest.hexdigest(), session=session, turn=turn,
        metadata=metadata, tags=_clean_tags(tags), delegation=delegation)
    item.file.save(filename, uploaded, save=False); item.save()
    return item


@router.get("")
def list_files(request, session_id: str = "", turn_id: str = "", delegation_id: str = "", tag: str = ""):
    items = ManagedFile.objects.all()
    if session_id: items = items.filter(session_id=session_id)
    if turn_id: items = items.filter(turn_id=turn_id)
    if delegation_id: items = items.filter(delegation_id=delegation_id)
    if tag: items = [item for item in items if tag in item.tags]
    return {"files": [file_payload(request, item) for item in items]}


@router.post("")
def create_file(request, payload: ManagedFileCreateIn):
    try:
        data = base64.b64decode(payload.content, validate=True) if payload.encoding == "base64" else payload.content.encode()
    except (ValueError, TypeError) as exc:
        raise HttpError(400, "content is not valid base64") from exc
    name = Path(payload.filename).name
    if not name or name in {".", ".."}: raise HttpError(400, "filename is required")
    session, turn = _relations(payload.session_id, payload.turn_id)
    return file_payload(request, _store(ContentFile(data), name, payload.content_type, session, turn, payload.metadata, payload.tags))


@router.post("/upload")
def upload_file(request):
    return _upload_file(request)


def _upload_file(request, delegation=None):
    uploaded = request.FILES.get("file")
    if not uploaded: raise HttpError(400, "multipart field 'file' is required")
    try:
        metadata = json.loads(request.POST.get("metadata", "{}")); tags = json.loads(request.POST.get("tags", "[]"))
    except json.JSONDecodeError as exc: raise HttpError(400, "metadata and tags must be valid JSON") from exc
    if not isinstance(metadata, dict): raise HttpError(400, "metadata must be an object")
    session, turn = _relations(request.POST.get("session_id"), request.POST.get("turn_id"))
    if delegation:
        if session and session.pk != delegation.session_id:
            raise HttpError(400, "session does not belong to delegation")
        if turn and str(turn.pk) not in delegation.coding_turn_ids:
            raise HttpError(400, "turn does not belong to delegation")
        session = delegation.session
    name = Path(uploaded.name).name
    content_type = getattr(uploaded, "content_type", "") or mimetypes.guess_type(name)[0]
    return file_payload(request, _store(uploaded, name, content_type, session, turn, metadata, tags, delegation))


@router.post("/delegations/{delegation_id}/upload")
def upload_delegation_file(request, delegation_id: UUID):
    delegation = get_object_or_404(
        FeatureDelegation.objects.select_related("session"), pk=delegation_id
    )
    return _upload_file(request, delegation)


@router.get("/{file_id}")
def get_file(request, file_id: UUID):
    return file_payload(request, get_object_or_404(ManagedFile, pk=file_id))


@router.get("/{file_id}/content")
def get_content(request, file_id: UUID, download: bool = False):
    item = get_object_or_404(ManagedFile, pk=file_id)
    if not item.file.storage.exists(item.file.name): raise HttpError(404, "file content was not found")
    return FileResponse(item.file.open("rb"), content_type=item.content_type, as_attachment=download, filename=item.filename)


@router.patch("/{file_id}")
def update_file(request, file_id: UUID, payload: ManagedFileUpdateIn):
    item = get_object_or_404(ManagedFile, pk=file_id)
    if payload.filename is not None:
        name = Path(payload.filename).name
        if not name or name in {".", ".."}: raise HttpError(400, "filename is required")
        item.filename = name
    if payload.content_type is not None: item.content_type = payload.content_type
    if payload.metadata is not None: item.metadata = payload.metadata
    if payload.tags is not None: item.tags = _clean_tags(payload.tags)
    item.save(); return file_payload(request, item)


@router.post("/{file_id}/attach")
def attach_file(request, file_id: UUID, payload: ManagedFileAttachIn):
    item = get_object_or_404(ManagedFile, pk=file_id); message = get_object_or_404(ChatMessage, pk=payload.message_id)
    if message.role != "assistant": raise HttpError(400, "files can only be attached to assistant messages")
    item.assistant_message = message; item.save(update_fields=["assistant_message", "updated_at"])
    metadata = message.metadata if isinstance(message.metadata, dict) else {}
    attachments = [entry for entry in metadata.get("attachments", []) if str(entry.get("id")) != str(item.id)]
    attachments.append(file_payload(request, item)); message.metadata = {**metadata, "attachments": attachments}; message.save(update_fields=["metadata"])
    return attachments[-1]


@router.delete("/{file_id}")
def delete_file(request, file_id: UUID):
    item = get_object_or_404(ManagedFile, pk=file_id); storage = item.file.storage; name = item.file.name
    item.delete()
    if name: storage.delete(name)
    return {"ok": True}

from __future__ import annotations

import hashlib
from uuid import UUID
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from coding.models import CodingDelegationWatch, CodingTurn, FeatureDelegation


class CodingChatWaitService:
    @staticmethod
    def _origin(chat=None, call_session=None):
        if chat is not None:
            return {"chat": chat, "call_session__isnull": True}
        if call_session is not None:
            return {"call_session": call_session, "chat__isnull": True}
        raise ValueError("A chat or call is required")

    @classmethod
    def watch_turn(cls, *, turn, chat=None, call_session=None, waiting=True):
        origin = cls._origin(chat, call_session)
        watch, _ = CodingDelegationWatch.objects.get_or_create(turn=turn, **origin, defaults={"session": turn.session, "waiting": waiting})
        if watch.waiting != waiting:
            watch.waiting = waiting; watch.save(update_fields=["waiting", "updated_at"])
        cls.publish_for_session(turn.session)
        return watch

    @classmethod
    def watch_delegation(cls, *, delegation, chat=None, call_session=None, waiting=True):
        origin = cls._origin(chat, call_session)
        watch, _ = CodingDelegationWatch.objects.get_or_create(delegation=delegation, **origin, defaults={"session": delegation.session, "waiting": waiting})
        if watch.waiting != waiting:
            watch.waiting = waiting; watch.save(update_fields=["waiting", "updated_at"])
        cls.publish_for_delegation(delegation)
        return watch

    @classmethod
    def advance_turn(cls, *, turn, chat=None, call_session=None):
        watch = CodingDelegationWatch.objects.filter(session=turn.session, delegation__isnull=True, active=True, **cls._origin(chat, call_session)).order_by("-created_at").first()
        if watch:
            watch.turn = turn; watch.last_event = ""; watch.save(update_fields=["turn", "last_event", "updated_at"])
        return watch

    @staticmethod
    def _label(watch):
        return watch.delegation.title if watch.delegation_id else watch.session.name

    @classmethod
    def payload(cls, watch):
        target = watch.delegation or watch.turn
        return {"watch_id": str(watch.pk), "kind": "feature" if watch.delegation_id else "task", "label": cls._label(watch), "session_id": str(watch.session_id), "session_name": watch.session.name, "turn_id": str(watch.turn_id) if watch.turn_id else None, "delegation_id": str(watch.delegation_id) if watch.delegation_id else None, "status": getattr(target, "status", "unknown") if target else "unknown", "active": watch.active, "waiting": watch.waiting, "question": getattr(target, "pending_question", "") or getattr(target, "question", "") if target else "", "options": getattr(target, "pending_options", []) or getattr(target, "options", []) if target else [], "summary": getattr(target, "qa_summary", "") or getattr(target, "implementation_summary", "") or getattr(target, "summary", "") if target else ""}

    @classmethod
    def list_for_origin(cls, *, chat=None, call_session=None, include_finished=True):
        qs = CodingDelegationWatch.objects.filter(**cls._origin(chat, call_session)).select_related("session", "turn", "delegation")
        if not include_finished: qs = qs.filter(active=True)
        items = [cls.payload(w) for w in qs[:50]]
        return {"waiting": any(x["active"] and x["waiting"] for x in items), "active_count": sum(x["active"] for x in items), "delegations": items}

    @classmethod
    def set_wait(cls, *, selector, waiting, chat=None, call_session=None):
        value = str(selector or "").strip(); query = Q(delegation__title__iexact=value) | Q(session__name__iexact=value)
        try:
            uid = UUID(value); query |= Q(pk=uid) | Q(turn_id=uid) | Q(delegation_id=uid)
        except (TypeError, ValueError): pass
        matches = list(CodingDelegationWatch.objects.filter(query, active=True, **cls._origin(chat, call_session)).select_related("session", "turn", "delegation")[:3])
        if not matches: raise ValueError(f"Active delegation '{value}' was not found in this conversation")
        if len(matches) > 1: raise ValueError("Delegation is ambiguous; use its watch id")
        watch = matches[0]; watch.waiting = bool(waiting); watch.save(update_fields=["waiting", "updated_at"])
        if watch.delegation_id: cls.publish_for_delegation(watch.delegation)
        else: cls.publish_for_session(watch.session)
        return cls.payload(watch)

    @staticmethod
    def _finish_silent(watch):
        CodingDelegationWatch.objects.filter(pk=watch.pk, active=True).update(active=False, finished_at=timezone.now(), updated_at=timezone.now())

    @staticmethod
    def _emit(watch_id, *, event, text, terminal):
        fingerprint = hashlib.sha256(f"{event}:{text}".encode()).hexdigest()
        with transaction.atomic():
            watch = CodingDelegationWatch.objects.select_for_update().get(pk=watch_id)
            if not watch.active or watch.last_event == fingerprint: return False
            if watch.chat_id:
                from chat.services import ChatService
                if not ChatService.add_message_to_chat(watch.chat_id, text, role="assistant", metadata={"kind": "coding_delegation_update", "coding_watch_id": str(watch.pk), "event": event}): return False
            elif watch.call_session_id:
                from orchestration.models import CallTranscriptEntry
                CallTranscriptEntry.objects.create(session_id=watch.call_session_id, role="system", content=f"[Delegation update:{watch.pk}:{event}] {text}")
            else: return False
            watch.last_event = fingerprint
            if terminal: watch.active = False; watch.finished_at = timezone.now()
            watch.save(update_fields=["last_event", "active", "finished_at", "updated_at"])
            return True

    @classmethod
    def publish_for_session(cls, session):
        for watch in CodingDelegationWatch.objects.filter(session=session, delegation__isnull=True, active=True).select_related("turn", "session"):
            turn = watch.turn
            if not turn: continue
            if turn.status == CodingTurn.STATUS_NEEDS_INPUT:
                opts = "".join(f"\n- {x}" for x in (turn.options or [])); block = "\n\nOptions:" + opts if opts else ""
                cls._emit(watch.pk, event="needs_input", text=f"Codex needs your input for delegated task “{session.name}”:\n\n{turn.question or 'Choose how Codex should continue.'}{block}\n\nTell me your choice and I’ll pass it back to Codex.", terminal=False)
            elif turn.status == CodingTurn.STATUS_COMPLETED:
                if watch.waiting: cls._emit(watch.pk, event="completed", text=f"Codex finished delegated task “{session.name}”.\n\n{turn.summary or session.last_summary or 'The task completed successfully.'}", terminal=True)
                else: cls._finish_silent(watch)
            elif turn.status in [CodingTurn.STATUS_FAILED, CodingTurn.STATUS_CANCELLED]: cls._emit(watch.pk, event="failed", text=f"Delegated task “{session.name}” stopped.\n\n{turn.error or session.last_error}", terminal=True)

    @classmethod
    def publish_for_delegation(cls, delegation):
        for watch in CodingDelegationWatch.objects.filter(delegation=delegation, active=True).select_related("delegation", "session"):
            if delegation.status == FeatureDelegation.STATUS_NEEDS_INPUT:
                opts = "".join(f"\n- {x}" for x in (delegation.pending_options or [])); block = "\n\nOptions:" + opts if opts else ""
                cls._emit(watch.pk, event="needs_input", text=f"Codex needs your input for “{delegation.title}”:\n\n{delegation.pending_question or 'Choose how Codex should continue.'}{block}\n\nTell me your choice and I’ll pass it back to Codex.", terminal=False)
            elif delegation.status == FeatureDelegation.STATUS_COMPLETED:
                if watch.waiting: cls._emit(watch.pk, event="completed", text=f"Codex finished “{delegation.title}”.\n\n{delegation.qa_summary or delegation.implementation_summary or 'Completed successfully.'}", terminal=True)
                else: cls._finish_silent(watch)
            elif delegation.status in [FeatureDelegation.STATUS_FAILED, FeatureDelegation.STATUS_STOPPED]: cls._emit(watch.pk, event="failed", text=f"Feature delegation “{delegation.title}” stopped.\n\n{delegation.last_error}", terminal=True)

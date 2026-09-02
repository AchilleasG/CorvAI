from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from orchestration.models import UserPresence


class PresenceService:
    @staticmethod
    def _number(data, key, *, required=False):
        value = data.get(key)
        if value is None:
            if required:
                raise ValueError(f"{key} is required")
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")

    @classmethod
    def update(cls, data):
        latitude = cls._number(data, "latitude", required=True)
        longitude = cls._number(data, "longitude", required=True)
        accuracy = cls._number(data, "accuracy_m")
        altitude = cls._number(data, "altitude_m")
        if not -90 <= latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")
        if not -180 <= longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if accuracy is not None and accuracy < 0:
            raise ValueError("accuracy_m cannot be negative")
        captured_at = parse_datetime(str(data.get("captured_at") or "")) or timezone.now()
        if timezone.is_naive(captured_at):
            captured_at = timezone.make_aware(captured_at, timezone.utc)
        if captured_at > timezone.now() + timedelta(minutes=5):
            captured_at = timezone.now()
        existing = UserPresence.objects.filter(key="default").first()
        if existing and captured_at < existing.captured_at:
            return cls.snapshot(existing)
        presence, _ = UserPresence.objects.update_or_create(
            key="default",
            defaults={
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_m": accuracy,
                "altitude_m": altitude,
                "captured_at": captured_at,
                "timezone_name": str(data.get("timezone_name") or "")[:64],
                "source": str(data.get("source") or "device")[:24],
            },
        )
        return cls.snapshot(presence)

    @staticmethod
    def snapshot(presence=None):
        presence = presence or UserPresence.objects.filter(key="default").first()
        if not presence:
            return None
        return {
            "latitude": presence.latitude,
            "longitude": presence.longitude,
            "accuracy_m": presence.accuracy_m,
            "altitude_m": presence.altitude_m,
            "captured_at": presence.captured_at.isoformat(),
            "timezone_name": presence.timezone_name,
            "source": presence.source,
        }

    @classmethod
    def message_metadata(cls, client_metadata=None):
        client_metadata = client_metadata if isinstance(client_metadata, dict) else {}
        location = client_metadata.get("location")
        if isinstance(location, dict):
            cls.update(location)
        return {
            "server_received_at": timezone.now().isoformat(),
            "client_sent_at": str(client_metadata.get("client_sent_at") or "")[:64],
            "timezone_name": str(client_metadata.get("timezone_name") or "")[:64],
            "source": str(client_metadata.get("source") or "")[:24],
            "location": cls.snapshot(),
        }

    @classmethod
    def prompt_block(cls):
        now = timezone.now()
        presence = UserPresence.objects.filter(key="default").first()
        lines = [f"Current server time: {now.isoformat()} (UTC)."]
        if not presence:
            return "\n".join(lines)
        age = max(0, int((now - presence.captured_at).total_seconds()))
        accuracy = f", accuracy about {presence.accuracy_m:.0f} m" if presence.accuracy_m is not None else ""
        lines.append(
            f"The user's device-reported location is {presence.latitude:.6f}, {presence.longitude:.6f}"
            f"{accuracy}; captured {presence.captured_at.isoformat()} ({age} seconds ago)."
        )
        if presence.timezone_name:
            lines.append(f"The device timezone is {presence.timezone_name}.")
        lines.append(
            "Automatically use this as the user's location whenever location matters. Do not ask where they are; "
            "if the fix is old, describe it as their last known location rather than claiming it is live."
        )
        return "\n".join(lines)

import os
import re
from typing import Callable

from django.conf import settings
from django.http import JsonResponse, HttpResponse


_SKIP_PATH_PREFIXES = (
    "/static/",
    "/favicon.ico",
)
_PUBLIC_DELEGATION_UPLOAD = re.compile(
    r"^/api/files/delegations/[0-9a-fA-F-]{36}/upload/?$"
)


class AccessTokenMiddleware:
    """
    Simple gate: require a shared access token header for all requests
    unless APP_ACCESS_TOKEN is unset.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request):
        app_token = getattr(settings, "APP_ACCESS_TOKEN", "") or os.getenv("APP_ACCESS_TOKEN") or ""
        if not app_token:
            return self.get_response(request)

        path = request.path or ""
        if any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
            return self.get_response(request)
        # A delegation UUID is a capability token for artifact upload only.
        # Listing, reading, changing, and deleting files remain protected.
        if request.method == "POST" and _PUBLIC_DELEGATION_UPLOAD.fullmatch(path):
            return self.get_response(request)

        header_token = request.headers.get("X-App-Token") or ""
        bearer = ""
        auth_header = request.headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()

        token = header_token or bearer
        if token == app_token:
            return self.get_response(request)

        # Default to JSON for API-like paths, otherwise plain text.
        if path.startswith("/api") or path.startswith("/orchestration") or path.startswith("/chat") or path.startswith("/input"):
            return JsonResponse({"detail": "Unauthorized"}, status=401)
        return HttpResponse("Unauthorized", status=401)

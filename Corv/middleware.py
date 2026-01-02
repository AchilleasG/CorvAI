import os
from typing import Callable

from django.http import JsonResponse, HttpResponse


APP_ACCESS_TOKEN = os.getenv("APP_ACCESS_TOKEN") or ""
_SKIP_PATH_PREFIXES = (
    "/static/",
    "/favicon.ico",
)


class AccessTokenMiddleware:
    """
    Simple gate: require a shared access token header for all requests
    unless APP_ACCESS_TOKEN is unset.
    """

    def __init__(self, get_response: Callable):
        self.get_response = get_response

    def __call__(self, request):
        if not APP_ACCESS_TOKEN:
            return self.get_response(request)

        path = request.path or ""
        if any(path.startswith(p) for p in _SKIP_PATH_PREFIXES):
            return self.get_response(request)

        header_token = request.headers.get("X-App-Token") or ""
        bearer = ""
        auth_header = request.headers.get("Authorization") or ""
        if auth_header.lower().startswith("bearer "):
            bearer = auth_header[7:].strip()

        token = header_token or bearer
        if token == APP_ACCESS_TOKEN:
            return self.get_response(request)

        # Default to JSON for API-like paths, otherwise plain text.
        if path.startswith("/api") or path.startswith("/orchestration") or path.startswith("/chat") or path.startswith("/input"):
            return JsonResponse({"detail": "Unauthorized"}, status=401)
        return HttpResponse("Unauthorized", status=401)

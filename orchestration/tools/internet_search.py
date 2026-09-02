from __future__ import annotations

from typing import Any

from orchestration.model_providers import get_client
from orchestration.registry import register_function
from orchestration.services import ModelConfigService, UsageService


def _as_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dump() if callable(dump) else {}


def _source_list(response: Any) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(url: Any, title: Any = ""):
        clean_url = str(url or "").strip()
        if not clean_url or clean_url in seen:
            return
        seen.add(clean_url)
        found.append({"title": str(title or clean_url).strip(), "url": clean_url})

    for output in getattr(response, "output", []) or []:
        item = _as_dict(output)
        action = item.get("action") or {}
        for source in action.get("sources") or []:
            source = _as_dict(source) if not isinstance(source, dict) else source
            add(source.get("url"), source.get("title"))
        for content in item.get("content") or []:
            content = _as_dict(content) if not isinstance(content, dict) else content
            for annotation in content.get("annotations") or []:
                annotation = _as_dict(annotation) if not isinstance(annotation, dict) else annotation
                citation = annotation.get("url_citation") or annotation
                add(citation.get("url"), citation.get("title"))
    return found[:12]


@register_function(
    manifest_id="internet_search.search",
    module="internet_search",
    name="internet_search.search",
    description=(
        "Search the public internet with an LLM and return a concise answer plus source URLs. "
        "Use for uncertain or current general knowledge, or when the user asks to search, verify, "
        "look up, or find information online."
    ),
    params_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "A focused public-web research question."},
            "context": {
                "type": "string",
                "description": "Optional constraints such as location, date range, or desired comparison.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    return_schema={
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "object"}},
        },
    },
)
def search(query: str, context: str = ""):
    query = " ".join(str(query or "").split())
    context = " ".join(str(context or "").split())
    if not query:
        raise ValueError("Search query cannot be empty")
    if len(query) > 1200 or len(context) > 1200:
        raise ValueError("Search query and context must each be at most 1200 characters")

    model = ModelConfigService.get_caller_model()
    if model.lower().startswith("grok"):
        model = ModelConfigService.DEFAULT_CALLER_MODEL
    prompt = query if not context else f"Question: {query}\nConstraints: {context}"
    response = get_client("openai").responses.create(
        model=model,
        tools=[{"type": "web_search"}],
        input=prompt,
        instructions=(
            "Search the public web before answering. Give a compact, factual answer grounded in the "
            "search results. Distinguish uncertainty and conflicting reports. Do not claim access to "
            "private or paywalled content."
        ),
        reasoning={"effort": "low"},
        timeout=45,
    )
    UsageService.log_usage(source="internet_search", model=model, usage=getattr(response, "usage", None))
    return {
        "query": query,
        "answer": str(getattr(response, "output_text", "") or "").strip(),
        "sources": _source_list(response),
    }

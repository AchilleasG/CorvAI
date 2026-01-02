from functools import lru_cache
from typing import Literal

from openai import OpenAI

from Corv.config import settings

ProviderName = Literal["openai", "xai"]


def resolve_provider(model_name: str) -> ProviderName:
  """
  Infer provider from model name.
  - grok-* -> x.ai (Grok)
  - default -> openai
  """
  name = (model_name or "").lower()
  if name.startswith("grok"):
    return "xai"
  return "openai"


@lru_cache(maxsize=4)
def get_client(provider: ProviderName) -> OpenAI:
  if provider == "xai":
    if not settings.xai_key:
      raise ValueError("XAI_API_KEY is not configured")
    base_url = settings.xai_base_url or "https://api.x.ai/v1"
    return OpenAI(api_key=settings.xai_key, base_url=base_url)

  if not settings.openai_key:
    raise ValueError("OPENAI_KEY is not configured")
  return OpenAI(api_key=settings.openai_key)

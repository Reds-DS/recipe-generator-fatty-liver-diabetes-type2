import anthropic
import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai.types import GenerateContentConfig, ImageConfig, Part
from rich.console import Console
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings

console = Console()

# Transient errors eligible for retry: network failures and 5xx server errors only.
# 4xx errors (auth, bad request, rate limit) propagate immediately.
_TRANSIENT_LLM_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.InternalServerError,
    genai_errors.ServerError,
    # Transport-level failures on the Google path surface as raw httpx errors
    # (e.g. connection reset / WinError 10053, read timeouts). TransportError is
    # the base for those but excludes HTTPStatusError, so 4xx still fails fast.
    httpx.TransportError,
)

# ── Singletons ──────────────────────────────────────────────

_anthropic_client: anthropic.Anthropic | None = None
_google_client: genai.Client | None = None


def _get_anthropic() -> anthropic.Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    return _anthropic_client


def _get_google() -> genai.Client:
    global _google_client
    if _google_client is None:
        _google_client = genai.Client(api_key=settings.google_api_key)
    return _google_client


# ── Provider-specific calls ─────────────────────────────────

def _call_anthropic(
    system: str,
    user: str,
    max_tokens: int,
    thinking_budget: int,
    model: str,
    cache_system: bool = False,
) -> str:
    client = _get_anthropic()
    system_param: str | list[dict] = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if cache_system
        else system
    )
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens + thinking_budget,
        thinking={"type": "adaptive"},
        system=system_param,
        messages=[{"role": "user", "content": user}],
    )
    for block in message.content:
        if hasattr(block, "text"):
            return block.text
    raise ValueError("Anthropic response contained no text block.")


def _call_google(
    system: str,
    user: str,
    max_tokens: int,
    thinking_budget: int,
    model: str,
) -> str:
    client = _get_google()
    response = client.models.generate_content(
        model=model,
        contents=user,
        config=GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            max_output_tokens=max_tokens + thinking_budget,
        ),
    )
    if response.text is None:
        raise ValueError("Google response contained no text.")
    return response.text


# ── Unified entry point ─────────────────────────────────────

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=10, max=60),
    retry=retry_if_exception_type(_TRANSIENT_LLM_ERRORS),
    reraise=True,
)
def create_message(
    system: str,
    user: str,
    max_tokens: int = 4096,
    thinking_budget: int = 8000,
    provider: str | None = None,
    model: str | None = None,
    cache_system: bool = False,
) -> str:
    """Call an LLM and return the response text.

    `provider` / `model` override the global settings when provided; leave
    them at None to use `settings.llm_provider` / `settings.llm_model`.

    `cache_system=True` marks the system prompt for prompt caching when the
    provider supports it (currently Anthropic only; ignored for Google).
    """
    effective_provider = provider or settings.llm_provider
    effective_model = model or settings.llm_model
    if effective_provider == "anthropic":
        return _call_anthropic(
            system, user, max_tokens, thinking_budget, effective_model,
            cache_system=cache_system,
        )
    return _call_google(system, user, max_tokens, thinking_budget, effective_model)


# ── Image pipeline helpers ─────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=30, max=120))
def create_message_with_model(
    system: str,
    user: str,
    model: str,
    max_tokens: int = 4096,
    thinking_budget: int = 4000,
) -> str:
    """Call a specific Google model and return response text."""
    client = _get_google()
    response = client.models.generate_content(
        model=model,
        contents=user,
        config=GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            max_output_tokens=max_tokens + thinking_budget,
        ),
    )
    if response.text is None:
        raise ValueError("Google response contained no text.")
    return response.text


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=15, max=90))
def generate_image(prompt: str, model: str, image_size: str = "4K") -> bytes:
    """Generate an image using a Gemini image model. Returns PNG bytes."""
    client = _get_google()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=ImageConfig(
                image_size=image_size,
                aspect_ratio="1:1",
            ),
        ),
    )
    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            return part.inline_data.data
    raise ValueError("Image generation response contained no image data.")


def generate_image_with_fallback(
    prompt: str,
    primary_model: str,
    fallback_model: str,
    image_size: str = "4K",
) -> tuple[bytes, str]:
    """Try primary model, fall back to secondary on failure. Returns (png_bytes, model_used)."""
    try:
        return generate_image(prompt, primary_model, image_size), primary_model
    except Exception:
        console.print(
            f"[yellow]⚠ Primary model {primary_model} unavailable, "
            f"falling back to {fallback_model}[/yellow]"
        )
        return generate_image(prompt, fallback_model, image_size), fallback_model


# ── Multimodal helpers ─────────────────────────────────────


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=10, max=60))
def create_message_with_image(
    system: str,
    user: str,
    image_bytes: bytes,
    model: str,
    max_tokens: int = 4096,
) -> str:
    """Send text + image to a Google model. Returns response text."""
    client = _get_google()
    image_part = Part.from_bytes(data=image_bytes, mime_type="image/png")
    response = client.models.generate_content(
        model=model,
        contents=[user, image_part],
        config=GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            max_output_tokens=max_tokens,
        ),
    )
    if response.text is None:
        raise ValueError("Google response contained no text.")
    return response.text

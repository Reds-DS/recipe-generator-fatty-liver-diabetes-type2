"""
Stage 7 — Image Generation (7a: prompt, 7b: generate, 7c: critic).
Generates a photorealistic image of the finished recipe for the cookbook.
"""
import json
from dataclasses import dataclass

from pydantic import ValidationError
from rich.console import Console

from src.config import settings
from src.llm import client as llm
from src.llm.output_schemas import ImageCriticOutput
from src.llm.prompts import image_critic as image_critic_prompts
from src.llm.prompts import image_prompt as image_prompt_prompts
from src.models.recipe import Recipe

console = Console()
MAX_IMAGE_RETRIES = 2  # original + 2 retries = 3 total attempts


@dataclass
class ImageResult:
    success: bool
    image_bytes: bytes | None = None
    image_prompt: str = ""
    attempts: int = 0
    failure_reason: str = ""


def build_prompt_request(recipe: Recipe, feedback: str = "") -> tuple[str, str, str, int, int]:
    """Return (system, user, model, max_tokens, thinking_budget) for 7a."""
    user = image_prompt_prompts.build_user(recipe, feedback=feedback)
    return image_prompt_prompts.SYSTEM, user, settings.image_prompt_model, 1024, 2000


def parse_prompt_response(raw: str) -> str:
    """Return the image prompt text from 7a."""
    return raw.strip()


def _generate_prompt(recipe: Recipe, feedback: str = "") -> str:
    """Stage 7a: Flash generates a detailed image prompt from the recipe."""
    system, user, model, max_tokens, thinking_budget = build_prompt_request(recipe, feedback)
    raw = llm.create_message_with_model(
        system=system, user=user, model=model,
        max_tokens=max_tokens, thinking_budget=thinking_budget,
    )
    return parse_prompt_response(raw)


def _generate_image(prompt: str) -> tuple[bytes, str]:
    """Stage 7b: Generate a PNG image from the prompt, with model fallback."""
    return llm.generate_image_with_fallback(
        prompt=prompt,
        primary_model=settings.image_generation_model,
        fallback_model=settings.image_generation_fallback_model,
        image_size=settings.image_size,
    )


def _critique_image(
    recipe: Recipe, image_bytes: bytes, image_prompt: str
) -> ImageCriticOutput | None:
    """Stage 7c: Pro evaluates image consistency. Returns None on parse failure."""
    schema_json = json.dumps(
        ImageCriticOutput.model_json_schema(), ensure_ascii=False, indent=2
    )
    user = image_critic_prompts.build_user(recipe, image_prompt, schema_json)
    text = llm.create_message_with_image(
        system=image_critic_prompts.SYSTEM,
        user=user,
        image_bytes=image_bytes,
        model=settings.image_critic_model,
        max_tokens=1024,
    )

    if "{" not in text:
        return None

    start = text.find("{")
    end = text.rfind("}") + 1
    try:
        return ImageCriticOutput.model_validate_json(text[start:end])
    except (ValidationError, ValueError):
        return None


def run(recipe: Recipe) -> ImageResult:
    """Run the 7a→7b→7c loop with retry on critic rejection."""
    critic_feedback = ""
    image_bytes: bytes | None = None
    image_prompt = ""

    for attempt in range(MAX_IMAGE_RETRIES + 1):
        # 7a — Generate image prompt
        image_prompt = _generate_prompt(recipe, feedback=critic_feedback)

        # 7b — Generate image
        try:
            image_bytes, model_used = _generate_image(image_prompt)
            console.print(f"  [dim]Image generated with {model_used}[/dim]")
        except Exception as e:
            return ImageResult(
                success=False,
                attempts=attempt + 1,
                image_prompt=image_prompt,
                failure_reason=f"Image generation failed: {e}",
            )

        # 7c — Critique image
        critic_result = _critique_image(recipe, image_bytes, image_prompt)

        if critic_result is None or critic_result.passed:
            return ImageResult(
                success=True,
                image_bytes=image_bytes,
                image_prompt=image_prompt,
                attempts=attempt + 1,
            )

        # Critic rejected — log and retry
        console.print(
            f"[yellow]⚠ Image critic not satisfied (attempt {attempt + 1}): "
            f"{critic_result.summary}[/yellow]"
        )
        for issue in critic_result.issues:
            console.print(f"  [red]✗[/red] {issue}")

        critic_feedback = critic_result.feedback_for_prompt

    # Max retries exhausted — return last image with warning
    return ImageResult(
        success=False,
        image_bytes=image_bytes,
        image_prompt=image_prompt,
        attempts=MAX_IMAGE_RETRIES + 1,
        failure_reason="Image rejected by the critic after the maximum number of attempts.",
    )

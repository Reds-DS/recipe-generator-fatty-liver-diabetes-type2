"""
Stage 1 — Ideation
LLM generates a constrained RecipeBrief. No quantities, no nutrition.
"""
import json
import re

from pydantic import ValidationError

from src.diet_rules.engine import DietRuleEngine
from src.llm import client as llm
from src.llm.output_schemas import RecipeBriefOutput
from src.llm.prompts import ideation as ideation_prompts
from src.models.recipe import RecipeBrief

MAX_RETRIES = 2


def build_request(
    main_ingredient: str | None = None,
    cuisine_hint: str | None = None,
    exclusions: list[str] | None = None,
    meal_type: str = "dinner",
    chapter: str = "poultry_meat_dinners",
    diversity_context: str = "",
) -> tuple[str, str, int, int]:
    """Return (system, user, max_tokens, thinking_budget) without calling LLM."""
    engine = DietRuleEngine(chapter=chapter)
    system = ideation_prompts.build_system(
        engine.constraint_text(for_stage="ideation"), diversity_context=diversity_context
    )
    user = ideation_prompts.build_user(
        main_ingredient=main_ingredient,
        cuisine_hint=cuisine_hint,
        exclusions=exclusions or [],
        meal_type=meal_type,
        chapter_brief=engine.chapter_brief(),
    )
    schema_json = RecipeBriefOutput.model_json_schema()
    user += f"\n\nJSON SCHEMA:\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}"
    # Ideation JSON is tiny (~500 tokens), but on Google the total output budget is
    # shared with Gemini's dynamic thinking (max_output_tokens = max_tokens +
    # thinking_budget). A heavy-thinking turn was starving the JSON and truncating
    # it mid-string, failing all retries. Give the response generous headroom so the
    # brief always fits after thinking. See CLAUDE.md ("size it generously").
    return system, user, 8192, 4000


def parse_response(raw: str, meal_type: str, chapter: str = "poultry_meat_dinners") -> RecipeBrief:
    """Parse raw LLM text into RecipeBrief.

    `meal_type` and `chapter` are assigned by the caller (not chosen by the LLM),
    mirroring how `meal_type` has always been injected here.
    """
    text = None
    raw = raw.strip()
    if raw.startswith("{"):
        text = raw
    else:
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
        if m:
            text = m.group(1)
    if text is None:
        raise ValueError("Stage 1: LLM did not return a valid JSON object.")

    output = RecipeBriefOutput.model_validate_json(text)

    return RecipeBrief(
        title_candidate=output.title_candidate,
        main_ingredient=output.main_ingredient,
        cuisine_style=output.cuisine_style,
        technique=output.technique,
        flavour_profile=output.flavour_profile,
        ingredients_sketch=output.ingredients_sketch,
        unique_angle=output.unique_angle,
        forbidden_items=output.forbidden_items,
        meal_type=meal_type,  # type: ignore[arg-type]
        chapter=chapter,  # type: ignore[arg-type]
    )


def run(
    main_ingredient: str | None = None,
    cuisine_hint: str | None = None,
    exclusions: list[str] | None = None,
    meal_type: str = "dinner",
    chapter: str = "poultry_meat_dinners",
    diversity_context: str = "",
) -> RecipeBrief:
    system, user, max_tokens, thinking_budget = build_request(
        main_ingredient=main_ingredient,
        cuisine_hint=cuisine_hint,
        exclusions=exclusions,
        meal_type=meal_type,
        chapter=chapter,
        diversity_context=diversity_context,
    )
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        raw = llm.create_message(system=system, user=user, max_tokens=max_tokens, thinking_budget=thinking_budget)
        try:
            return parse_response(raw, meal_type, chapter)
        except (ValueError, ValidationError) as e:
            last_error = e
            if attempt <= MAX_RETRIES:
                continue
    raise last_error  # type: ignore[misc]

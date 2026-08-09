"""
Stage 2 — Draft Generation
LLM expands the brief into a full RecipeDraft with exact quantities and
instructions. Nutrition is computed later in Stage 4.
"""
import json

from pydantic import ValidationError

from src.diet_rules.engine import DietRuleEngine
from src.llm import client as llm
from src.llm.output_schemas import RecipeDraftOutput
from src.llm.prompts import draft as draft_prompts
from src.models.recipe import Ingredient, RecipeBrief, RecipeDraft

MAX_RETRIES = 2


def _parse_draft(output: RecipeDraftOutput, brief: RecipeBrief, model: str, meal_type: str) -> RecipeDraft:
    ingredients = [
        Ingredient(
            name=i.name,
            canonical_name=i.canonical_name,
            quantity_g=i.quantity_g,
            quantity_display=i.quantity_display,
            preparation=i.preparation,
        )
        for i in output.ingredients
    ]

    return RecipeDraft(
        title=output.title,
        intro=output.intro,
        meal_type=meal_type,  # type: ignore[arg-type]
        chapter=brief.chapter,
        servings=2,
        prep_time_min=output.prep_time_min,
        cook_time_min=output.cook_time_min,
        cook_time_max_min=output.cook_time_max_min,
        passive_time=output.passive_time,
        ingredients=ingredients,
        instructions=output.instructions,
        variation=output.variation,
        conservation=output.conservation,
        llm_model=model,
    )


def build_request(brief: RecipeBrief, correction_feedback: str = "") -> tuple[str, str, int, int]:
    """Return (system, user, max_tokens, thinking_budget) without calling LLM."""
    engine = DietRuleEngine(chapter=brief.chapter)
    system = draft_prompts.build_system(engine.constraint_text())
    schema_json = json.dumps(
        RecipeDraftOutput.model_json_schema(), ensure_ascii=False, indent=2
    )
    _style_name, style_instruction = draft_prompts.pick_intro_style()
    user = draft_prompts.build_user(
        brief, schema_json, intro_style_instruction=style_instruction, chapter_brief=engine.chapter_brief()
    )

    if correction_feedback:
        user += f"\n\nCORRECTION REQUIRED:\n{correction_feedback}"

    # A full recipe JSON (ingredients + up to 7 steps + prose) is long, and Gemini's dynamic
    # thinking shares this budget — keep max_tokens generous so the draft doesn't truncate mid-JSON.
    return system, user, 8192, 8000


def parse_response(raw: str, brief: RecipeBrief) -> RecipeDraft:
    """Parse raw LLM text into RecipeDraft. Raises on parse failure."""
    if "{" not in raw:
        raise ValueError("Stage 2: No JSON in LLM response.")

    start = raw.find("{")
    end = raw.rfind("}") + 1
    json_str = raw[start:end]

    output = RecipeDraftOutput.model_validate_json(json_str)
    from src.config import settings
    return _parse_draft(output, brief, settings.llm_model, meal_type=brief.meal_type)


def run(brief: RecipeBrief, correction_feedback: str = "") -> RecipeDraft:
    system, user, max_tokens, thinking_budget = build_request(brief, correction_feedback)

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        text = llm.create_message(
            system=system, user=user, max_tokens=max_tokens, thinking_budget=thinking_budget
        )
        try:
            return parse_response(text, brief)
        except (ValidationError, ValueError) as e:
            last_error = e
            user += f"\n\nAttempt {attempt} failed. Validation error: {e}\nFix the JSON."

    raise RuntimeError(
        f"Stage 2: could not produce a valid draft after {MAX_RETRIES + 1} attempts. "
        f"Last error: {last_error}"
    )

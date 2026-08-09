"""
Stage 6 — Final Formatting (LLM, tightly constrained).
Only rewrites intro and instructions prose. All numeric data is unchanged.
"""
import json

from pydantic import ValidationError

from src.llm import client as llm
from src.llm.output_schemas import FormattedRecipeOutput
from src.llm.prompts import format as format_prompts
from src.models.nutrition import NutritionInfo
from src.models.recipe import Recipe, RecipeDraft


def build_request(draft: RecipeDraft) -> tuple[str, str, int, int]:
    """Return (system, user, max_tokens, thinking_budget) without calling LLM."""
    schema_json = json.dumps(
        FormattedRecipeOutput.model_json_schema(), ensure_ascii=False, indent=2
    )
    user = format_prompts.build_user(draft.intro, draft.instructions, schema_json)
    return format_prompts.SYSTEM, user, 2048, 2000


def parse_response(raw: str, draft: RecipeDraft, nutrition: NutritionInfo) -> Recipe:
    """Parse raw LLM text into final Recipe. Falls back to original prose on failure."""
    intro = draft.intro
    instructions = draft.instructions

    if "{" in raw:
        start = raw.find("{")
        end = raw.rfind("}") + 1
        try:
            output = FormattedRecipeOutput.model_validate_json(raw[start:end])
            if len(output.instructions) == len(draft.instructions):
                intro = output.intro
                instructions = output.instructions
        except (ValidationError, ValueError):
            pass

    return Recipe(
        title=draft.title,
        intro=intro,
        diet_tags=draft.diet_tags,
        meal_type=draft.meal_type,
        chapter=draft.chapter,
        servings=2,
        prep_time_min=draft.prep_time_min,
        cook_time_min=draft.cook_time_min,
        cook_time_max_min=draft.cook_time_max_min,
        passive_time=draft.passive_time,
        ingredients=draft.ingredients,
        instructions=instructions,
        variation=draft.variation,
        conservation=draft.conservation,
        nutrition_per_serving=nutrition,
        generation_id=draft.generation_id,
    )


def run(draft: RecipeDraft, nutrition: NutritionInfo) -> Recipe:
    system, user, max_tokens, thinking_budget = build_request(draft)
    text = llm.create_message(
        system=system, user=user, max_tokens=max_tokens, thinking_budget=thinking_budget
    )
    return parse_response(text, draft, nutrition)

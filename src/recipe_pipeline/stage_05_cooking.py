"""
Stage 5 — Cooking-logic & editorial validation (deterministic, no LLM).

Six advisory checks (warnings only — none blocks; the v2 air-fryer settings validator
was removed several books ago in this engine's lineage):

  * per-serving quantity plausibility — ``src/cooking/quantity_checker.py``;
  * cooking-process sanity (heavy/greasy preparation, implausible oven temperature) —
    ``src/cooking/method_checker.check_cooking_method``;
  * thirty-minute overshoot (too many meaningful ingredients, too long) —
    ``src/cooking/method_checker.check_thirty_minutes``;
  * disallowed equipment (air fryer, pressure cooker, slow cooker, sous-vide …) —
    ``src/cooking/method_checker.check_equipment``;
  * ambiguous grain base (a carb base that doesn't say whether it's a whole grain) —
    ``src/cooking/method_checker.check_grain_base``;
  * hard-to-find ingredients — ``src/cooking/method_checker.check_everyday_ingredients``.

All six feed the orchestrator's aggregate ``validation_warnings`` and the ``cooking`` log entry.
"""
from src.cooking.method_checker import (
    check_cooking_method,
    check_equipment,
    check_everyday_ingredients,
    check_grain_base,
    check_thirty_minutes,
)
from src.cooking.quantity_checker import check_quantities
from src.models.recipe import RecipeDraft


def run(draft: RecipeDraft) -> tuple[RecipeDraft, list[str], list[str]]:
    """Return (draft, warnings, corrections).

    `corrections` is always empty for now (kept for signature compatibility with the
    orchestrator); the draft is returned unchanged.
    """
    qty_result = check_quantities(draft)
    method_result = check_cooking_method(draft)
    time_result = check_thirty_minutes(draft)
    equipment_result = check_equipment(draft)
    grain_result = check_grain_base(draft)
    ingredient_result = check_everyday_ingredients(draft)
    warnings = [
        *qty_result.warnings,
        *method_result.warnings,
        *time_result.warnings,
        *equipment_result.warnings,
        *grain_result.warnings,
        *ingredient_result.warnings,
    ]
    return draft, warnings, []

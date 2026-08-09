"""
Stage 3 — Diet validation (deterministic, no LLM).

Runs the fatty-liver (MASLD) + type-2-diabetes diet rules (``src/diet_rules/``) against the draft:

  * pre-nutrition — the structural hard blocks (blocking: a failure sends the
    draft back through Stage 2's correction loop);
  * post-nutrition — the hard blocks again plus the chapter's per-tier nutrient
    targets (the latter need the computed nutrition; their misses surface as
    warnings, not blockers).

The diet rules / nutrient tiers are sourced from
``data/fatty_liver_diabetes_guidelines.yaml`` — see ``src/diet_rules/``.
"""
from src.diet_rules.engine import DietRuleEngine
from src.models.diet import DietValidationReport
from src.models.nutrition import NutritionInfo
from src.models.recipe import RecipeDraft

MAX_CORRECTION_LOOPS = 2


def run_pre_nutrition(draft: RecipeDraft) -> DietValidationReport:
    """Structural diet check before nutrition is computed (the hard blocks)."""
    return DietRuleEngine(chapter=draft.chapter).validate(draft)


def run_post_nutrition(
    draft: RecipeDraft, nutrition: NutritionInfo | None = None
) -> DietValidationReport:
    """Full diet check once nutrition is attached: hard blocks + the chapter's per-tier targets.

    ``nutrition`` may be ``None`` (e.g. the standalone ``validate-recipe`` CLI before nutrition
    is available), in which case only the structural checks run.
    """
    return DietRuleEngine(chapter=draft.chapter).validate(draft, nutrition)


def build_correction_prompt(report: DietValidationReport) -> str:
    """Convert blocking violations into a correction instruction for Stage 2."""
    lines = ["The recipe breaks the diet rules. Required corrections:"]
    for i, v in enumerate(report.blocking_violations, 1):
        lines.append(f"{i}. {v}")
    lines.append(
        "\nChange the ingredients or quantities to fix these violations. "
        "Keep all the other constraints (recipe for 2 people, etc.)."
    )
    return "\n".join(lines)

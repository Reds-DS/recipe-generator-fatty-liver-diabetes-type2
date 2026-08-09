"""
Diet-rule engine.

Runs the fatty-liver (MASLD) + type-2-diabetes diet rules for a recipe and
supplies the constraint text injected into the ideation / draft prompts. The rule
set is sourced from ``data/fatty_liver_diabetes_guidelines.yaml`` (parsed by
:mod:`src.diet_rules.spec`) and implemented in :mod:`src.diet_rules.rules`.

The rule set is *chapter-parameterized*: the hard-block rules are the same for
every chapter, but the soft per-tier checks depend on the chapter's nutrient
tier (``main`` / ``light_main`` / ``snack`` / ``dessert`` — see
``RECIPE_CHAPTER_NUTRIENT_TIER`` in ``src/constants.py``). So the rule list is
built per ``DietRuleEngine`` instance from the chapter.
"""
from src.diet_rules import rules, spec
from src.diet_rules.base_rule import BaseDietRule
from src.models.diet import DietValidationReport
from src.models.nutrition import NutritionInfo
from src.models.recipe import RecipeDraft

# "masld" = metabolic dysfunction-associated steatotic liver disease, the current
# clinical name for fatty liver (the 2023 multi-society Delphi consensus retired
# "NAFLD"). The book itself says "fatty liver" to the reader; the engine uses the
# clinical id.
DIET_ID = "masld"
SUPPORTED_DIETS: tuple[str, ...] = (DIET_ID,)


class DietRuleEngine:
    """Validates a recipe against the diet rules and renders the prompt-side constraint text."""

    def __init__(self, diet: str = DIET_ID, chapter: str = "poultry_meat_dinners") -> None:
        self.diet = diet
        self.chapter = chapter
        self.rules: list[BaseDietRule] = (
            rules.build_rules(chapter) if diet == DIET_ID else []
        )

    def validate(
        self, draft: RecipeDraft, nutrition: NutritionInfo | None = None
    ) -> DietValidationReport:
        results = [rule.evaluate(draft, nutrition) for rule in self.rules]
        return DietValidationReport.from_results(self.diet, results)

    def constraint_text(self, for_stage: str = "drafting") -> str:
        """Pre-rendered diet-rule prose for the LLM prompts.

        ``for_stage`` is a key in the YAML's ``prompt_snippets`` (``"ideation"``
        for Stage 1, ``"drafting"`` for Stage 2). Falls back to the drafting
        snippet, then to ``""``.
        """
        if self.diet != DIET_ID:
            return ""
        snippets = spec.load_spec().prompt_snippets
        return snippets.get(for_stage) or snippets.get("drafting") or ""

    def chapter_brief(self) -> str:
        """Block describing the target chapter (title, intent, character, per-serving
        tier targets) for injection into the ideation / draft prompts."""
        if self.diet != DIET_ID:
            return ""
        return spec.chapter_brief(self.chapter)

    def list_rules(self) -> list[str]:
        return [r.name for r in self.rules]

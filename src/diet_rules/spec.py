"""Loader for ``data/fatty_liver_diabetes_guidelines.yaml``.

Parses the machine-readable fatty-liver (MASLD) + type-2-diabetes recipe spec
into typed structures the diet-rules engine and the prompt builders consume. The
YAML is the ground truth (companion to
``docs/fatty_liver_diabetes_guidelines.md``); this module just normalizes its
slightly-irregular shape — some nutrient fields are ``{floor, target, ...}``,
some ``{value, ...}``, some ``{min, max, ...}`` — into flat per-serving envelopes.

Two axes here differ from the engine's parent cookbook, and both are deliberate:

* **Carbohydrate is a WINDOW, and both ends warn.** ``total_carbs_g`` carries
  ``{floor, target, max}``. A recipe that is impressively low in carbohydrate is
  a *defect* in this book: readers on SGLT2 inhibitors are cautioned against
  ketogenic patterns, readers on insulin or a sulfonylurea risk hypoglycemia when
  carbohydrate drops unannounced, and the book's whole positioning is a refusal
  of the "cut all carbs, try keto" advice its reader already found. The floors
  are sized so a day built entirely of floor-hugging recipes still lands above
  26% of energy from carbohydrate.
* **There is no ``net_carbs`` axis.** The ADA and FDA both count *total*
  carbohydrate, "net carbs" has no regulatory definition, and a reader dosing
  insulin must not be shown a subtracted number. The parent engine's
  ``net_carbs_g_max`` field was removed rather than left unused.

Nothing here makes network calls; the spec is read once and cached.
"""
from functools import lru_cache
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

from src.config import GUIDELINES

# Used when the YAML is missing a piece (keeps the engine importable even if the
# spec file is hand-edited badly). Mirrors the `main` tier / dinners chapter.
_FALLBACK_TIER = "main"
_FALLBACK_CHAPTER = "poultry_meat_dinners"


class NutrientEnvelope(BaseModel):
    """Per-serving targets for one meal category (nutrient tier). Every field is
    optional — a tier only constrains what the YAML lists for it."""

    tier: str
    protein_g_floor: float | None = None
    protein_g_target: float | None = None
    fiber_g_floor: float | None = None
    fiber_g_target: float | None = None
    # Carbohydrate is a WINDOW — see the module docstring. `total_carbs_g_floor`
    # is load-bearing and must never be quietly dropped to "simplify" the axis.
    total_carbs_g_floor: float | None = None
    total_carbs_g_target: float | None = None
    total_carbs_g_max: float | None = None
    added_sugar_g_max: float | None = None
    saturated_fat_g_max: float | None = None
    sodium_mg_max: float | None = None
    added_oil_tbsp_max: float | None = None
    energy_kcal_min: float | None = None
    energy_kcal_max: float | None = None


class HardBlock(BaseModel):
    rule: str
    description: str


class RecipeCategory(BaseModel):
    """One book chapter / generation target (see ``recipe_categories`` in the YAML)."""

    slug: str
    book_title: str
    planner_meal_types: list[str] = Field(default_factory=list)
    nutrient_tier: str = _FALLBACK_TIER
    also_nutrient_tiers: list[str] = Field(default_factory=list)
    target_recipe_count: str | None = None
    intent: str = ""
    dossier_refs: list[str] = Field(default_factory=list)
    character: str = ""

    @property
    def target_count(self) -> int:
        """``target_recipe_count`` parsed to a single int (the range midpoint)."""
        return _parse_count(self.target_recipe_count)


class Spec(BaseModel):
    schema_version: int = 0
    meal_categories: dict[str, NutrientEnvelope] = Field(default_factory=dict)
    hard_blocks: list[HardBlock] = Field(default_factory=list)
    recipe_categories: dict[str, RecipeCategory] = Field(default_factory=dict)
    prompt_snippets: dict[str, str] = Field(default_factory=dict)
    cooking_methods_prefer: list[str] = Field(default_factory=list)
    cooking_methods_avoid: list[str] = Field(default_factory=list)

    # ── lookups ─────────────────────────────────────────────
    def category(self, chapter: str) -> RecipeCategory:
        return (
            self.recipe_categories.get(chapter)
            or self.recipe_categories.get(_FALLBACK_CHAPTER)
            or RecipeCategory(slug=chapter, book_title=chapter)
        )

    def tier_for_chapter(self, chapter: str) -> str:
        return self.category(chapter).nutrient_tier or _FALLBACK_TIER

    def envelope_for_chapter(self, chapter: str) -> NutrientEnvelope:
        tier = self.tier_for_chapter(chapter)
        return self.meal_categories.get(tier) or NutrientEnvelope(tier=tier)


# ── parsing ─────────────────────────────────────────────────

def _num(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def _parse_count(s: str | None) -> int:
    """Parse a ``target_recipe_count`` value ("18-22", "20", …) to a single int (the range midpoint)."""
    if not s:
        return 0
    nums: list[int] = []
    for part in str(s).replace("–", "-").split("-"):
        try:
            nums.append(int(part.strip()))
        except ValueError:
            continue
    return int(round(sum(nums) / len(nums))) if nums else 0


def _parse_envelope(tier: str, raw: dict[str, Any]) -> NutrientEnvelope:
    def fld(key: str) -> dict[str, Any]:
        v = raw.get(key)
        return v if isinstance(v, dict) else {}

    pg, fg, ek = fld("protein_g"), fld("fiber_g"), fld("energy_kcal")
    tc = fld("total_carbs_g")
    return NutrientEnvelope(
        tier=tier,
        protein_g_floor=_num(pg.get("floor")),
        protein_g_target=_num(pg.get("target")),
        fiber_g_floor=_num(fg.get("floor")),
        fiber_g_target=_num(fg.get("target")),
        total_carbs_g_floor=_num(tc.get("floor")),
        total_carbs_g_target=_num(tc.get("target")),
        total_carbs_g_max=_num(tc.get("max")),
        added_sugar_g_max=_num(fld("added_sugar_g_max").get("value")),
        saturated_fat_g_max=_num(fld("saturated_fat_g_max").get("value")),
        sodium_mg_max=_num(fld("sodium_mg_max").get("value")),
        added_oil_tbsp_max=_num(fld("added_oil_tbsp_max").get("value")),
        energy_kcal_min=_num(ek.get("min")),
        energy_kcal_max=_num(ek.get("max")),
    )


def _parse(data: Any) -> Spec:
    if not isinstance(data, dict):
        return Spec()
    meta = data.get("meta") or {}
    prc = data.get("per_recipe_constraints") or {}

    cats_raw = prc.get("meal_categories") or {}
    meal_categories = {
        str(tier): _parse_envelope(str(tier), raw)
        for tier, raw in cats_raw.items()
        if isinstance(raw, dict)
    }

    hard_blocks = [
        HardBlock(
            rule=str(hb.get("rule", "")),
            description=" ".join(str(hb.get("description", "")).split()),
        )
        for hb in (prc.get("hard_blocks") or [])
        if isinstance(hb, dict) and hb.get("rule")
    ]

    recipe_categories: dict[str, RecipeCategory] = {}
    for slug, raw in (data.get("recipe_categories") or {}).items():
        if not isinstance(raw, dict):
            continue
        trc = raw.get("target_recipe_count")
        recipe_categories[str(slug)] = RecipeCategory(
            slug=str(slug),
            book_title=str(raw.get("book_title", slug)),
            planner_meal_types=[str(m) for m in (raw.get("planner_meal_types") or [])],
            nutrient_tier=str(raw.get("nutrient_tier", _FALLBACK_TIER)),
            also_nutrient_tiers=[str(t) for t in (raw.get("also_nutrient_tiers") or [])],
            target_recipe_count=(str(trc) if trc is not None else None),
            intent=" ".join(str(raw.get("intent", "")).split()),
            dossier_refs=[str(r) for r in (raw.get("dossier_refs") or [])],
            character=" ".join(str(raw.get("character", "")).split()),
        )

    cm = data.get("cooking_methods") or {}
    prompt_snippets = {
        str(k): str(v) for k, v in (data.get("prompt_snippets") or {}).items() if isinstance(v, str)
    }

    return Spec(
        schema_version=int(meta.get("schema_version", 0)),
        meal_categories=meal_categories,
        hard_blocks=hard_blocks,
        recipe_categories=recipe_categories,
        prompt_snippets=prompt_snippets,
        cooking_methods_prefer=[str(m) for m in (cm.get("prefer") or [])],
        cooking_methods_avoid=[str(m) for m in (cm.get("avoid") or [])],
    )


@lru_cache(maxsize=1)
def load_spec() -> Spec:
    """Load + parse ``data/fatty_liver_diabetes_guidelines.yaml`` (cached). Do not mutate the result."""
    return _parse(yaml.safe_load(GUIDELINES.read_text(encoding="utf-8")))


def chapter_target_counts() -> dict[str, int]:
    """Per-chapter target recipe counts, parsed from ``target_recipe_count`` in the YAML."""
    return {slug: cat.target_count for slug, cat in load_spec().recipe_categories.items()}


# ── rendered prompt fragments ───────────────────────────────

def render_envelope(env: NutrientEnvelope) -> str:
    """One-line summary of a tier's per-serving targets (empty if it constrains nothing)."""
    bits: list[str] = []
    if env.protein_g_floor:
        t = f" (aim for {env.protein_g_target:g})" if env.protein_g_target else ""
        bits.append(f"protein ≥ {env.protein_g_floor:g} g{t}")
    if env.fiber_g_floor:
        t = f" (aim for {env.fiber_g_target:g})" if env.fiber_g_target else ""
        bits.append(f"fiber ≥ {env.fiber_g_floor:g} g{t}")
    # Carbohydrate prints as a WINDOW whenever a floor exists — "≤ 55 g" alone
    # would read as "less is better", which is exactly the failure mode this
    # book's carbohydrate floor exists to prevent. See the module docstring.
    if env.total_carbs_g_floor is not None and env.total_carbs_g_max is not None:
        t = f" (aim for {env.total_carbs_g_target:g})" if env.total_carbs_g_target else ""
        bits.append(
            f"total carbohydrate {env.total_carbs_g_floor:g}–{env.total_carbs_g_max:g} g{t} "
            f"— A WINDOW: below {env.total_carbs_g_floor:g} g is a defect, not a feature"
        )
    elif env.total_carbs_g_max is not None:
        bits.append(f"total carbohydrate ≤ {env.total_carbs_g_max:g} g")
    elif env.total_carbs_g_floor is not None:
        bits.append(f"total carbohydrate ≥ {env.total_carbs_g_floor:g} g")
    if env.added_sugar_g_max is not None:
        bits.append(f"added sugar ≤ {env.added_sugar_g_max:g} g")
    if env.saturated_fat_g_max is not None:
        bits.append(f"saturated fat ≤ {env.saturated_fat_g_max:g} g")
    if env.sodium_mg_max is not None:
        bits.append(f"sodium ≤ {env.sodium_mg_max:g} mg")
    if env.added_oil_tbsp_max is not None:
        bits.append(f"added oil ≤ {env.added_oil_tbsp_max:g} tbsp")
    if env.energy_kcal_min is not None and env.energy_kcal_max is not None:
        bits.append(f"≈ {env.energy_kcal_min:g}–{env.energy_kcal_max:g} kcal")
    return "; ".join(bits)


def chapter_brief(chapter: str) -> str:
    """Block describing the target chapter (title, intent, character, tier targets)."""
    spec = load_spec()
    cat = spec.category(chapter)
    env = spec.envelope_for_chapter(chapter)
    lines = [f"TARGET CHAPTER: \"{cat.book_title}\" (nutrient tier: {cat.nutrient_tier})."]
    if cat.intent:
        lines.append(f"Chapter goal: {cat.intent}")
    if cat.character:
        lines.append(f"Expected style: {cat.character}")
    env_line = render_envelope(env)
    if env_line:
        lines.append(f"Per-serving targets (recipe for 2 people): {env_line}.")
    return "\n".join(lines)

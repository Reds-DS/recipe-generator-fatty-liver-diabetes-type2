"""Per-person quantity plausibility checks (Stage 2b — blocking — and re-run as a Stage-5 advisory).

A cheap deterministic pre-filter: it catches GROSS errors — a recipe accidentally written for
4 people, a fat-fingered quantity ("2 kg chicken"), a 50 g "meal" — before the expensive
nutrition (Stage 4) and critic (Stage 5b) stages. It is NOT the diet gate: the per-tier nutrient
limits are enforced by Stage 3 (``src/diet_rules/``) on computed nutrition, and the Stage-5b critic
covers qualitative fit. So the bounds here are deliberately WIDE — they must never bounce a recipe
that's on-target per ``data/fatty_liver_diabetes_guidelines.yaml``; they only catch ~2x overshoots and
near-zero.

All bounds are per person (total / 2, since ``servings`` is always 2). They are keyed on the recipe's
NUTRIENT TIER (derived from ``draft.chapter``), not the planner meal-type — so the ``light_main``
(Soups & Salads), ``snack`` (Snacks & Sides) and ``dessert`` chapters aren't judged against
full-size ``main``-meal bounds.
"""
import re
from dataclasses import dataclass

from src.constants import RECIPE_CHAPTER_NUTRIENT_TIER
from src.models.recipe import Ingredient, RecipeDraft

SERVINGS = 2

# Per-person plausibility bounds (grams), keyed by nutrient tier (see the YAML's
# `per_recipe_constraints.meal_categories`). Each: {"total_raw": (lo, hi), "protein": (lo, hi),
# "oil": (lo, hi)}. Loosely scaled to the tier's YAML envelope (noted in the trailing comment) but
# DELIBERATELY WIDE — see the module docstring. The protein lo/hi are on the *gram weight of
# protein-source ingredients* (only checked when some are present), not on protein content, so the
# band is generous enough to span ~9-30 g protein / 100 g whole foods.
#                                  total_raw g/p   protein g/p   oil g/p
_BOUNDS_BY_TIER: dict[str, dict[str, tuple[int, int]]] = {
    # YAML envelope: protein >=26 g, 380-540 kcal
    "main":       {"total_raw": (250, 950),  "protein": (70, 380), "oil": (0, 18)},
    # `light_main` carries the Soups & Salads chapter. Its total_raw ceiling is the
    # HIGHEST in the book despite being the lighter tier: a brothy soup for two is
    # mostly water by weight, and judging it against `main`'s ceiling would bounce
    # every soup in the chapter. Its floor is lower for the same reason a big salad
    # is light — this is the one tier where raw grams say least about the portion.
    # YAML envelope: protein >=20 g, 300-440 kcal
    "light_main": {"total_raw": (200, 1000), "protein": (50, 320), "oil": (0, 18)},
    # `snack` also holds SIDES (a tray of roasted vegetables is legitimately 150-200 g
    # per person with almost no protein-source weight), which is why the protein floor
    # here is 0 and the raw-weight ceiling is generous.
    # YAML envelope: protein >=5 g, 120-230 kcal
    "snack":      {"total_raw": (50, 500),   "protein": (0, 250),  "oil": (0, 14)},
    # YAML envelope: protein >=4 g, 120-220 kcal
    "dessert":    {"total_raw": (40, 350),   "protein": (0, 250),  "oil": (0, 20)},
}
_FALLBACK_TIER_BOUNDS = _BOUNDS_BY_TIER["main"]

_TIER_LABELS = {
    "main": "a main meal",
    "light_main": "a soup or salad eaten as a light meal",
    "snack": "a snack or side",
    "dessert": "a dessert",
}

# Per-person cap on added salt + salty condiments (grams). Flat, and coarse on purpose: it lumps
# table-salt-scale (~388 mg sodium / g) with soy-sauce-scale (~58 mg / g) grams, so it only catches
# a gross typo (e.g. "1 tbsp of table salt"). Stage 3's computed-sodium check is the real sodium gate.
_SALT_MAX_G_PER_PERSON = 5.0

# Whole-food protein sources. The gram-weight heuristic only makes sense for these — concentrated
# isolates (whey / pea protein / "protein powder") are intentionally absent, so a recipe built on
# those simply skips the protein check via the `if total_protein_g` guard, leaving protein adequacy
# to Stage 3.
_PROTEIN_KEYWORDS = [
    # meat & poultry
    "chicken", "turkey", "beef", "veal", "lamb", "pork",
    # fish & seafood
    "fish", "salmon", "tuna", "cod", "tilapia", "halibut", "haddock", "trout", "mackerel",
    "sardine", "anchovy", "pollock", "snapper", "catfish", "swordfish", "monkfish",
    "shrimp", "prawn", "scallop", "mussel", "clam", "crab", "lobster", "seafood", "shellfish",
    # eggs & soy
    "egg", "tofu", "tempeh", "edamame", "soybean", "seitan",
    # dairy
    "yogurt", "cottage cheese", "skyr", "quark", "ricotta",
    # legumes
    "lentil", "chickpea", "hummus", "black bean", "kidney bean", "white bean", "cannellini",
    "navy bean", "pinto bean", "great northern bean", "lima bean", "fava bean", "split pea",
    "black-eyed pea",
]
# Liquids that CARRY a protein word but are not a protein source. Without this,
# "low-sodium chicken broth" matches "chicken" and 900 g of broth in a soup lands
# in the protein tally, blowing the per-person protein ceiling on every recipe in
# the Soups & Salads chapter. Checked BEFORE _PROTEIN_KEYWORDS.
_NOT_A_PROTEIN_SOURCE_KEYWORDS = [
    "broth", "stock", "bouillon", "consomme", "consommé", "bone broth",
    "fish sauce", "oyster sauce", "worcestershire", "anchovy paste",
]
_OIL_KEYWORDS = ["oil", "butter", "margarine"]   # also re-used by src/cooking/method_checker.py
_SALT_KEYWORDS = ["salt", "soy sauce", "tamari", "miso"]
_SALT_CONDIMENTS = ["soy sauce", "tamari", "miso"]  # a salt source even when "low-sodium"
# "no-salt-added" / "low-salt" / "salt-free" items are NOT salt sources — "salt" appears only as a
# negation. Guard the bare-"salt" match so the sodium-conscious "no-salt-added ..." naming the draft
# prompt now requires isn't misread as a big dose of added salt.
_NO_SALT_RE = re.compile(r"\b(?:no|low|reduced|less|without)[\s-]*salt\b|\bsalt[\s-]*free\b", re.I)


@dataclass
class QuantityCheckResult:
    passed: bool
    warnings: list[str]


def _has_word(text: str, keywords: list[str]) -> bool:
    """True if any keyword appears as a whole word in ``text`` (allowing a trailing plural ``-s``).

    Word-boundary matching avoids substring false positives such as "egg" inside "eggplant" while
    still catching regular plurals ("eggs", "black beans", "lentils")."""
    return any(re.search(rf"\b{re.escape(kw)}s?\b", text) for kw in keywords)


def _classify(ingredient: Ingredient) -> str | None:
    """Bucket an ingredient as "protein" / "oil" / "salt" / None by name.

    ORDER MATTERS. Broth/stock is excluded first (a "chicken broth" is not a protein
    source, and a soup carries it by the litre). Then protein, so e.g. "peanut butter"
    stays "oil" — it's fat-dominant and should count against the oil cap rather than
    being excused into the protein tally.
    """
    name = (ingredient.canonical_name or ingredient.name).lower()
    # Broth/stock first: "chicken broth" must not count as a protein source.
    if _has_word(name, _NOT_A_PROTEIN_SOURCE_KEYWORDS):
        return None
    if _has_word(name, _PROTEIN_KEYWORDS):
        return "protein"
    if _has_word(name, _OIL_KEYWORDS):
        return "oil"
    if _has_word(name, _SALT_KEYWORDS):
        # A salty condiment (soy sauce, miso, ...) always counts; a bare "salt" match on a
        # "no-salt-added" / "salt-free" ingredient does NOT — the word is only a negation.
        if _has_word(name, _SALT_CONDIMENTS) or not _NO_SALT_RE.search(name):
            return "salt"
    return None


def _tier_for(draft: RecipeDraft) -> str:
    return RECIPE_CHAPTER_NUTRIENT_TIER.get(draft.chapter, "main")


def check_quantities(draft: RecipeDraft) -> QuantityCheckResult:
    warnings: list[str] = []
    tier = _tier_for(draft)
    bounds = _BOUNDS_BY_TIER.get(tier, _FALLBACK_TIER_BOUNDS)
    tier_label = _TIER_LABELS.get(tier, "this recipe")

    total_raw_g = sum(i.quantity_g for i in draft.ingredients)
    total_protein_g = sum(i.quantity_g for i in draft.ingredients if _classify(i) == "protein")
    total_oil_g = sum(i.quantity_g for i in draft.ingredients if _classify(i) == "oil")
    total_salt_g = sum(i.quantity_g for i in draft.ingredients if _classify(i) == "salt")

    per_person_raw = total_raw_g / SERVINGS
    per_person_protein = total_protein_g / SERVINGS
    per_person_oil = total_oil_g / SERVINGS
    per_person_salt = total_salt_g / SERVINGS

    lo, hi = bounds["total_raw"]
    if per_person_raw < lo:
        warnings.append(
            f"Total raw weight too low: {total_raw_g:.0f}g for 2 people "
            f"({per_person_raw:.0f}g/person; expected at least {lo}g/person for {tier_label})."
        )
    if per_person_raw > hi:
        warnings.append(
            f"Total raw weight suspect: {total_raw_g:.0f}g for 2 people "
            f"({per_person_raw:.0f}g/person). The recipe may have been written for 4 people."
        )

    if total_protein_g > 0:
        lo, hi = bounds["protein"]
        if per_person_protein < lo:
            warnings.append(
                f"Low protein amount: {per_person_protein:.0f}g/person of protein-rich ingredients "
                f"(expected at least {lo}g/person for {tier_label})."
            )
        if per_person_protein > hi:
            warnings.append(
                f"Suspect protein amount: {per_person_protein:.0f}g/person of protein-rich ingredients "
                f"(expected at most {hi}g/person). Check whether the recipe is for 4 people."
            )

    oil_max = bounds["oil"][1]
    if per_person_oil > oil_max:
        warnings.append(
            f"High oil / fat amount: {per_person_oil:.0f}g/person "
            f"(recommended at most {oil_max}g/person for {tier_label})."
        )

    if per_person_salt > _SALT_MAX_G_PER_PERSON:
        warnings.append(
            f"High salt / salty-sauce amount: {per_person_salt:.1f}g/person "
            f"(recommended at most {_SALT_MAX_G_PER_PERSON:.0f}g/person)."
        )

    return QuantityCheckResult(passed=len(warnings) == 0, warnings=warnings)


def build_correction_prompt(result: QuantityCheckResult) -> str:
    """Convert a failed quantity check into a correction instruction for Stage 2."""
    lines = ["The recipe's quantities look wrong for 2 people. Required corrections:"]
    for i, w in enumerate(result.warnings, 1):
        lines.append(f"{i}. {w}")
    lines.append(
        "\nRevise the quantities so they match exactly 2 servings. Do not write a 4-person recipe."
    )
    return "\n".join(lines)

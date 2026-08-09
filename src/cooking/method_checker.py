"""Stage 5 — cooking-process & editorial sanity checks (advisory only).

Warnings only (never blocking), run alongside the per-serving quantity plausibility in
``quantity_checker.py``:

  * **Heavy / greasy preparation** (``check_cooking_method``) — a softer net below the
    ``no_deep_fried`` diet hard block: cooking *in* a lot of fat (duck fat, lard, "plenty of
    oil", an oil bath…), which is heavier than the book's light-cooking stance even when it
    isn't strictly deep-frying.
  * **Implausible oven temperature** (``check_cooking_method``) — a Celsius value hotter than a
    home oven ever runs is almost always an °F value mislabeled as °C (the draft prompt asks for
    both, e.g. "375°F / 190°C", so the °F figures are expected — only the °C one matters here).
  * **Thirty-minute overshoot** (``check_thirty_minutes``) — a soft companion to the editorial
    ``easy_recipe_constraints`` in ``data/fatty_liver_diabetes_guidelines.yaml``: too many meaningful
    ingredients, or too long. Thresholds sit *just above* the editorial 10 / 25 / 30 targets so this
    only fires on a clear overshoot; the LLM critic handles the grey zone. **There is no
    set-and-forget exemption in this book** — the cover says "in Under 30 Minutes" and the
    description answers the no-time objection with "no exceptions", so a long recipe is always
    worth a warning.
  * **Disallowed equipment** (``check_equipment``) — the book's editorial promise is that a reader
    who owns only a stovetop, an oven and a blender can cook every recipe. An air fryer, pressure
    cooker, Instant Pot, sous-vide rig or slow cooker breaks that (and a slow cooker cannot meet the
    30-minute promise either).
  * **Ambiguous grain base** (``check_grain_base``) — a soft companion to the ``no_refined_grain_base``
    diet hard block (which only trips on an *explicitly* refined name like "white rice"): a
    carbohydrate base named only "pasta" / "rice" / "bread" / … with no whole-grain qualifier.
    Note this book wants the carbohydrate PRESENT — the fix is always to swap its quality, never to
    delete it.

The keyword lists are intentionally conservative — they catch blatant cases, not subtle ones.
"""
import re
from dataclasses import dataclass, field

from src.cooking.quantity_checker import _OIL_KEYWORDS
from src.diet_rules.rules import _REFINED_GRAIN_MIN_G
from src.models.recipe import RecipeDraft

# Cooking *in* a substantial amount of fat — heavier than the diet rules already block.
_HEAVY_COOKING_KW: tuple[str, ...] = (
    "duck fat", "goose fat", "bacon grease", "lard ",
    "plenty of oil", "generous amount of oil", "lots of oil", "copious oil",
    "cover with oil", "oil to cover", "submerge in oil", "submerged in oil",
    "bath of oil", "oil bath", "deep fryer", "deep-fryer",
)

# A home oven / broiler tops out around ~290 °C; anything above this with a °C label is
# almost certainly an °F figure mislabeled (350 / 400 / 425 °F → "°C").
_MAX_PLAUSIBLE_OVEN_C = 290
_CELSIUS_RE = re.compile(r"(\d{2,4})\s*°\s*C\b")

# ── Thirty-minute thresholds (just above the editorial 10 / 25 / 30 so we only flag a clear
#    overshoot). Tighter than the engine's parent cookbook, which allowed 45 min total: here
#    "Under 30 Minutes" is on the cover and "no exceptions" is in the description. ──
_MAX_MEANINGFUL_INGREDIENTS = 12
_MAX_PREP_MIN = 30
_MAX_TOTAL_MIN = 38
# Ingredient names that don't count toward the "meaningful ingredient" tally (a small cooking-oil
# amount is also excluded — see _OIL_MAX_FREE_G below).
_FREEBIE_INGREDIENT_KW: tuple[str, ...] = ("salt", "pepper", "black pepper", "water", "cooking spray")
_OIL_MAX_FREE_G = 20.0  # a small drizzle of oil — not "meaningful"

# ── Equipment the reader may not own (and, for the slow cooker, cannot meet the
#    30-minute promise with). The parent cookbook only banned the air fryer; this
#    book's "everyday, under 30 minutes" positioning rules out the rest too. ──
_DISALLOWED_EQUIPMENT_KW: tuple[str, ...] = (
    "air fryer", "air-fryer", "airfryer",
    "pressure cooker", "instant pot", "instapot",
    "slow cooker", "crock pot", "crock-pot", "crockpot",
    "sous vide", "sous-vide", "immersion circulator",
    "deep fryer", "deep-fryer",
    "stand mixer", "food dehydrator", "ice cream maker", "waffle iron",
)

# ── Ambiguous grain base ──
_BASE_GRAIN_KW: tuple[str, ...] = (
    "pasta", "noodle", "noodles", "bread", "tortilla", "couscous", "rice", "flour",
    "bun", "wrap", "pita",
)
_WHOLE_GRAIN_QUALIFIER_KW: tuple[str, ...] = (
    "whole", "whole-wheat", "wholewheat", "whole-grain", "wholegrain", "brown", "wild",
    "multigrain", "multi-grain", "rye", "oat", "quinoa", "buckwheat", "spelt", "farro",
    "barley", "bulgur", "sprouted",
)


# Health-food / specialty items a typical US shopper can't reliably find at a mainstream supermarket
# (Walmart / Kroger / Target). Conservative + advisory only — the ideation/draft prompts steer away
# and the LLM critic catches nuanced cases; this is a deterministic backstop. Extend as needed.
_HARD_TO_FIND_KW: tuple[str, ...] = (
    "nutritional yeast",
    "coconut aminos", "liquid aminos",
    "psyllium husk", "psyllium",
    "vital wheat gluten", "seitan",
    "lupin flour", "lupini", "teff", "cassava flour", "tigernut", "green banana flour",
    "powdered peanut butter", "peanut butter powder", "pb2",
)


@dataclass
class CookingMethodResult:
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:  # advisory only — Stage 5 never blocks on this
        return not self.warnings


def check_cooking_method(draft: RecipeDraft) -> CookingMethodResult:
    """Inspect the instructions for a heavy/greasy preparation or an implausible oven temperature."""
    warnings: list[str] = []

    for step in draft.instructions:
        low = step.lower()
        hit = next((kw for kw in _HEAVY_COOKING_KW if kw in low), None)
        if hit:
            warnings.append(
                f"Possibly heavy / greasy preparation (\"{hit.strip()}\") — favor a lighter method "
                f"(oven, steaming, stovetop with a drizzle of oil, broiling, poaching)."
            )
            break

    for m in _CELSIUS_RE.finditer(" ".join(draft.instructions)):
        val = int(m.group(1))
        if val > _MAX_PLAUSIBLE_OVEN_C:
            warnings.append(
                f"Suspect temperature: {val}°C — a home oven rarely exceeds ~260°C. "
                f"Check the °C / °F conversion (every temperature should appear in both units)."
            )
            break

    return CookingMethodResult(warnings=warnings)


def _is_meaningful_ingredient(name: str, quantity_g: float) -> bool:
    low = name.lower()
    if any(kw in low for kw in _FREEBIE_INGREDIENT_KW):
        return False
    if any(kw in low for kw in _OIL_KEYWORDS) and quantity_g <= _OIL_MAX_FREE_G:
        return False
    return True


def check_thirty_minutes(draft: RecipeDraft) -> CookingMethodResult:
    """Flag a clear overshoot of the editorial caps (≈10 ingredients / 25 min active / 30 min total —
    see ``easy_recipe_constraints`` in ``data/fatty_liver_diabetes_guidelines.yaml``).

    There is deliberately NO set-and-forget exemption: "in Under 30 Minutes" is on this book's
    cover and its description answers the no-time objection with "no exceptions".
    """
    warnings: list[str] = []

    meaningful = sum(
        1 for ing in draft.ingredients
        if _is_meaningful_ingredient(ing.canonical_name or ing.name, ing.quantity_g)
    )
    if meaningful > _MAX_MEANINGFUL_INGREDIENTS:
        warnings.append(
            f"Long ingredient list: {meaningful} meaningful ingredients (the book aims for about 10 "
            f"or fewer — salt, pepper, water, and a small amount of cooking oil don't count). Consider "
            f"trimming or consolidating."
        )

    if draft.prep_time_min > _MAX_PREP_MIN:
        warnings.append(
            f"Long active time: {draft.prep_time_min} min hands-on (the book aims for about 25 min "
            f"or less). Consider a simpler prep."
        )

    total_min = draft.prep_time_min + (draft.cook_time_max_min or draft.cook_time_min)
    if total_min > _MAX_TOTAL_MIN:
        warnings.append(
            f"Over the 30-minute promise: ~{total_min} min start to finish. The cover says every "
            f"recipe is ready in under 30 minutes and the description says \"no exceptions\" — "
            f"shorten the prep or the cook, or change the format."
        )

    return CookingMethodResult(warnings=warnings)


def check_equipment(draft: RecipeDraft) -> CookingMethodResult:
    """Flag equipment the book does not allow.

    Every recipe must work for a reader who owns only a stovetop, an oven, a sheet pan, a skillet, a
    saucepan and a blender. A slow cooker additionally cannot meet the 30-minute promise.
    """
    haystack = " ".join(draft.instructions).lower()
    haystack += " " + " ".join((ing.name or "") for ing in draft.ingredients).lower()
    hits = sorted({kw for kw in _DISALLOWED_EQUIPMENT_KW if kw in haystack})
    if not hits:
        return CookingMethodResult(warnings=[])
    return CookingMethodResult(warnings=[
        f"Equipment the book does not allow: {', '.join(hits)}. Every recipe must work with a "
        f"stovetop, an oven, a sheet pan, a skillet, a saucepan and a blender — the reader may own "
        f"nothing else, and a slow cooker cannot be ready in 30 minutes."
    ])


def check_grain_base(draft: RecipeDraft) -> CookingMethodResult:
    """Flag a carbohydrate base whose name doesn't say whether it's a whole grain. Soft companion to
    the ``no_refined_grain_base`` hard block, which only trips on an explicitly refined name."""
    warnings: list[str] = []

    for ing in draft.ingredients:
        # BOTH names, concatenated — matching how `_ing_text()` works in
        # src/diet_rules/rules.py, and for a load-bearing reason. `canonical_name`
        # is the USDA-style LOOKUP string and deliberately drops variant qualifiers
        # to match the database: a "Whole wheat couscous, dry" ingredient carries
        # canonical_name "Couscous, dry". Checking canonical_name alone therefore
        # false-positives on every correctly-specified whole grain whose USDA record
        # has no qualifier — observed live on a parchment-baked cod recipe, where the
        # hard block (which reads both) passed and this advisory contradicted it.
        name = f"{ing.name} {ing.canonical_name}".lower()
        if not any(re.search(rf"\b{re.escape(kw)}\b", name) for kw in _BASE_GRAIN_KW):
            continue
        if any(kw in name for kw in _WHOLE_GRAIN_QUALIFIER_KW):
            continue
        if ing.quantity_g < _REFINED_GRAIN_MIN_G:
            continue
        warnings.append(
            f"Carb base \"{ing.name}\" ({ing.quantity_g:g} g) doesn't say whether it's a whole grain "
            f"— the book wants whole/intact grains. Specify e.g. \"brown rice\" / \"100% whole-wheat "
            f"pasta\" / \"whole-grain tortilla\", or swap it. SWAP ITS QUALITY, DO NOT REMOVE IT: "
            f"this book is deliberately not low-carbohydrate and every tier has a carbohydrate floor."
        )

    return CookingMethodResult(warnings=warnings)


def check_everyday_ingredients(draft: RecipeDraft) -> CookingMethodResult:
    """Flag ingredients a typical US shopper can't easily find at a mainstream supermarket
    (health-food / specialty items). Advisory only — a deterministic backstop for the common
    offenders; the prompts steer away and the LLM critic handles the nuanced cases."""
    hits = [
        ing.name
        for ing in draft.ingredients
        if any(kw in (ing.name or "").lower() for kw in _HARD_TO_FIND_KW)
    ]
    if not hits:
        return CookingMethodResult(warnings=[])
    return CookingMethodResult(warnings=[
        f"Hard-to-find ingredient(s): {', '.join(hits)} — health-food / specialty items many US "
        f"shoppers can't easily source. Swap for a mainstream-supermarket staple (e.g. grated "
        f"parmesan for nutritional yeast; soy sauce for aminos; natural peanut butter for the powder)."
    ])

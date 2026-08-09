"""Fatty-liver (MASLD) + type-2-diabetes diet rules.

Deterministic checks derived from ``data/fatty_liver_diabetes_guidelines.yaml``
(parsed by :mod:`src.diet_rules.spec`).

Two kinds of rule:

  * **Hard-block rules** (structural, blocking) — catch *blatant* violations of
    the YAML's eight ``hard_blocks``: an alcoholic ingredient, deep-frying, a
    sugar-sweetened beverage or fruit juice as a component, a high-fructose
    syrup, a recipe that is essentially a sugar-delivery vehicle, a refined-grain
    base, a processed/cured-meat base, or a tropical saturated fat used as the
    cooking fat. They run pre- and post-nutrition. They are deliberately
    **conservative** (quantity thresholds, narrow keyword lists, false-friend
    guards): a false positive sends the draft back through Stage 2's correction
    loop, so we err toward leniency and let the prompt (which states the hard
    rules up front), the Stage-5b critic, and the human review gate catch what
    slips through.

  * **Soft per-tier rules** (warnings, never blocking) — once nutrition is
    computed, check the recipe against its chapter's nutrient tier
    (``main`` / ``light_main`` / ``snack`` / ``dessert``): protein and fiber
    floors, the **carbohydrate window (BOTH ends)**, sodium / saturated-fat /
    energy bounds, and an added-sugar ceiling (preferring the LLM-estimated
    ``NutritionInfo.added_sugar_g``, falling back to an added-sweetener
    ingredient-gram proxy — ``NutritionInfo.sugar_g`` is *total* sugars, not
    *added*, so it can't substitute).

Two things here differ from the engine's parent cookbook and are load-bearing:

  1. **``no_alcohol_ingredient`` blocks at ANY quantity.** This is the signature
     rule of a fatty-liver book. The AGA asks readers to restrict or eliminate
     alcohol; AASLD reports that *moderate* use increases the probability of
     advanced fibrosis. Retention after cooking is unreliable, so "it cooks off"
     is not a defence.
  2. **Carbohydrate warns in BOTH directions.** A recipe that is impressively low
     in carbohydrate is a *defect* in this book — see the docstring of
     :mod:`src.diet_rules.spec`. There is no ``net_carbs`` rule at all.

FALSE-FRIEND ORDER MATTERS in several lists below (``"wine vinegar"`` inside
``"red wine vinegar"``, ``"apple cider vinegar"`` inside ``"cider"``,
``"no added sugar"`` inside ``"sugar"``). The guards are tested *before* the
positive keyword in every case. Reordering or "simplifying" them silently flips
the polarity of a block.

The keyword lists match English ingredient/instruction text. Cf.
``src/cooking/quantity_checker.py`` and ``src/cooking/method_checker.py``, which
carry similar lists.
"""
import re
from functools import cache

from src.diet_rules.base_rule import BaseDietRule
from src.diet_rules.spec import NutrientEnvelope, load_spec
from src.models.diet import RuleResult
from src.models.nutrition import NutritionInfo
from src.models.recipe import Ingredient, RecipeDraft

# Every recipe in this book serves 2. Used for the added-sugar ingredient proxy.
SERVINGS = 2

# ── English keyword lists (best-effort, conservative) ───────

# --- 1. Alcohol. The signature block: ANY quantity fails. -------------------
# Bare "gin" is deliberately absent — `\bgin` matches the start of "ginger".
# Bare "port" is absent — it matches "portobello" and "portion".
# Bare "ale" is absent — it matches the start of "aleppo".
_ALCOHOL_KW = (
    "wine", "beer", "lager", "pale ale", "amber ale", "stout", "porter",
    "hard cider", "hard seltzer", "sake", "mirin", "shaoxing", "vermouth",
    "sherry", "marsala", "madeira", "port wine", "brandy", "cognac", "armagnac",
    "calvados", "kirsch", "rum", "bourbon", "whiskey", "whisky", "scotch",
    "vodka", "tequila", "mezcal", "london dry gin", "dry gin", "liqueur",
    "amaretto", "grand marnier", "cointreau", "triple sec", "kahlua", "baileys",
    "campari", "aperol", "prosecco", "champagne", "chardonnay", "sauvignon",
    "merlot", "pinot noir", "cabernet", "riesling", "rioja", "grappa", "ouzo",
    "schnapps", "absinthe", "curacao", "creme de cassis", "irish cream",
)
# Tested FIRST. Vinegars are the big one — "red wine vinegar", "white wine
# vinegar", "rice wine vinegar" and "sherry vinegar" are pantry staples and this
# book leans on acid as its main salt replacement, so a wine block that swallows
# them would make most recipes undraftable. "Bourbon vanilla" is a bean variety.
# "Root beer" and "ginger beer" are soft drinks (caught by the SSB block instead).
# Extracts are alcohol-based but used by the teaspoon and explicitly exempt.
_ALCOHOL_FALSE_FRIENDS = (
    "wine vinegar", "sherry vinegar", "champagne vinegar", "rice wine vinegar",
    "apple cider vinegar", "cider vinegar", "bourbon vanilla", "root beer",
    "ginger beer", "beer-battered onion",  # a name we block anyway via deep-fry
    "non-alcoholic", "nonalcoholic", "alcohol-free", "de-alcoholized",
    "vanilla extract", "almond extract", "rum extract", "brandy extract",
    "wine-poached pear substitute",
)
# Instruction techniques that only work with alcohol.
_ALCOHOL_TECHNIQUE_KW = (
    "flambe", "flambé", "flame the", "deglaze with wine", "deglaze with the wine",
    "deglaze with beer", "deglaze with sherry", "deglaze with vermouth",
    "add the wine", "pour in the wine", "add the beer",
)

# --- 2. Deep-frying --------------------------------------------------------
_DEEP_FRY_KW = (
    "deep-fry", "deep fry", "deep-fried", "deep fried", "deep frying", "deep-frying",
    "shallow-fry", "shallow fry", "bath of oil", "submerged in hot oil",
    "submerge in hot oil", "in a deep fryer", "inch of oil", "inches of oil",
    "cm of oil", "batter and fry", "dredge and fry",
)
_DEEP_FRY_OIL_KW = (
    "deep-frying oil", "deep frying oil", "oil for deep frying",
    "oil for deep-frying", "oil for frying",
)

# --- 3. Sugar-sweetened beverages and fruit juice ---------------------------
_SSB_KW = (
    "soda", "cola", "coca-cola", "pepsi", "sprite", "fanta", "mountain dew", "dr pepper",
    "lemonade", "iced tea", "sweet tea", "energy drink", "red bull", "monster energy",
    "gatorade", "powerade", "sports drink", "fruit punch", "kool-aid", "hi-c", "sunny d",
    "root beer", "ginger beer", "tonic water", "sweetened condensed",
)
# "soda" is also a leavening agent and an unsweetened mixer; without these guards
# every baked dessert trips the block. ("cola" inside "chocolate" is handled by
# the word-start anchoring in `_has_kw`, not here.)
_SSB_FALSE_FRIENDS = (
    "baking soda", "bicarbonate of soda", "club soda", "soda water", "soda bread",
    "diet soda",  # still discouraged in prose, but not a hard structural block
    "unsweetened iced tea", "unsweetened tea",
)
# Fruit juices and nectars. NIDDK names juices alongside soda as a source of the
# simple sugars to avoid — this is the fructose vehicle the book exists to remove.
_JUICE_KW = (
    "orange juice", "apple juice", "apple cider", "grape juice", "pineapple juice",
    "fruit juice", "mango juice", "pomegranate juice", "cranberry juice",
    "juice cocktail", "fruit nectar", "juice concentrate", "cider concentrate",
)
# Lemon and lime juice are this book's main salt replacement and must never trip.
_JUICE_FALSE_FRIENDS = (
    "lemon juice", "lime juice", "tomato juice", "apple cider vinegar",
    "cider vinegar", "lemon juice concentrate", "lime juice concentrate",
)
_JUICE_MIN_G = 25.0  # total for 2 servings — below this it is seasoning, not a component

# --- 4. High-fructose syrups. Any quantity fails. --------------------------
# Fructose raises MASLD/MASH/fibrosis risk independent of calorie intake, and the
# AGA asks readers to limit or eliminate commercially produced fructose. These
# three are never necessary and always replaceable.
_HIGH_FRUCTOSE_KW = (
    "high-fructose corn syrup", "high fructose corn syrup", "hfcs",
    "corn syrup", "glucose-fructose syrup", "fructose syrup", "crystalline fructose",
    "agave nectar", "agave syrup", "agave",
)
_HIGH_FRUCTOSE_FALSE_FRIENDS = ("agave plant", "corn syrup solids-free")

# --- 5. Added sweetener as the primary base --------------------------------
_SWEETENER_KW = (
    "sugar", "honey", "maple syrup", "agave", "agave nectar", "corn syrup", "glucose syrup",
    "rice syrup", "rice malt syrup", "brown sugar", "cane sugar", "coconut sugar",
    "powdered sugar", "confectioners sugar", "confectioner's sugar", "molasses",
    "turbinado sugar", "demerara sugar", "date syrup", "date paste", "palm sugar",
)
_SWEETENER_FALSE_FRIENDS = (
    "no sugar", "no added sugar", "no-sugar-added", "sugar-free", "sugar free",
    "unsweetened", "sugar snap", "sugar substitute", "sugar alcohol", "sugar pumpkin",
)
_SWEETENER_PRIMARY_MIN_G = 40.0  # total for 2 servings — below this it is a flavoring

# --- 6. Refined-grain base -------------------------------------------------
# Only trips when the name *explicitly* says refined AND it is present at
# carbohydrate-base weight. "white beans"/"white onion"/"white fish"/"white
# pepper" cannot match because every keyword is a full phrase.
_REFINED_GRAIN_KW = (
    "white rice", "polished rice", "instant rice", "white pasta", "white bread",
    "white sandwich bread", "white flour", "refined flour", "bleached flour",
    "white all-purpose flour", "white bread flour", "white semolina",
    "flour tortilla", "white tortilla", "white baguette", "white roll",
    "couscous", "instant cereal", "corn flakes", "puffed rice", "white pita",
)
_REFINED_GRAIN_FALSE_FRIENDS = (
    "whole-wheat couscous", "whole wheat couscous", "whole-grain couscous",
    "whole-wheat flour tortilla", "whole wheat flour tortilla",
    "whole-wheat pita", "whole wheat pita",
)
_REFINED_GRAIN_MIN_G = 50.0  # total for 2 servings → the carbohydrate base

# --- 7. Processed / cured meat base ----------------------------------------
_PROCESSED_MEAT_KW = (
    "bacon", "sausage", "salami", "chorizo", "pepperoni", "prosciutto", "mortadella",
    "pastrami", "bologna", "hot dog", "frankfurter", "deli ham", "deli turkey",
    "corned beef", "spam", "guanciale", "speck", "kielbasa", "andouille", "pancetta",
)
_VEGGIE_FALSE_FRIENDS = (
    "vegan", "veggie ", "plant-based", "plant based", "tofu", "soy ", "seitan",
    "tempeh", "meatless",
)
_PROCESSED_MEAT_MIN_G = 60.0  # total for 2 servings (~30 g/serving) → a base, not an accent

# --- 8. Tropical saturated fat as the cooking fat --------------------------
# Coconut oil is ~82-90% saturated. These are the "healthy-sounding" fats that
# would quietly break the <10%-of-energy saturated-fat rule while looking
# virtuous on the ingredient list.
_TROPICAL_FAT_KW = (
    "coconut oil", "palm oil", "palm kernel oil", "palm shortening",
    "coconut cream", "cream of coconut", "coconut butter", "creamed coconut",
)
_TROPICAL_FAT_MIN_G = 5.0  # ~1 tsp — any culinary amount counts
# Full-fat coconut milk is a legitimate ingredient in a small amount; blocked
# only at base weight, and never when it is the light/lite version.
_COCONUT_MILK_KW = ("coconut milk",)
_COCONUT_MILK_FALSE_FRIENDS = ("light coconut milk", "lite coconut milk", "reduced-fat coconut milk")
_COCONUT_MILK_MIN_G = 120.0  # total for 2 servings (~60 g/serving)
_TROPICAL_FAT_FALSE_FRIENDS = (
    "coconut water", "coconut aminos", "coconut flour", "coconut extract",
    "coconut sugar", "shredded coconut", "desiccated coconut", "coconut flakes",
    "hearts of palm", "heart of palm", "palm heart", "coconut vinegar",
)


def _ing_text(ing: Ingredient) -> str:
    return f"{ing.name} {ing.canonical_name}".lower()


@cache
def _kw_pattern(keywords: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")")


def _has_kw(text: str, keywords: tuple[str, ...]) -> bool:
    """True when a keyword starts at a word boundary in *text*.

    Only the *start* is anchored, so inflections still match ("sausage" →
    "sausages", "deep-fry" → "deep-frying"). A plain substring test also matched
    *inside* longer words — "cola" in "chocolate" — which blocked every chocolate
    dessert as a sugar-sweetened beverage.
    """
    return bool(_kw_pattern(keywords).search(text))


def _is_sweetener(ing: Ingredient) -> bool:
    n = _ing_text(ing)
    if _has_kw(n, _SWEETENER_FALSE_FRIENDS):
        return False
    return _has_kw(n, _SWEETENER_KW)


# ── hard-block rules (structural, blocking) ─────────────────

class NoAlcoholIngredient(BaseDietRule):
    """No alcoholic ingredient at ANY quantity — the book's signature rule.

    Alcohol should be restricted or eliminated in fatty liver (AGA), and moderate
    use increases the probability of advanced fibrosis (AASLD). Retention after
    cooking is unreliable, so a "it burns off" exception is not offered. Wine,
    sherry, champagne and rice-wine *vinegars* are explicitly exempt — this book
    leans on acid as its main salt replacement.
    """

    @property
    def name(self) -> str:
        return "masld.no_alcohol_ingredient"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        for ing in draft.ingredients:
            n = _ing_text(ing)
            if _has_kw(n, _ALCOHOL_FALSE_FRIENDS):
                continue
            if _has_kw(n, _ALCOHOL_KW):
                return self._fail([
                    f"Alcoholic ingredient: \"{ing.name}\". This is a fatty-liver cookbook — no wine, "
                    f"beer, cider, spirits, liqueur, mirin, sake or \"cooking wine\" at any quantity. "
                    f"Deglaze or braise with low-sodium broth, tomato, citrus juice or vinegar instead."
                ])
        for step in draft.instructions:
            s = step.lower()
            if _has_kw(s, _ALCOHOL_FALSE_FRIENDS):
                continue
            if _has_kw(s, _ALCOHOL_TECHNIQUE_KW):
                return self._fail([
                    "The method depends on alcohol (flambé / deglazing with wine or beer). "
                    "Rewrite it to deglaze with low-sodium broth, tomato, citrus or vinegar."
                ])
        return self._ok()


class NoDeepFried(BaseDietRule):
    @property
    def name(self) -> str:
        return "masld.no_deep_fried"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        for step in draft.instructions:
            if _has_kw(step.lower(), _DEEP_FRY_KW):
                return self._fail([
                    "The recipe involves deep- or shallow-frying in a depth of oil. Use the oven, "
                    "the stovetop with a drizzle of olive oil, steaming, broiling, or poaching instead."
                ])
        for ing in draft.ingredients:
            if _has_kw(_ing_text(ing), _DEEP_FRY_OIL_KW):
                return self._fail([
                    "Ingredient names frying oil: the recipe must not be fried in a depth of oil."
                ])
        return self._ok()


class NoSugarSweetenedBeverageOrJuiceComponent(BaseDietRule):
    """No sweetened drink and no fruit juice as a recipe component.

    NIDDK names juices alongside soda as a source of the simple sugars — chiefly
    fructose — to avoid in fatty liver. Lemon and lime juice are exempt: they are
    this book's main salt replacement.
    """

    @property
    def name(self) -> str:
        return "masld.no_sugar_sweetened_beverage_or_juice_component"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        for ing in draft.ingredients:
            n = _ing_text(ing)
            if _has_kw(n, _SSB_KW) and not _has_kw(n, _SSB_FALSE_FRIENDS):
                return self._fail([
                    f"Sugar-sweetened beverage as an ingredient: \"{ing.name}\". No sweetened drink "
                    f"(soda, sweet tea, energy or sports drink, sweetened condensed milk) belongs in a "
                    f"recipe for a reader with fatty liver."
                ])
            if _has_kw(n, _JUICE_FALSE_FRIENDS):
                continue
            if _has_kw(n, _JUICE_KW) and ing.quantity_g >= _JUICE_MIN_G:
                return self._fail([
                    f"Fruit juice as a component: \"{ing.name}\" ({ing.quantity_g:g} g). Fruit juice is a "
                    f"fructose delivery vehicle — use the whole fruit, or lemon/lime juice for acidity."
                ])
        return self._ok()


class NoHighFructoseSweetener(BaseDietRule):
    """No high-fructose corn syrup, corn syrup or agave, at any quantity.

    Excessive fructose raises the risk of MASLD, MASH and advanced fibrosis
    *independent of calorie intake* (AASLD), and the AGA asks readers to limit or
    eliminate commercially produced fructose. Agave nectar is ~85% fructose and is
    the one that most often arrives disguised as the "healthy" sweetener.
    """

    @property
    def name(self) -> str:
        return "masld.no_high_fructose_sweetener"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        for ing in draft.ingredients:
            n = _ing_text(ing)
            if _has_kw(n, _HIGH_FRUCTOSE_FALSE_FRIENDS):
                continue
            if _has_kw(n, _HIGH_FRUCTOSE_KW):
                return self._fail([
                    f"High-fructose sweetener: \"{ing.name}\". Fructose drives the liver to make fat "
                    f"independently of calories — no high-fructose corn syrup, corn syrup or agave at any "
                    f"amount. Sweeten with whole fruit, or a small measured amount of ordinary sugar or "
                    f"maple syrup inside the tier's added-sugar ceiling."
                ])
        return self._ok()


class NoAddedSugarPrimaryBase(BaseDietRule):
    """The recipe must not be essentially a sugar-delivery vehicle — added sugar (or another
    added sweetener) must not be the primary ingredient by weight. Conservative: only trips when
    a single added sweetener is the largest ingredient in the recipe (and above a floor). Desserts
    are held to this too, but their softer added-sugar ceiling is enforced by ``AddedSugarLimit``."""

    @property
    def name(self) -> str:
        return "masld.no_added_sugar_primary_base"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        if not draft.ingredients:
            return self._ok()
        heaviest = max(draft.ingredients, key=lambda i: i.quantity_g)
        if _is_sweetener(heaviest) and heaviest.quantity_g >= _SWEETENER_PRIMARY_MIN_G:
            return self._fail([
                f"Added sweetener is the primary ingredient by weight: \"{heaviest.name}\" "
                f"({heaviest.quantity_g:g} g). The recipe reads as a sugar-delivery vehicle — build it "
                f"on fruit, dairy, nuts, a vegetable or a whole grain and use sweeteners only in a small "
                f"measured amount."
            ])
        return self._ok()


class NoRefinedGrainBase(BaseDietRule):
    @property
    def name(self) -> str:
        return "masld.no_refined_grain_base"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        for ing in draft.ingredients:
            n = _ing_text(ing)
            if _has_kw(n, _REFINED_GRAIN_FALSE_FRIENDS):
                continue
            if _has_kw(n, _REFINED_GRAIN_KW) and ing.quantity_g >= _REFINED_GRAIN_MIN_G:
                return self._fail([
                    f"Refined-grain carbohydrate base: \"{ing.name}\" ({ing.quantity_g:g} g). Use a whole "
                    f"or intact grain (brown rice, quinoa, barley, farro, bulgur, whole-wheat pasta or "
                    f"bread, whole-wheat tortilla) or a base of legumes or vegetables. Keep the "
                    f"carbohydrate — swap its quality, do not remove it."
                ])
        return self._ok()


class NoProcessedCuredMeatBase(BaseDietRule):
    @property
    def name(self) -> str:
        return "masld.no_processed_cured_meat_base"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        for ing in draft.ingredients:
            n = _ing_text(ing)
            if _has_kw(n, _VEGGIE_FALSE_FRIENDS):
                continue
            if _has_kw(n, _PROCESSED_MEAT_KW) and ing.quantity_g >= _PROCESSED_MEAT_MIN_G:
                return self._fail([
                    f"Recipe built on processed / cured meat: \"{ing.name}\" ({ing.quantity_g:g} g). The "
                    f"AGA names red and processed meat specifically when asking readers with fatty liver "
                    f"to cut saturated fat. Use fish, seafood, poultry, eggs, legumes or tofu instead."
                ])
        return self._ok()


class NoTropicalSaturatedFatBase(BaseDietRule):
    """No coconut oil, palm oil, palm kernel oil or coconut cream as an added fat,
    and no full-fat coconut milk at base weight.

    Coconut oil is ~82-90% saturated. These are the fats that look virtuous on an
    ingredient list and quietly break the <10%-of-energy saturated-fat rule.
    Coconut water, aminos, flour, extract and a scatter of shredded coconut are exempt.
    """

    @property
    def name(self) -> str:
        return "masld.no_tropical_saturated_fat_base"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        for ing in draft.ingredients:
            n = _ing_text(ing)
            if _has_kw(n, _TROPICAL_FAT_FALSE_FRIENDS):
                continue
            if _has_kw(n, _TROPICAL_FAT_KW) and ing.quantity_g >= _TROPICAL_FAT_MIN_G:
                return self._fail([
                    f"Tropical saturated fat as the cooking fat: \"{ing.name}\" ({ing.quantity_g:g} g). "
                    f"Coconut oil is ~82-90% saturated and palm oil about half. Use extra-virgin olive "
                    f"oil, or another unsaturated oil."
                ])
            if (
                _has_kw(n, _COCONUT_MILK_KW)
                and not _has_kw(n, _COCONUT_MILK_FALSE_FRIENDS)
                and ing.quantity_g >= _COCONUT_MILK_MIN_G
            ):
                return self._fail([
                    f"Full-fat coconut milk at base weight: \"{ing.name}\" ({ing.quantity_g:g} g). Use the "
                    f"light version, cut the amount, or build the sauce on tomato, broth or low-fat dairy."
                ])
        return self._ok()


# ── soft per-tier rules (warnings) ──────────────────────────

class MealCategoryNutritionTargets(BaseDietRule):
    """Post-nutrition: warn (never block) when the recipe misses its chapter's tier targets.

    CARBOHYDRATE WARNS IN BOTH DIRECTIONS. The under-carbohydrate message is
    written so an editor reading the log cannot mistake a low number for a
    success — see the module docstring and ``daily_targets.carbohydrate`` in the
    spec for why the floor exists.
    """

    def __init__(self, chapter: str) -> None:
        self.chapter = chapter
        self._env: NutrientEnvelope = load_spec().envelope_for_chapter(chapter)

    @property
    def name(self) -> str:
        return f"masld.tier_targets[{self._env.tier}]"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        if nutrition is None:
            return self._ok()  # can't check until nutrition is computed
        env = self._env
        t = env.tier
        w: list[str] = []
        if env.protein_g_floor and nutrition.protein_g < env.protein_g_floor:
            w.append(f"protein {nutrition.protein_g:g} g/serving < floor {env.protein_g_floor:g} g (\"{t}\")")
        if env.fiber_g_floor and nutrition.fiber_g < env.fiber_g_floor:
            w.append(f"fiber {nutrition.fiber_g:g} g/serving < floor {env.fiber_g_floor:g} g (\"{t}\")")
        if env.total_carbs_g_floor is not None and nutrition.carbs_g < env.total_carbs_g_floor:
            w.append(
                f"UNDER-CARBOHYDRATE: total carbohydrate {nutrition.carbs_g:g} g/serving < floor "
                f"{env.total_carbs_g_floor:g} g (\"{t}\"). This is a DEFECT, not a success — this book is "
                f"deliberately not low-carbohydrate. Add a quality carbohydrate (whole grain, legume, "
                f"starchy vegetable or fruit) in a measured portion."
            )
        if env.total_carbs_g_max is not None and nutrition.carbs_g > env.total_carbs_g_max:
            w.append(
                f"total carbohydrate {nutrition.carbs_g:g} g/serving > ceiling "
                f"{env.total_carbs_g_max:g} g (\"{t}\")"
            )
        if env.sodium_mg_max is not None and nutrition.sodium_mg > env.sodium_mg_max:
            w.append(f"sodium {nutrition.sodium_mg:g} mg/serving > ceiling {env.sodium_mg_max:g} mg (\"{t}\")")
        if (
            env.saturated_fat_g_max is not None
            and nutrition.saturated_fat_g is not None
            and nutrition.saturated_fat_g > env.saturated_fat_g_max
        ):
            w.append(
                f"saturated fat {nutrition.saturated_fat_g:g} g/serving > ceiling "
                f"{env.saturated_fat_g_max:g} g (\"{t}\")"
            )
        if env.energy_kcal_min is not None and nutrition.calories_kcal < env.energy_kcal_min:
            w.append(f"{nutrition.calories_kcal:g} kcal/serving < low bound {env.energy_kcal_min:g} kcal (\"{t}\")")
        if env.energy_kcal_max is not None and nutrition.calories_kcal > env.energy_kcal_max:
            w.append(f"{nutrition.calories_kcal:g} kcal/serving > high bound {env.energy_kcal_max:g} kcal (\"{t}\")")
        return self._ok(warnings=w)


class AddedSugarLimit(BaseDietRule):
    """Added-sugar ceiling — the tightest axis in this book.

    Prefers the LLM-estimated ``NutritionInfo.added_sugar_g`` when available;
    otherwise falls back to a structural proxy (sum of added-sweetener ingredient
    grams ÷ servings). ``NutritionInfo.sugar_g`` is *total* sugars, not *added*,
    so it can never substitute.
    """

    def __init__(self, chapter: str) -> None:
        self.chapter = chapter
        self._env: NutrientEnvelope = load_spec().envelope_for_chapter(chapter)

    @property
    def name(self) -> str:
        return f"masld.added_sugar[{self._env.tier}]"

    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult:
        cap = self._env.added_sugar_g_max
        if cap is None:
            return self._ok()
        if nutrition is not None and nutrition.added_sugar_g is not None:
            per_serving = nutrition.added_sugar_g
            note = ""
        else:
            total = 0.0
            for ing in draft.ingredients:
                if _is_sweetener(ing):
                    total += ing.quantity_g
            per_serving = total / float(SERVINGS)
            note = f" (estimated from sweetener grams: {total:g} g total)"
        if per_serving > cap:
            return self._ok(warnings=[
                f"added sugar ≈ {per_serving:g} g/serving{note} > ceiling {cap:g} g (\"{self._env.tier}\") "
                f"— added sugar is the liver-specific axis in this book"
            ])
        return self._ok()


# ── registry ────────────────────────────────────────────────

# Chapter-agnostic — stateless and reused across DietRuleEngine instances.
# ORDER MATCHES `per_recipe_constraints.hard_blocks` IN THE YAML. A test asserts
# that the declared set and the implemented set are identical: a rule id declared
# in the spec with no class here is a silent no-op.
_HARD_BLOCK_RULES: tuple[BaseDietRule, ...] = (
    NoAlcoholIngredient(),
    NoDeepFried(),
    NoSugarSweetenedBeverageOrJuiceComponent(),
    NoHighFructoseSweetener(),
    NoAddedSugarPrimaryBase(),
    NoRefinedGrainBase(),
    NoProcessedCuredMeatBase(),
    NoTropicalSaturatedFatBase(),
)


def build_rules(chapter: str = "poultry_meat_dinners") -> list[BaseDietRule]:
    """The fatty-liver + type-2-diabetes rule set for ``chapter``: the (chapter-agnostic)
    hard blocks plus the chapter's per-tier soft checks."""
    return [
        *_HARD_BLOCK_RULES,
        MealCategoryNutritionTargets(chapter),
        AddedSugarLimit(chapter),
    ]

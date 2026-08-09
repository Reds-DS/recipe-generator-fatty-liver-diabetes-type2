"""
Pydantic schemas used as structured output targets for LLM responses.
These are separate from the domain models to allow strict LLM-facing validation.
"""
from typing import Literal

from pydantic import BaseModel, Field


class BriefIngredient(BaseModel):
    name: str = Field(description="Ingredient name, no quantity")


class RecipeBriefOutput(BaseModel):
    title_candidate: str = Field(description="Short title (max 8-10 words), descriptive and appetizing. The reader should understand the recipe from the title alone.")
    main_ingredient: str
    cuisine_style: str = Field(description="e.g. Mediterranean, Asian, classic American, Tex-Mex")
    technique: str = Field(description="Main cooking technique")
    flavour_profile: str = Field(description="e.g. spicy, mild, umami, lemony")
    ingredients_sketch: list[str] = Field(
        description="Ingredient names only, no quantities",
        min_length=4,
        max_length=12,
    )
    unique_angle: str = Field(description="What makes this recipe distinct")
    forbidden_items: list[str] = Field(
        description="Ingredients to exclude (allergens + diet rules)"
    )


class DraftIngredient(BaseModel):
    name: str = Field(description="Name as it appears in the recipe (English)")
    canonical_name: str = Field(
        description="English name to look this ingredient up in the USDA FoodData Central database — "
        "use the MOST SPECIFIC name available, worded like a USDA description (noun first, then "
        "qualifiers / cooking state). E.g. 'Chicken, broilers or fryers, breast, meat only, cooked, roasted'; "
        "'Rice, brown, long-grain, cooked'; 'Oats, raw'. Never a generic name when a specific one exists."
    )
    quantity_g: float = Field(gt=0, description="Amount in grams (always grams)")
    quantity_display: str = Field(description="Human-readable AMOUNT ONLY — never repeat the ingredient name here. Liquids in spoons show ml: '1 tbsp (15 ml)'. Solid spoon amounts show grams: '1 tsp (2 g)'. Large amounts: '10 oz (300 g)'.")
    preparation: str | None = Field(None, description="e.g. diced, finely chopped, sliced")


class RecipeDraftOutput(BaseModel):
    """Strict schema for Stage 2 LLM output."""
    title: str = Field(description="Short title (max 8-10 words), descriptive and appetizing. Should reflect the main ingredients (protein + side/topping).")
    intro: str = Field(
        description="1-2 sentences max. Mentions the main ingredients. Style varies per the INTRO STYLE given in the brief."
    )
    servings: Literal[2] = 2
    prep_time_min: int = Field(
        gt=0,
        description="Active hands-on minutes, INCLUDING chopping and prep. The cover promises every "
        "recipe is ready in under 30 minutes and the book's description says 'no exceptions': keep "
        "this at about 25 min or less, and prep + cook at 30 min or less. There is no set-and-forget "
        "exemption in this book.",
    )
    cook_time_min: int = Field(
        ge=0,
        description="Low end of the ACTIVE cook-time range, in minutes — heat applied on the stovetop or "
        "in the oven only. Use 0 for a no-cook recipe (blend / mash / assemble / marinate / chill). Do "
        "NOT count blending, whisking, marinating, resting, or refrigerator chilling as cook time.",
    )
    cook_time_max_min: int = Field(
        ge=0,
        description="High end of the ACTIVE cook-time range, in minutes (0 for a no-cook recipe). Same "
        "rule as cook_time_min: only heat-applied stovetop/oven time counts.",
    )
    passive_time: str | None = Field(
        None,
        description="Hands-off waiting that is NOT active cooking, as a short labeled phrase — e.g. "
        "'Chill 30-45 min', 'Marinate 5-10 min', 'Rest 5 min'. null if there is none. Refrigerator "
        "chilling, marinating, and resting go HERE, never in cook_time, and never count toward the "
        "book's 30-minute promise — so any wait declared here must be genuinely optional or clearly "
        "make-ahead. Prefer recipes that need none at all.",
    )
    ingredients: list[DraftIngredient] = Field(
        min_length=4,
        max_length=15,
        description="Aim for about 10 meaningful ingredients or fewer — salt, pepper, water, and a "
        "small amount of cooking oil don't count toward that.",
    )
    instructions: list[str] = Field(
        min_length=3,
        max_length=7,
        description="7 steps maximum. Each step starts with an imperative action verb (Chop, Mix, ...). Temperatures always in °F AND °C (e.g. 375°F / 190°C). Plain language. Do NOT repeat quantities.",
    )
    variation: str = Field(
        description="10-11 words max. A real change: swap a vegetable / protein / spice. "
        "E.g. 'Swap the zucchini for eggplant.'"
    )
    conservation: str = Field(
        description="If it doesn't keep: 6-7 words (e.g. 'Best enjoyed right away; does not keep.'). "
        "If it keeps: 'Keeps X hr in a [container]; reheat [method].'"
    )


# ── Nutrition (Stage 4) ───────────────────────────────────────

class EstimatedNutrientsPer100g(BaseModel):
    """The LLM's per-100 g estimate for an ingredient with no good USDA match."""
    calories_kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    fiber_g: float = Field(ge=0)
    total_sugar_g: float = Field(ge=0)
    sodium_mg: float = Field(ge=0)
    saturated_fat_g: float | None = Field(None, description="Estimate it if you can; null if unsure.")


class NutritionIngredientPick(BaseModel):
    """The LLM's choice of a USDA FoodData Central food for one recipe ingredient."""
    ingredient_name: str
    fdc_id: int | None = Field(
        None,
        description="The fdc_id of the best-matching USDA food from the shortlist. "
        "null ONLY if no candidate is a reasonable match — in that case fill estimate_per_100g.",
    )
    fdc_description: str | None = Field(None, description="The chosen food's description (for the record).")
    estimate_per_100g: EstimatedNutrientsPer100g | None = Field(
        None, description="Required if and only if fdc_id is null."
    )
    note: str = Field("", description="Optional: one short clause if the pick was a stretch or estimated.")


class NutritionOutput(BaseModel):
    """Stage 4 — the LLM picks a USDA food per ingredient (or estimates) and estimates the
    recipe's added sugar; the application does all the per-serving arithmetic."""
    per_ingredient: list[NutritionIngredientPick] = Field(
        description="One entry per recipe ingredient, in the order given."
    )
    added_sugar_g_recipe_total: float = Field(
        ge=0,
        description="Estimated grams of ADDED sugar in the whole 2-serving recipe — sugar from "
        "added sweeteners (table/brown sugar, honey, maple syrup, agave, molasses, syrups, "
        "fruit-juice concentrate used as a sweetener, etc.), NOT the sugar naturally in fruit, "
        "milk, or vegetables. 0 if the recipe uses no added sweetener.",
    )
    reasoning: str = Field(
        default="", description="1-2 sentences on hard picks or estimated ingredients."
    )


class FormattedRecipeOutput(BaseModel):
    """Stage 6 output — only the prose fields are rewritten."""
    intro: str = Field(description="1-2 sentences max; keep the original intro's style and angle")
    instructions: list[str] = Field(description="Short steps (1-2 sentences), imperative verbs, precise times")


# ── Image Critic (Stage 7c) ──────────────────────────────────

class ImageCriticOutput(BaseModel):
    """Structured output from the image critic (Stage 7c)."""
    passed: bool = Field(description="True if the image is acceptable")
    issues: list[str] = Field(
        default_factory=list,
        description="Specific problems found (empty if passed=True)",
    )
    feedback_for_prompt: str = Field(
        default="",
        description="Specific feedback for improving the image prompt on the next attempt",
    )
    summary: str = Field(description="Concise assessment in English")


# ── Critic (Stage 5b) ─────────────────────────────────────────

class CriticDimensionVerdict(BaseModel):
    """Verdict for a single quality dimension."""
    dimension: str = Field(description="Name of the dimension evaluated")
    passed: bool = Field(description="True if acceptable, False if it needs improvement")
    severity: Literal["minor", "major", "critical"] = Field(
        description="minor=cosmetic, major=should be fixed, critical=must be fixed"
    )
    feedback: str = Field(
        description="Specific, actionable feedback in English. "
        "If passed=True, briefly say why. "
        "If passed=False, describe the problem and suggest a concrete fix."
    )


class CriticOutput(BaseModel):
    """Structured output from the critic LLM (Stage 5b)."""
    overall_pass: bool = Field(
        description="True only if EVERY dimension is passed=True or severity=minor"
    )
    dimensions: list[CriticDimensionVerdict] = Field(
        min_length=8,
        max_length=14,
        description="The 8 culinary + ~4 guideline-fit verdicts (8–14), one per quality dimension",
    )
    summary: str = Field(
        description="1-2 sentences: overall assessment of the recipe in English"
    )


# ── Course-list alias resolver ────────────────────────────────

class AliasGroup(BaseModel):
    canonical: str = Field(
        description="Short canonical name to show in the shopping list (e.g. 'Plain soy yogurt')"
    )
    members: list[str] = Field(
        min_length=1,
        description="Exact names from the input group that map to this product"
    )


class AliasResolverOutput(BaseModel):
    """Output of the LLM alias-merging pass for ambiguous ingredient clusters."""
    groups: list[AliasGroup] = Field(
        description=(
            "One entry per identified sub-group. "
            "Members of the same input cluster may be split into several AliasGroups "
            "if the LLM decides they are different products."
        )
    )

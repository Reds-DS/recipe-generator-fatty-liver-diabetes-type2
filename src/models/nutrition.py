"""Pydantic models for computed nutrition.

`NutritionInfo` is the per-recipe nutrition panel (per serving — every recipe serves 2).
The first 7 fields are the always-present core macros; the rest are the FDA-Nutrition-Facts
extras + the diet-rule inputs, populated by Stage 4 from USDA FoodData Central where the
data exists and `None` otherwise. `added_sugar_g` is always an LLM estimate (USDA carries
no "added sugars" value for generic foods). The full per-recipe panel — which nutrients,
why, units, food-DB source ids — is defined in `data/fatty_liver_diabetes_guidelines.yaml`
(`nutrition_panel`) and `docs/fatty_liver_diabetes_guidelines.md` (section C). A nutrient a
food DB doesn't carry for a given food is `None`, never a fake `0`.
"""
from typing import Literal

from pydantic import BaseModel, Field


class NutritionInfo(BaseModel):
    """Per-serving nutrition for a recipe — computed from USDA FoodData Central (or
    LLM-estimated where USDA has no match). See the module docstring for the panel."""
    # ── core macros: always present (fall back to 0 + a warning if a food DB lacks them) ──
    calories_kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)  # total carbohydrate incl. fiber & sugars (not "net carbs")
    fat_g: float = Field(ge=0)  # total fat
    fiber_g: float = Field(ge=0)
    sodium_mg: float = Field(ge=0)
    sugar_g: float = Field(ge=0)  # total sugars (added + naturally occurring)
    # ── FDA-Nutrition-Facts extras + diet-rule inputs; None where USDA has no value ──
    saturated_fat_g: float | None = None
    added_sugar_g: float | None = None  # always an LLM estimate — USDA has no value for generic foods
    cholesterol_mg: float | None = None
    potassium_mg: float | None = None  # needs individualization for chronic kidney disease
    trans_fat_g: float | None = None  # sparse in USDA (~31% of generic foods)
    mufa_g: float | None = None  # monounsaturated fat
    pufa_g: float | None = None  # polyunsaturated fat
    calcium_mg: float | None = None
    iron_mg: float | None = None
    vitamin_d_mcg: float | None = None  # sparse in USDA (~78% of generic foods)
    # the old "ciqual"/"llm_ciqual"/etc. values are kept so older recipe JSON validates
    source: Literal["usda", "llm_usda", "mixed", "ciqual", "open_food_facts", "fallback", "llm", "llm_ciqual"] = "fallback"
    missing_ingredients: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"

    # ── derived helpers (no extra data needed) ──
    @property
    def net_carbs_g(self) -> float:
        """Net carbohydrate — a low-carb convenience metric, NOT an FDA/ADA term:
        max(0, total carbohydrate − dietary fiber). Sugar alcohols (rare in these recipes)
        are not tracked as a separate field, so they are not subtracted. Always print total
        carbs + fiber alongside it and footnote that "net carbs" has no regulatory definition."""
        return max(0.0, self.carbs_g - self.fiber_g)

    @property
    def saturated_fat_pct_kcal(self) -> float | None:
        """Saturated fat as a percentage of this serving's calories (the DGA frames the
        limit as < 10% of calories). `None` if saturated fat is unknown or calories is 0."""
        if self.saturated_fat_g is None or not self.calories_kcal:
            return None
        return self.saturated_fat_g * 9 / self.calories_kcal * 100

    @property
    def protein_per_100kcal(self) -> float | None:
        """Protein density — grams of protein per 100 kcal; used for internal targeting of
        protein-dense recipes (the book's headline promise). `None` if calories is 0."""
        if not self.calories_kcal:
            return None
        return self.protein_g / self.calories_kcal * 100


class IngredientNutrition(BaseModel):
    """Nutrition contribution of a single ingredient (total for the recipe, before per-serving
    division). Carries the same nutrient set as `NutritionInfo`; extra fields are `None` where
    the food DB has no value. (Stage 4 currently attaches per-ingredient provenance directly to
    `Ingredient` rather than constructing these — kept for the `meal-plan` / lookup code paths.)"""
    ingredient_name: str
    quantity_g: float
    calories_kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sodium_mg: float
    sugar_g: float
    saturated_fat_g: float | None = None
    added_sugar_g: float | None = None
    cholesterol_mg: float | None = None
    potassium_mg: float | None = None
    trans_fat_g: float | None = None
    mufa_g: float | None = None
    pufa_g: float | None = None
    calcium_mg: float | None = None
    iron_mg: float | None = None
    vitamin_d_mcg: float | None = None
    source: Literal["usda", "ciqual", "open_food_facts", "fallback", "missing"] = "missing"

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Book chapters / recipe-generation categories. Keep in sync with
# RECIPE_CHAPTERS in src/constants.py and the `recipe_categories:` keys in
# data/fatty_liver_diabetes_guidelines.yaml.
RecipeChapter = Literal[
    "breakfasts",
    "soups_salads",
    "lunches",
    "poultry_meat_dinners",
    "fish_seafood_dinners",
    "vegetable_meatless_dinners",
    "snacks_sides",
    "desserts",
]


class Ingredient(BaseModel):
    name: str
    canonical_name: str
    quantity_g: float = Field(gt=0, description="Always stored in grams internally")
    quantity_display: str = Field(description="Human-readable e.g. '200 g' or '2 tbsp'")
    preparation: str | None = None
    fdc_id: int | None = None  # USDA FoodData Central food picked in Stage 4
    # "usda"/"llm_estimate" are the current values; the rest are kept so older recipe JSON validates
    nutrition_source: Literal["usda", "llm_estimate", "ciqual", "open_food_facts", "fallback", "missing"] = "missing"
    is_optional: bool = False


class RecipeBrief(BaseModel):
    """Output of Stage 1 — ideation. No quantities, no nutrition."""
    title_candidate: str
    main_ingredient: str
    cuisine_style: str
    technique: str
    flavour_profile: str
    ingredients_sketch: list[str] = Field(description="Names only, no quantities")
    unique_angle: str = Field(description="What makes this recipe distinct")
    forbidden_items: list[str] = Field(description="Derived from diet rules + user exclusions")
    meal_type: Literal["breakfast", "lunch", "snack", "dinner", "dessert"] = "dinner"
    chapter: RecipeChapter = "poultry_meat_dinners"


class RecipeDraft(BaseModel):
    """Output of Stage 2 — draft. Quantities and LLM-estimated nutrition present."""
    title: str
    intro: str
    diet_tags: list[str] = Field(default_factory=list)
    meal_type: Literal["breakfast", "lunch", "snack", "dinner", "dessert"] = "dinner"
    chapter: RecipeChapter = "poultry_meat_dinners"
    servings: Literal[2] = 2
    prep_time_min: int = Field(gt=0)
    cook_time_min: int = Field(ge=0)  # 0 = no-cook (blend/assemble/marinate/chill)
    cook_time_max_min: int | None = None
    passive_time: str | None = None  # e.g. "Chill 30-45 min" — hands-off, not active cooking
    ingredients: list[Ingredient]
    instructions: list[str] = Field(min_length=3, max_length=7)
    variation: str | None = None
    conservation: str | None = None
    llm_model: str = ""
    generation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class Recipe(BaseModel):
    """Final validated model written to disk."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    intro: str
    diet_tags: list[str] = Field(default_factory=list)
    meal_type: Literal["breakfast", "lunch", "snack", "dinner", "dessert"] = "dinner"
    chapter: RecipeChapter = "poultry_meat_dinners"
    servings: Literal[2] = 2
    prep_time_min: int
    cook_time_min: int
    cook_time_max_min: int | None = None
    passive_time: str | None = None  # e.g. "Chill 30-45 min" — hands-off, not active cooking
    ingredients: list[Ingredient]
    instructions: list[str]
    variation: str | None = None
    conservation: str | None = None
    nutrition_per_serving: "NutritionInfo | None" = None
    validation_passed: bool = False
    validation_warnings: list[str] = Field(default_factory=list)
    image_path: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    generation_id: str = ""


# Avoid circular import — NutritionInfo imported at runtime
from src.models.nutrition import NutritionInfo  # noqa: E402

RecipeDraft.model_rebuild()
Recipe.model_rebuild()


# ---------------------------------------------------------------------------
# Per-recipe structured log (not persisted in Recipe itself)
# ---------------------------------------------------------------------------

@dataclass
class StageLogEntry:
    stage: str
    status: str  # "ok", "warning", "corrected", "failed"
    warnings: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecipeLog:
    # Input parameters
    main_ingredient: str | None = None
    meal_type: str = ""
    chapter: str = ""
    exclusions: list[str] = field(default_factory=list)

    # Pipeline execution
    recipe_title: str = ""
    recipe_id: str = ""
    generation_id: str = ""
    llm_model: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    draft_attempts: int = 0
    critic_attempts: int = 0
    stages: list[StageLogEntry] = field(default_factory=list)

    # Aggregated outcome
    validation_passed: bool = False
    total_warnings: int = 0
    total_corrections: int = 0

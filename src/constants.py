"""Shared constants: meal-type keys, on-disk folder names, and book chapters.

Extracted from cli.py so code under src/planning/ can reuse them without
importing the Typer app.
"""

VALID_MEAL_TYPES: set[str] = {"breakfast", "lunch", "snack", "dinner", "dessert"}

MEAL_TYPE_FOLDERS: dict[str, str] = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "snack": "Snack",
    "dinner": "Dinner",
    "dessert": "Dessert",
}

MEAL_TYPE_LABELS: dict[str, str] = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "snack": "Snack",
    "dinner": "Dinner",
    "dessert": "Dessert",
}

# Meals a reader may skip without breaking the plan.
#
# DESSERT ONLY — the snack slot is deliberately NOT optional in this book. The
# ADA names skipped meals and irregular intake as hypoglycemia drivers for
# readers on insulin or a sulfonylurea, and the snack tier carries part of the
# day's carbohydrate floor (see `masld_diabetes_mitigations.insulin_or_sulfonylurea`
# in the spec). Dropping the snack takes the day's carbohydrate below the line the
# floors were sized to clear. Kept as a separate constant rather than baked into
# MEAL_TYPE_LABELS because those labels also title the recipe-book PDF sections
# (see `export-recipes-pdf`), where "Snack (optional)s" would be nonsense.
OPTIONAL_MEAL_TYPES: frozenset[str] = frozenset({"dessert"})

# ---------------------------------------------------------------------------
# Book chapters / recipe-generation categories.
#
# Each chapter is both a section of the printed book and a generation target.
# It maps to one of the meal-type keys above so the meal planner can
# place its recipes, and to one nutrient tier in
# data/fatty_liver_diabetes_guidelines.yaml -> per_recipe_constraints.meal_categories.
# Full per-chapter detail (intent, "character" brief, target recipe count)
# lives in that YAML under `recipe_categories`.
#
# Keep RECIPE_CHAPTERS in sync with the `RecipeChapter` Literal in
# src/models/recipe.py and the `recipe_categories:` keys in the YAML.
# (tests/test_recipe_pipeline.py asserts all three agree.)
#
# 8 chapters, 106 recipes. Three chapters share the `dinner` slot and two share
# `lunch`, so RECIPE_CHAPTER_MEAL_TYPES is NOT a bijection —
# MEAL_TYPE_DEFAULT_CHAPTER nominates one chapter per slot.
# ---------------------------------------------------------------------------
RECIPE_CHAPTERS: tuple[str, ...] = (
    "breakfasts",
    "soups_salads",
    "lunches",
    "poultry_meat_dinners",
    "fish_seafood_dinners",
    "vegetable_meatless_dinners",
    "snacks_sides",
    "desserts",
)

# Dead code kept only to avoid drift — the LIVE chapter title flows from the
# YAML `recipe_categories.<slug>.book_title` via spec.load_spec(). Editing this
# map alone changes nothing the LLM sees.
RECIPE_CHAPTER_TITLES: dict[str, str] = {
    "breakfasts": "Breakfasts",
    "soups_salads": "Soups & Salads",
    "lunches": "Lunches",
    "poultry_meat_dinners": "Chicken, Turkey & Lean Meat Dinners",
    "fish_seafood_dinners": "Fish & Seafood Dinners",
    "vegetable_meatless_dinners": "Vegetable & Meatless Dinners",
    "snacks_sides": "Snacks & Sides",
    "desserts": "Desserts",
}

# Planner meal-slot key(s) a chapter's recipes can occupy.
RECIPE_CHAPTER_MEAL_TYPES: dict[str, tuple[str, ...]] = {
    "breakfasts": ("breakfast",),
    "soups_salads": ("lunch",),
    "lunches": ("lunch",),
    "poultry_meat_dinners": ("dinner",),
    "fish_seafood_dinners": ("dinner",),
    "vegetable_meatless_dinners": ("dinner",),
    "snacks_sides": ("snack",),
    "desserts": ("dessert",),
}

# Primary per-recipe nutrient tier (see the YAML `meal_categories`).
# `soups_salads` is the only `light_main` chapter: a soup or salad eaten as a
# lunch is a real meal but a smaller one, and judging it against full-main
# bounds would false-flag every recipe in the chapter.
RECIPE_CHAPTER_NUTRIENT_TIER: dict[str, str] = {
    "breakfasts": "main",
    "soups_salads": "light_main",
    "lunches": "main",
    "poultry_meat_dinners": "main",
    "fish_seafood_dinners": "main",
    "vegetable_meatless_dinners": "main",
    "snacks_sides": "snack",
    "desserts": "dessert",
}

# Canonical chapter to assume when a planner meal-slot is given without an
# explicit chapter. NOT the inverse of RECIPE_CHAPTER_MEAL_TYPES (that map is
# many-to-one for lunch and dinner) — this nominates one chapter per slot.
MEAL_TYPE_DEFAULT_CHAPTER: dict[str, str] = {
    "breakfast": "breakfasts",
    "lunch": "lunches",
    "snack": "snacks_sides",
    "dinner": "poultry_meat_dinners",
    "dessert": "desserts",
}

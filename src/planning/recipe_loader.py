"""Load already-generated Recipe JSON files from a cookbook folder."""
import json
from pathlib import Path
from typing import Any

from src.constants import MEAL_TYPE_FOLDERS
from src.models.recipe import Recipe


def load_cookbook(cookbook_dir: Path) -> dict[str, list[Recipe]]:
    """Return `{meal_type_key: [Recipe, ...]}` for all recipes in the cookbook.

    Meal-type folders that don't exist on disk produce an empty list (not an
    error) so a cookbook without e.g. `Collation/` can still plan the others.
    """
    recipes: dict[str, list[Recipe]] = {}
    for meal_type_key, folder_name in MEAL_TYPE_FOLDERS.items():
        json_dir = cookbook_dir / folder_name / "JSON"
        if not json_dir.exists():
            recipes[meal_type_key] = []
            continue
        bucket: list[Recipe] = []
        for p in sorted(json_dir.glob("*.json")):
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
                _normalise_legacy_fields(raw)
                bucket.append(Recipe.model_validate(raw))
            except Exception as e:  # noqa: BLE001
                raise ValueError(f"Invalid recipe: {p.name} ({e})") from e
        recipes[meal_type_key] = bucket
    return recipes


def flat_index(recipes_by_meal: dict[str, list[Recipe]]) -> dict[str, Recipe]:
    """Flatten `{meal_type: [Recipe, ...]}` into `{recipe_id: Recipe}`."""
    return {r.id: r for bucket in recipes_by_meal.values() for r in bucket}


# ── Legacy data adapter ─────────────────────────────────────────
# Recipes from older pipeline variants stored `nutrition_source` values like
# "ciqual:51550" and French meal-type keys ("petit-dejeuner", …) that the
# current models no longer accept. Normalise on read so an old book that's been
# moved into the new English folder layout still loads.

_VALID_SOURCES = {
    "usda", "llm_estimate", "ciqual", "open_food_facts", "fallback", "missing",
}
_LEGACY_MEAL_TYPES = {
    "petit-dejeuner": "breakfast",
    "dejeuner": "lunch",
    "collation": "snack",
    "diner": "dinner",
}


def _normalise_legacy_fields(raw: dict[str, Any]) -> None:
    mt = raw.get("meal_type")
    if isinstance(mt, str) and mt in _LEGACY_MEAL_TYPES:
        raw["meal_type"] = _LEGACY_MEAL_TYPES[mt]
    for ing in raw.get("ingredients", []) or []:
        src = ing.get("nutrition_source")
        if not isinstance(src, str) or src in _VALID_SOURCES:
            continue
        low = src.lower()
        if low.startswith("ciqual"):
            ing["nutrition_source"] = "ciqual"
        elif low.startswith("usda"):
            ing["nutrition_source"] = "usda"
        elif low.startswith("off") or low.startswith("open_food"):
            ing["nutrition_source"] = "open_food_facts"
        elif low.startswith("llm"):
            ing["nutrition_source"] = "llm_estimate"
        else:
            ing["nutrition_source"] = "fallback"

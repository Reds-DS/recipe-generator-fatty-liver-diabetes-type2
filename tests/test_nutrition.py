"""Tests for Stage 4 nutrition — mocks the USDA loader + the LLM, no DB / API calls."""
from unittest.mock import patch

import pytest

from src.models.recipe import Ingredient, RecipeDraft
from src.nutrition.usda_loader import UsdaFood

_S4 = "src.recipe_pipeline.stage_04_nutrition"


def _ingredient(name: str, grams: float) -> Ingredient:
    return Ingredient(
        name=name, canonical_name=name, quantity_g=grams,
        quantity_display=f"{grams} g", nutrition_source="missing",
    )


def _draft(ingredients: list[Ingredient]) -> RecipeDraft:
    return RecipeDraft(
        title="Test", intro="Test", servings=2, prep_time_min=10, cook_time_min=20,
        ingredients=ingredients, instructions=["Prep.", "Cook.", "Serve."],
    )


def _food(fdc_id: int, **over) -> UsdaFood:
    base = dict(
        fdc_id=fdc_id, data_type="sr_legacy_food", description="Test food", category=None,
        calories_kcal=165.0, protein_g=31.0, carbs_g=0.0, fiber_g=0.0, total_sugar_g=0.0,
        total_fat_g=3.6, saturated_fat_g=1.0, mufa_g=1.2, pufa_g=0.8, trans_fat_g=None,
        cholesterol_mg=85.0, sodium_mg=74.0, potassium_mg=256.0, calcium_mg=15.0, iron_mg=1.0,
        vitamin_d_mcg=None, water_g=65.0,
    )
    base.update(over)
    return UsdaFood(**base)


def _llm_pick_json(*picks: dict, added_sugar: float = 0.0) -> str:
    import json
    return json.dumps({"per_ingredient": list(picks), "added_sugar_g_recipe_total": added_sugar, "reasoning": ""})


@patch(f"{_S4}.usda_loader.register_alias")
@patch(f"{_S4}.usda_loader.get_alias", return_value=None)
@patch(f"{_S4}.usda_loader.fetch_by_id")
@patch(f"{_S4}.usda_loader.lookup_candidates")
@patch(f"{_S4}.llm.create_message")
def test_python_computes_per_serving(mock_llm, mock_cands, mock_fetch, _mock_alias, _mock_reg):
    food = _food(999, description="Chicken, broilers or fryers, breast, meat only, cooked, roasted")
    mock_cands.return_value = [food]
    mock_fetch.return_value = food
    mock_llm.return_value = _llm_pick_json(
        {"ingredient_name": "chicken breast", "fdc_id": 999,
         "fdc_description": food.description, "estimate_per_100g": None, "note": ""},
    )
    from src.recipe_pipeline import stage_04_nutrition
    draft = _draft([_ingredient("chicken breast", 200)])
    nutrition, warnings = stage_04_nutrition.run(draft)

    # 200 g × (per-100 g value) / 2 servings
    assert nutrition.calories_kcal == pytest.approx(165.0)
    assert nutrition.protein_g == pytest.approx(31.0)
    assert nutrition.fat_g == pytest.approx(3.6)
    assert nutrition.saturated_fat_g == pytest.approx(1.0)
    assert nutrition.cholesterol_mg == pytest.approx(85.0)
    assert nutrition.potassium_mg == pytest.approx(256.0)
    # the food carries no value for these → the panel field stays None
    assert nutrition.trans_fat_g is None
    assert nutrition.vitamin_d_mcg is None
    assert nutrition.added_sugar_g == pytest.approx(0.0)
    assert nutrition.source == "llm_usda"
    assert nutrition.confidence == "high"
    assert nutrition.missing_ingredients == []
    assert draft.ingredients[0].fdc_id == 999
    assert draft.ingredients[0].nutrition_source == "usda"


@patch(f"{_S4}.usda_loader.register_alias")
@patch(f"{_S4}.usda_loader.get_alias", return_value=None)
@patch(f"{_S4}.usda_loader.fetch_by_id", return_value=None)
@patch(f"{_S4}.usda_loader.lookup_candidates", return_value=[])
@patch(f"{_S4}.llm.create_message")
def test_estimated_ingredient_flagged(mock_llm, _mock_cands, _mock_fetch, _mock_alias, _mock_reg):
    mock_llm.return_value = _llm_pick_json(
        {"ingredient_name": "exotic thing", "fdc_id": None, "fdc_description": None,
         "estimate_per_100g": {"calories_kcal": 100.0, "protein_g": 5.0, "carbs_g": 10.0,
                               "fat_g": 2.0, "fiber_g": 1.0, "total_sugar_g": 3.0, "sodium_mg": 50.0,
                               "saturated_fat_g": 0.5},
         "note": "no USDA match"},
        added_sugar=4.0,
    )
    from src.recipe_pipeline import stage_04_nutrition
    draft = _draft([_ingredient("exotic thing", 200)])
    nutrition, warnings = stage_04_nutrition.run(draft)

    assert "exotic thing" in nutrition.missing_ingredients
    assert nutrition.confidence == "low"            # the only ingredient was estimated
    assert nutrition.calories_kcal == pytest.approx(100.0)   # 200 × 100/100 / 2
    assert nutrition.saturated_fat_g == pytest.approx(0.5)
    assert nutrition.added_sugar_g == pytest.approx(2.0)     # 4 g / 2 servings
    assert nutrition.cholesterol_mg is None                  # estimates don't carry it
    assert any("exotic thing" in w for w in warnings)
    assert draft.ingredients[0].nutrition_source == "llm_estimate"


@patch(f"{_S4}.usda_loader.register_alias")
@patch(f"{_S4}.usda_loader.get_alias", return_value=None)
@patch(f"{_S4}.usda_loader.fetch_by_id")
@patch(f"{_S4}.usda_loader.lookup_candidates")
@patch(f"{_S4}.llm.create_message")
def test_two_ingredients_summed(mock_llm, mock_cands, mock_fetch, _mock_alias, _mock_reg):
    food_a = _food(1, calories_kcal=200.0, protein_g=10.0, total_fat_g=5.0)
    food_b = _food(2, calories_kcal=400.0, protein_g=2.0, total_fat_g=40.0)
    mock_cands.return_value = [food_a, food_b]
    mock_fetch.side_effect = lambda fid: {1: food_a, 2: food_b}.get(int(fid))
    mock_llm.return_value = _llm_pick_json(
        {"ingredient_name": "a", "fdc_id": 1, "fdc_description": "A", "estimate_per_100g": None, "note": ""},
        {"ingredient_name": "b", "fdc_id": 2, "fdc_description": "B", "estimate_per_100g": None, "note": ""},
    )
    from src.recipe_pipeline import stage_04_nutrition
    draft = _draft([_ingredient("a", 100), _ingredient("b", 100)])
    nutrition, _ = stage_04_nutrition.run(draft)

    assert nutrition.calories_kcal == pytest.approx(300.0)   # (100×2 + 100×4) / 2
    assert nutrition.protein_g == pytest.approx(6.0)         # (10 + 2) / 2
    assert nutrition.fat_g == pytest.approx(22.5)            # (5 + 40) / 2
    assert nutrition.confidence == "high"

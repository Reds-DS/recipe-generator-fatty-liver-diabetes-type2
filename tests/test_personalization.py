"""Unit tests for BMR/TDEE/targets derivation."""
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from src.models.meal_plan import CookbookManifest, UserProfile
from src.models.nutrition import NutritionInfo
from src.models.recipe import Ingredient, Recipe
from src.planning.personalization import (
    ACTIVITY_FACTORS,
    BMR_DROP_KCAL_PER_KG,
    CAPACITY_BLOCK_SHORTFALL,
    DEFAULT_MEAL_SHARE,
    KCAL_FLOOR,
    KCAL_PER_KG_FAT,
    MIN_MEAL_SHARE,
    STEPS_BY_ACTIVITY,
    WATER_L_CAP,
    WATER_ML_PER_KG,
    check_cookbook_capacity,
    compute_bmr,
    compute_targets,
    compute_tdee,
    derive_insights,
    derive_weekly_loss,
)


def _profile(**overrides) -> UserProfile:
    base = dict(
        name="test",
        sex="M",
        age=35,
        height_cm=175,
        weight_kg=80,
        activity_level="moderate",
        weekly_loss_kg=0.5,
    )
    base.update(overrides)
    # Default target_weight_kg = current − 7 kg (consistent lose direction)
    # so callers that override weight_kg without target_weight_kg stay valid.
    base.setdefault("target_weight_kg", base["weight_kg"] - 7)
    return UserProfile(**base)


def _manifest(**overrides) -> CookbookManifest:
    base = dict(
        name="test-book",
        objective="test",
    )
    base.update(overrides)
    return CookbookManifest(**base)


# ---------------------------------------------------------------------------
# BMR — Mifflin-St Jeor
# ---------------------------------------------------------------------------

def test_bmr_male_reference():
    # 80 kg, 175 cm, 35 yr, M → 10·80 + 6.25·175 − 5·35 + 5 = 800 + 1093.75 − 175 + 5 = 1723.75
    assert compute_bmr(_profile()) == pytest.approx(1723.75)


def test_bmr_female_reference():
    # 60 kg, 165 cm, 35 yr, F → 10·60 + 6.25·165 − 5·35 − 161 = 600 + 1031.25 − 175 − 161 = 1295.25
    p = _profile(sex="F", age=35, height_cm=165, weight_kg=60)
    assert compute_bmr(p) == pytest.approx(1295.25)


def test_bmr_male_minus_female_constant_offset():
    """For identical biometrics, M − F BMR ≡ 166 kcal (the +5/−161 difference)."""
    common = dict(age=40, height_cm=170, weight_kg=70)
    male = compute_bmr(_profile(sex="M", **common))
    female = compute_bmr(_profile(sex="F", **common))
    assert male - female == pytest.approx(166.0)


# ---------------------------------------------------------------------------
# TDEE — activity factors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level,factor", list(ACTIVITY_FACTORS.items()))
def test_tdee_applies_correct_activity_factor(level, factor):
    p = _profile(activity_level=level)
    assert compute_tdee(p) == pytest.approx(compute_bmr(p) * factor)


# ---------------------------------------------------------------------------
# compute_targets — kcal, macros, per-meal split
# ---------------------------------------------------------------------------

def test_targets_subtract_weekly_deficit_then_round_to_50():
    p = _profile()  # TDEE = 1723.75 · 1.55 = 2671.81 ; deficit 0.5·7700/7 = 550 → 2121.81
    targets = compute_targets(p, _manifest())
    # rounded to nearest 50
    assert targets.daily_kcal % 50 == 0
    assert targets.daily_kcal == 2100  # round(2121.81 / 50) * 50 = 2100


def test_targets_enforce_floor_for_aggressive_deficit():
    # Tiny old woman + max deficit → would fall below 1200 floor.
    p = _profile(sex="F", age=70, height_cm=150, weight_kg=55, target_weight_kg=50,
                 activity_level="sedentary", weekly_loss_kg=1.0)
    targets = compute_targets(p, _manifest())
    assert targets.daily_kcal >= KCAL_FLOOR["F"]
    # Plain-language floor warning (was "plancher" jargon previously).
    assert any("safe minimum" in w for w in targets.warnings)


def test_targets_protein_uses_current_weight():
    p = _profile(weight_kg=80)
    targets = compute_targets(p, _manifest())
    # PROTEIN_G_PER_KG = 1.5 — upper half of the DGA 2025-2030 band of 1.2-1.6 g/kg/day,
    # and where the book's own printed plan lands (see
    # data/fatty_liver_diabetes_guidelines.yaml daily_targets.protein_g_per_kg_bodyweight).
    assert targets.protein_g == pytest.approx(80 * 1.5, rel=0.01)


def test_targets_macros_sum_close_to_daily_kcal():
    """Protein·4 + carbs·4 + fat·9 should reconstruct daily_kcal within 5%."""
    p = _profile()
    t = compute_targets(p, _manifest())
    reconstituted = t.protein_g * 4 + t.carbs_g * 4 + t.fat_g * 9
    assert abs(reconstituted - t.daily_kcal) / t.daily_kcal < 0.05


def test_targets_per_meal_share_sums_to_daily_kcal():
    p = _profile()
    t = compute_targets(p, _manifest())
    total_per_meal_kcal = sum(pm.kcal for pm in t.per_meal.values())
    assert total_per_meal_kcal == pytest.approx(t.daily_kcal, rel=0.005)


def test_targets_default_meal_share_27_25_10_28():
    """The default split is RE-DERIVED from this book's tier energy bands, not
    inherited. Lunch is 0.25 (not the parent's 0.35) because the lunch slot also
    draws from Soups & Salads, whose `light_main` tier caps at 440 kcal — asking
    that slot for 35% of the day would be asking for recipes the book doesn't have."""
    p = _profile()
    t = compute_targets(p, _manifest())
    assert t.per_meal["breakfast"].kcal == pytest.approx(t.daily_kcal * 0.27, rel=0.01)
    assert t.per_meal["lunch"].kcal == pytest.approx(t.daily_kcal * 0.25, rel=0.01)
    assert t.per_meal["snack"].kcal == pytest.approx(t.daily_kcal * 0.10, rel=0.01)
    assert t.per_meal["dinner"].kcal == pytest.approx(t.daily_kcal * 0.28, rel=0.01)
    assert t.per_meal["dessert"].kcal == pytest.approx(t.daily_kcal * 0.10, rel=0.01)


def test_targets_custom_meal_share_from_manifest():
    m = _manifest(
        meal_structure=["breakfast", "lunch", "snack", "dinner"],
        meal_share={"breakfast": 0.2, "lunch": 0.4, "snack": 0.1, "dinner": 0.3},
    )
    t = compute_targets(_profile(), m)
    assert t.per_meal["lunch"].kcal == pytest.approx(t.daily_kcal * 0.4, rel=0.01)


def test_targets_meal_share_renormalized_for_partial_structure():
    """3-meal structure (no snack) should still sum to 1.0 after fallback split."""
    m = _manifest(meal_structure=["breakfast", "lunch", "dinner"])
    t = compute_targets(_profile(), m)
    assert sum(pm.kcal for pm in t.per_meal.values()) == pytest.approx(t.daily_kcal, rel=0.005)


# ---------------------------------------------------------------------------
# Safety warnings
# ---------------------------------------------------------------------------

def test_warning_on_aggressive_weekly_loss():
    p = _profile(weekly_loss_kg=0.9)
    t = compute_targets(p, _manifest())
    # Plain-language wording (was "hebdomadaire" previously).
    assert any("fast loss" in w.lower() and "kg per week" in w.lower() for w in t.warnings)


def test_warning_on_underweight_target_bmi():
    # 165 cm, target 45 kg → BMI ≈ 16.5
    p = _profile(sex="F", height_cm=165, weight_kg=55, target_weight_kg=45)
    t = compute_targets(p, _manifest())
    # Plain-language wording (was "sous-poids"/"IMC" previously).
    assert any("underweight" in w.lower() for w in t.warnings)


def test_no_warnings_for_moderate_realistic_profile():
    p = _profile(weekly_loss_kg=0.5)
    t = compute_targets(p, _manifest())
    assert t.warnings == []


# ---------------------------------------------------------------------------
# Pydantic validation
# ---------------------------------------------------------------------------

def test_profile_rejects_invalid_weekly_loss_above_one_kg():
    with pytest.raises(ValidationError):
        _profile(weekly_loss_kg=1.5)


def test_profile_rejects_invalid_per_meal_cap_below_one():
    with pytest.raises(ValidationError):
        _profile(per_meal_kcal_cap_pct=0.9)


def test_profile_requires_sex_and_activity():
    """Pydantic must reject construction missing required fields."""
    with pytest.raises(ValidationError):
        UserProfile(name="x", age=30, height_cm=170, weight_kg=70,
                    target_weight_kg=65)  # no sex, no activity_level


def test_manifest_rejects_meal_share_not_summing_to_one():
    with pytest.raises(ValidationError):
        CookbookManifest(
            name="x", objective="x",
            meal_share={"breakfast": 0.3, "lunch": 0.3, "snack": 0.1, "dinner": 0.1},
        )


def test_kcal_per_kg_fat_constant_is_seven_thousand_seven_hundred():
    """Sanity guard: changing this constant changes every user's deficit math."""
    assert KCAL_PER_KG_FAT == 7700.0


# ---------------------------------------------------------------------------
# Fix 1 — target_date derivation + sign validation
# ---------------------------------------------------------------------------

def test_target_date_derives_weekly_loss():
    today = date(2026, 1, 1)
    p = _profile(weekly_loss_kg=None,
                 target_date=today + timedelta(weeks=10),
                 weight_kg=80, target_weight_kg=73)
    rate, warning = derive_weekly_loss(p, today=today)
    assert rate == pytest.approx(0.7, rel=0.01)  # 7 kg / 10 wk
    assert warning is None


def test_target_date_clamps_unsafe_rate_and_warns():
    today = date(2026, 1, 1)
    # 7 kg in 1 week → 7 kg/week, must be clamped to 1.0
    p = _profile(weekly_loss_kg=None,
                 target_date=today + timedelta(weeks=1),
                 weight_kg=80, target_weight_kg=73)
    rate, warning = derive_weekly_loss(p, today=today)
    assert rate == 1.0
    assert warning is not None
    assert "safe limit" in warning.lower() or "capped" in warning.lower()


def test_target_date_in_the_past_yields_zero_rate_with_warning():
    today = date(2026, 1, 1)
    p = _profile(weekly_loss_kg=None,
                 target_date=today - timedelta(days=10),
                 weight_kg=80, target_weight_kg=73)
    rate, warning = derive_weekly_loss(p, today=today)
    assert rate == 0.0
    assert warning is not None


def test_target_date_takes_priority_over_explicit_weekly_loss():
    """If both fields are set, target_date wins (the user's natural input)."""
    today = date(2026, 1, 1)
    p = _profile(weekly_loss_kg=0.2,
                 target_date=today + timedelta(weeks=10),
                 weight_kg=80, target_weight_kg=73)
    rate, _ = derive_weekly_loss(p, today=today)
    assert rate == pytest.approx(0.7, rel=0.01)  # NOT 0.2


def test_compute_targets_uses_derived_rate_for_kcal_target():
    today = date(2026, 1, 1)
    p = _profile(weekly_loss_kg=None,
                 target_date=today + timedelta(weeks=10),
                 weight_kg=80, target_weight_kg=73)
    t = compute_targets(p, _manifest(), today=today)
    # TDEE = 1723.75·1.55 ≈ 2671.81; deficit = 0.7·7700/7 = 770; raw = 1901.81 → round to 1900
    assert t.daily_kcal == 1900


def test_profile_validator_rejects_sign_mismatch():
    """target=80 from current=70 with weekly_loss=+0.5 (lose) is contradictory."""
    with pytest.raises(ValidationError, match="Inconsistent direction"):
        UserProfile(
            name="x", sex="M", age=30, height_cm=175,
            weight_kg=70, target_weight_kg=80,  # gain direction
            activity_level="moderate",
            weekly_loss_kg=0.5,                 # but rate says lose
        )


def test_profile_validator_accepts_consistent_gain():
    """Negative weekly_loss with target > current is valid."""
    p = UserProfile(
        name="x", sex="M", age=30, height_cm=175,
        weight_kg=70, target_weight_kg=80,
        activity_level="moderate",
        weekly_loss_kg=-0.3,
    )
    assert p.weekly_loss_kg == -0.3


def test_profile_falls_back_to_default_rate_when_neither_set():
    """No weekly_loss_kg and no target_date → 0.5 in the implied direction."""
    p = UserProfile(
        name="x", sex="M", age=30, height_cm=175,
        weight_kg=80, target_weight_kg=73,  # implies lose
        activity_level="moderate",
    )
    assert p.weekly_loss_kg == 0.5


def test_profile_default_rate_flips_for_gain_direction():
    p = UserProfile(
        name="x", sex="M", age=30, height_cm=175,
        weight_kg=70, target_weight_kg=80,  # implies gain
        activity_level="moderate",
    )
    assert p.weekly_loss_kg == -0.5


# ---------------------------------------------------------------------------
# Fix 2 — cookbook capacity check
# ---------------------------------------------------------------------------

def _make_recipe(meal_type: str, kcal: float) -> Recipe:
    return Recipe(
        title=f"{meal_type}-{kcal}",
        intro="x",
        diet_tags=[],
        meal_type=meal_type,  # type: ignore[arg-type]
        prep_time_min=5,
        cook_time_min=10,
        ingredients=[Ingredient(
            name="x", canonical_name="x", quantity_g=100,
            quantity_display="100 g", nutrition_source="ciqual",
        )],
        instructions=["a", "b", "c"],
        nutrition_per_serving=NutritionInfo(
            calories_kcal=kcal, protein_g=20, carbs_g=30, fat_g=10,
            fiber_g=4, sodium_mg=200, sugar_g=3,
            source="ciqual", confidence="high",
        ),
    )


def test_capacity_report_meets_target_when_recipes_are_generous():
    p = _profile()
    t = compute_targets(p, _manifest())  # ~2100 kcal/day
    # Buckets with medians that comfortably reach the target.
    recipes = {
        "breakfast": [_make_recipe("breakfast", 550)],
        "lunch":       [_make_recipe("lunch", 750)],
        "snack":      [_make_recipe("snack", 250)],
        "dinner":          [_make_recipe("dinner", 700)],
    }
    report = check_cookbook_capacity(recipes, t, _manifest())
    assert report.shortfall_pct == 0.0
    assert not report.blocking


def test_capacity_report_blocks_when_recipes_are_too_light():
    p = _profile(weight_kg=90, height_cm=185, age=30, activity_level="very_active")
    t = compute_targets(p, _manifest())
    # All recipes tiny — daily total ~600 kcal, well below user's >3000 kcal target.
    recipes = {
        "breakfast": [_make_recipe("breakfast", 150)],
        "lunch":       [_make_recipe("lunch", 200)],
        "snack":      [_make_recipe("snack", 80)],
        "dinner":          [_make_recipe("dinner", 200)],
    }
    report = check_cookbook_capacity(recipes, t, _manifest())
    assert report.shortfall_pct > CAPACITY_BLOCK_SHORTFALL
    assert report.blocking
    assert "force" in report.message.lower()


def test_capacity_uses_median_not_max():
    """One outlier high-kcal recipe should not lift the feasibility estimate."""
    p = _profile()
    t = compute_targets(p, _manifest())
    bucket = [_make_recipe("lunch", 200)] * 5 + [_make_recipe("lunch", 1500)]
    recipes = {
        "breakfast": [_make_recipe("breakfast", 300)],
        "lunch": bucket,
        "snack": [_make_recipe("snack", 150)],
        "dinner": [_make_recipe("dinner", 300)],
    }
    report = check_cookbook_capacity(recipes, t, _manifest())
    assert report.medians_per_meal["lunch"] == 200  # median, not 1500


# ---------------------------------------------------------------------------
# Fix 5 — dessert share + low-share guard
# ---------------------------------------------------------------------------

def test_dessert_default_share_is_non_zero():
    assert DEFAULT_MEAL_SHARE["dessert"] > 0
    assert DEFAULT_MEAL_SHARE["dessert"] >= MIN_MEAL_SHARE


def test_dessert_in_meal_structure_gets_meaningful_per_meal_kcal():
    """When dessert is in meal_structure, its PerMealTarget.kcal must be > 0."""
    m = _manifest(meal_structure=["breakfast", "lunch", "dinner", "dessert"])
    t = compute_targets(_profile(), m)
    assert t.per_meal["dessert"].kcal > 0


def test_low_share_guard_rejects_meal_with_share_below_threshold():
    """Share below MIN_MEAL_SHARE for any meal type should fail loudly."""
    m = CookbookManifest(
        name="x", objective="x",
        meal_structure=["breakfast", "lunch", "snack", "dinner"],
        meal_share={"breakfast": 0.49, "lunch": 0.49,
                    "snack": 0.01, "dinner": 0.01},  # snack+dinner < MIN
    )
    with pytest.raises(ValueError, match="too small"):
        compute_targets(_profile(), m)


# ---------------------------------------------------------------------------
# Fix 9 — safety_warnings still fire on aggressive derived rate
# ---------------------------------------------------------------------------

def test_pace_warning_propagates_to_targets_warnings():
    today = date(2026, 1, 1)
    # Forces clamping → pace_warning should appear in targets.warnings
    p = _profile(weekly_loss_kg=None,
                 target_date=today + timedelta(weeks=2),
                 weight_kg=85, target_weight_kg=70)
    t = compute_targets(p, _manifest(), today=today)
    assert any("capped" in w.lower() or "safe limit" in w.lower() for w in t.warnings)


# ---------------------------------------------------------------------------
# Insights — personalized success-guide derivations
# ---------------------------------------------------------------------------

def _insights(**overrides):
    """Build (profile, manifest, insights) with `today` fixed to 2026-01-01."""
    today = date(2026, 1, 1)
    profile_overrides = {k: v for k, v in overrides.items() if k != "today"}
    p = _profile(**profile_overrides)
    m = _manifest()
    t = compute_targets(p, m, today=today)
    return p, m, derive_insights(p, t, m, today=today)


def test_insights_direction_lose_for_canonical_profile():
    _, _, i = _insights()  # weight 80 → target 73
    assert i.direction == "lose"
    assert i.direction_label == "deficit"
    assert i.direction_verb == "lose"
    assert i.delta_kg == pytest.approx(7.0, abs=0.05)


def test_insights_direction_gain():
    _, _, i = _insights(weight_kg=70, target_weight_kg=78, weekly_loss_kg=-0.3)
    assert i.direction == "gain"
    assert i.direction_label == "surplus"
    assert i.daily_deficit_kcal < 0  # surplus stored as negative deficit


def test_insights_direction_maintain():
    _, _, i = _insights(weight_kg=72, target_weight_kg=72, weekly_loss_kg=0.0)
    assert i.direction == "maintain"
    assert i.projected_target_date is None
    assert i.weeks_to_target == 0.0


def test_insights_water_intake_uses_baseline_per_kg():
    _, _, i = _insights(weight_kg=80)
    assert i.water_l_per_day == pytest.approx(WATER_ML_PER_KG * 80 / 1000.0, abs=0.01)


def test_insights_water_intake_capped_for_very_heavy_user():
    _, _, i = _insights(weight_kg=200, target_weight_kg=180)  # cap at 4 L
    assert i.water_l_per_day <= WATER_L_CAP


def test_insights_steps_target_from_activity_table():
    for level, expected in STEPS_BY_ACTIVITY.items():
        _, _, i = _insights(activity_level=level)
        assert i.daily_steps_target == expected


def test_insights_projected_date_matches_weeks_to_target():
    today = date(2026, 1, 1)
    p = _profile(weekly_loss_kg=0.5, weight_kg=80, target_weight_kg=73)
    t = compute_targets(p, _manifest(), today=today)
    i = derive_insights(p, t, _manifest(), today=today)
    # 7 kg / 0.5 = 14 weeks
    assert i.weeks_to_target == pytest.approx(14.0, abs=0.05)
    assert i.projected_target_date == today + timedelta(weeks=14)


def test_insights_projected_date_uses_target_date_when_set():
    today = date(2026, 1, 1)
    target_date = today + timedelta(weeks=10)
    p = _profile(weekly_loss_kg=None, target_date=target_date,
                 weight_kg=80, target_weight_kg=73)
    t = compute_targets(p, _manifest(), today=today)
    i = derive_insights(p, t, _manifest(), today=today)
    # Derived rate ≈ 0.7 kg/wk → weeks ≈ 10 → projected date ≈ target_date.
    assert abs((i.projected_target_date - target_date).days) <= 1


def test_insights_checkpoint_one_month_signed_correctly():
    _, _, i_lose = _insights(weight_kg=80, target_weight_kg=73, weekly_loss_kg=0.5)
    # 1 month ≈ 4 weeks at 0.5 kg/wk → -2 kg → 78
    assert i_lose.checkpoint_1_month_kg == pytest.approx(78.0, abs=0.1)

    _, _, i_gain = _insights(weight_kg=70, target_weight_kg=78, weekly_loss_kg=-0.3)
    # 4 weeks at -0.3 kg/wk → +1.2 → 71.2
    assert i_gain.checkpoint_1_month_kg == pytest.approx(71.2, abs=0.1)


def test_insights_bmr_drop_uses_mifflin_coefficient():
    _, _, i = _insights(weight_kg=80, target_weight_kg=73)
    # |delta| = 7 kg → 70 kcal/day projected BMR drop
    assert i.bmr_drop_estimate == int(round(BMR_DROP_KCAL_PER_KG * 7))


def test_insights_initial_water_loss_caveat_only_for_heavy_lose():
    _, _, i_heavy = _insights(weight_kg=85, target_weight_kg=75)
    assert i_heavy.initial_water_loss_caveat is True

    _, _, i_light = _insights(weight_kg=60, target_weight_kg=55,
                              height_cm=160, sex="F")
    assert i_light.initial_water_loss_caveat is False  # under threshold

    _, _, i_gain = _insights(weight_kg=85, target_weight_kg=92, weekly_loss_kg=-0.3)
    assert i_gain.initial_water_loss_caveat is False  # not lose direction


def test_insights_protein_per_main_meal_from_lunch():
    """Most cookbooks have lunch — its protein target should drive the hint."""
    _, _, i = _insights()
    # Default targets for the canonical 80 kg profile: protein_g = 80·1.5 = 120,
    # lunch share 0.25 → 30 g, right on the ~25-30 g per-meal satiety + MPS
    # threshold and matching the `main` tier's 26 g floor / 31 g target.
    assert 26 <= i.protein_per_main_meal <= 55


def test_insights_diet_note_falls_back_for_unknown_tags():
    today = date(2026, 1, 1)
    p = _profile()
    m = CookbookManifest(name="x", objective="x", diet_tags=["keto"])
    t = compute_targets(p, m, today=today)
    i = derive_insights(p, t, m, today=today)
    # Generic fallback rather than an empty string
    assert i.cookbook_diet_note != ""
    assert (
        "quantities" in i.cookbook_diet_note.lower()
        or "calibrated" in i.cookbook_diet_note.lower()
    )

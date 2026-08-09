"""Planner tests for the personalized path: backward compat + macro adherence
+ hard kcal-cap filtering + relaxation fallback."""

from src.models.meal_plan import CookbookManifest, UserProfile
from src.models.nutrition import NutritionInfo
from src.models.recipe import Ingredient, Recipe
from src.planning import meal_planner, personalization

# The book's day is FIVE slots (dessert included) — see `meal_structure` on
# CookbookManifest and the per-serving envelope in the spec, which was derived
# against a five-slot day.
MEAL_TYPES = ("breakfast", "lunch", "snack", "dinner", "dessert")


def _ingredient() -> Ingredient:
    return Ingredient(
        name="chicken breast",
        canonical_name="chicken breast",
        quantity_g=200,
        quantity_display="200 g",
        nutrition_source="ciqual",
    )


def _recipe(
    title: str,
    meal_type: str,
    *,
    kcal: float = 400,
    protein: float = 25,
    fat: float = 12,
    carbs: float = 35,
    fiber: float = 5,
) -> Recipe:
    return Recipe(
        title=title,
        intro="x",
        diet_tags=[],
        meal_type=meal_type,  # type: ignore[arg-type]
        prep_time_min=10,
        cook_time_min=15,
        ingredients=[_ingredient()],
        instructions=["a", "b", "c"],
        nutrition_per_serving=NutritionInfo(
            calories_kcal=kcal,
            protein_g=protein,
            carbs_g=carbs,
            fat_g=fat,
            fiber_g=fiber,
            sodium_mg=200,
            sugar_g=3,
            source="ciqual",
            confidence="high",
        ),
    )


def _bucket_for(meal_type: str, n: int = 12, kcal_base: float = 400) -> list[Recipe]:
    """A diverse bucket of recipes — kcal varies so the planner has range."""
    return [
        _recipe(
            f"{meal_type}-{i}",
            meal_type,
            kcal=kcal_base + i * 25,
            protein=15 + i,
            fat=8 + i * 0.5,
            fiber=3 + (i % 4),
        )
        for i in range(n)
    ]


def _recipes_by_meal(buckets: dict[str, int] | None = None) -> dict[str, list[Recipe]]:
    bases = {"breakfast": 250, "lunch": 450, "snack": 150, "dinner": 400, "dessert": 150}
    sizes = buckets or {mt: 12 for mt in MEAL_TYPES}
    return {mt: _bucket_for(mt, n=sizes[mt], kcal_base=bases[mt]) for mt in MEAL_TYPES}


def _manifest() -> CookbookManifest:
    return CookbookManifest(name="test-book", objective="test")


def _profile(**overrides) -> UserProfile:
    base = dict(
        name="reda",
        sex="M",
        age=35,
        height_cm=175,
        weight_kg=80,
        target_weight_kg=73,
        activity_level="moderate",
        weekly_loss_kg=0.5,
    )
    base.update(overrides)
    return UserProfile(**base)


# ---------------------------------------------------------------------------
# Backward compatibility — without targets, behavior is unchanged
# ---------------------------------------------------------------------------

def test_backward_compat_without_targets_still_builds_a_plan():
    plan = meal_planner.build_plan(
        recipes_by_meal=_recipes_by_meal(),
        manifest=_manifest(),
        days=7,
        seed=42,
    )
    assert len(plan.days) == 7
    for day in plan.days:
        assert len(day.slots) == len(MEAL_TYPES)
    assert plan.user_profile is None
    assert plan.targets is None


def test_backward_compat_same_seed_same_recipes():
    """Without targets, calling twice with same seed yields identical recipe ids."""
    recipes = _recipes_by_meal()
    plan_a = meal_planner.build_plan(recipes, _manifest(), days=14, seed=42)
    plan_b = meal_planner.build_plan(recipes, _manifest(), days=14, seed=42)
    ids_a = [(s.day, s.meal_type, s.recipe_id) for d in plan_a.days for s in d.slots]
    ids_b = [(s.day, s.meal_type, s.recipe_id) for d in plan_b.days for s in d.slots]
    assert ids_a == ids_b


# ---------------------------------------------------------------------------
# Personalized path — adherence to targets
# ---------------------------------------------------------------------------

def test_personalized_plan_lands_near_daily_kcal_target():
    profile = _profile()
    targets = personalization.compute_targets(profile, _manifest())
    plan = meal_planner.build_plan(
        recipes_by_meal=_recipes_by_meal(),
        manifest=_manifest(),
        days=14,
        seed=42,
        targets=targets,
        profile=profile,
    )
    avg = plan.avg_daily_nutrition.calories_kcal
    # Planner can only choose from the cookbook — allow 25% slack.
    assert abs(avg - targets.daily_kcal) / targets.daily_kcal < 0.25


def test_personalized_plan_preserves_no_repeat_window():
    """Variety guarantee: no recipe used twice inside max_repeat_window_days."""
    profile = _profile()
    manifest = _manifest()
    targets = personalization.compute_targets(profile, manifest)
    plan = meal_planner.build_plan(
        recipes_by_meal=_recipes_by_meal({mt: 12 for mt in MEAL_TYPES}),
        manifest=manifest,
        days=14,
        seed=42,
        targets=targets,
        profile=profile,
    )
    last_seen: dict[str, int] = {}
    for day in plan.days:
        for slot in day.slots:
            prev = last_seen.get(slot.recipe_id)
            if prev is not None:
                assert day.day_number - prev > manifest.max_repeat_window_days, (
                    f"Recipe {slot.recipe_id} repeated at days {prev} → {day.day_number}"
                )
            last_seen[slot.recipe_id] = day.day_number


def test_plan_carries_profile_and_targets_through():
    profile = _profile()
    targets = personalization.compute_targets(profile, _manifest())
    plan = meal_planner.build_plan(
        recipes_by_meal=_recipes_by_meal(),
        manifest=_manifest(),
        days=3,
        seed=42,
        targets=targets,
        profile=profile,
    )
    assert plan.user_profile is not None
    assert plan.user_profile.name == "reda"
    assert plan.targets is not None
    assert plan.targets.daily_kcal == targets.daily_kcal


# ---------------------------------------------------------------------------
# Hard kcal-cap filter
# ---------------------------------------------------------------------------

def test_kcal_cap_filters_out_recipes_above_ceiling():
    """A recipe whose kcal exceeds per-meal cap × 1.15 must never appear when
    plenty of in-cap alternatives exist."""
    profile = _profile()
    targets = personalization.compute_targets(profile, _manifest())

    cap_pct = profile.per_meal_kcal_cap_pct
    # Forge an outlier lunch above the cap by a wide margin.
    outlier_kcal = targets.per_meal["lunch"].kcal * cap_pct * 2
    outlier = _recipe("lunch-outlier", "lunch", kcal=outlier_kcal)

    recipes = _recipes_by_meal()
    recipes["lunch"].append(outlier)

    plan = meal_planner.build_plan(
        recipes_by_meal=recipes,
        manifest=_manifest(),
        days=14,
        seed=42,
        targets=targets,
        profile=profile,
    )
    seen_ids = {s.recipe_id for d in plan.days for s in d.slots}
    assert outlier.id not in seen_ids


def test_kcal_cap_relaxation_when_no_recipe_fits(caplog):
    """When every recipe in the bucket exceeds the cap, the planner relaxes
    the cap (with a warning) instead of crashing."""
    profile = _profile(per_meal_kcal_cap_pct=1.0)  # very strict
    targets = personalization.compute_targets(profile, _manifest())

    # Replace lunch bucket with recipes all far above the cap.
    over_cap = targets.per_meal["lunch"].kcal * 1.30  # 30% over → forces relaxation
    bucket_over = [
        _recipe(f"too-heavy-{i}", "lunch", kcal=over_cap + i * 5)
        for i in range(10)
    ]
    recipes = _recipes_by_meal()
    recipes["lunch"] = bucket_over

    with caplog.at_level("WARNING", logger="src.planning.meal_planner"):
        plan = meal_planner.build_plan(
            recipes_by_meal=recipes,
            manifest=_manifest(),
            days=3,
            seed=42,
            targets=targets,
            profile=profile,
        )

    assert any(
        "larger than" in r.getMessage() or "no recipe" in r.getMessage().lower()
        for r in caplog.records
    )
    # And the plan still contains a lunch slot every day.
    for day in plan.days:
        types = {s.meal_type for s in day.slots}
        assert "lunch" in types


# ---------------------------------------------------------------------------
# Fix 3 — generation_warnings surfaced on the MealPlan
# ---------------------------------------------------------------------------

def test_relaxation_appends_to_plan_generation_warnings():
    """Cap relaxation should populate plan.generation_warnings (not just logs)."""
    profile = _profile(per_meal_kcal_cap_pct=1.0)
    targets = personalization.compute_targets(profile, _manifest())
    over_cap = targets.per_meal["lunch"].kcal * 1.30
    recipes = _recipes_by_meal()
    recipes["lunch"] = [
        _recipe(f"big-{i}", "lunch", kcal=over_cap + i * 5) for i in range(10)
    ]
    plan = meal_planner.build_plan(
        recipes_by_meal=recipes,
        manifest=_manifest(),
        days=3,
        seed=42,
        targets=targets,
        profile=profile,
    )
    assert plan.generation_warnings  # non-empty
    assert any("larger than" in w or "no recipe" in w.lower() for w in plan.generation_warnings)


def test_generation_warnings_deduped():
    """Same warning across multiple days should appear once on the MealPlan."""
    profile = _profile(per_meal_kcal_cap_pct=1.0)
    targets = personalization.compute_targets(profile, _manifest())
    over_cap = targets.per_meal["lunch"].kcal * 1.30
    recipes = _recipes_by_meal()
    recipes["lunch"] = [
        _recipe(f"big-{i}", "lunch", kcal=over_cap + i * 5) for i in range(10)
    ]
    plan = meal_planner.build_plan(
        recipes_by_meal=recipes, manifest=_manifest(),
        days=14, seed=42, targets=targets, profile=profile,
    )
    # Without dedup, the relaxation message would fire at least once per (day,
    # meal-with-relaxation) — a 14-day plan touching multiple meals would yield
    # 14+ warnings. With dedup, only distinct messages survive — at most one
    # per (cap-level reached × meal-type), well below the unduped count.
    n_warnings = len(plan.generation_warnings)
    assert n_warnings < 14, (
        f"Expected dedup to keep warnings under per-day count; got {n_warnings}: "
        f"{plan.generation_warnings}"
    )
    # And every warning is actually unique.
    assert len(set(plan.generation_warnings)) == n_warnings


def test_no_warnings_for_well_fitted_cookbook():
    """Backward-compat path: no targets → no generation_warnings."""
    plan = meal_planner.build_plan(
        recipes_by_meal=_recipes_by_meal(),
        manifest=_manifest(),
        days=7,
        seed=42,
    )
    assert plan.generation_warnings == []


# ---------------------------------------------------------------------------
# Fix 6 — low-confidence nutrition penalty
# ---------------------------------------------------------------------------

def test_personalized_plan_carries_insights():
    """build_plan should populate MealPlan.insights when targets is set."""
    profile = _profile()
    targets = personalization.compute_targets(profile, _manifest())
    plan = meal_planner.build_plan(
        recipes_by_meal=_recipes_by_meal(),
        manifest=_manifest(),
        days=3, seed=42, targets=targets, profile=profile,
    )
    assert plan.insights is not None
    assert plan.insights.direction == "lose"
    assert plan.insights.water_l_per_day > 0
    assert plan.insights.daily_steps_target > 0


def test_non_personalized_plan_has_no_insights():
    """Backward-compat: no targets/profile → no insights."""
    plan = meal_planner.build_plan(
        recipes_by_meal=_recipes_by_meal(),
        manifest=_manifest(),
        days=3, seed=42,
    )
    assert plan.insights is None


def test_high_confidence_recipe_preferred_over_low_confidence_at_same_distance():
    """Two recipes identical except for confidence — high-confidence wins first."""
    profile = _profile()
    targets = personalization.compute_targets(profile, _manifest())

    target_kcal = targets.per_meal["dinner"].kcal
    # Both within the cap, same kcal → distance ties before the penalty.
    high = _recipe("dinner-high-conf", "dinner", kcal=target_kcal,
                   protein=targets.per_meal["dinner"].protein_g,
                   fat=targets.per_meal["dinner"].fat_g,
                   fiber=targets.per_meal["dinner"].fiber_g)
    low = _recipe("dinner-low-conf", "dinner", kcal=target_kcal,
                  protein=targets.per_meal["dinner"].protein_g,
                  fat=targets.per_meal["dinner"].fat_g,
                  fiber=targets.per_meal["dinner"].fiber_g)
    # Mutate confidence
    low.nutrition_per_serving = low.nutrition_per_serving.model_copy(
        update={"confidence": "low"}
    )
    recipes = _recipes_by_meal()
    recipes["dinner"] = [low, high]  # order shouldn't matter

    plan = meal_planner.build_plan(
        recipes_by_meal=recipes,
        manifest=_manifest(),
        days=1,
        seed=42,
        targets=targets,
        profile=profile,
    )
    dinner_slot = next(s for s in plan.days[0].slots if s.meal_type == "dinner")
    assert dinner_slot.recipe_id == high.id, (
        "Low-confidence recipe should be deprioritized vs equivalent high-confidence one."
    )

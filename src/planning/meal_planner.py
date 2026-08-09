"""Deterministic, seedable meal-plan assembler (default 60 days).

Variety + kcal-balance scoring, no LLM. When `targets` (and `profile`) are
provided, the planner additionally biases recipe selection toward the
personalized macro/kcal envelope and applies a hard per-meal kcal cap.
"""
import logging
import random

from src.models.meal_plan import (
    CookbookManifest,
    DayPlan,
    MealPlan,
    MealSlot,
    MealTypeKey,
    PerMealTarget,
    PersonalizedTargets,
    UserProfile,
)
from src.models.nutrition import NutritionInfo
from src.models.recipe import Recipe

logger = logging.getLogger(__name__)

CAP_RELAX_STEP = 0.05
CAP_RELAX_MAX = 0.50

# Distance penalty added when a recipe's nutrition has confidence="low".
# Matters only when `targets` is given (legacy path uses absolute kcal distance).
# Numbers are unitless on the same scale as the macro-distance score, where a
# perfectly-matching recipe scores ~0 and a mediocre one scores ~0.4–0.6 — a
# 0.30 penalty pushes a low-confidence recipe behind a similar high-confidence
# alternative without making it unselectable.
LOW_CONFIDENCE_PENALTY = 0.30


def build_plan(
    recipes_by_meal: dict[str, list[Recipe]],
    manifest: CookbookManifest,
    days: int = 60,
    seed: int = 42,
    targets: PersonalizedTargets | None = None,
    profile: UserProfile | None = None,
) -> MealPlan:
    """Assemble `days` days × `len(manifest.meal_structure)` slots.

    When `targets` is given, per-meal budgets follow the personalized share
    and recipes above the per-meal kcal cap (scaled by `profile.per_meal_kcal_cap_pct`)
    are filtered out before scoring.
    """
    meal_structure: list[MealTypeKey] = manifest.meal_structure

    for mt in meal_structure:
        if not recipes_by_meal.get(mt):
            raise ValueError(
                f"No recipes available for meal type '{mt}' — cannot build the plan."
            )

    target_daily_kcal = (
        targets.daily_kcal if targets is not None else manifest.target_daily_kcal
    )
    cap_pct = profile.per_meal_kcal_cap_pct if profile is not None else None
    window = manifest.max_repeat_window_days

    usage_count: dict[str, int] = {}
    last_used_day: dict[str, int] = {}
    generation_warnings: list[str] = []

    day_plans: list[DayPlan] = []

    for day in range(1, days + 1):
        slots: list[MealSlot] = []
        kcal_so_far = 0.0
        meals_total = len(meal_structure)

        for meal_idx, meal_type in enumerate(meal_structure):
            bucket = recipes_by_meal[meal_type]
            per_meal_target = targets.per_meal[meal_type] if targets is not None else None

            if per_meal_target is not None:
                per_meal_budget = per_meal_target.kcal
            else:
                meals_done = meal_idx
                meals_remaining = meals_total - meals_done
                per_meal_budget = (target_daily_kcal - kcal_so_far) / max(meals_remaining, 1)

            candidates = _eligible_candidates(
                bucket, last_used_day, day, window,
                per_meal_target=per_meal_target,
                cap_pct=cap_pct,
                meal_type=meal_type,
                generation_warnings=generation_warnings,
            )

            rng = random.Random(seed * 1_000_003 + day * 997 + meal_idx)
            scored = [
                (
                    _score(r, per_meal_budget, usage_count, per_meal_target),
                    rng.random(),  # deterministic tie-break among equal scores
                    r,
                )
                for r in candidates
            ]
            scored.sort(key=lambda t: (t[0], t[1]))
            chosen = scored[0][2]

            nutrition = chosen.nutrition_per_serving or _zero_nutrition()
            slots.append(MealSlot(
                day=day,
                meal_type=meal_type,
                recipe_id=chosen.id,
                recipe_title=chosen.title,
                nutrition_per_serving=nutrition,
            ))

            kcal_so_far += nutrition.calories_kcal
            usage_count[chosen.id] = usage_count.get(chosen.id, 0) + 1
            last_used_day[chosen.id] = day

        day_plans.append(DayPlan(
            day_number=day,
            slots=slots,
            daily_totals=_sum_nutrition([s.nutrition_per_serving for s in slots]),
        ))

    avg = average_nutrition([d.daily_totals for d in day_plans])

    insights = None
    if targets is not None and profile is not None:
        from src.planning.personalization import derive_insights
        insights = derive_insights(profile, targets, manifest)

    return MealPlan(
        cookbook_name=manifest.name,
        manifest=manifest,
        seed=seed,
        days=day_plans,
        avg_daily_nutrition=avg,
        user_profile=profile,
        targets=targets,
        insights=insights,
        generation_warnings=_dedupe_warnings(generation_warnings),
    )


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    """De-duplicate warnings while preserving order — many days can trigger
    the same relaxation message; we only want each unique line once."""
    seen: set[str] = set()
    out: list[str] = []
    for w in warnings:
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def _eligible_candidates(
    bucket: list[Recipe],
    last_used_day: dict[str, int],
    current_day: int,
    window: int,
    *,
    per_meal_target: PerMealTarget | None,
    cap_pct: float | None,
    meal_type: str,
    generation_warnings: list[str] | None = None,
) -> list[Recipe]:
    """Recipes not seen within `window` days; relax the window first, then —
    if a per-meal kcal cap is set — relax the cap until the pool is non-empty.

    Relaxation events are appended to `generation_warnings` (when given) so
    the CLI can surface them — `logger.warning` alone is invisible without
    a configured handler.
    """
    w = window
    while w >= 0:
        fresh = [
            r for r in bucket
            if current_day - last_used_day.get(r.id, -10_000) > w
        ]
        if fresh:
            if per_meal_target is None or cap_pct is None:
                return fresh
            kcal_filtered = _apply_kcal_cap(
                fresh, per_meal_target.kcal, cap_pct, meal_type,
                day=current_day, generation_warnings=generation_warnings,
            )
            if kcal_filtered:
                return kcal_filtered
        w -= 1

    # Repeat-window already at -1 (no restriction). The pool is the whole bucket.
    if per_meal_target is None or cap_pct is None:
        return list(bucket)
    kcal_filtered = _apply_kcal_cap(
        list(bucket), per_meal_target.kcal, cap_pct, meal_type,
        day=current_day, generation_warnings=generation_warnings,
    )
    return kcal_filtered or list(bucket)


def _apply_kcal_cap(
    pool: list[Recipe],
    target_kcal: float,
    cap_pct: float,
    meal_type: str,
    *,
    day: int,
    generation_warnings: list[str] | None = None,
) -> list[Recipe]:
    """Drop recipes above `target_kcal · cap_pct`; if empty, relax cap by
    +CAP_RELAX_STEP until non-empty (capped at +CAP_RELAX_MAX). Returns []
    if no relaxation succeeds — caller falls back to the unfiltered pool."""
    cap = cap_pct
    while cap <= cap_pct + CAP_RELAX_MAX + 1e-9:
        ceiling = target_kcal * cap
        kept = [
            r for r in pool
            if (r.nutrition_per_serving.calories_kcal if r.nutrition_per_serving else 0.0)
            <= ceiling
        ]
        if kept:
            if cap > cap_pct + 1e-9:
                meal_label = _meal_label(meal_type)
                msg = (
                    f"For {meal_label}, the book's recipes run a bit larger than your "
                    f"ideal target ({target_kcal:.0f} calories). We picked the smallest "
                    f"recipe available each time — some days will slightly exceed your "
                    f"daily target."
                )
                logger.warning(msg)
                if generation_warnings is not None:
                    generation_warnings.append(msg)
            return kept
        cap += CAP_RELAX_STEP
    meal_label = _meal_label(meal_type)
    msg = (
        f"For {meal_label}, no recipe in the book fit your ideal target "
        f"({target_kcal:.0f} calories). We took the smallest recipe available — "
        f"your daily total will exceed the target a little."
    )
    logger.warning(msg)
    if generation_warnings is not None:
        generation_warnings.append(msg)
    return []


def _meal_label(meal_type: str) -> str:
    """Inline label so warnings read naturally without importing constants."""
    labels = {
        "breakfast": "breakfast",
        "lunch": "lunch",
        "snack": "the snack",
        "dinner": "dinner",
        "dessert": "dessert",
    }
    return labels.get(meal_type, meal_type)


def _score(
    recipe: Recipe,
    per_meal_budget_kcal: float,
    usage_count: dict[str, int],
    per_meal_target: PerMealTarget | None,
) -> tuple[int, float, str]:
    """Lower is better. Least-used first ensures full rotation through the
    bucket before any recipe repeats; macro distance tie-breaks."""
    nutrition = recipe.nutrition_per_serving
    if nutrition is None:
        return (usage_count.get(recipe.id, 0), per_meal_budget_kcal, recipe.id)

    if per_meal_target is None:
        distance = abs(nutrition.calories_kcal - per_meal_budget_kcal)
    else:
        t = per_meal_target
        distance = (
            0.50 * abs(nutrition.calories_kcal - t.kcal) / max(t.kcal, 1.0)
            + 0.25 * abs(nutrition.protein_g - t.protein_g) / max(t.protein_g, 1.0)
            + 0.15 * abs(nutrition.fat_g - t.fat_g) / max(t.fat_g, 1.0)
            + 0.10 * abs(nutrition.fiber_g - t.fiber_g) / max(t.fiber_g, 1.0)
        )
        # Low-confidence nutrition typically under-reports kcal/macros (missing
        # CIQUAL data → ingredient contributions defaulted to 0). That makes such
        # recipes artificially close to a low target and biases selection toward
        # them. Push them behind comparable high-confidence alternatives.
        if nutrition.confidence == "low":
            distance += LOW_CONFIDENCE_PENALTY
    return (usage_count.get(recipe.id, 0), distance, recipe.id)


# Panel fields aggregated by _sum_nutrition / average_nutrition (the 7 core macros + the
# optional extras). A field that is None on every item stays None; core macros default to 0.
_AGG_FIELDS: tuple[str, ...] = (
    "calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg", "sugar_g",
    "saturated_fat_g", "added_sugar_g", "cholesterol_mg", "potassium_mg", "trans_fat_g",
    "mufa_g", "pufa_g", "calcium_mg", "iron_mg", "vitamin_d_mcg",
)
_CORE_AGG_FIELDS = {"calories_kcal", "protein_g", "carbs_g", "fat_g", "fiber_g", "sodium_mg", "sugar_g"}


def _zero_nutrition() -> NutritionInfo:
    return NutritionInfo(
        calories_kcal=0, protein_g=0, carbs_g=0, fat_g=0,
        fiber_g=0, sodium_mg=0, sugar_g=0,
        source="fallback", confidence="low",
    )


def _aggregate_nutrition(items: list[NutritionInfo], *, average: bool) -> NutritionInfo:
    """Sum (or average) the panel across ``items``, ignoring ``None`` contributions per
    field — so e.g. a day-average's ``vitamin_d_mcg`` averages only over the recipes that
    actually carried a vitamin-D value."""
    if not items:
        return _zero_nutrition()
    panel: dict[str, float | None] = {}
    for f in _AGG_FIELDS:
        vals = [v for v in (getattr(n, f) for n in items) if v is not None]
        if vals:
            panel[f] = (sum(vals) / len(vals)) if average else sum(vals)
        else:
            panel[f] = 0.0 if f in _CORE_AGG_FIELDS else None
    return NutritionInfo(**panel, source="mixed", confidence="medium")


def _sum_nutrition(items: list[NutritionInfo]) -> NutritionInfo:
    return _aggregate_nutrition(items, average=False)


def average_nutrition(items: list[NutritionInfo]) -> NutritionInfo:
    return _aggregate_nutrition(items, average=True)


def core_day_averages(plan: MealPlan) -> dict[str, float] | None:
    """Daily averages counting only the meals a reader cannot skip.

    Snack and dessert are optional in this book, so both the PDF and the
    Markdown need to state what a day looks like without them rather than
    leaving the reader to guess. Returns None when the plan has no optional
    meals to drop.
    """
    from src.constants import OPTIONAL_MEAL_TYPES

    structure = plan.manifest.meal_structure
    core = [mt for mt in structure if mt not in OPTIONAL_MEAL_TYPES]
    if not core or len(core) == len(structure) or not plan.days:
        return None

    kcal: list[float] = []
    protein: list[float] = []
    fiber: list[float] = []
    for day in plan.days:
        slots = [s for s in day.slots if s.meal_type in core]
        kcal.append(sum(s.nutrition_per_serving.calories_kcal for s in slots))
        protein.append(sum(s.nutrition_per_serving.protein_g for s in slots))
        fiber.append(sum(s.nutrition_per_serving.fiber_g for s in slots))

    n = len(kcal)
    mean_kcal = sum(kcal) / n
    return {
        "kcal": mean_kcal,
        "protein_g": sum(protein) / n,
        "fiber_g": sum(fiber) / n,
        "kcal_saved": (plan.avg_daily_nutrition.calories_kcal or 0.0) - mean_kcal,
    }

"""BMR / TDEE / daily-target derivation for personalized meal plans.

Pure-functional, no I/O. All inputs are validated Pydantic models.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median

from src.models.meal_plan import (
    CookbookManifest,
    Insights,
    MealTypeKey,
    PerMealTarget,
    PersonalizedTargets,
    UserProfile,
)
from src.models.recipe import Recipe

# Mifflin-St Jeor activity multipliers (Harris-Benedict revised, 2005).
ACTIVITY_FACTORS: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# Display labels for the activity-level enum (used in PDF + markdown output).
ACTIVITY_LABELS: dict[str, str] = {
    "sedentary": "sedentary",
    "light": "light",
    "moderate": "moderate",
    "active": "active",
    "very_active": "very active",
}

# Display labels for the sex enum.
SEX_LABELS: dict[str, str] = {
    "M": "Male",
    "F": "Female",
}

# Energy density of body fat (~7700 kcal per kg) used to convert weekly loss
# target into a daily kcal deficit.
KCAL_PER_KG_FAT = 7700.0

# WHO/EFSA safety floors below which medical supervision is required.
KCAL_FLOOR: dict[str, int] = {"M": 1500, "F": 1200}

# Default per-meal energy share — RE-DERIVED from THIS book's tier energy bands,
# not inherited. The tier midpoints for the planner's default day
# (main 460 / main 460 / snack 175 / main 460 / dessert 170 = 1,725 kcal) give
# 0.27 / 0.27 / 0.10 / 0.27 / 0.10. Lunch is nudged to 0.25 and dinner to 0.28
# because the lunch slot also draws from Soups & Salads, whose `light_main` tier
# caps at 440 kcal — asking that slot for 27% of the day would be asking for
# recipes this book does not contain.
#
# (The inherited split aimed 35% of the day at lunch, which no tier here supports.)
DEFAULT_MEAL_SHARE: dict[str, float] = {
    "breakfast": 0.27,
    "lunch": 0.25,
    "snack": 0.10,
    "dinner": 0.28,
    "dessert": 0.10,
}

# Minimum allowed share for any meal type that appears in `meal_structure` —
# below this the per-meal target is too small to be useful and the hard kcal
# cap effectively excludes every recipe in the bucket.
MIN_MEAL_SHARE = 0.02

# Block planning when the cookbook's recipe medians can't reach this fraction
# of the user's daily kcal target. CLI users can override with --force.
CAPACITY_BLOCK_SHORTFALL = 0.25

# Insights — personalized success-guide constants.
# Water: WHO baseline of ~35 ml per kg of body weight per day, capped at 4 L
# (above which over-hydration risks rise without metabolic benefit).
WATER_ML_PER_KG = 35.0
WATER_L_CAP = 4.0
# Daily-step targets calibrated by activity level — ~1500 step delta between
# tiers, anchored on 10 000/day for the canonical "moderate" mid-point.
STEPS_BY_ACTIVITY: dict[str, int] = {
    "sedentary": 7000,
    "light": 8500,
    "moderate": 10000,
    "active": 11500,
    "very_active": 13000,
}
# Mifflin-St Jeor: BMR drops ~10 kcal/day per kg of body mass lost (the W
# coefficient in the formula). Used to warn users about metabolic adaptation.
BMR_DROP_KCAL_PER_KG = 10.0
# Initial water-loss caveat (1–3 kg in week 1) only mentioned for users with
# enough body mass for the effect to be visible; tiny users see less swing.
WATER_LOSS_CAVEAT_MIN_WEIGHT_KG = 70.0

# Macronutrient policy:
#   protein  = PROTEIN_G_PER_KG · current weight (preserves lean mass)
#   fat      ≈ FAT_PCT_OF_KCAL of total energy
#   fiber    = FIBER_G_PER_1000_KCAL · daily kcal / 1000
#   carbs    = residual
# PROTEIN_G_PER_KG = 1.5 sits in the upper half of the DGA 2025-2030 band of
# 1.2-1.6 g/kg/day, and is exactly where the book's own printed plan lands
# (day targets = 1.43-1.53 g/kg for a 70 kg reader — see
# data/fatty_liver_diabetes_guidelines.yaml daily_targets.protein_g_per_kg_bodyweight and
# the arithmetic block in section 4 of the dossier). Protein is a therapeutic axis
# here, not just satiety: isocaloric high-protein diets lowered liver fat in adults
# with type 2 diabetes independently of body weight (Markova 2017).
# CAVEAT carried in the disclaimer, not in code: chronic kidney disease restricts
# protein to ~0.55-0.80 g/kg/day under clinician guidance, and diabetic kidney
# disease is common in this readership.
PROTEIN_G_PER_KG = 1.5
# 35% of energy from fat is the Mediterranean shape this book is built on (most of
# it unsaturated and olive-oil-led, with saturated fat held under 10% of energy).
# It also makes the residual carbohydrate land at ~40% of energy, matching the
# spec's day-at-targets figure of 39.4% — the inherited 27.5% pushed the residual
# to ~48%, higher than any tier in this book targets.
FAT_PCT_OF_KCAL = 0.35
# ADA's route: at least 14 g fiber per 1,000 kcal, from minimally processed,
# nutrient-dense sources. Scales with the reader's own energy target.
FIBER_G_PER_1000_KCAL = 14.0


def compute_bmr(profile: UserProfile) -> float:
    """Mifflin-St Jeor basal metabolic rate (kcal/day)."""
    base = 10.0 * profile.weight_kg + 6.25 * profile.height_cm - 5.0 * profile.age
    return base + (5.0 if profile.sex == "M" else -161.0)


def compute_tdee(profile: UserProfile) -> float:
    """Total daily energy expenditure: BMR × activity factor."""
    return compute_bmr(profile) * ACTIVITY_FACTORS[profile.activity_level]


def derive_weekly_loss(
    profile: UserProfile,
    today: date | None = None,
) -> tuple[float, str | None]:
    """Return the rate (kg/week) and an optional clamp/zero-day warning.

    If `target_date` is set, derive from time-to-target. Otherwise return the
    profile's explicit `weekly_loss_kg` (which the model_validator guarantees
    is non-None when target_date is None).
    """
    if profile.target_date is not None:
        today = today or date.today()
        days = (profile.target_date - today).days
        if days <= 0:
            # Target date is today or past — fall back to a safe maintenance
            # rate of 0 (no deficit/surplus); warn the user.
            return 0.0, (
                f"Target date {profile.target_date.isoformat()} is today or in the "
                f"past (today: {today.isoformat()}) — rate set to 0; set a new date "
                f"to resume a trajectory."
            )
        weeks = max(days / 7.0, 1e-9)
        raw = (profile.weight_kg - profile.target_weight_kg) / weeks
        clamped = max(-1.0, min(1.0, raw))
        if abs(raw - clamped) > 1e-6:
            extended_weeks = abs(profile.weight_kg - profile.target_weight_kg) / max(abs(clamped), 1e-9)
            return clamped, (
                f"Required pace {raw:+.2f} kg/week exceeds the safe limit "
                f"(±1.0 kg/week) — capped at {clamped:+.2f}. At this pace, "
                f"the goal will be reached in ~{extended_weeks:.0f} weeks."
            )
        return clamped, None
    # weekly_loss_kg is guaranteed non-None by UserProfile._validate_pace.
    assert profile.weekly_loss_kg is not None
    return profile.weekly_loss_kg, None


def compute_targets(
    profile: UserProfile,
    manifest: CookbookManifest,
    today: date | None = None,
) -> PersonalizedTargets:
    """Derive daily kcal + macros + per-meal breakdown from biometrics."""
    bmr = compute_bmr(profile)
    tdee = compute_tdee(profile)

    weekly_loss_kg, pace_warning = derive_weekly_loss(profile, today=today)

    daily_deficit = weekly_loss_kg * KCAL_PER_KG_FAT / 7.0
    raw_kcal = tdee - daily_deficit
    floor = KCAL_FLOOR[profile.sex]
    daily_kcal = max(int(round(raw_kcal / 50.0) * 50), floor)

    protein_g = round(PROTEIN_G_PER_KG * profile.weight_kg, 1)
    fat_g = round(FAT_PCT_OF_KCAL * daily_kcal / 9.0, 1)
    fiber_g = round(FIBER_G_PER_1000_KCAL * daily_kcal / 1000.0, 1)
    carbs_g = round(max(daily_kcal - protein_g * 4 - fat_g * 9, 0) / 4.0, 1)

    share = _resolve_meal_share(manifest)
    too_small = [mt for mt in manifest.meal_structure if share[mt] < MIN_MEAL_SHARE]
    if too_small:
        raise ValueError(
            f"Meal share too small (< {MIN_MEAL_SHARE:.0%}) for: {too_small}. "
            f"Increase the share in cookbook.meal_share or remove these meals from meal_structure."
        )

    per_meal: dict[MealTypeKey, PerMealTarget] = {}
    for mt in manifest.meal_structure:
        s = share[mt]
        per_meal[mt] = PerMealTarget(
            kcal=round(daily_kcal * s, 1),
            protein_g=round(protein_g * s, 1),
            fat_g=round(fat_g * s, 1),
            carbs_g=round(carbs_g * s, 1),
            fiber_g=round(fiber_g * s, 1),
        )

    targets = PersonalizedTargets(
        daily_kcal=daily_kcal,
        protein_g=protein_g,
        fat_g=fat_g,
        carbs_g=carbs_g,
        fiber_g=fiber_g,
        per_meal=per_meal,
        bmr=round(bmr, 1),
        tdee=round(tdee, 1),
    )
    targets.warnings = safety_warnings(
        profile, targets, raw_kcal,
        weekly_loss_kg=weekly_loss_kg, pace_warning=pace_warning,
    )
    return targets


def safety_warnings(
    profile: UserProfile,
    targets: PersonalizedTargets,
    raw_kcal_before_floor: float | None = None,
    weekly_loss_kg: float | None = None,
    pace_warning: str | None = None,
) -> list[str]:
    """Surface medically-relevant red flags in plain English (no jargon).

    `weekly_loss_kg` is the *resolved* rate (post target-date derivation).
    Pass None to fall back to the profile's explicit `weekly_loss_kg`.
    """
    warnings: list[str] = []
    if pace_warning is not None:
        warnings.append(pace_warning)

    rate = weekly_loss_kg if weekly_loss_kg is not None else (profile.weekly_loss_kg or 0.0)
    floor_label = "women" if profile.sex == "F" else "men"

    if rate > 0.75:
        warnings.append(
            f"You're aiming for fast loss of {rate:.2f} kg per week. "
            f"Above 0.75 kg per week, check with a doctor before you start."
        )

    bmi_target = profile.target_weight_kg / (profile.height_cm / 100.0) ** 2
    if bmi_target < 18.5:
        warnings.append(
            f"At your target weight of {profile.target_weight_kg:.1f} kg you'd be "
            f"underweight for your height. Check this goal with a doctor."
        )

    if raw_kcal_before_floor is not None and targets.daily_kcal > raw_kcal_before_floor + 1:
        warnings.append(
            f"Your daily calories were raised to {targets.daily_kcal} — that's the "
            f"safe minimum for {floor_label}. Eating less than that risks tiring your "
            f"body out and slowing your weight loss."
        )

    bmi_current = profile.weight_kg / (profile.height_cm / 100.0) ** 2
    if bmi_current >= 30 and 0 < rate < 0.25:
        warnings.append(
            f"Given your current weight, you could safely lose a bit faster. "
            f"A pace of {rate:.2f} kg per week is very slow."
        )

    return warnings


@dataclass
class CapacityReport:
    """Outcome of comparing the cookbook's recipe medians vs the user target."""
    feasible_daily_kcal: float
    target_daily_kcal: int
    shortfall_pct: float  # 0.0 = feasible meets/exceeds target; 0.4 = 40% short
    medians_per_meal: dict[str, float]
    blocking: bool
    message: str


def check_cookbook_capacity(
    recipes_by_meal: dict[str, list[Recipe]],
    targets: PersonalizedTargets,
    manifest: CookbookManifest,
) -> CapacityReport:
    """Estimate the cookbook's deliverable kcal/day and compare to the target.

    Uses the *median* kcal of recipes in each meal-type bucket — more robust
    than the maximum (which would over-promise) or the diet-rule ceiling
    (which is hypothetical, not based on what was actually generated).
    """
    medians: dict[str, float] = {}
    for mt in manifest.meal_structure:
        bucket = recipes_by_meal.get(mt, [])
        kcals = [
            r.nutrition_per_serving.calories_kcal
            for r in bucket if r.nutrition_per_serving is not None
        ]
        medians[mt] = median(kcals) if kcals else 0.0

    feasible = sum(medians.values())
    target = targets.daily_kcal
    shortfall = max(0.0, (target - feasible) / target) if target > 0 else 0.0
    blocking = shortfall > CAPACITY_BLOCK_SHORTFALL

    if shortfall <= 0.05:
        message = (
            f"Book capacity adequate: ~{feasible:.0f} kcal/day available "
            f"vs target {target} kcal/day."
        )
    elif blocking:
        message = (
            f"This book can deliver at most ~{feasible:.0f} kcal/day ({(1-shortfall)*100:.0f}% "
            f"of your {target} target). Pick another book, or use --force to "
            f"generate anyway (the average plan will fall well short of the target)."
        )
    else:
        message = (
            f"Book capacity borderline: ~{feasible:.0f} kcal/day available "
            f"vs target {target} ({shortfall*100:.0f}% below) — the average plan "
            f"will be close to {feasible:.0f} kcal."
        )

    return CapacityReport(
        feasible_daily_kcal=feasible,
        target_daily_kcal=target,
        shortfall_pct=shortfall,
        medians_per_meal=medians,
        blocking=blocking,
        message=message,
    )


def derive_insights(
    profile: UserProfile,
    targets: PersonalizedTargets,
    manifest: CookbookManifest,
    today: date | None = None,
) -> Insights:
    """Build the personalized success-guide content shown on the PDF intro page.

    Pure-functional, deterministic for a given (profile, targets, manifest, today).
    """
    today = today or date.today()
    rate, _ = derive_weekly_loss(profile, today=today)

    delta_kg = profile.weight_kg - profile.target_weight_kg

    if abs(rate) < 1e-3 or abs(delta_kg) < 0.5:
        direction = "maintain"
    elif delta_kg > 0:
        direction = "lose"
    else:
        direction = "gain"

    direction_label = {"lose": "deficit", "gain": "surplus", "maintain": "maintenance"}[direction]
    direction_verb = {"lose": "lose", "gain": "gain", "maintain": "maintain"}[direction]

    if direction == "maintain" or abs(rate) < 1e-3:
        weeks_to_target = 0.0
        projected_target_date: date | None = None
        checkpoint_1_month = profile.weight_kg
    else:
        weeks_to_target = abs(delta_kg) / max(abs(rate), 0.05)
        projected_target_date = today + timedelta(days=int(round(weeks_to_target * 7)))
        # `rate` carries the loss sign (positive = lose); subtract so loss
        # decreases the projected weight and gain (negative rate) increases it.
        checkpoint_1_month = profile.weight_kg - 4 * rate

    daily_deficit_kcal = int(round(rate * KCAL_PER_KG_FAT / 7.0))
    water_l_per_day = min(WATER_ML_PER_KG * profile.weight_kg / 1000.0, WATER_L_CAP)
    daily_steps_target = STEPS_BY_ACTIVITY[profile.activity_level]
    activity_factor = ACTIVITY_FACTORS[profile.activity_level]

    protein_g_per_kg = round(targets.protein_g / max(profile.weight_kg, 1.0), 1)
    main_meal = targets.per_meal.get("lunch") or targets.per_meal.get("dinner")
    if main_meal is not None:
        protein_per_main_meal = int(round(main_meal.protein_g))
    else:
        protein_per_main_meal = int(round(targets.protein_g / max(len(manifest.meal_structure), 1)))

    bmr_drop_estimate = int(round(BMR_DROP_KCAL_PER_KG * abs(delta_kg)))

    cookbook_diet_note = _diet_note(manifest.diet_tags)
    initial_water_loss_caveat = (
        direction == "lose" and profile.weight_kg >= WATER_LOSS_CAVEAT_MIN_WEIGHT_KG
    )

    return Insights(
        direction=direction,
        direction_label=direction_label,
        direction_verb=direction_verb,
        delta_kg=round(delta_kg, 1),
        weekly_loss_kg=round(rate, 2),
        weeks_to_target=round(weeks_to_target, 1),
        projected_target_date=projected_target_date,
        checkpoint_1_month_kg=round(checkpoint_1_month, 1),
        activity_factor=activity_factor,
        daily_deficit_kcal=daily_deficit_kcal,
        water_l_per_day=round(water_l_per_day, 2),
        daily_steps_target=daily_steps_target,
        protein_g_per_kg=protein_g_per_kg,
        protein_per_main_meal=protein_per_main_meal,
        bmr_drop_estimate=bmr_drop_estimate,
        cookbook_diet_note=cookbook_diet_note,
        initial_water_loss_caveat=initial_water_loss_caveat,
    )


def _diet_note(diet_tags: list[str]) -> str:
    """One-sentence rationale for *this* book's diet stance, in plain English.

    The book's stance is Mediterranean in character, energy-controlled, very low in
    added sugar, fiber- and protein-forward, alcohol-free, and deliberately NOT
    low-carbohydrate — the recipes already encode all of that, so this just reassures
    the reader they can follow the quantities as written. (`diet_tags` is kept for
    signature stability.)
    """
    return (
        "Just follow the quantities in each recipe — they're calibrated for your target, and "
        "the same plate is already doing both jobs: less added sugar and lighter, olive-oil-led "
        "fat for your liver, steady carbohydrate with plenty of fiber and protein for your blood "
        "sugar. Nothing here asks you to cut carbohydrate out."
    )


def _resolve_meal_share(manifest: CookbookManifest) -> dict[MealTypeKey, float]:
    """Use the manifest's meal_share if set; otherwise the default split,
    re-normalized to the cookbook's actual meal_structure (so a 3-meal
    structure still sums to 1.0)."""
    if manifest.meal_share is not None:
        return manifest.meal_share

    raw = {mt: DEFAULT_MEAL_SHARE.get(mt, 0.0) for mt in manifest.meal_structure}
    total = sum(raw.values())
    if total <= 0:
        even = 1.0 / len(manifest.meal_structure)
        return {mt: even for mt in manifest.meal_structure}
    return {mt: v / total for mt, v in raw.items()}

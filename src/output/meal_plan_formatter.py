"""Render a MealPlan (with per-week slices) to Markdown, JSON, or CSV."""
import csv
import io
import json

from src.constants import MEAL_TYPE_LABELS, OPTIONAL_MEAL_TYPES
from src.models.meal_plan import CourseList, DayPlan, MealPlan
from src.planning.meal_planner import core_day_averages
from src.planning.personalization import ACTIVITY_LABELS, SEX_LABELS


def to_markdown(plan: MealPlan) -> str:
    """Human-readable plan + shopping list, organised per week."""
    m = plan.manifest
    weeks = plan.weeks or []
    book_title = m.display_name or plan.cookbook_name

    lines: list[str] = []
    lines.append(f"# {len(plan.days)}-Day Plan — {book_title}")
    lines.append("")
    lines.append(f"**Objective**: {m.objective}")
    lines.append(
        f"**Actual average**: "
        f"{plan.avg_daily_nutrition.calories_kcal:.0f} kcal/day"
    )
    optional_labels = [
        MEAL_TYPE_LABELS[mt].lower()
        for mt in m.meal_structure
        if mt in OPTIONAL_MEAL_TYPES
    ]
    if optional_labels:
        joined = " and the ".join(optional_labels)
        core = core_day_averages(plan)
        note = (
            f"**The {joined} are optional** — if you are not hungry, skip "
            f"{'them' if len(optional_labels) > 1 else 'it'}; do not force "
            f"yourself to eat on schedule."
        )
        if core is not None:
            note += (
                f" A day without {'either' if len(optional_labels) > 1 else 'it'} "
                f"still comes to about {core['kcal']:.0f} kcal, "
                f"{core['protein_g']:.0f} g protein and "
                f"{core['fiber_g']:.0f} g fiber."
            )
        lines.append(note)
    lines.append("")

    if plan.user_profile is not None and plan.targets is not None:
        lines.extend(_render_md_profile_block(plan))
        lines.append("")

    if plan.insights is not None and plan.user_profile is not None and plan.targets is not None:
        lines.extend(_render_md_insights_block(plan))
        lines.append("")

    if plan.generation_warnings:
        lines.append("## Automatic adjustments during generation")
        lines.append("")
        for w in plan.generation_warnings:
            lines.append(f"- ⚠ {w}")
        lines.append("")

    pantry_lines = _render_md_pantry(plan)
    if pantry_lines:
        lines.extend(pantry_lines)
        lines.append("")

    daily_target = plan.targets.daily_kcal if plan.targets is not None else None

    for week in weeks:
        lines.append(f"## {week.label}")
        lines.append("")
        lines.append(
            f"_Average: {week.avg_daily_nutrition.calories_kcal:.0f} kcal/day_"
        )
        lines.append("")

        # ── Per-week table ─────────────────────────────────────
        lines.append("### Schedule")
        lines.append("")
        lines.extend(_render_md_table(m.meal_structure, week.days, daily_target))
        lines.append("")

        # ── Per-week shopping list ────────────────────────────
        lines.append(f"### Shopping list (Week {week.week_number})")
        lines.append("")
        lines.extend(_render_md_course_list(week.course_list))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def to_json(plan: MealPlan) -> str:
    """Machine-readable serialization of the full plan including all weeks."""
    return json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2)


def to_csv(plan: MealPlan) -> str:
    """Combined CSV of every week's shopping list. First column is the week."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([
        "week", "category", "item", "quantity_g", "quantity_display",
        "is_optional", "is_pantry",
    ])

    for week in plan.weeks or []:
        cl = week.course_list
        for category, items in cl.items_by_category.items():
            for item in items:
                writer.writerow([
                    week.week_number,
                    category,
                    item.display_name,
                    f"{item.total_quantity_g:.1f}",
                    item.total_quantity_display,
                    "false",
                    "false",
                ])
        for item in cl.pantry_items:
            writer.writerow([
                week.week_number,
                item.category,
                item.display_name,
                f"{item.total_quantity_g:.1f}",
                item.total_quantity_display,
                "false",
                "true",
            ])
        for item in cl.optional_items:
            writer.writerow([
                week.week_number,
                item.category,
                item.display_name,
                f"{item.total_quantity_g:.1f}",
                item.total_quantity_display,
                "true",
                "false",
            ])

    return buf.getvalue()


# ── Internal helpers ──────────────────────────────────────────

def _render_md_table(
    meal_structure: list[str],
    days: list[DayPlan],
    daily_target: int | None = None,
) -> list[str]:
    # Markdown tables have no width limit, so the full word fits here — unlike
    # the PDF, where it goes in a small second line inside the header cell.
    header_cols = (
        ["Day"]
        + [
            MEAL_TYPE_LABELS[mt] + (" (optional)" if mt in OPTIONAL_MEAL_TYPES else "")
            for mt in meal_structure
        ]
        + ["Total"]
    )
    if daily_target is not None:
        header_cols.append("Δ kcal")
    out = [
        "| " + " | ".join(header_cols) + " |",
        "| " + " | ".join("---" for _ in header_cols) + " |",
    ]
    for day in days:
        cells = [str(day.day_number)]
        slots_by_type = {s.meal_type: s for s in day.slots}
        for mt in meal_structure:
            slot = slots_by_type.get(mt)
            if slot is None:
                cells.append("—")
            else:
                kcal = int(round(slot.nutrition_per_serving.calories_kcal))
                cells.append(f"{slot.recipe_title} ({kcal} kcal)")
        total = int(round(day.daily_totals.calories_kcal))
        cells.append(f"**{total} kcal**")
        if daily_target is not None:
            delta = total - daily_target
            sign = "+" if delta >= 0 else "−"
            label = f"{sign}{abs(delta)}"
            if abs(delta) > daily_target * 0.10:
                cells.append(f"**`{label}`**")  # bold + monospace flags off-target days
            else:
                cells.append(label)
        out.append("| " + " | ".join(cells) + " |")
    return out


def _render_md_profile_block(plan: MealPlan) -> list[str]:
    p = plan.user_profile
    t = plan.targets
    i = plan.insights
    assert p is not None and t is not None

    activity_hint = {
        "sedentary": "little walking, no regular exercise",
        "light": "some walking, occasional exercise",
        "moderate": "daily walking and some exercise",
        "active": "lots of walking, regular exercise",
        "very_active": "intense exercise almost every day",
    }.get(p.activity_level, "")

    out = [
        "## Your profile and your plan",
        "",
        "### You, in a few words",
        "",
        f"**{p.name}**, {SEX_LABELS[p.sex].lower()}, {p.age} years old, "
        f"{p.height_cm:.0f} cm. You currently weigh **{p.weight_kg:.1f} kg** "
        f"and you want to reach **{p.target_weight_kg:.1f} kg**.",
        "",
        f"Day to day, your physical activity is "
        f"**{ACTIVITY_LABELS[p.activity_level]}** "
        f"({activity_hint})." if activity_hint
        else f"Day to day, your physical activity is "
             f"**{ACTIVITY_LABELS[p.activity_level]}**.",
        "",
        "### Your goal, in numbers",
        "",
    ]
    if i is not None and p.target_date is not None:
        verb = "losing" if i.direction == "lose" else "gaining"
        out.append(
            f"Reach **{p.target_weight_kg:.1f} kg** by "
            f"**{p.target_date.isoformat()}**, by {verb} about "
            f"{abs(i.weekly_loss_kg):.1f} kg per week."
        )
    elif i is not None:
        verb = {"lose": "Lose", "gain": "Gain", "maintain": "Keep"}[i.direction]
        out.append(
            f"{verb} weight at a gentle pace of "
            f"**{abs(i.weekly_loss_kg):.1f} kg per week**, "
            f"safely for your health."
        )
    elif p.weekly_loss_kg is not None:
        out.append(
            f"Target pace: **{abs(p.weekly_loss_kg):.1f} kg per week**."
        )
    out.append("")

    out.extend([
        "### Your new target: what you eat each day",
        "",
        f"To reach your goal, you'll eat **{t.daily_kcal} calories total** each "
        f"day, broken down as: "
        f"**{t.protein_g:.0f} g protein** (meat, fish, eggs, legumes) · "
        f"**{t.carbs_g:.0f} g carbs** (whole grains, starches, fruit) · "
        f"**{t.fat_g:.0f} g healthy fats** (olive oil, nuts, fatty fish) · "
        f"**{t.fiber_g:.0f} g fiber** (vegetables, fruit, whole grains).",
        "",
        "### How much at each meal",
        "",
    ])
    parts: list[str] = []
    for mt in plan.manifest.meal_structure:
        pt = t.per_meal.get(mt)
        if pt is None:
            continue
        parts.append(f"**{MEAL_TYPE_LABELS[mt]}** {pt.kcal:.0f} calories")
    out.append(" · ".join(parts) + ".")

    if t.warnings:
        out.append("")
        out.append("### Important to know")
        out.append("")
        for w in t.warnings:
            out.append(f"- ⚠ {w}")
    return out


def _render_md_insights_block(plan: MealPlan) -> list[str]:
    """Personalized success guide in plain English. Mirrors the PDF insights page."""
    p = plan.user_profile
    t = plan.targets
    i = plan.insights
    assert p is not None and t is not None and i is not None

    out: list[str] = [
        f"## {p.name}, here's how to reach your goal",
        "",
    ]

    # 1. Where you go, and when
    out.extend(["### Where you're headed, and when", ""])
    if i.direction == "maintain":
        out.append(f"- You'll keep your weight around **{p.weight_kg:.1f} kg**.")
    else:
        verb = "to lose" if i.direction == "lose" else "to gain"
        out.append(
            f"- You'll go from **{p.weight_kg:.1f} kg** to "
            f"**{p.target_weight_kg:.1f} kg** — that's **{abs(i.delta_kg):.1f} kg "
            f"{verb}** — in about **{int(round(i.weeks_to_target))} weeks**."
        )
        if i.projected_target_date is not None:
            out.append(
                f"- If you follow the plan, you'll hit your goal around "
                f"**{i.projected_target_date.isoformat()}**."
            )
        out.append(
            f"- In **1 month**, you should weigh about "
            f"{i.checkpoint_1_month_kg:.1f} kg."
        )
        if i.initial_water_loss_caveat:
            out.append(
                f"- _Tip — in the first week you may lose 1 to 3 kg more than "
                f"expected: that's just water. After that, the pace settles to "
                f"about {abs(i.weekly_loss_kg):.1f} kg per week._"
            )
    out.append("")

    # 2. Energy explained in plain words
    out.extend(["### How many calories per day, and why", ""])
    out.append(
        f"- At rest, your body uses about **{t.bmr:.0f} calories** a day just to "
        f"stay alive (breathing, digesting, keeping your heart beating)."
    )
    out.append(
        f"- With your daily activity ({ACTIVITY_LABELS[p.activity_level]}), "
        f"you burn **{t.tdee:.0f} in total**."
    )
    if i.direction == "lose":
        out.append(
            f"- To lose weight safely, you'll eat "
            f"**{i.daily_deficit_kcal} calories less** per day than you burn."
        )
        out.append(f"- → Your target: **{t.daily_kcal} calories per day**.")
    elif i.direction == "gain":
        out.append(
            f"- To gain weight, you'll eat "
            f"**{-i.daily_deficit_kcal} calories more** per day than you burn."
        )
        out.append(f"- → Your target: **{t.daily_kcal} calories per day**.")
    else:
        out.append(
            f"- → Your target: **{t.daily_kcal} calories per day** "
            f"(balance — no loss, no gain)."
        )
    out.append("")

    # 3. Daily macros, with food examples and the why
    out.extend([
        "### Your new target: what you eat each day",
        "",
        f"To reach your goal, you'll eat **{t.daily_kcal} calories total** each "
        f"day, broken down as:",
        "",
    ])
    out.append(
        f"- **Protein: {t.protein_g:.0f} g** (fish, poultry, eggs, beans and lentils, "
        f"cottage cheese and Greek yogurt) — aim for about **{i.protein_per_main_meal} g "
        f"per main meal**. It keeps you from losing muscle while you lose weight, and it "
        f"helps steady your blood sugar."
    )
    out.append(
        f"- **Healthy fats: {t.fat_g:.0f} g** (olive oil, nuts, fatty fish, "
        f"avocado). They fuel your brain and your hormones."
    )
    out.append(
        f"- **Carbs: {t.carbs_g:.0f} g** (whole grains, legumes, vegetables, "
        f"fruit). {i.cookbook_diet_note}"
    )
    out.append(
        f"- **Fiber: {t.fiber_g:.0f} g** (vegetables, fruit, whole grains). "
        f"It keeps you full and eases digestion."
    )
    out.append("")

    # 4. Habits
    out.extend(["### 5 habits for success", ""])
    glasses = round(i.water_l_per_day * 4)
    out.append(
        f"- 💧 **Drink {i.water_l_per_day:.1f} liters of water a day** "
        f"(about {glasses} large glasses). It keeps you from mistaking hunger for "
        f"thirst, and it makes the extra fiber in this plan much easier on your gut."
    )
    steps_fmt = f"{i.daily_steps_target:,}"
    km = round(i.daily_steps_target * 0.7 / 1000)
    out.append(
        f"- 🚶 **Walk at least {steps_fmt} steps a day** "
        f"(about {km} km, or a 1-hour walk). Guidelines for fatty liver ask for "
        f"150 to 300 minutes of moderate activity a week — a daily walk gets you there."
    )
    out.append(
        "- 😴 **Sleep 7 to 9 hours a night**. Poor sleep raises next-day hunger "
        "by 20%."
    )
    if i.direction == "lose":
        out.append(
            "- 🍷 **Watch sugary drinks and alcohol**. A glass of wine, a soda, "
            "or a fruit juice can add 100 to 200 invisible calories. It's the "
            "number-one trap."
        )
    else:
        out.append(
            "- 🥑 **Eat energy-dense foods**: add nuts, olive oil, and whole "
            "grains to hit your target without forcing yourself to overeat."
        )
    out.append(
        "- 🍽 **Eat at regular times**. Your last meal should be at least 3 hours "
        "before you go to bed."
    )
    out.append("")

    # 5. Tracking — weekly weighing protocol + replan trigger
    out.extend(["### Tracking your progress", ""])
    out.append(
        "- **Weigh yourself once a week**, in the morning before eating, under the "
        "same conditions (same scale, same clothing)."
    )
    out.append(
        "- Weight naturally swings ±1 kg from one day to the next (water, salt, "
        "hormonal cycle) — that's normal, don't worry about it."
    )
    if i.direction != "maintain":
        verb = "lose" if i.direction == "lose" else "gain"
        out.append(
            f"- If you don't {verb} weight for 3 weeks in a row, ask to update "
            f"your plan with your new weight — your body burns less as you change "
            f"weight (about {i.bmr_drop_estimate} fewer calories a day at "
            f"{p.target_weight_kg:.1f} kg)."
        )
    return out


def _render_md_course_list(course_list: CourseList) -> list[str]:
    out: list[str] = []
    for category, items in course_list.items_by_category.items():
        out.append(f"#### {category}")
        out.append("")
        for item in items:
            out.append(f"- {item.display_name} — **{item.total_quantity_display}**")
        out.append("")
    if course_list.pantry_items:
        out.append("#### Pantry check — you should already have these")
        out.append("")
        out.append(
            "_From your pantry page. Check you have enough for the week; "
            "only buy more if you are running low._"
        )
        out.append("")
        for item in course_list.pantry_items:
            out.append(f"- {item.display_name} — {item.total_quantity_display}")
        out.append("")
    if course_list.optional_items:
        out.append("#### Condiments and optional ingredients")
        out.append("")
        for item in course_list.optional_items:
            out.append(
                f"- {item.display_name} — {item.total_quantity_display} _(optional)_"
            )
        out.append("")
    return out


def _render_md_pantry(plan: MealPlan) -> list[str]:
    """Front-matter "stock your pantry" section."""
    pantry = plan.pantry
    if pantry is None or not pantry.total_items:
        return []
    out = [
        "## Stock your pantry once",
        "",
        f"These {pantry.total_items} ingredients come up again and again across "
        f"the {len(plan.days)} days. Buy them at the start and most evenings "
        f"become a 20-minute job instead of a shopping trip. They are **not** "
        f"repeated on the weekly shopping lists — each week ends with a short "
        f"pantry check instead.",
        "",
    ]
    for category, items in pantry.items_by_category.items():
        out.append(f"### {category}")
        out.append("")
        for item in items:
            out.append(
                f"- {item.display_name} — **{item.total_quantity_display}** "
                f"total, used in {item.recipe_count} recipes"
            )
        out.append("")
    out.append(
        f"_Quantities are the total across all {len(plan.days)} days — a guide "
        f"to what size to buy, not a single shopping trip._"
    )
    return out

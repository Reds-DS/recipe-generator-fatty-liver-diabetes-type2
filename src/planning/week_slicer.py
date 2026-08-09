"""Slice a meal plan into weeks; build a course list per week.

The program is shopped one week at a time, so each output (PDF, MD, JSON, CSV)
is organised into 7-day weeks. A short trailing remainder (fewer than 4 days) is
folded into the previous week to avoid a stub mini-week at the end — e.g. a
30-day plan yields weeks of 7/7/7/9 days, a 60-day plan yields 7×8 + a final
4-day week (no days are ever dropped).
"""
from __future__ import annotations

from pathlib import Path

from src.models.meal_plan import MealPlan, WeekSlice
from src.models.recipe import Recipe
from src.planning import course_list as course_mod
from src.planning.meal_planner import average_nutrition

WEEK_LEN = 7
# A trailing partial week shorter than this many days is merged into the prior
# week (so we never emit a 1-3 day stub week).
MIN_TAIL_DAYS = 4


def build_week_spans(days: int) -> list[tuple[int, int]]:
    """Return ``(start_day, end_day)`` inclusive spans covering ``1..days`` in
    7-day weeks. A trailing remainder shorter than ``MIN_TAIL_DAYS`` is folded
    into the previous week.

    Examples: ``30 -> [(1,7),(8,14),(15,21),(22,30)]`` (the original 4-week
    layout); ``60 -> [(1,7), ..., (50,56),(57,60)]`` (nine weeks, none dropped).
    """
    if days <= 0:
        return []
    spans: list[tuple[int, int]] = []
    start = 1
    while start <= days:
        end = min(start + WEEK_LEN - 1, days)
        spans.append((start, end))
        start = end + 1
    if len(spans) >= 2:
        last_start, last_end = spans[-1]
        if last_end - last_start + 1 < MIN_TAIL_DAYS:
            prev_start, _ = spans[-2]
            spans[-2] = (prev_start, last_end)
            spans.pop()
    return spans


def build_weeks(
    plan: MealPlan,
    recipes_by_id: dict[str, Recipe],
    *,
    book_dir: Path | None = None,
    use_llm_aliases: bool = False,
) -> list[WeekSlice]:
    """Split the plan into weeks and build a CourseList per week.

    The LLM alias cache is shared across weeks (it lives at <book>/aliases.db),
    so only Week 1 incurs new LLM cost; Weeks 2-4 hit cached mappings.
    """
    days_by_number = {d.day_number: d for d in plan.days}
    total_days = max(days_by_number, default=0)

    # Resolve the whole plan once first. Two things depend on it:
    #   * the printed name per ingredient, so olive oil is not "Extra-virgin
    #     olive oil" in week 1 and "Olive oil" in week 3;
    #   * the LLM alias cache, which otherwise learns incrementally and leaves
    #     week 1 keyed on names that later weeks have since merged away.
    full = course_mod.build_course_list(
        plan, recipes_by_id, book_dir=book_dir, use_llm_aliases=use_llm_aliases,
    )
    display_overrides: dict[str, str] = {
        item.canonical_name: item.display_name
        for items in full.items_by_category.values()
        for item in items
    }
    display_overrides.update({
        item.canonical_name: item.display_name for item in full.optional_items
    })

    weeks: list[WeekSlice] = []
    for week_number, (start, end) in enumerate(build_week_spans(total_days), start=1):
        day_numbers = [n for n in range(start, end + 1) if n in days_by_number]
        if not day_numbers:
            continue
        days = [days_by_number[n] for n in day_numbers]

        sub_plan = plan.model_copy(update={"days": days, "weeks": None})
        course = course_mod.build_course_list(
            sub_plan,
            recipes_by_id,
            book_dir=book_dir,
            use_llm_aliases=use_llm_aliases,
            display_overrides=display_overrides,
        )
        course = course.model_copy(update={
            "label": f"Shopping list — Week {week_number}",
        })

        weeks.append(WeekSlice(
            week_number=week_number,
            label=f"Week {week_number} — days {day_numbers[0]}-{day_numbers[-1]}",
            day_numbers=day_numbers,
            days=days,
            avg_daily_nutrition=average_nutrition([d.daily_totals for d in days]),
            course_list=course,
        ))

    return weeks

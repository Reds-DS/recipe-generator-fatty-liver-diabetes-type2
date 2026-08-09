"""Pick the shelf-stable staples worth stocking once for the whole plan.

A 60-day plan repeats the same cupboard ingredients constantly — olive oil turns
up in nearly half the recipes, vanilla and garlic powder in a quarter. Listing
those on every single weekly shopping list buries the fresh food the reader
actually has to go out and buy. So they are lifted into a front-matter "stock
your pantry" page and demoted, within each week, to a short "check you still
have enough" block.

Selection is deliberately conservative: an item has to be BOTH shelf-stable and
frequently used. Anything perishable stays on the weekly list where it belongs,
because telling someone to keep fresh spinach "in the pantry" is worse than
saying nothing.
"""
from __future__ import annotations

from collections import defaultdict

from src.models.meal_plan import CourseItem, PantryItem, PantryList, WeekSlice
from src.planning.course_list import format_quantity

# How many of the book's recipes must use an ingredient before it earns a place
# in the cupboard. Set from the observed distribution for this book: 71% of
# ingredients appear in <=2 recipes, and the per-count bucket sizes collapse
# (48 -> 22 -> 21 -> 11) right up to 5, then stay flat. Five is the knee.
DEFAULT_MIN_RECIPES = 5

# Dried spices, blends, extracts and leaveners qualify sooner: the smallest jar
# you can buy is many times a 60-day need, so making someone shop for 6 g of
# thyme in week 6 is a failure of the plan, not a saving. That reasoning only
# holds while the quantity really is jar-sized — hence the ceiling, which keeps
# the exception from sweeping in 840 g of almond milk on a technicality.
SPICE_MIN_RECIPES = 3
SPICE_MAX_TOTAL_G = 150.0

# Categories whose contents keep for months unopened.
_SHELF_STABLE_CATEGORIES: frozenset[str] = frozenset({
    "Oils & Fats",
    "Herbs & Spices",
    "Condiments & Sauces",
    "Pantry & Baking",
    "Nuts & Seeds",
})

_SPICE_CATEGORIES: frozenset[str] = frozenset({"Herbs & Spices", "Pantry & Baking"})

# Grains/legumes are mixed — canned beans and dry grains keep for a year, bread
# goes stale in days. Only these qualify.
_GRAINS_CATEGORY = "Grains, Starches & Legumes"
_GRAINS_SHELF_STABLE_KW: tuple[str, ...] = (
    "bean", "lentil", "chickpea", "oat", "quinoa", "rice", "pasta",
    "farro", "barley", "couscous", "bulgur", "millet", "polenta", "buckwheat",
)

# Sold fresh and used within days, despite sitting in an otherwise-stable aisle.
# A name that explicitly says "dried" overrides this (see `_is_shelf_stable`).
_FRESH_HERB_KW: tuple[str, ...] = (
    "basil", "cilantro", "coriander", "parsley", "dill", "mint", "chive",
    "tarragon", "sage leaf", "ginger root",
)

# Never worth listing as a pantry item, whatever the counts say.
_NEVER_PANTRY_KW: tuple[str, ...] = (
    "zest",          # comes off a lemon you already bought — not a purchase
    "juice",         # fresh-squeezed throughout this book
    "bread", "pita", "tortilla", "wrap", "baguette", "flatbread", "bagel",
    "milk",          # refrigerated cartons, except the shelf-stable ones below
)
# ...except these, which are shelf-stable cartons.
_PANTRY_MILK_KW: tuple[str, ...] = ("soy milk", "almond milk", "oat milk", "coconut milk")

_DRIED_MARKERS: tuple[str, ...] = ("dried", "dry ", "ground ", "powder", "flake", "seasoning")


def _is_shelf_stable(item: CourseItem) -> bool:
    """True when the item keeps in a cupboard for months."""
    name = item.display_name.lower()

    if any(kw in name for kw in _PANTRY_MILK_KW):
        return True
    if any(kw in name for kw in _NEVER_PANTRY_KW):
        return False

    if item.category == _GRAINS_CATEGORY:
        return any(kw in name for kw in _GRAINS_SHELF_STABLE_KW)

    if item.category not in _SHELF_STABLE_CATEGORIES:
        return False

    # A fresh herb is perishable unless the name marks it as dried/ground.
    if any(kw in name for kw in _FRESH_HERB_KW):
        return any(m in name for m in _DRIED_MARKERS)

    return True


def is_pantry_item(item: CourseItem, recipe_count: int, total_g: float) -> bool:
    """Shelf-stable AND used often enough to be worth keeping in stock."""
    if not _is_shelf_stable(item):
        return False
    if recipe_count >= DEFAULT_MIN_RECIPES:
        return True
    return (
        item.category in _SPICE_CATEGORIES
        and recipe_count >= SPICE_MIN_RECIPES
        and total_g <= SPICE_MAX_TOTAL_G
    )


def plan_wide_usage(
    weeks: list[WeekSlice],
) -> dict[str, tuple[int, int, int, float, CourseItem]]:
    """Aggregate each ingredient across every week of the plan.

    Returns ``{canonical_name: (recipe_count, day_count, week_count,
    total_grams, exemplar_item)}``. Counts are of *distinct* recipes and days,
    taken from each item's ``source_recipes``, so an ingredient used twice in
    one recipe still counts once.
    """
    recipes: dict[str, set[str]] = defaultdict(set)
    days: dict[str, set[int]] = defaultdict(set)
    week_nums: dict[str, set[int]] = defaultdict(set)
    grams: dict[str, float] = defaultdict(float)
    exemplar: dict[str, CourseItem] = {}

    for week in weeks:
        for items in week.course_list.items_by_category.values():
            for item in items:
                key = item.canonical_name
                for src in item.source_recipes:
                    recipes[key].add(src.recipe_title)
                    days[key].add(src.day)
                week_nums[key].add(week.week_number)
                grams[key] += item.total_quantity_g
                # Keep the longest display name seen — the most informative one.
                prev = exemplar.get(key)
                if prev is None or len(item.display_name) > len(prev.display_name):
                    exemplar[key] = item

    return {
        key: (
            len(recipes[key]), len(days[key]), len(week_nums[key]),
            grams[key], exemplar[key],
        )
        for key in exemplar
    }


def build_pantry_list(weeks: list[WeekSlice]) -> PantryList:
    """Select the plan's pantry staples, grouped by shopping category."""
    usage = plan_wide_usage(weeks)

    by_category: dict[str, list[PantryItem]] = defaultdict(list)
    for key, (n_recipes, n_days, n_weeks, total_g, item) in usage.items():
        if not is_pantry_item(item, n_recipes, total_g):
            continue
        by_category[item.category].append(PantryItem(
            canonical_name=key,
            display_name=item.display_name,
            category=item.category,
            recipe_count=n_recipes,
            day_count=n_days,
            week_count=n_weeks,
            total_quantity_g=round(total_g, 1),
            total_quantity_display=format_quantity(total_g),
        ))

    # Most-used first inside each aisle — that is the order a reader stocks up in.
    for items in by_category.values():
        items.sort(key=lambda i: (-i.recipe_count, i.display_name.lower()))

    return PantryList(
        items_by_category=dict(sorted(by_category.items())),
        min_recipe_count=DEFAULT_MIN_RECIPES,
    )


def split_week_course_lists(weeks: list[WeekSlice], pantry: PantryList) -> list[WeekSlice]:
    """Move pantry staples out of each week's aisles into its pantry-check block.

    Returns new `WeekSlice` objects; the inputs are left untouched.
    """
    pantry_keys = {
        i.canonical_name
        for items in pantry.items_by_category.values()
        for i in items
    }
    if not pantry_keys:
        return weeks

    out: list[WeekSlice] = []
    for week in weeks:
        kept: dict[str, list[CourseItem]] = {}
        moved: list[CourseItem] = []
        for category, items in week.course_list.items_by_category.items():
            remaining = [i for i in items if i.canonical_name not in pantry_keys]
            moved.extend(i for i in items if i.canonical_name in pantry_keys)
            if remaining:
                kept[category] = remaining
        # Biggest quantities first: what actually needs re-buying floats up.
        moved.sort(key=lambda i: -i.total_quantity_g)
        out.append(week.model_copy(update={
            "course_list": week.course_list.model_copy(update={
                "items_by_category": kept,
                "pantry_items": moved,
            })
        }))
    return out

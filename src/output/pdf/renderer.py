"""Render a MealPlan + CourseList to a professionally designed PDF.

Uses Jinja2 for templating and WeasyPrint for the HTML→PDF conversion.
The template + stylesheet live under ``assets/`` next to this module.
"""
from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from src.constants import MEAL_TYPE_FOLDERS, MEAL_TYPE_LABELS, OPTIONAL_MEAL_TYPES
from src.models.meal_plan import MealPlan
from src.models.recipe import Recipe
from src.planning.meal_planner import core_day_averages
from src.planning.personalization import ACTIVITY_LABELS, SEX_LABELS

# Month names — avoid depending on system locale inside Docker.
_MONTHS = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}

# Recipe PNGs are 1024+ px and several MB each. In the PDF they render at
# ~9 mm (~35 px at 100 dpi) — so we downscale to a small JPEG once and cache.
_THUMB_SIZE = (160, 160)
_THUMB_QUALITY = 80
_THUMB_DIRNAME = ".thumbs"

# Larger thumbnails for recipe-book pages (~60 mm at 100 dpi).
_RECIPE_THUMB_SIZE = (400, 400)
_RECIPE_THUMB_DIRNAME = ".thumbs-recipe"


def render_to_pdf(
    plan: MealPlan,
    book_dir: Path,
    recipes_by_id: dict[str, Recipe],
) -> bytes:
    """Render the given plan (with per-week slices) into a single combined PDF.

    `book_dir` is the cookbook folder; it is used as the WeasyPrint base URL
    and to scope image-path validation. Course lists are pulled from
    `plan.weeks[i].course_list`.
    """
    from weasyprint import CSS, HTML  # imported lazily — heavy deps

    env = Environment(
        loader=PackageLoader("src.output.pdf", "assets"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("meal_plan.html.j2")

    context: dict[str, Any] = {
        "plan": plan,
        "manifest": plan.manifest,
        "meal_labels": MEAL_TYPE_LABELS,
        "activity_labels": ACTIVITY_LABELS,
        "sex_labels": SEX_LABELS,
        "generated_on": _format_date(plan.created_at),
        "image_urls": _build_image_map(plan, recipes_by_id, book_dir),
        "target_rows": _build_target_rows(plan),
        "optional_meals": OPTIONAL_MEAL_TYPES,
        "optional_labels": [
            MEAL_TYPE_LABELS[mt].lower()
            for mt in plan.manifest.meal_structure
            if mt in OPTIONAL_MEAL_TYPES
        ],
        "core_day": core_day_averages(plan),
    }

    html_str = template.render(**context)

    css_text = (files("src.output.pdf.assets") / "meal_plan.css").read_text(encoding="utf-8")

    return HTML(string=html_str, base_url=str(book_dir)).write_pdf(
        stylesheets=[CSS(string=css_text, base_url=str(_assets_dir()))]
    )


# ── helpers ──────────────────────────────────────────────────────

# Main meals — used to report protein per main meal on the calibration page.
_MAIN_MEALS = ("breakfast", "lunch", "dinner")


def _build_target_rows(plan: MealPlan) -> list[dict[str, str]]:
    """Rows for the calibration table: what the plan actually delivers per day,
    next to the guideline it is built against.

    Values are measured off the assembled plan (not restated from the spec) so
    the page stays honest if the recipe mix changes. Guideline column mirrors
    ``data/fatty_liver_diabetes_guidelines.yaml`` → ``daily_targets``.
    """
    avg = plan.avg_daily_nutrition
    kcal = avg.calories_kcal or 0.0

    def pct_kcal(grams: float | None, kcal_per_g: int) -> str:
        if not grams or kcal <= 0:
            return ""
        return f"{grams * kcal_per_g / kcal * 100:.0f}% of calories"

    # Protein per main meal, averaged over every breakfast/lunch/dinner slot.
    main_protein = [
        s.nutrition_per_serving.protein_g
        for day in plan.days
        for s in day.slots
        if s.meal_type in _MAIN_MEALS
    ]
    per_main = sum(main_protein) / len(main_protein) if main_protein else 0.0

    rows = [
        {
            "label": "Calories",
            "value": f"{kcal:,.0f} kcal/day",
            "note": "",
            "guideline": f"{plan.manifest.target_daily_kcal:,} kcal/day target for this plan",
        },
        {
            "label": "Protein",
            "value": f"{avg.protein_g:.0f} g/day",
            "note": pct_kcal(avg.protein_g, 4),
            "guideline": "1.6 g per kg bodyweight per day — preserves muscle in a deficit",
        },
        {
            "label": "Protein per main meal",
            "value": f"{per_main:.0f} g",
            "note": "",
            "guideline": "25-30 g — the muscle-building and fullness threshold",
        },
        {
            "label": "Fiber",
            "value": f"{avg.fiber_g:.0f} g/day",
            "note": "",
            "guideline": "28-38 g/day — FDA Daily Value is 28 g",
        },
    ]
    if avg.added_sugar_g is not None:
        rows.append({
            "label": "Added sugar",
            "value": f"{avg.added_sugar_g:.0f} g/day",
            "note": pct_kcal(avg.added_sugar_g, 4),
            "guideline": "Under 10% of calories",
        })
    if avg.saturated_fat_g is not None:
        rows.append({
            "label": "Saturated fat",
            "value": f"{avg.saturated_fat_g:.0f} g/day",
            "note": pct_kcal(avg.saturated_fat_g, 9),
            "guideline": "Under 10% of calories",
        })
    rows.append({
        "label": "Sodium",
        "value": f"{avg.sodium_mg:,.0f} mg/day",
        "note": "",
        "guideline": "Under 2,300 mg/day",
    })
    return rows


def _assets_dir() -> Path:
    """Filesystem directory backing the assets package (for CSS base_url)."""
    return Path(str(files("src.output.pdf.assets"))).resolve()


def _format_date(dt) -> str:
    return f"{_MONTHS[dt.month]} {dt.day}, {dt.year}"


def _build_image_map(
    plan: MealPlan,
    recipes_by_id: dict[str, Recipe],
    book_dir: Path,
) -> dict[str, str | None]:
    """Resolve each plan recipe_id → cached-thumbnail URL (or None).

    Logs a warning naming any recipes used in the plan that have no usable
    image — useful for spotting which ones to regenerate.
    """
    from rich.console import Console
    book_root = book_dir.resolve()
    thumb_dir = book_root / "MealPlan" / _THUMB_DIRNAME
    thumb_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str | None] = {}
    missing_titles: list[str] = []
    for day in plan.days:
        for slot in day.slots:
            if slot.recipe_id in result:
                continue
            recipe = recipes_by_id.get(slot.recipe_id)
            url = _resolve_thumbnail(recipe, book_root, thumb_dir)
            result[slot.recipe_id] = url
            if url is None:
                missing_titles.append(slot.recipe_title)

    if missing_titles:
        console = Console()
        console.print(
            f"[yellow]Missing images for {len(missing_titles)} plan recipe(s) "
            f"(cells with no thumbnail):[/yellow]"
        )
        for t in missing_titles:
            console.print(f"[yellow]  - {t}[/yellow]")

    return result


def _source_image(recipe: Recipe, book_root: Path) -> Path | None:
    """Locate a recipe's source image inside ``book_root``, or None.

    ``recipe.image_path`` is stored as an absolute path from the machine that
    generated the book, so it stops resolving as soon as the book is rendered
    somewhere else — a different checkout, or the Docker image (where a
    ``C:\\Users\\...`` path is neither absolute nor present). Fall back to
    matching the file *name* inside the cookbook's own ``<MealType>/IMG/``
    folders, which keeps books portable.
    """
    if not recipe.image_path:
        return None

    try:
        src = Path(recipe.image_path).resolve()
    except (OSError, ValueError):
        src = None
    if src is not None and src.is_file():
        # Path-traversal guard — original image must live inside the cookbook.
        try:
            src.relative_to(book_root)
        except ValueError:
            return None
        return src

    # Portable fallback: same basename under this book's own IMG folders.
    # Split on both separators — on POSIX, Path("C:\\a\\b.png").name is the
    # whole string, so Path.name alone would not recover the file name.
    name = re.split(r"[\\/]", str(recipe.image_path))[-1]
    if not name or name in (".", ".."):
        return None
    for folder in MEAL_TYPE_FOLDERS.values():
        candidate = book_root / folder / "IMG" / name
        if candidate.is_file():
            return candidate
    return None


def _resolve_thumbnail(
    recipe: Recipe | None,
    book_root: Path,
    thumb_dir: Path,
) -> str | None:
    """Return a file:// URL for a downscaled JPEG thumbnail (generate on miss)."""
    if recipe is None:
        return None
    src = _source_image(recipe, book_root)
    if src is None:
        return None

    thumb = thumb_dir / f"{recipe.id}.jpg"
    if not thumb.exists() or thumb.stat().st_mtime < src.stat().st_mtime:
        try:
            _make_thumbnail(src, thumb)
        except Exception:  # noqa: BLE001
            return None
    return thumb.as_uri()


def _make_thumbnail(src: Path, dst: Path, size: tuple[int, int] = _THUMB_SIZE) -> None:
    from PIL import Image

    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail(size, Image.Resampling.LANCZOS)
        im.save(dst, format="JPEG", quality=_THUMB_QUALITY, optimize=True)


# ── Recipe book PDF ────────────────────────────────────────────

def render_recipe_book_pdf(
    recipes: list[Recipe],
    book_dir: Path,
    section_title: str = "Desserts",
    book_name: str = "",
) -> bytes:
    """Render a list of recipes into a professionally designed PDF booklet."""
    from weasyprint import CSS, HTML

    env = Environment(
        loader=PackageLoader("src.output.pdf", "assets"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("recipe_book.html.j2")

    image_urls = _build_recipe_image_map(recipes, book_dir)

    context: dict[str, Any] = {
        "section_title": section_title,
        "book_name": book_name,
        "recipes": recipes,
        "image_urls": image_urls,
    }

    html_str = template.render(**context)
    css_text = (files("src.output.pdf.assets") / "recipe_book.css").read_text(encoding="utf-8")

    return HTML(string=html_str, base_url=str(book_dir)).write_pdf(
        stylesheets=[CSS(string=css_text, base_url=str(_assets_dir()))]
    )


def _build_recipe_image_map(
    recipes: list[Recipe],
    book_dir: Path,
) -> dict[str, str | None]:
    """Resolve each recipe.id → cached thumbnail URL for recipe-book pages."""
    from rich.console import Console

    book_root = book_dir.resolve()
    thumb_dir = book_root / "Export" / _RECIPE_THUMB_DIRNAME
    thumb_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, str | None] = {}
    missing_titles: list[str] = []

    for recipe in recipes:
        url = _resolve_recipe_thumbnail(recipe, book_root, thumb_dir)
        result[recipe.id] = url
        if url is None:
            missing_titles.append(recipe.title)

    if missing_titles:
        console = Console()
        console.print(
            f"[yellow]Missing images for {len(missing_titles)} recipe(s):[/yellow]"
        )
        for t in missing_titles:
            console.print(f"[yellow]  - {t}[/yellow]")

    return result


def _resolve_recipe_thumbnail(
    recipe: Recipe,
    book_root: Path,
    thumb_dir: Path,
) -> str | None:
    """Like _resolve_thumbnail but with larger size for recipe-book pages."""
    src = _source_image(recipe, book_root)
    if src is None:
        return None

    thumb = thumb_dir / f"{recipe.id}.jpg"
    if not thumb.exists() or thumb.stat().st_mtime < src.stat().st_mtime:
        try:
            _make_thumbnail(src, thumb, size=_RECIPE_THUMB_SIZE)
        except Exception:  # noqa: BLE001
            return None
    return thumb.as_uri()

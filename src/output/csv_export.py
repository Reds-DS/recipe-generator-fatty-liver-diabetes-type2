"""
Build an InDesign-safe tab-delimited TXT file from generated recipe .md files.
Reusable module — called from CLI or scripts/build_csv.py.

The .md files are produced by `src.output.formatter.to_markdown` (English,
FDA-Nutrition-Facts-style nutrition panel).
"""
import csv
import re
import unicodedata
import warnings
from pathlib import Path

# Sized to the 100 recipes actually in the book, re-measured 2026-08-18:
# ingredients run 5-13 (mean 9.6, median 10), instructions 3-7 (mean 6.3).
#
# INSTRUCTIONS: 7 is a real cap — src/llm/output_schemas.py DraftRecipe.instructions
# has max_length=7 and draft.py states it — and 0/100 recipes exceed it.
# INGREDIENTS ARE NOT CAPPED ANYWHERE. The schema allows 15, and the spec's
# `easy_recipe_constraints.max_ingredients: 10` is editorial only: no code reads it
# and it reaches the model just as "about 10 or fewer" in the IDEATION prompt, not
# the draft prompt. 26/100 recipes are already over it (20x11, 5x12, 1x13). This
# constant was 12, which would have SILENTLY DROPPED the 13th ingredient of
# "Spiced Beef, Herb, and Bulgur Salad Bowls" — a missing line in a printed book.
# Truncation here is silent by design (short lists pad with ""), so re-measure
# after any regeneration rather than trusting this number:
#   max(len(json.load(open(f))["ingredients"]) for f in <book>/*/JSON/*.json)
# A recipe that overflows now raises a warning in parse_recipe rather than
# vanishing quietly.
NUM_INGREDIENTS = 13
NUM_INSTRUCTIONS = 7

# Nutrition-panel labels (as they appear in the markdown table, with the
# leading `**`/`&nbsp;` stripped) → CSV column name. Keep the KEYS in sync with
# `_nutrition_lines()` in formatter.py: a key that stops matching the panel's
# wording yields a silently EMPTY column, not an error.
#
# The eight VALUES below are the layout's required set, named and ordered as the
# design asks for them. Column order here is merge-field order only — InDesign
# Data Merge places fields by NAME, so it does not constrain the printed panel,
# which keeps its own HERO SIX order in formatter.py (that order is the book's
# thesis and is not this file's business).
#
# Sodium is carried as a ninth column beyond the required eight, deliberately:
# every tier in this book has a hard per-serving sodium ceiling (550/500/250/150
# mg) and the canned-goods finding in CLAUDE.md makes it the axis most worth
# proofing on the page. Drop it only on an explicit editorial decision.
#
# There is no NetCarbs column: this book does not compute or print net carbs (no
# FDA definition; the ADA counts total carbohydrate). Do not "restore" it.
_NUTRITION_LABELS = {
    "calories": "Calories",
    "protein": "Protein",
    "dietary fiber": "Fiber",
    "total carbohydrate": "Carbs",
    "total fat": "TotalFat",
    "saturated fat": "SaturatedFat",
    "total sugars": "TotalSugars",
    "incl. added sugars": "AddedSugars",
    "sodium": "Sodium",
}
_NUTRITION_COLUMNS = list(dict.fromkeys(_NUTRITION_LABELS.values()))


def clean_field(value: str) -> str:
    """Clean text for safer InDesign Data Merge import."""
    if not value:
        return ""
    value = value.replace("**", "")
    value = value.replace("&nbsp;", " ")
    value = value.replace("\xa0", " ")
    value = value.replace(" ", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def safe_search(pattern: str, text: str, flags: int = 0, default: str = "") -> str:
    match = re.search(pattern, text, flags)
    return clean_field(match.group(1)) if match else default


def parse_bullet_list(section_text: str) -> list[str]:
    items = []
    for line in section_text.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            item = clean_field(stripped.lstrip("-").strip())
            if item:
                items.append(item)
    return items


def parse_numbered_list(section_text: str) -> list[str]:
    items = []
    for line in section_text.strip().splitlines():
        stripped = line.strip()
        if re.match(r"^\d+\.\s+", stripped):
            item = clean_field(re.sub(r"^\d+\.\s*", "", stripped))
            if item:
                items.append(item)
    return items


def parse_nutrition_table(text: str) -> dict[str, str]:
    """Pull the per-serving nutrition panel (a `| label | value |` Markdown table)."""
    result = {col: "" for col in _NUTRITION_COLUMNS}
    section = re.search(r"## Nutrition \(per serving\).*?\n((?:\|.*\n?)+)", text)
    if not section:
        return result
    for row in section.group(1).splitlines():
        cells = [clean_field(c) for c in row.strip().strip("|").split("|")]
        if len(cells) != 2:
            continue
        label = cells[0].lower().strip()
        # Strip a leading "of which " / "incl. " is kept (it's a key in the map).
        col = _NUTRITION_LABELS.get(label)
        if col and not result.get(col):
            result[col] = cells[1]
    return result


def parse_recipe(md_path: Path) -> dict:
    text = md_path.read_text(encoding="utf-8")

    title = safe_search(r"^# (.+)$", text, flags=re.M)
    introduction = safe_search(
        r"^# .+\n\n(?:!\[.*?\]\(.*?\)\n\n)?(.+?)\n\n## Details",
        text,
        flags=re.S,
    )
    prep = safe_search(r"\*\*Prep time:\*\*\s*(.+)", text)
    cook = safe_search(r"\*\*Cook time:\*\*\s*(.+)", text)

    ingr_section_match = re.search(
        r"## Ingredients\n(.*?)\n\n## Instructions", text, re.S
    )
    ingr_list = parse_bullet_list(ingr_section_match.group(1)) if ingr_section_match else []

    instr_section_match = re.search(
        r"## Instructions\n(.*?)\n\n##", text, re.S
    )
    instr_list = parse_numbered_list(instr_section_match.group(1)) if instr_section_match else []

    nutrition = parse_nutrition_table(text)

    variation = safe_search(r"## Variation\n(.+?)(?:\n\n|$)", text, flags=re.S)
    storage = safe_search(r"## Storage\n(.+?)(?:\n\n|$)", text, flags=re.S)

    row: dict[str, str] = {
        "Title": title,
        "Introduction": introduction,
        "Preparation_time": prep,
        "Cooking": cook,
        "Variation": variation,
        "Storage": storage,
        "@Image": str(md_path.parent.parent / "IMG" / (md_path.stem + ".png")),
    }
    for col in _NUTRITION_COLUMNS:
        row[col] = nutrition[col]

    # NEVER let a recipe lose a line to the column count — an ingredient that
    # falls off the end of the table is invisible in the laid-out page. Short
    # lists pad with "" (fine); long ones are shouted about (see the constants).
    for name, items, width in (
        ("ingredients", ingr_list, NUM_INGREDIENTS),
        ("instructions", instr_list, NUM_INSTRUCTIONS),
    ):
        if len(items) > width:
            warnings.warn(
                f"{md_path.name}: {len(items)} {name} but only {width} columns — "
                f"dropping {items[width:]}. Raise NUM_{name.upper()} in csv_export.py.",
                stacklevel=2,
            )

    for i in range(NUM_INGREDIENTS):
        row[f"Ingredient_{i + 1}"] = ingr_list[i] if i < len(ingr_list) else ""

    for i in range(NUM_INSTRUCTIONS):
        row[f"Instruction_{i + 1}"] = instr_list[i] if i < len(instr_list) else ""

    return row


def _slug(name: str) -> str:
    """ASCII, lowercase, underscores — for output file names."""
    ascii_only = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "_", ascii_only.lower()).strip("_") or "recipes"


def build_indesign_txt(
    source_dirs: list[Path],
    output_dir: Path,
    host_base_path: str = "",
) -> int:
    """Build tab-delimited exports from .md files, one file per meal type.

    Each file has 2 recipes per row with duplicated columns (suffixed _1 and _2).
    Recipes are paired sequentially within each meal type.
    If host_base_path is set, image paths are rewritten from the container /app/data
    prefix to the host filesystem path (e.g. C:\\Users\\...\\data).
    Returns total recipe count across all files.
    """
    base_headers = [
        "Title",
        "Introduction",
        "Preparation_time",
        "Cooking",
    ]
    base_headers += [f"Ingredient_{i + 1}" for i in range(NUM_INGREDIENTS)]
    base_headers += [f"Instruction_{i + 1}" for i in range(NUM_INSTRUCTIONS)]
    base_headers += ["Variation", "Storage"]
    base_headers += _NUTRITION_COLUMNS
    base_headers += ["@Image"]

    headers = [f"{h}_1" for h in base_headers] + [f"{h}_2" for h in base_headers]

    output_dir.mkdir(parents=True, exist_ok=True)
    total = 0

    for d in source_dirs:
        md_files = sorted(d.glob("*.md"))
        if not md_files:
            continue
        recipes = [parse_recipe(md) for md in md_files]
        if host_base_path:
            for r in recipes:
                r["@Image"] = r["@Image"].replace("/app/data", host_base_path).replace("/", "\\")
        total += len(recipes)

        # Pair recipes 2 by 2
        paired_rows: list[dict[str, str]] = []
        for i in range(0, len(recipes), 2):
            left = {f"{k}_1": v for k, v in recipes[i].items()}
            if i + 1 < len(recipes):
                right = {f"{k}_2": v for k, v in recipes[i + 1].items()}
            else:
                right = {f"{h}_2": "" for h in base_headers}
            paired_rows.append({**left, **right})

        # File name from meal-type folder (e.g. "Lunch" -> "lunch")
        safe_name = _slug(d.parent.name)
        file_path = output_dir / f"{safe_name}_indesign.txt"

        with open(file_path, "w", newline="", encoding="utf-16") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=headers,
                delimiter="\t",
                quoting=csv.QUOTE_MINIMAL,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(paired_rows)

        # Also write CSV (comma-separated, UTF-8)
        csv_path = output_dir / f"{safe_name}_indesign.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=headers,
                delimiter=";",
                quoting=csv.QUOTE_MINIMAL,
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(paired_rows)

    return total

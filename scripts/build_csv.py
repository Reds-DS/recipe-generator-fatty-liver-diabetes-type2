"""Build an InDesign-safe tab-delimited TXT file from generated recipe .md files.

Usage:
    python scripts/build_csv.py
"""
import csv
import pathlib
import re

DIR = pathlib.Path("data/generated_recipes")
NUM_INGREDIENTS = 13
NUM_INSTRUCTIONS = 6


def clean_field(value: str) -> str:
    """Clean text for safer InDesign Data Merge import."""
    if not value:
        return ""

    # Remove markdown bold markers
    value = value.replace("**", "")

    # Normalize common whitespace issues
    value = value.replace("\xa0", " ")  # non-breaking space
    value = value.replace("\u202f", " ")  # narrow no-break space

    # Collapse internal whitespace/newlines/tabs into single spaces
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def safe_search(pattern: str, text: str, flags: int = 0, default: str = "") -> str:
    """Return first regex group if found, otherwise default."""
    match = re.search(pattern, text, flags)
    return clean_field(match.group(1)) if match else default


def parse_bullet_list(section_text: str) -> list[str]:
    """Extract markdown bullet list items."""
    items = []
    for line in section_text.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            item = stripped.lstrip("-").strip()
            item = clean_field(item)
            if item:
                items.append(item)
    return items


def parse_numbered_list(section_text: str) -> list[str]:
    """Extract markdown numbered list items like '1. Text'."""
    items = []
    for line in section_text.strip().splitlines():
        stripped = line.strip()
        if re.match(r"^\d+\.\s+", stripped):
            item = re.sub(r"^\d+\.\s*", "", stripped)
            item = clean_field(item)
            if item:
                items.append(item)
    return items


def parse_nutrition_table(text: str) -> dict[str, str]:
    """Extract nutrition values from the markdown table."""
    result = {
        "Calories": "",
        "Proteine": "",
        "Glucides": "",
        "Sugar": "",
        "Lipides": "",
        "Fiber": "",
    }

    # Match first nutrition table body row after header/separator
    table_match = re.search(
        r"\| *Énergie.*?\n\|[-| :]+\n\|(.+?)\|(?:\n|$)",
        text,
        re.S
    )

    if not table_match:
        return result

    vals = [clean_field(v) for v in table_match.group(1).split("|")]

    if len(vals) >= 5:
        result["Calories"] = vals[0]
        result["Proteine"] = vals[1]
        result["Glucides"] = vals[2]
        result["Lipides"] = vals[3]
        result["Fiber"] = vals[4]

    if len(vals) > 6:
        result["Sugar"] = vals[6]

    return result


def parse_recipe(md_path: pathlib.Path) -> dict:
    text = md_path.read_text(encoding="utf-8")

    title = safe_search(r"^# (.+)$", text, flags=re.M)
    introduction = safe_search(
        r"^# .+\n\n(.+?)\n\n## Informations",
        text,
        flags=re.S
    )

    prep = safe_search(r"\*\*Préparation\s*:\*\*\s*(.+)", text)
    cook = safe_search(r"\*\*Cuisson\s*:\*\*\s*(.+)", text)
    temp = safe_search(r"\*\*Température\s*:\*\*\s*(.+)", text)

    ingr_section_match = re.search(
        r"## Ingrédients\n(.*?)\n\n## Préparation",
        text,
        re.S
    )
    ingr_section = ingr_section_match.group(1) if ingr_section_match else ""
    ingr_list = parse_bullet_list(ingr_section)

    instr_section_match = re.search(
        r"## Préparation\n(.*?)\n\n## Valeurs",
        text,
        re.S
    )
    instr_section = instr_section_match.group(1) if instr_section_match else ""
    instr_list = parse_numbered_list(instr_section)

    nutrition = parse_nutrition_table(text)

    row = {
        "Title": title,
        "Introduction": introduction,
        "Preparation_time": prep,
        "Cooking": cook,
        "Temperature": temp,
        "Calories": nutrition["Calories"],
        "Proteine": nutrition["Proteine"],
        "Glucides": nutrition["Glucides"],
        "Sugar": nutrition["Sugar"],
        "Lipides": nutrition["Lipides"],
        "Fiber": nutrition["Fiber"],
    }

    for i in range(NUM_INGREDIENTS):
        row[f"Ingredient_{i+1}"] = ingr_list[i] if i < len(ingr_list) else ""

    for i in range(NUM_INSTRUCTIONS):
        row[f"Instruction_{i+1}"] = instr_list[i] if i < len(instr_list) else ""

    return row


def build_indesign_txt():
    md_files = sorted(DIR.glob("*.md"))
    if not md_files:
        print(f"No .md recipe files found in {DIR}")
        return

    headers = [
        "Title",
        "Introduction",
        "Preparation_time",
        "Cooking",
        "Temperature",
    ]
    headers += [f"Ingredient_{i+1}" for i in range(NUM_INGREDIENTS)]
    headers += [f"Instruction_{i+1}" for i in range(NUM_INSTRUCTIONS)]
    headers += ["Calories", "Proteine", "Glucides", "Sugar", "Lipides", "Fiber"]

    rows = [parse_recipe(md) for md in md_files]

    out = DIR / "recipes_indesign.txt"

    # UTF-16 + tab delimiter is usually the safest for InDesign Data Merge
    with open(out, "w", newline="", encoding="utf-16") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=headers,
            delimiter="\t",
            quoting=csv.QUOTE_MINIMAL,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)

    print(f"Created {out} with {len(rows)} recipes.")
    for r in rows:
        n_ingr = sum(1 for i in range(NUM_INGREDIENTS) if r[f"Ingredient_{i+1}"])
        n_instr = sum(1 for i in range(NUM_INSTRUCTIONS) if r[f"Instruction_{i+1}"])
        print(
            f"  - {r['Title'][:60]}  |  {n_ingr} ingredients  |  {n_instr} instructions"
        )


if __name__ == "__main__":
    build_indesign_txt()
"""
Interactive review gate — pause after ideation so the user can pick which
proposed recipes to actually generate.

Flow:
  1. Pipeline writes a markdown checklist via `write_review_file()`.
  2. User edits the file (uncheck `[x]` → `[ ]` to skip a recipe), then runs
     `generate-resume {run_id}`.
  3. Resume command parses the file via `parse_review_file()` and applies
     decisions via `apply_review_decisions()`.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from src.models.recipe import RecipeBrief
from src.recipe_pipeline.batch_state import BatchRunState

SLOT_RE = re.compile(r"-\s*\[( |x|X)\].*\[slot:(\d+)\]")
RESUME_CMD = "docker compose run app generate-resume {run_id}"

MEAL_ORDER: tuple[str, ...] = ("breakfast", "lunch", "snack", "dinner", "dessert")
MEAL_TITLES: dict[str, str] = {
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "snack": "Snack",
    "dinner": "Dinner",
    "dessert": "Dessert",
}


def write_review_file(state: BatchRunState, state_dir: Path) -> Path:
    """Render the review markdown next to the state file."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / f"{state.run_id}_review.md"
    path.write_text(_render(state), encoding="utf-8")
    return path


def parse_review_file(path: Path) -> dict[int, bool]:
    """Return {slot_index: kept}. Lines without a `[slot:N]` marker are ignored.

    Missing slots (e.g. user deleted the line) are treated as skipped by
    `apply_review_decisions()`.
    """
    decisions: dict[int, bool] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = SLOT_RE.match(line.strip())
        if m:
            decisions[int(m.group(2))] = m.group(1).lower() == "x"
    return decisions


def apply_review_decisions(
    state: BatchRunState, decisions: dict[int, bool]
) -> tuple[int, int]:
    """Mutate state in-place. Returns (kept, skipped).

    Only slots with status="stage2" (post-ideation, pre-draft) are subject to
    review. Failed or otherwise-progressed slots are left alone.
    """
    kept = skipped = 0
    for slot in state.slots:
        if slot.status != "stage2":
            continue
        if decisions.get(slot.index, False):
            kept += 1
        else:
            slot.status = "skipped"
            skipped += 1
    state.review_applied = True
    state.pause_after_ideation = False
    return kept, skipped


def _render(state: BatchRunState) -> str:
    """Build the markdown review document."""
    lines: list[str] = []
    lines.append(f"# Review ideations — {state.run_id}")
    lines.append("")
    lines.append(f"- Run ID: `{state.run_id}`")
    lines.append(f"- Book: {state.book_name}")
    lines.append(f"- Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("Uncheck the recipes you want to reject (change `[x]` to `[ ]`).")
    lines.append("Keep the `[slot:N]` markers — they're used to identify the lines.")
    lines.append("Save the file, then run the command at the bottom.")
    lines.append("")

    # Group reviewable slots by meal type (only stage2 slots are reviewable)
    by_meal: dict[str, list] = {mt: [] for mt in MEAL_ORDER}
    for slot in state.slots:
        if slot.status != "stage2" or slot.brief_json is None:
            continue
        if slot.meal_type not in by_meal:
            by_meal[slot.meal_type] = []
        by_meal[slot.meal_type].append(slot)

    for mt in MEAL_ORDER:
        slots = by_meal.get(mt, [])
        if not slots:
            continue
        lines.append(f"## {MEAL_TITLES.get(mt, mt)}")
        lines.append("")
        for slot in slots:
            try:
                brief = RecipeBrief.model_validate_json(slot.brief_json)
                title = brief.title_candidate
                ing = brief.main_ingredient
                cuisine = brief.cuisine_style
                lines.append(f"- [x] {title} — {ing} ({cuisine}) [slot:{slot.index}]")
            except Exception as e:  # noqa: BLE001
                lines.append(f"- [x] (unreadable brief: {e}) [slot:{slot.index}]")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("```")
    lines.append(RESUME_CMD.format(run_id=state.run_id))
    lines.append("```")
    lines.append("")
    return "\n".join(lines)

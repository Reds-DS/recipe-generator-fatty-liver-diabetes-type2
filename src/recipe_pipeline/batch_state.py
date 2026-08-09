"""
Persistent state model for multi-recipe runs with pause/resume support
(used by the review-and-confirm gate). Class name is historical — this
module no longer carries any batch-API code.
Serialized to data/batch_state/{run_id}.json.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class RecipeSlot(BaseModel):
    """Tracks one recipe through the pipeline."""

    index: int
    meal_type: str
    chapter: str = "poultry_meat_dinners"  # book chapter / generation category (see RECIPE_CHAPTERS)
    main_ingredient: str | None = None
    cuisine_hint: str | None = None
    status: str = "pending"  # pending|stage2|done|failed|skipped

    # Serialized intermediate results
    brief_json: str | None = None
    draft_json: str | None = None
    nutrition_json: str | None = None
    recipe_json: str | None = None
    image_bytes_path: str | None = None  # path to temp PNG file on disk
    image_prompt: str | None = None
    rlog_json: str | None = None  # serialized RecipeLog

    # Retry tracking
    diversity_attempts: int = 0
    correction_attempts: int = 0
    critic_attempts: int = 0
    image_attempts: int = 0
    feedback: str = ""  # current retry feedback
    error: str | None = None


class BatchRunState(BaseModel):
    """Persisted state for the entire batch run."""

    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.now)
    book_name: str = "default"
    exclusions: list[str] = Field(default_factory=list)
    generate_image: bool = True
    current_wave: str = "init"
    pause_after_ideation: bool = False
    review_applied: bool = False
    slots: list[RecipeSlot] = Field(default_factory=list)

    def save(self, state_dir: Path) -> Path:
        """Serialize state to JSON file. Returns the file path."""
        state_dir.mkdir(parents=True, exist_ok=True)
        path = state_dir / f"{self.run_id}.json"
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, state_dir: Path, run_id: str) -> "BatchRunState":
        """Load state from JSON file."""
        path = state_dir / f"{run_id}.json"
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def slots_at_status(self, status: str) -> list[RecipeSlot]:
        """Return slots matching a specific status."""
        return [s for s in self.slots if s.status == status]

    def active_slots(self) -> list[RecipeSlot]:
        """Return slots that are not done, failed, or skipped."""
        return [s for s in self.slots if s.status not in ("done", "failed", "skipped")]

    def kept_slots(self) -> list[RecipeSlot]:
        """Return slots that have not been skipped via review."""
        return [s for s in self.slots if s.status != "skipped"]

    @classmethod
    def list_runs(cls, state_dir: Path) -> list[dict]:
        """List all saved batch runs with summary info."""
        runs = []
        if not state_dir.exists():
            return runs
        for path in sorted(state_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                total = len(data.get("slots", []))
                done = sum(1 for s in data.get("slots", []) if s.get("status") == "done")
                failed = sum(1 for s in data.get("slots", []) if s.get("status") == "failed")
                skipped = sum(1 for s in data.get("slots", []) if s.get("status") == "skipped")
                runs.append({
                    "run_id": data.get("run_id", path.stem),
                    "created_at": data.get("created_at", ""),
                    "book_name": data.get("book_name", ""),
                    "current_wave": data.get("current_wave", ""),
                    "total": total,
                    "done": done,
                    "failed": failed,
                    "skipped": skipped,
                    "in_progress": total - done - failed - skipped,
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return runs

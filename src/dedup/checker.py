"""
Deduplication checker — prevents generating near-duplicate recipes.
Uses SQLite fingerprint store.
"""
import hashlib
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from src.config import DEDUP_DB
from src.models.recipe import Recipe


@dataclass
class DedupResult:
    is_duplicate: bool
    reason: str = ""


@dataclass
class DiversityResult:
    is_diverse: bool
    reason: str = ""


@dataclass
class ExistingSummary:
    """Concise summary of existing recipes for injection into ideation prompt."""
    main_ingredients: Counter[str] = field(default_factory=Counter)
    cuisine_styles: Counter[str] = field(default_factory=Counter)
    titles: list[str] = field(default_factory=list)
    total: int = 0
    cross_meal_titles: list[str] = field(default_factory=list)
    cross_meal_ingredients: Counter[str] = field(default_factory=Counter)
    cross_meal_label: str = ""
    # Meal-type-scoped details (populated when meal_type is provided to get_existing_summary)
    same_meal_label: str = ""
    same_meal_titles: list[str] = field(default_factory=list)
    same_meal_main_ingredients: Counter[str] = field(default_factory=Counter)
    same_meal_techniques: Counter[str] = field(default_factory=Counter)

    def to_prompt_block(self) -> str:
        if self.total == 0:
            return ""
        lines = [
            f"\nRECIPES ALREADY IN THE BOOK ({self.total} recipes) — DIVERSITY REQUIRED:",
        ]
        if self.main_ingredients:
            top = self.main_ingredients.most_common(15)
            items = ", ".join(f"{name} ({n}x)" for name, n in top)
            lines.append(f"- Main ingredients already used: {items}")
        if self.cuisine_styles:
            top = self.cuisine_styles.most_common(10)
            items = ", ".join(f"{name} ({n}x)" for name, n in top)
            lines.append(f"- Cuisine styles already used: {items}")
        if self.titles:
            lines.append(f"- Titles of existing recipes: {', '.join(self.titles)}")
        lines.append(
            "You MUST propose a main ingredient DIFFERENT from the ones listed above. "
            "Favor variety in flavors, techniques, and cuisines."
        )
        return "\n".join(lines)

    def to_same_meal_block(self) -> str:
        """Prompt block highlighting recipes from the same meal type (stricter diversity)."""
        if not self.same_meal_titles:
            return ""
        lines = [
            f"\n{self.same_meal_label.upper()} RECIPES ALREADY IN THE BOOK "
            f"({len(self.same_meal_titles)}) — STRICTER DIVERSITY:",
        ]
        if self.same_meal_main_ingredients:
            items = ", ".join(
                f"{name} ({n}x)" for name, n in self.same_meal_main_ingredients.most_common(15)
            )
            lines.append(f"- {self.same_meal_label} main ingredients: {items}")
        if self.same_meal_techniques:
            items = ", ".join(
                f"{name} ({n}x)" for name, n in self.same_meal_techniques.most_common(15)
            )
            lines.append(f"- {self.same_meal_label} techniques/formats already used: {items}")
        lines.append(f"- {self.same_meal_label} titles: {', '.join(self.same_meal_titles)}")
        lines.append(
            f"For {self.same_meal_label}, you MUST propose a main ingredient AND a format "
            f"DIFFERENT from everything listed above — no repetition tolerated."
        )
        return "\n".join(lines)

    def to_cross_meal_block(self) -> str:
        """Prompt block highlighting recipes from the paired meal (lunch <-> dinner)."""
        if not self.cross_meal_titles:
            return ""
        lines = [
            f"\n{self.cross_meal_label.upper()} RECIPES ALREADY IN THE BOOK — DO NOT REPEAT:",
        ]
        if self.cross_meal_ingredients:
            items = ", ".join(
                f"{name} ({n}x)" for name, n in self.cross_meal_ingredients.most_common(10)
            )
            lines.append(f"- {self.cross_meal_label} main ingredients: {items}")
        lines.append(f"- {self.cross_meal_label} titles: {', '.join(self.cross_meal_titles)}")
        lines.append(
            f"You MUST NOT use the same main ingredient as a {self.cross_meal_label} recipe. "
            f"Lunch and dinner in the same book should be complementary, not redundant."
        )
        return "\n".join(lines)


def _get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or DEDUP_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recipes (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            ingredient_fingerprint TEXT NOT NULL,
            diet_tags TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS recipe_meta (
            id TEXT PRIMARY KEY,
            main_ingredient TEXT NOT NULL,
            cuisine_style TEXT NOT NULL DEFAULT '',
            ingredients_sketch TEXT NOT NULL DEFAULT '',
            meal_type TEXT NOT NULL DEFAULT ''
        )
    """)
    # Migration for existing DBs missing the meal_type column
    try:
        conn.execute("ALTER TABLE recipe_meta ADD COLUMN meal_type TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Migration for existing DBs missing the technique column
    try:
        conn.execute("ALTER TABLE recipe_meta ADD COLUMN technique TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    return conn


def _ingredient_fingerprint(recipe: Recipe) -> str:
    names = sorted(i.canonical_name.lower() for i in recipe.ingredients)
    return hashlib.sha256("|".join(names).encode()).hexdigest()


def _trigram_similarity(a: str, b: str) -> float:
    def trigrams(s: str) -> set[str]:
        s = s.lower()
        return {s[i:i+3] for i in range(len(s) - 2)}
    t_a, t_b = trigrams(a), trigrams(b)
    if not t_a or not t_b:
        return 0.0
    return len(t_a & t_b) / len(t_a | t_b)


def check(recipe: Recipe, db_path: Path | None = None) -> DedupResult:
    conn = _get_conn(db_path)
    fingerprint = _ingredient_fingerprint(recipe)
    diet_str = ",".join(sorted(recipe.diet_tags))

    # 1. Exact title match
    cur = conn.execute("SELECT id FROM recipes WHERE title = ?", (recipe.title,))
    if cur.fetchone():
        conn.close()
        return DedupResult(is_duplicate=True, reason=f"Identical title: '{recipe.title}'")

    # 2. Same ingredient fingerprint + same diet
    cur = conn.execute(
        "SELECT title FROM recipes WHERE ingredient_fingerprint = ? AND diet_tags = ?",
        (fingerprint, diet_str),
    )
    row = cur.fetchone()
    if row:
        conn.close()
        return DedupResult(
            is_duplicate=False,
            reason=f"Warning: ingredients similar to '{row[0]}' (same diet).",
        )

    # 3. Title trigram similarity
    cur = conn.execute("SELECT title FROM recipes WHERE diet_tags = ?", (diet_str,))
    for (existing_title,) in cur.fetchall():
        sim = _trigram_similarity(recipe.title, existing_title)
        if sim > 0.7:
            conn.close()
            return DedupResult(
                is_duplicate=False,
                reason=f"Warning: title similar to '{existing_title}' (similarity {sim:.0%}).",
            )

    conn.close()
    return DedupResult(is_duplicate=False)


CROSS_MEAL_PAIRS = {"lunch", "dinner"}

# Stricter thresholds for meal types with narrow ingredient vocabulary (e.g., desserts)
SAME_MEAL_OVERLAP_MAX = 0.40
SAME_MEAL_MAIN_INGREDIENT_MAX = 1  # ≥2 uses in the same meal type → reject

_MEAL_TYPE_LABELS = {
    "breakfast": "breakfast",
    "lunch": "lunch",
    "snack": "snack",
    "dinner": "dinner",
    "dessert": "dessert",
}


def get_existing_summary(db_path: Path | None = None, meal_type: str = "") -> ExistingSummary:
    """Build a concise summary of all existing recipes for diversity guidance.

    When meal_type is lunch or dinner, also populates cross-meal fields
    with recipes from the paired meal type.
    """
    conn = _get_conn(db_path)
    summary = ExistingSummary()

    cur = conn.execute("SELECT title FROM recipes")
    for (title,) in cur.fetchall():
        summary.titles.append(title)
    summary.total = len(summary.titles)

    cur = conn.execute("SELECT main_ingredient, cuisine_style FROM recipe_meta")
    for main_ing, style in cur.fetchall():
        summary.main_ingredients[main_ing.lower()] += 1
        if style:
            summary.cuisine_styles[style.lower()] += 1

    # Same-meal-type breakdown (for stricter diversity on categories like desserts)
    if meal_type:
        summary.same_meal_label = _MEAL_TYPE_LABELS.get(meal_type, meal_type)
        cur = conn.execute(
            """SELECT r.title, m.main_ingredient, m.technique
               FROM recipes r JOIN recipe_meta m ON r.id = m.id
               WHERE m.meal_type = ?""",
            (meal_type,),
        )
        for title, main_ing, technique in cur.fetchall():
            summary.same_meal_titles.append(title)
            if main_ing:
                summary.same_meal_main_ingredients[main_ing.lower()] += 1
            if technique:
                summary.same_meal_techniques[technique.lower()] += 1

    # Cross-meal awareness for lunch <-> dinner
    if meal_type in CROSS_MEAL_PAIRS:
        paired_meal = "lunch" if meal_type == "dinner" else "dinner"
        summary.cross_meal_label = paired_meal

        cur = conn.execute(
            """SELECT r.title, m.main_ingredient
               FROM recipes r JOIN recipe_meta m ON r.id = m.id
               WHERE m.meal_type = ?""",
            (paired_meal,),
        )
        for title, main_ing in cur.fetchall():
            summary.cross_meal_titles.append(title)
            summary.cross_meal_ingredients[main_ing.lower()] += 1

    conn.close()
    return summary


def check_diversity(
    main_ingredient: str,
    ingredients_sketch: list[str],
    db_path: Path | None = None,
) -> DiversityResult:
    """Check whether a proposed recipe idea is diverse enough vs existing recipes."""
    conn = _get_conn(db_path)

    # 1. Main ingredient already used 3+ times → not diverse
    cur = conn.execute(
        "SELECT COUNT(*) FROM recipe_meta WHERE LOWER(main_ingredient) = ?",
        (main_ingredient.lower(),),
    )
    count = cur.fetchone()[0]
    if count >= 3:
        conn.close()
        return DiversityResult(
            is_diverse=False,
            reason=f"'{main_ingredient}' already used {count} times. Propose a different main ingredient.",
        )

    # 2. Ingredient sketch overlap > 60% with any existing recipe
    sketch_set = {s.lower() for s in ingredients_sketch}
    cur = conn.execute("SELECT id, ingredients_sketch FROM recipe_meta")
    for _, existing_sketch_str in cur.fetchall():
        if not existing_sketch_str:
            continue
        existing_set = {s.strip().lower() for s in existing_sketch_str.split("|")}
        if not sketch_set or not existing_set:
            continue
        overlap = len(sketch_set & existing_set) / len(sketch_set | existing_set)
        if overlap > 0.6:
            conn.close()
            return DiversityResult(
                is_diverse=False,
                reason=f"Ingredients too similar to an existing recipe (similarity {overlap:.0%}). Propose different ingredients.",
            )

    conn.close()
    return DiversityResult(is_diverse=True)


def check_same_meal_diversity(
    main_ingredient: str,
    ingredients_sketch: list[str],
    technique: str,
    meal_type: str,
    db_path: Path | None = None,
) -> DiversityResult:
    """Stricter, meal-type-scoped diversity check.

    Rejects if, within the same meal type:
      • the main ingredient has already been used (≥1 prior use),
      • the technique/format has already been used,
      • or the ingredient sketch overlaps > 40% with any existing recipe.
    """
    conn = _get_conn(db_path)
    meal_label = _MEAL_TYPE_LABELS.get(meal_type, meal_type)

    cur = conn.execute(
        "SELECT COUNT(*) FROM recipe_meta WHERE LOWER(main_ingredient) = ? AND meal_type = ?",
        (main_ingredient.lower(), meal_type),
    )
    count = cur.fetchone()[0]
    if count > SAME_MEAL_MAIN_INGREDIENT_MAX:
        conn.close()
        return DiversityResult(
            is_diverse=False,
            reason=(
                f"'{main_ingredient}' already used {count} times for {meal_label}. "
                f"Propose a different main ingredient."
            ),
        )

    if technique:
        cur = conn.execute(
            "SELECT COUNT(*) FROM recipe_meta WHERE LOWER(technique) = ? AND meal_type = ?",
            (technique.lower(), meal_type),
        )
        tech_count = cur.fetchone()[0]
        if tech_count >= 1:
            conn.close()
            return DiversityResult(
                is_diverse=False,
                reason=(
                    f"Format/technique '{technique}' already used for {meal_label}. "
                    f"Propose a clearly different format."
                ),
            )

    sketch_set = {s.lower() for s in ingredients_sketch}
    cur = conn.execute(
        "SELECT ingredients_sketch FROM recipe_meta WHERE meal_type = ?",
        (meal_type,),
    )
    for (existing_sketch_str,) in cur.fetchall():
        if not existing_sketch_str:
            continue
        existing_set = {s.strip().lower() for s in existing_sketch_str.split("|")}
        if not sketch_set or not existing_set:
            continue
        overlap = len(sketch_set & existing_set) / len(sketch_set | existing_set)
        if overlap > SAME_MEAL_OVERLAP_MAX:
            conn.close()
            return DiversityResult(
                is_diverse=False,
                reason=(
                    f"Ingredients too similar to a {meal_label} recipe "
                    f"(similarity {overlap:.0%}). Propose a clearly different "
                    f"ingredient combination."
                ),
            )

    conn.close()
    return DiversityResult(is_diverse=True)


def check_cross_meal_diversity(
    main_ingredient: str,
    ingredients_sketch: list[str],
    meal_type: str,
    db_path: Path | None = None,
) -> DiversityResult:
    """Stricter diversity check against the paired meal type (lunch <-> dinner)."""
    if meal_type not in CROSS_MEAL_PAIRS:
        return DiversityResult(is_diverse=True)

    paired_meal = "lunch" if meal_type == "dinner" else "dinner"
    paired_label = paired_meal
    conn = _get_conn(db_path)

    # 1. Same main ingredient used even once in the paired meal → reject
    cur = conn.execute(
        "SELECT COUNT(*) FROM recipe_meta WHERE LOWER(main_ingredient) = ? AND meal_type = ?",
        (main_ingredient.lower(), paired_meal),
    )
    count = cur.fetchone()[0]
    if count >= 1:
        conn.close()
        return DiversityResult(
            is_diverse=False,
            reason=f"'{main_ingredient}' already used for {paired_label}. "
                   f"Choose a different main ingredient to avoid repetition across meals.",
        )

    # 2. Ingredient sketch Jaccard overlap > 40% with any paired-meal recipe
    sketch_set = {s.lower() for s in ingredients_sketch}
    cur = conn.execute(
        "SELECT ingredients_sketch FROM recipe_meta WHERE meal_type = ?",
        (paired_meal,),
    )
    for (existing_sketch_str,) in cur.fetchall():
        if not existing_sketch_str:
            continue
        existing_set = {s.strip().lower() for s in existing_sketch_str.split("|")}
        if not sketch_set or not existing_set:
            continue
        overlap = len(sketch_set & existing_set) / len(sketch_set | existing_set)
        if overlap > 0.40:
            conn.close()
            return DiversityResult(
                is_diverse=False,
                reason=f"Ingredients too similar to a {paired_label} recipe "
                       f"(similarity {overlap:.0%}). Propose clearly different ingredients.",
            )

    conn.close()
    return DiversityResult(is_diverse=True)


def register(recipe: Recipe, main_ingredient: str = "", cuisine_style: str = "",
             ingredients_sketch: list[str] | None = None, meal_type: str = "",
             technique: str = "", db_path: Path | None = None) -> None:
    """Add recipe to the dedup store after generation."""
    conn = _get_conn(db_path)
    conn.execute(
        "INSERT OR IGNORE INTO recipes (id, title, ingredient_fingerprint, diet_tags, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            recipe.id,
            recipe.title,
            _ingredient_fingerprint(recipe),
            ",".join(sorted(recipe.diet_tags)),
            recipe.created_at.isoformat(),
        ),
    )
    sketch_str = "|".join(ingredients_sketch) if ingredients_sketch else ""
    conn.execute(
        "INSERT OR IGNORE INTO recipe_meta "
        "(id, main_ingredient, cuisine_style, ingredients_sketch, meal_type, technique) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (recipe.id, main_ingredient, cuisine_style, sketch_str, meal_type, technique),
    )
    conn.commit()
    conn.close()

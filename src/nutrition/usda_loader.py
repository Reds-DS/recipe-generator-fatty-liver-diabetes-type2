"""
USDA FoodData Central — local SQLite food database + ingredient lookup.

Source: the FDC "Full Download" CSV bundle, unzipped into ``usda_source_data/``
(see ``src.config.USDA_SOURCE_DIR``). Only the *generic* foods are loaded —
Foundation Foods + SR Legacy + FNDDS (≈ 13.7 k foods); the ~2 M Branded
products are intentionally skipped (label-rounded values, noisy descriptions).

``build_db()`` streams the CSVs once and writes ``data/usda.db``: a wide
``food`` table carrying the per-100 g nutrition panel resolved per food (``NULL``
where USDA has no value — never a fake ``0``), an FTS5 index over the
description for keyword search (falls back to a normalized-LIKE matcher if FTS5
is unavailable), plus an ``alias`` table (in ``data/usda_alias.db``) that records
the LLM's chosen ``fdc_id`` per canonical ingredient name so picks stay
consistent across runs.

``lookup_candidates()`` returns a tiered shortlist: cooked-form matches for the
recipe's technique first, then any cooked form, then non-raw, then raw, then
progressively relaxed searches, then a head-noun catch-all.
"""
from __future__ import annotations

import csv
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config import USDA_ALIAS_DB, USDA_DB, USDA_SOURCE_DIR
from src.nutrition import qualifiers

# ── which FDC foods we load ────────────────────────────────────
USDA_DATA_TYPES: tuple[str, ...] = ("foundation_food", "sr_legacy_food", "survey_fndds_food")

# ── nutrient resolution ────────────────────────────────────────
# panel column → ordered USDA ``nutrient_id``s to coalesce (first present wins).
# ``calories_kcal`` and ``vitamin_d_mcg`` have extra derivations — see _resolve_row().
NUTRIENT_RESOLUTION: dict[str, tuple[int, ...]] = {
    "calories_kcal":   (1008, 2048, 2047),  # Energy → Atwater specific → Atwater general (else 4·P + 4·C + 9·fat)
    "protein_g":       (1003,),             # N × factor already applied by USDA
    "carbs_g":         (1005, 1050),         # carbohydrate by difference → by summation
    "fiber_g":         (1079, 2033),         # fiber, total dietary → AOAC 2011.25
    "total_sugar_g":   (2000, 1063),         # Total Sugars → Sugars, Total (NLEA)
    "total_fat_g":     (1004, 1085),         # Total lipid (fat) → Total fat (NLEA)
    "saturated_fat_g": (1258,),
    "mufa_g":          (1292,),
    "pufa_g":          (1293,),
    "trans_fat_g":     (1257,),               # sparse (~31 % of generic foods)
    "cholesterol_mg":  (1253,),
    "sodium_mg":       (1093,),
    "potassium_mg":    (1092,),
    "calcium_mg":      (1087,),
    "iron_mg":         (1089,),
    "vitamin_d_mcg":   (1114,),               # µg; else nutrient 1110 (IU) ÷ 40 — sparse (~78 %)
    "water_g":         (1051,),               # kept for sanity; not surfaced on NutritionInfo
}
_VIT_D_IU_ID = 1110

# every source nutrient_id we keep from food_nutrient.csv
ALL_SOURCE_NUTRIENT_IDS: frozenset[int] = frozenset(
    {nid for ids in NUTRIENT_RESOLUTION.values() for nid in ids} | {_VIT_D_IU_ID}
)

# the wide per-100 g columns, in order (matches the UsdaFood field order after the meta fields)
NUTRIENT_COLUMNS: tuple[str, ...] = tuple(NUTRIENT_RESOLUTION.keys())

# cooking technique → keywords that appear in USDA (English) descriptions
TECHNIQUE_TO_USDA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "oven":      ("roasted", "baked"),
    "grill":     ("grilled", "broiled", "roasted"),
    "pan_fry":   ("pan-fried", "pan fried", "sauteed", "cooked"),
    "steamed":   ("steamed", "cooked"),
    "boiled":    ("boiled", "simmered", "cooked"),
    "poached":   ("poached", "simmered", "cooked"),
    "air_fryer": ("roasted", "baked", "grilled"),  # legacy briefs still emit this
}
COOKED_KEYWORDS: tuple[str, ...] = (
    "cooked", "roasted", "baked", "grilled", "broiled", "boiled", "steamed",
    "braised", "pan-fried", "stewed", "simmered", "poached",
)

# words USDA descriptions usually omit — dropped during the *relaxation* tiers only.
# NOTE: salt words are deliberately absent. "unsalted"/"salted" are not noise — they pick
# out a different food with a different sodium basis, so dropping them during relaxation is
# how a no-salt-added request ends up matched to a salted record (see src/nutrition/qualifiers.py).
_NOISE_WORDS: frozenset[str] = frozenset({
    "raw", "fresh", "frozen", "canned", "dried", "drained", "cooked",
    "chopped", "sliced", "diced", "minced", "shredded", "grated", "ground",
    "peeled", "trimmed", "boneless", "skinless",
    "organic", "ripe", "large", "small", "medium", "whole", "pieces", "piece",
})
_STOPWORDS: frozenset[str] = frozenset({"and", "or", "of", "the", "a", "an", "with", "in"})
_NUMERIC_RE = re.compile(r"^\d+([.,]\d+)?%?$")
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class UsdaFood:
    fdc_id: int
    data_type: str
    description: str
    category: str | None
    # ── per-100 g panel (None where USDA carries no value) ──
    calories_kcal: float | None
    protein_g: float | None
    carbs_g: float | None
    fiber_g: float | None
    total_sugar_g: float | None
    total_fat_g: float | None
    saturated_fat_g: float | None
    mufa_g: float | None
    pufa_g: float | None
    trans_fat_g: float | None
    cholesterol_mg: float | None
    sodium_mg: float | None
    potassium_mg: float | None
    calcium_mg: float | None
    iron_mg: float | None
    vitamin_d_mcg: float | None
    water_g: float | None


# ── text normalization ─────────────────────────────────────────

def _fold(text: str) -> str:
    """Lowercase + fold accents: 'Crème Fraîche' → 'creme fraiche'."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if unicodedata.category(ch) != "Mn").lower()


def _normalize_text(text: str) -> str:
    """The ``description_norm`` / alias-key form: fold + collapse whitespace."""
    return " ".join(_fold(text).split())


def _tokens(name: str) -> list[str]:
    """Tokenize for search: fold, split on non-alphanumeric, drop stopwords /
    numerics / 1-char tokens, preserve order."""
    out: list[str] = []
    for t in _TOKEN_SPLIT_RE.split(_fold(name)):
        if not t or t in _STOPWORDS or _NUMERIC_RE.match(t) or len(t) < 2:
            continue
        out.append(t)
    return out


def _fts_query(tokens: list[str], *, prefix: bool = False) -> str:
    suffix = "*" if prefix else ""
    return " ".join(f'"{t}"{suffix}' for t in tokens)


# ── DB build ───────────────────────────────────────────────────

def _fts5_available() -> bool:
    try:
        c = sqlite3.connect(":memory:")
        c.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
        c.close()
        return True
    except sqlite3.OperationalError:
        return False


def _csv_map(path: Path, key_idx: int, val_idx: int) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if len(row) > max(key_idx, val_idx) and row[key_idx]:
                out[row[key_idx]] = row[val_idx]
    return out


def _resolve_row(nut: dict[int, float]) -> dict[str, float | None]:
    """Resolve a food's per-100 g panel from its raw ``{nutrient_id: amount}`` map."""
    out: dict[str, float | None] = {}
    for col, ids in NUTRIENT_RESOLUTION.items():
        out[col] = next((nut[nid] for nid in ids if nid in nut), None)
    if out["vitamin_d_mcg"] is None and _VIT_D_IU_ID in nut:
        out["vitamin_d_mcg"] = round(nut[_VIT_D_IU_ID] / 40.0, 4)
    if out["calories_kcal"] is None:
        p, c, fat = out["protein_g"], out["carbs_g"], out["total_fat_g"]
        if p is not None or c is not None or fat is not None:
            out["calories_kcal"] = round(4 * (p or 0) + 4 * (c or 0) + 9 * (fat or 0), 1)
    return out


def build_db() -> None:
    """Build ``data/usda.db`` from the FDC CSV bundle in ``USDA_SOURCE_DIR``."""
    src = USDA_SOURCE_DIR
    food_csv = src / "food.csv"
    fn_csv = src / "food_nutrient.csv"
    for required in (food_csv, fn_csv):
        if not required.exists():
            raise FileNotFoundError(
                f"USDA source file not found: {required}\n"
                "Download the FoodData Central 'Full Download' CSV bundle from "
                "https://fdc.nal.usda.gov/download-datasets and unzip it under "
                f"{src.parent}/ so that {src.name}/food.csv exists."
            )

    # 1. working set of generic foods
    print("Reading food.csv …", flush=True)
    foods: dict[int, tuple[str, str, str]] = {}  # fdc_id → (data_type, description, food_category_id)
    with open(food_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 4 or row[1] not in USDA_DATA_TYPES:
                continue
            try:
                fid = int(row[0])
            except ValueError:
                continue
            foods[fid] = (row[1], row[2], row[3])
    wanted = set(foods)
    print(f"  {len(wanted):,} generic foods (Foundation + SR Legacy + FNDDS)", flush=True)

    # 2. category maps
    food_cat = _csv_map(src / "food_category.csv", 0, 2)          # id → description (SR / Foundation)
    wweia_cat = _csv_map(src / "wweia_food_category.csv", 0, 1)   # code → description (FNDDS)
    fndds_wweia = _csv_map(src / "survey_fndds_food.csv", 0, 2)   # fdc_id(str) → WWEIA code

    def _category_for(fid: int, data_type: str, food_category_id: str) -> str | None:
        if data_type == "survey_fndds_food":
            return wweia_cat.get(fndds_wweia.get(str(fid), "")) or None
        return food_cat.get(food_category_id) or None

    # 3. stream food_nutrient.csv (1.7 GB / ~27 M rows)
    print("Reading food_nutrient.csv (large -- streaming) ...", flush=True)
    raw: dict[int, dict[int, float]] = {}
    n_seen = 0
    with open(fn_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            n_seen += 1
            if n_seen % 5_000_000 == 0:
                print(f"  {n_seen:,} rows …", flush=True)
            if len(row) < 4:
                continue
            try:
                fid = int(row[1])
            except ValueError:
                continue
            if fid not in wanted:
                continue
            try:
                nid = int(row[2])
            except ValueError:
                continue
            if nid not in ALL_SOURCE_NUTRIENT_IDS:
                continue
            amt = row[3].strip()
            if not amt:
                continue
            try:
                raw.setdefault(fid, {})[nid] = float(amt)
            except ValueError:
                continue
    print(f"  scanned {n_seen:,} rows; kept nutrients for {len(raw):,} foods", flush=True)

    # 4. resolve wide rows
    rows: list[tuple] = []
    for fid, (data_type, desc, fcid) in foods.items():
        resolved = _resolve_row(raw.get(fid, {}))
        rows.append((
            fid, data_type, desc, _normalize_text(desc), _category_for(fid, data_type, fcid),
            *(resolved[c] for c in NUTRIENT_COLUMNS),
        ))

    # 5. write the DB
    USDA_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USDA_DB)
    conn.execute("DROP TABLE IF EXISTS food")
    conn.execute("DROP TABLE IF EXISTS food_fts")
    col_defs = ", ".join(f"{c} REAL" for c in NUTRIENT_COLUMNS)
    conn.execute(f"""
        CREATE TABLE food (
            fdc_id           INTEGER PRIMARY KEY,
            data_type        TEXT NOT NULL,
            description      TEXT NOT NULL,
            description_norm TEXT NOT NULL,
            category         TEXT,
            {col_defs}
        )
    """)
    placeholders = ", ".join("?" for _ in range(5 + len(NUTRIENT_COLUMNS)))
    conn.executemany(f"INSERT INTO food VALUES ({placeholders})", rows)
    conn.execute("CREATE INDEX idx_food_desc_norm ON food(description_norm)")
    conn.execute("CREATE INDEX idx_food_data_type ON food(data_type)")

    has_fts = _fts5_available()
    if has_fts:
        conn.execute(
            "CREATE VIRTUAL TABLE food_fts USING fts5("
            "description, content='food', content_rowid='fdc_id', "
            "tokenize='porter unicode61 remove_diacritics 2')"
        )
        conn.execute("INSERT INTO food_fts(rowid, description) SELECT fdc_id, description FROM food")
    conn.commit()
    conn.close()
    print(
        f"USDA DB built: {len(rows):,} foods -> {USDA_DB}"
        + ("" if has_fts else "  (FTS5 unavailable -- using LIKE matcher)")
    )


# ── lookup ─────────────────────────────────────────────────────

_META_COLS = "f.fdc_id, f.data_type, f.description, f.category"


def _select_cols() -> str:
    return _META_COLS + ", " + ", ".join(f"f.{c}" for c in NUTRIENT_COLUMNS)


def _row_to_food(row: tuple) -> UsdaFood:
    vals = row[4:]
    return UsdaFood(
        fdc_id=int(row[0]),
        data_type=row[1],
        description=row[2],
        category=row[3],
        **{c: (float(vals[i]) if vals[i] is not None else None) for i, c in enumerate(NUTRIENT_COLUMNS)},
    )


def _get_conn() -> sqlite3.Connection:
    if not USDA_DB.exists():
        raise FileNotFoundError(
            f"USDA food DB not found at {USDA_DB}. Run: docker compose run app build-nutrition-db"
        )
    return sqlite3.connect(USDA_DB)


def _has_fts(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = 'food_fts'"
    ).fetchone() is not None


def lookup_candidates(name_en: str, technique: str = "", limit: int = 8) -> list[UsdaFood]:
    """Return up to ``limit`` USDA foods ranked by tier, then by description length.

    Tiers: (0) match + an unsalted marker, when the name asks for no-salt-added/low-sodium;
    then either (1r) match + "raw" when the name says raw, or (1) match + a cooked-form
    keyword for ``technique``, (2) match + any cooked-form keyword, (3) match + not "raw";
    (4) match (incl. raw); (5) relaxed — drop noise words, then trailing words, then
    prefix-match; (6) head-noun only. Duplicate ``fdc_id``s are removed, preserving tier order.

    Tiers 0 and 1r keep the *basis* qualifiers (salt, raw/cooked) at the top of the shortlist;
    Stage 4 enforces them deterministically afterwards via ``src.nutrition.qualifiers``.
    """
    toks = _tokens(name_en)
    if not toks:
        return []
    conn = _get_conn()
    try:
        fts = _has_fts(conn)
        select_cols = _select_cols()
        collected: list[tuple] = []
        seen: set[int] = set()

        def _extend(found: list[tuple]) -> None:
            for r in found:
                fid = int(r[0])
                if fid in seen:
                    continue
                seen.add(fid)
                collected.append(r)

        def _query(token_list: list[str], *, like_any: list[str] | None = None,
                   not_like: str | None = None, prefix: bool = False) -> list[tuple]:
            remaining = limit - len(collected)
            if not token_list or remaining <= 0:
                return []
            params: list = []
            if fts:
                sql = f"SELECT {select_cols} FROM food f JOIN food_fts ON food_fts.rowid = f.fdc_id WHERE food_fts MATCH ?"
                params.append(_fts_query(token_list, prefix=prefix))
            else:
                conds = " AND ".join("f.description_norm LIKE ?" for _ in token_list)
                sql = f"SELECT {select_cols} FROM food f WHERE {conds}"
                params.extend(f"%{t}%" for t in token_list)
            if like_any:
                sql += " AND (" + " OR ".join("f.description_norm LIKE ?" for _ in like_any) + ")"
                params.extend(f"%{kw}%" for kw in like_any)
            if not_like:
                sql += " AND f.description_norm NOT LIKE ?"
                params.append(f"%{not_like}%")
            sql += " ORDER BY length(f.description) LIMIT ?"
            params.append(remaining)
            try:
                return conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                return []

        tech_kw = list(TECHNIQUE_TO_USDA_KEYWORDS.get(technique, ())) if technique else []
        # An ingredient's stated grams are the weight as bought/added. When the name says
        # "raw", the cooked-form tiers below would actively rank the wrong basis first.
        wants_raw = qualifiers.state_polarity(name_en) == "raw"
        wants_unsalted = qualifiers.salt_polarity(name_en) == "unsalted"

        if wants_unsalted:                                            # 0 — salt-qualified
            _extend(_query(toks, like_any=list(qualifiers.UNSALTED_LIKE)))
        if wants_raw:
            _extend(_query(toks, like_any=["raw"]))                   # 1r — keep the raw basis
        else:
            if tech_kw:
                _extend(_query(toks, like_any=tech_kw))               # 1
            _extend(_query(toks, like_any=list(COOKED_KEYWORDS)))     # 2
            _extend(_query(toks, not_like="raw"))                     # 3
        _extend(_query(toks))                                         # 4
        if len(collected) < limit:                                    # 5 — relaxed
            core = [t for t in toks if t not in _NOISE_WORDS] or toks[:]
            if core != toks:
                _extend(_query(core))
            shrunk = core[:]
            while len(collected) < limit and len(shrunk) > 1:
                shrunk = shrunk[:-1]
                _extend(_query(shrunk))
            if len(collected) < limit:
                _extend(_query(core, prefix=True))
        if len(collected) < limit:                                    # 6 — head noun
            _extend(_query(toks[:1]))
            if len(collected) < limit:
                _extend(_query(toks[:1], prefix=True))

        return [_row_to_food(r) for r in collected[:limit]]
    finally:
        conn.close()


def fetch_by_id(fdc_id: int) -> UsdaFood | None:
    """Fetch a single USDA food by ``fdc_id`` (used by the alias cache + Stage 4)."""
    conn = _get_conn()
    try:
        row = conn.execute(
            f"SELECT {_select_cols()} FROM food f WHERE f.fdc_id = ?", (int(fdc_id),)
        ).fetchone()
        return _row_to_food(row) if row else None
    finally:
        conn.close()


# ── alias cache ────────────────────────────────────────────────
# Records the LLM's chosen fdc_id per canonical ingredient name so future lookups
# can short-circuit the matcher and keep picks consistent across runs.

def _alias_conn() -> sqlite3.Connection:
    USDA_ALIAS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(USDA_ALIAS_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alias (
            canonical_name TEXT PRIMARY KEY,
            fdc_id         INTEGER NOT NULL,
            first_seen     TEXT NOT NULL,
            last_seen      TEXT NOT NULL,
            hit_count      INTEGER NOT NULL DEFAULT 1
        )
    """)
    return conn


def _alias_key(canonical_name: str) -> str:
    return _normalize_text(canonical_name)


def get_alias(canonical_name: str) -> int | None:
    """Return the cached ``fdc_id`` for this canonical name, or ``None``."""
    key = _alias_key(canonical_name)
    if not key:
        return None
    conn = _alias_conn()
    try:
        row = conn.execute("SELECT fdc_id FROM alias WHERE canonical_name = ?", (key,)).fetchone()
        return int(row[0]) if row else None
    finally:
        conn.close()


def register_alias(canonical_name: str, fdc_id: int) -> None:
    """Record / refresh an alias. The first-stored ``fdc_id`` is kept stable; later
    hits just bump ``hit_count`` + ``last_seen``. No-ops on an empty name or a
    non-positive id."""
    key = _alias_key(canonical_name)
    if not key or fdc_id is None or int(fdc_id) <= 0:
        return
    now = datetime.now().isoformat(timespec="seconds")
    conn = _alias_conn()
    try:
        existing = conn.execute("SELECT fdc_id FROM alias WHERE canonical_name = ?", (key,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO alias (canonical_name, fdc_id, first_seen, last_seen, hit_count) VALUES (?, ?, ?, ?, 1)",
                (key, int(fdc_id), now, now),
            )
        else:
            conn.execute(
                "UPDATE alias SET last_seen = ?, hit_count = hit_count + 1 WHERE canonical_name = ?",
                (now, key),
            )
        conn.commit()
    finally:
        conn.close()

"""Per-cookbook SQLite cache for LLM-resolved ingredient name aliases.

Mirrors the food-DB alias cache in `src/nutrition/usda_loader.py`:
the LLM resolves ambiguous ingredient name clusters once, results are
persisted, subsequent runs read from the cache (deterministic + free).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CACHE_FILENAME = "aliases.db"


class AliasCache:
    """SQLite-backed mapping  raw_name → (canonical_key, canonical_display)."""

    def __init__(self, book_dir: Path) -> None:
        self.path = book_dir / CACHE_FILENAME

    # ── Connection management ──────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alias (
                raw_name           TEXT PRIMARY KEY,
                canonical_key      TEXT NOT NULL,
                canonical_display  TEXT,
                method             TEXT NOT NULL,
                first_seen         TEXT NOT NULL,
                last_seen          TEXT NOT NULL,
                hit_count          INTEGER NOT NULL DEFAULT 1
            )
        """)
        return conn

    # ── Public API ─────────────────────────────────────────

    def get(self, raw_name: str) -> tuple[str, str | None] | None:
        """Return (canonical_key, canonical_display) or None on miss."""
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT canonical_key, canonical_display FROM alias WHERE raw_name = ?",
                (raw_name,),
            ).fetchone()
            return (row[0], row[1]) if row else None
        finally:
            conn.close()

    def bulk_register(
        self,
        items: dict[str, tuple[str, str | None, str]],
    ) -> None:
        """UPSERT rows. items: { raw_name: (canonical_key, canonical_display, method) }."""
        if not items:
            return
        now = datetime.now().isoformat(timespec="seconds")
        conn = self._conn()
        try:
            for raw_name, (canonical_key, canonical_display, method) in items.items():
                conn.execute("""
                    INSERT INTO alias (
                        raw_name, canonical_key, canonical_display,
                        method, first_seen, last_seen, hit_count
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(raw_name) DO UPDATE SET
                        last_seen = excluded.last_seen,
                        hit_count = hit_count + 1
                """, (raw_name, canonical_key, canonical_display, method, now, now))
            conn.commit()
        finally:
            conn.close()

    def reset(self) -> None:
        """Drop and recreate the alias table."""
        conn = self._conn()
        try:
            conn.execute("DROP TABLE IF EXISTS alias")
            conn.commit()
        finally:
            conn.close()
        # Touch the file with a fresh schema.
        self._conn().close()


# ── Clustering ─────────────────────────────────────────────

def jaccard_clusters(
    raw_keys: list[str],
    threshold: float = 0.5,
) -> list[list[str]]:
    """Return clusters of raw_keys with token-set Jaccard similarity ≥ threshold.

    Connected components: if A~B and B~C, A and C land in the same cluster
    even if A and C alone don't pass the threshold. Singletons are dropped.
    """
    if len(raw_keys) < 2:
        return []

    tokens: list[set[str]] = [set(k.split()) for k in raw_keys]
    parent = list(range(len(raw_keys)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i in range(len(raw_keys)):
        for j in range(i + 1, len(raw_keys)):
            ti, tj = tokens[i], tokens[j]
            if not ti or not tj:
                continue
            inter = len(ti & tj)
            union_count = len(ti | tj)
            if union_count > 0 and inter / union_count >= threshold:
                union(i, j)

    groups: dict[int, list[str]] = defaultdict(list)
    for i, k in enumerate(raw_keys):
        groups[find(i)].append(k)

    return [sorted(g) for g in groups.values() if len(g) >= 2]

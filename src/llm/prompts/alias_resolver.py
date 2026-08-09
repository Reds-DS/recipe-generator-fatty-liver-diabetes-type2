"""Prompt builder for the shopping-list alias resolver.

Given clusters of look-alike ingredient display names, asks the LLM which
ones refer to the same grocery item and proposes a single canonical name
per group.
"""
from __future__ import annotations

SYSTEM = """You are an expert at US grocery shopping. You receive groups of
ingredient names that look alike (plural forms, synonyms, spelling or brand
variants).

For each group:
  1. Identify which names mean EXACTLY the same product you'd buy at the store.
  2. Keep genuinely different products separate:
       - "Lemon" ≠ "Lime"
       - "Cow's milk" ≠ "Almond milk"
       - "Tomato" ≠ "Cherry tomato"
       - "Chicken" ≠ "Turkey"
  3. For each subgroup, propose a short, readable canonical name (4 words max).
     Prefer the most natural name for a shopping list (e.g. "Plain soy yogurt"
     rather than "Yogurt, plain, soy").

If an input group contains several different products, split it into multiple
subgroups in the output.

Respond only with JSON, matching the provided schema."""


def build_user(
    clusters: list[list[str]],
    cookbook_objective: str,
    schema_json: str,
) -> str:
    """Render the user prompt with all clusters in one batched call."""
    parts: list[str] = []
    parts.append(f"Book context: {cookbook_objective}")
    parts.append("")
    parts.append(f"Groups to analyze ({len(clusters)} total):")
    parts.append("")

    for i, cluster in enumerate(clusters, start=1):
        parts.append(f"Group {i}:")
        for name in cluster:
            parts.append(f'  - "{name}"')
        parts.append("")

    parts.append("Expected JSON schema:")
    parts.append(schema_json)
    return "\n".join(parts)

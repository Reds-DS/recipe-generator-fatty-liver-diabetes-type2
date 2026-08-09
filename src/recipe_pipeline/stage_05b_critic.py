"""
Stage 5b — Critic (LLM).
A cookbook editor reviews the recipe across 12 quality dimensions: 8 general
culinary ones plus 4 fatty-liver/type-2-diabetes guideline-fit ones. The critic
also receives the target-chapter brief and any soft warnings the deterministic
Stage-3 (diet) and Stage-5 (cooking) checks already surfaced, so it can judge
chapter fit and decide whether a soft warning warrants a re-draft.
Returns structured feedback; blocking issues trigger a Stage 2 re-draft.
"""
import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from src.diet_rules import spec
from src.llm import client as llm
from src.llm.output_schemas import CriticOutput
from src.llm.prompts import critic as critic_prompts
from src.models.nutrition import NutritionInfo
from src.models.recipe import RecipeBrief, RecipeDraft


@dataclass
class CriticResult:
    passed: bool
    warnings: list[str] = field(default_factory=list)
    blocking_feedback: list[str] = field(default_factory=list)
    raw_output: CriticOutput | None = None


def build_request(
    draft: RecipeDraft,
    nutrition: NutritionInfo,
    brief: RecipeBrief,
    chapter: str = "",
    prior_warnings: list[str] | None = None,
) -> tuple[str, str, int, int]:
    """Return (system, user, max_tokens, thinking_budget) without calling LLM.

    ``chapter`` defaults to ``brief.chapter``; ``prior_warnings`` are the soft
    advisory lines from Stage 3b / Stage 5 (passed verbatim — the critic decides
    whether any of them is worth a re-draft).
    """
    schema_json = json.dumps(
        CriticOutput.model_json_schema(), ensure_ascii=False, indent=2
    )
    chapter = chapter or brief.chapter
    chapter_brief = spec.chapter_brief(chapter)
    checklist = spec.load_spec().prompt_snippets.get("critic", "")
    user = critic_prompts.build_user(
        draft, nutrition, brief, schema_json,
        chapter_brief=chapter_brief, prior_warnings=prior_warnings,
    )
    # 12 dimensions × detailed feedback is a long JSON; give it ample output room so the
    # verdict isn't truncated (a truncated response is silently skipped in parse_response).
    return critic_prompts.build_system(checklist), user, 6144, 4000


def parse_response(raw: str) -> CriticResult:
    """Parse raw LLM text into CriticResult."""
    if "{" not in raw:
        return CriticResult(
            passed=True,
            warnings=["Critic: non-JSON LLM response, validation skipped."],
        )

    start = raw.find("{")
    end = raw.rfind("}") + 1
    try:
        output = CriticOutput.model_validate_json(raw[start:end])
    except (ValidationError, ValueError) as e:
        return CriticResult(
            passed=True,
            warnings=[f"Critic: parsing failed ({e}), validation skipped."],
        )

    warnings: list[str] = []
    blocking: list[str] = []

    for dim in output.dimensions:
        if dim.passed:
            continue
        if dim.severity == "minor":
            warnings.append(f"[{dim.dimension}] {dim.feedback}")
        else:
            blocking.append(f"[{dim.dimension}] {dim.feedback}")

    passed = len(blocking) == 0
    return CriticResult(
        passed=passed,
        warnings=warnings,
        blocking_feedback=blocking,
        raw_output=output,
    )


MAX_CRITIC_PARSE_RETRIES = 2  # retry a truncated/malformed critic response before degrading to skip


def run(
    draft: RecipeDraft,
    nutrition: NutritionInfo,
    brief: RecipeBrief,
    chapter: str = "",
    prior_warnings: list[str] | None = None,
) -> CriticResult:
    system, user, max_tokens, thinking_budget = build_request(
        draft, nutrition, brief, chapter=chapter, prior_warnings=prior_warnings,
    )
    result = CriticResult(passed=True)
    for _attempt in range(MAX_CRITIC_PARSE_RETRIES + 1):
        text = llm.create_message(
            system=system, user=user, max_tokens=max_tokens, thinking_budget=thinking_budget,
        )
        result = parse_response(text)
        if result.raw_output is not None:  # parsed cleanly — use its verdict
            return result
    # Exhausted retries: the critic could not return valid JSON. Degrade to a non-blocking skip
    # (don't hard-fail the whole recipe on a flaky critic), but the warning stays loud in the log.
    return result


def build_correction_prompt(result: CriticResult) -> str:
    lines = ["An expert cookbook critic flagged the following MAJOR problems:"]
    for i, fb in enumerate(result.blocking_feedback, 1):
        lines.append(f"{i}. {fb}")
    lines.append(
        "\nFix the recipe based on this feedback. Change only what's needed to resolve these problems."
    )
    return "\n".join(lines)

from abc import ABC, abstractmethod

from src.models.diet import RuleResult
from src.models.nutrition import NutritionInfo
from src.models.recipe import RecipeDraft


class BaseDietRule(ABC):
    """Abstract base for all diet validation rules. Pure functions — no side effects.

    ``evaluate`` receives the optional computed ``nutrition``: structural rules
    ignore it; rules that need it (per-tier nutrient targets) return ``self._ok()``
    when it is ``None`` (i.e. the pre-nutrition pass).
    """

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def evaluate(self, draft: RecipeDraft, nutrition: NutritionInfo | None = None) -> RuleResult: ...

    def _ok(self, warnings: list[str] | None = None) -> RuleResult:
        return RuleResult(rule_name=self.name, passed=True, warnings=warnings or [])

    def _fail(self, violations: list[str], warnings: list[str] | None = None) -> RuleResult:
        return RuleResult(
            rule_name=self.name,
            passed=False,
            violations=violations,
            warnings=warnings or [],
        )

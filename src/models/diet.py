from pydantic import BaseModel


class RuleResult(BaseModel):
    rule_name: str
    passed: bool
    violations: list[str] = []
    warnings: list[str] = []


class DietValidationReport(BaseModel):
    diet: str
    overall_passed: bool
    rule_results: list[RuleResult]
    blocking_violations: list[str]
    warnings: list[str]

    @classmethod
    def from_results(cls, diet: str, results: list[RuleResult]) -> "DietValidationReport":
        blocking = [v for r in results for v in r.violations]
        warnings = [w for r in results for w in r.warnings]
        return cls(
            diet=diet,
            overall_passed=all(r.passed for r in results),
            rule_results=results,
            blocking_violations=blocking,
            warnings=warnings,
        )

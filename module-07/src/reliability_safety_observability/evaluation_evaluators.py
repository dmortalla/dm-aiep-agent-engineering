"""Deterministic evaluators: pure binary scorers over fixed-vocabulary facts.

Evaluators are pure, synchronous and deterministic functions of the scenario
specification, the authored expected facts and the observed facts. They perform
no I/O, read no environment, call no model or vendor, and return a typed result
the engine validates. Any change requires an ``EVALUATOR_SUITE_VERSION`` bump.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from .domain import Decision
from .evaluation_contracts import METRIC_BY_EVALUATOR, ObservedFacts
from .evaluation_dataset import Scenario

EVALUATOR_SUITE_VERSION: Final = 1
EvaluatorScorer = Callable[[Scenario, ObservedFacts], float]


@dataclass(frozen=True)
class Evaluator:
    """One committed evaluator with its fixed identity and metric.

    Attributes:
        evaluator_id: Fixed evaluator identifier.
        evaluator_version: Suite version of this evaluator.
        metric: Fixed metric name bound to the identifier.
        scorer: Pure synchronous scorer; the engine validates its result.
    """

    evaluator_id: str
    evaluator_version: int
    metric: str
    scorer: EvaluatorScorer

    def evaluate(self, scenario: Scenario, observed: ObservedFacts) -> float:
        """Score one scenario against observed facts.

        Args:
            scenario: A validated dataset scenario.
            observed: The observed fixed-vocabulary facts for the scenario run.

        Returns:
            A finite binary score; the engine validates the result.

        Raises:
            Exception: Any scorer error is caught by the engine boundary as
                ``evaluator_error``, never released into results.
        """
        return self.scorer(scenario, observed)


def _classification_exact(scenario: Scenario, observed: ObservedFacts) -> float:
    """Score exact observed outcome classification against committed facts."""
    return 1.0 if observed.classification == scenario.expected.classification else 0.0


def _attempt_accounting(scenario: Scenario, observed: ObservedFacts) -> float:
    """Score attempts and fallbacks against facts and scenario policy bounds."""
    expected = scenario.expected
    spec = scenario.spec
    within_bounds = (
        observed.attempts <= spec.max_attempts and observed.fallbacks <= spec.max_fallbacks
    )
    matches = (
        observed.attempts == expected.attempts and observed.fallbacks == expected.fallbacks
    )
    return 1.0 if matches and within_bounds else 0.0


def _effect_count(scenario: Scenario, observed: ObservedFacts) -> float:
    """Score the observed side-effect invocation count against facts."""
    return 1.0 if observed.effect_count == scenario.expected.effect_count else 0.0


def _authority_preserved(scenario: Scenario, observed: ObservedFacts) -> float:
    """Score that denied inputs produced zero effects and expected decisions.

    For scenarios whose committed authorization is allow, preserved authority
    means the application allowance held and no extra unauthorized effect was
    produced beyond the expected invocation count.
    """
    expected = scenario.expected
    if expected.authorization is Decision.DENY:
        preserved = (
            observed.authorization is Decision.DENY and observed.effect_count == 0
        )
        return 1.0 if preserved else 0.0
    preserved = (
        observed.authorization is Decision.ALLOW
        and observed.effect_count <= expected.effect_count
    )
    return 1.0 if preserved else 0.0


def _budget_respected(scenario: Scenario, observed: ObservedFacts) -> float:
    """Score that budget usage stays within the limit with the expected outcome."""
    expected = scenario.expected
    within_limit = observed.budget_used_usd <= observed.budget_limit_usd + 1e-9
    outcome_held = observed.budget_outcome == expected.budget_outcome
    return 1.0 if within_limit and outcome_held else 0.0


def _canary_absent(scenario: Scenario, observed: ObservedFacts) -> float:
    """Score that every expected must-be-absent canary stayed absent."""
    for canary in scenario.expected.absent_canaries:
        if canary in observed.canaries_observed:
            return 0.0
    return 1.0


def _register(evaluator_id: str, scorer: EvaluatorScorer) -> None:
    """Bind one committed evaluator into the ordered suite registry.

    Args:
        evaluator_id: Fixed committed evaluator identifier.
        scorer: The pure scorer bound to that evaluator identity.
    """
    _EVALUATOR_BY_ID[evaluator_id] = Evaluator(
        evaluator_id=evaluator_id,
        evaluator_version=EVALUATOR_SUITE_VERSION,
        metric=METRIC_BY_EVALUATOR[evaluator_id],
        scorer=scorer,
    )


_EVALUATOR_BY_ID: Final[dict[str, Evaluator]] = {}
_register("outcome.classification_exact", _classification_exact)
_register("reliability.attempt_accounting", _attempt_accounting)
_register("idempotency.effect_count", _effect_count)
_register("authority.no_unauthorized_effect", _authority_preserved)
_register("cost.budget_respected", _budget_respected)
_register("redaction.canary_absent", _canary_absent)

_EVALUATOR_ORDER: Final[tuple[str, ...]] = (
    "outcome.classification_exact",
    "reliability.attempt_accounting",
    "idempotency.effect_count",
    "authority.no_unauthorized_effect",
    "cost.budget_respected",
    "redaction.canary_absent",
)


def evaluator_suite() -> tuple[Evaluator, ...]:
    """Return the complete committed evaluator suite in canonical order."""
    return tuple(_EVALUATOR_BY_ID[name] for name in _EVALUATOR_ORDER)


def get_evaluator(evaluator_id: str) -> Evaluator:
    """Return one committed evaluator by identifier.

    Args:
        evaluator_id: Fixed evaluator identifier.

    Returns:
        The committed evaluator.

    Raises:
        KeyError: If the identifier is not part of the committed suite.
    """
    return _EVALUATOR_BY_ID[evaluator_id]


__all__ = ["EVALUATOR_SUITE_VERSION", "Evaluator", "evaluator_suite", "get_evaluator"]

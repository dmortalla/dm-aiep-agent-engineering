"""Explicit operational wrappers; accepted lifecycle/persistence still own semantics."""

from collections.abc import Callable

from harness_engineering.approval_lifecycle import SuspendedWorkflow
from harness_engineering.latency import Measurement, Outcome
from harness_engineering.observability import TelemetrySession
from harness_engineering.orchestration import (
    LifecycleInput,
    LifecyclePhase,
    LifecycleState,
    StepExecutor,
    StepResult,
)
from harness_engineering.planning import ExecutableSubtask


def observe_workflow(
    session: TelemetrySession,
    operation: Callable[[], LifecycleState | SuspendedWorkflow],
    *, resumed: bool = False,
) -> LifecycleState | SuspendedWorkflow:
    """Measure one invocation/segment, leaving critical observers inside operation.

    Args:
        session: Trusted application-owned telemetry segment.
        operation: Bound run, run_observed, checkpointed run, or HITL start/resume.
            Any persistence observer remains directly owned by that operation.
        resumed: Required True for resume invocations, so segment timing cannot
            receive an end-to-end workflow SLO assessment.

    Returns:
        The original lifecycle or suspension result. Suspension is never success.
        Resumed invocation duration is segment latency, not full end-to-end time.
    """
    def classify(result: LifecycleState | SuspendedWorkflow) -> Outcome:
        if type(result) is SuspendedWorkflow:
            SuspendedWorkflow.model_validate(result)
            return Outcome.SUSPENDED
        if type(result) is LifecycleState:
            checked = LifecycleState.model_validate(result)
            if checked.phase is LifecyclePhase.COMPLETED:
                return Outcome.SUCCEEDED
            if checked.phase is LifecyclePhase.SAFE_STOP:
                return Outcome.STOPPED
        # Do not turn an unsupported return into apparently successful evidence.
        return Outcome.REJECTED

    if type(resumed) is not bool:
        raise ValueError("Declare whether this application invocation is a resume segment.")
    return session.call(
        Measurement.SEGMENT if resumed else Measurement.WORKFLOW, operation, classify=classify,
    )


def observe_step(
    session: TelemetrySession, execute: StepExecutor, *, step_ids: tuple[str, ...],
) -> StepExecutor:
    """Wrap a trusted step callback without copying IDs, descriptions, or results.

    Bind the accepted scheduling order (at most 100 references). Events use only
    numeric ordinals. Callback return means RETURNED; runtime validation remains
    authoritative for step completion. Retries/fallback remain runtime decisions.
    """
    if (type(step_ids) is not tuple or not 1 <= len(step_ids) <= 100
            or any(type(item) is not str or not 1 <= len(item) <= 128 for item in step_ids)
            or len(set(step_ids)) != len(step_ids) or not callable(execute)):
        raise ValueError("Bind a callable step and finite accepted step order.")
    indices = {step_id: index for index, step_id in enumerate(step_ids, start=1)}

    def invoke(task: ExecutableSubtask, request: LifecycleInput) -> StepResult:
        # Unknown references are omitted, never retained as arbitrary labels.
        return session.call(
            Measurement.ACTION, lambda: execute(task, request),
            step_index=indices.get(task.task_id),
        )

    return invoke

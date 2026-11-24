"""Offline deterministic operations checker; authoritative logic lives in module10_ai.operations.

The CLI opens exactly one operator-supplied evidence file read-only, validates
it through the bounded fail-closed operations library, prints one
machine-readable JSON report, and exits 0 (validated), 1 (rejected evidence)
or 2 (usage error). It never performs network, cloud, subprocess or
privileged operations, and no accepted result constitutes authorization.
"""

import argparse
import json
import sys

from module10_ai.operations import (
    EvidenceError,
    checklist_report,
    cost_report,
    incident_report,
    load_evidence,
    rollback_plan_report,
    slo_report,
)

COMMANDS = {
    "checklist": (checklist_report, "ready"),
    "incident": (incident_report, "classified"),
    "rollback-plan": (rollback_plan_report, "validated"),
    "slo": (slo_report, "consistent"),
    "cost": (cost_report, "consistent"),
}


def main() -> None:
    """Run one bounded offline operations check and exit with its outcome."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=sorted(COMMANDS),
                        help="Which operations register to validate.")
    parser.add_argument("--evidence", required=True,
                        help="Exact path of one minimized JSON evidence file.")
    args = parser.parse_args()
    validator, accepted_status = COMMANDS[args.command]
    try:
        evidence = load_evidence(args.evidence)
    except EvidenceError as exc:
        print(json.dumps({"status": exc.status, "error": str(exc)}))
        raise SystemExit(1) from exc
    except (ValueError, RecursionError) as exc:
        print(json.dumps({"status": "malformed", "error": "The evidence file "
                          "could not be accepted for display."}))
        raise SystemExit(1) from exc
    report = validator(evidence)
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report.get("status") == accepted_status else 1)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        sys.exit(1)

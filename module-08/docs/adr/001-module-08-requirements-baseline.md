# ADR 001 - Module 8 Requirements Baseline

## Status

Accepted and frozen on 2026-10-12.

## Decision Authority

The human reviewer explicitly selected Option 1: approve all 33 proposed requirements unchanged.

The approved baseline contains 23 source-derived requirements and 10 additive engineering requirements, for 33 total requirements.

## Context

Module 8 is governed by the human-supplied MCP & Modern AI Infrastructure course screenshot as the ultimate source of truth.

The requirements derive the source objective, four topic groups, three hands-on labs, three named tools, and two deliverables while keeping additive production-grade engineering requirements explicitly separate.

Prior-module governance informs engineering method only. Prior-module implementation and module-specific requirements are not inherited by Module 8.

## Decision

1. Freeze the 23 source-derived requirements without modification.
2. Freeze the 10 additive engineering requirements without modification.
3. Preserve AUTHORITATIVE_SOURCE.md as controlling if any derived requirement conflicts with the original source.
4. Require explicit human approval for future changes to this frozen requirements baseline.
5. Proceed next to architecture research and architecture design; implementation remains premature until architecture is approved and frozen.
6. Preserve Module 8 as a standalone module with no implementation dependency on Modules 6.5 or 7.

## Verification Basis

- Source-derived requirements: 23 of 23 approved.
- Additive engineering requirements: 10 of 10 approved.
- Total requirements: 33 of 33 approved.
- Source topic groups represented: 4 of 4.
- Source hands-on labs represented: 3 of 3.
- Source-named technologies represented: 3 of 3.
- Source deliverables represented: 2 of 2.
- No Module 8 architecture or implementation existed at approval time.

## Consequences

Architecture must cover all 33 approved requirements.

Architecture may introduce additive implementation decisions only when they remain source-faithful, production-grade, cost-conscious, and consistent with repository governance.

Architecture must not silently inherit unrelated Module 6.5 or Module 7 technology or implementation choices.

# AGENTS.md

## Purpose

Repository-level policy for Codex and other compatible coding agents.

## Authority and precedence

Apply authority in this order:

1. Authoritative source requirements for the active module.
2. Explicit human-approved decisions and architecture records.
3. docs/ENGINEERING_SOP.md.
4. Module-local documentation and implementation conventions.

The engineering SOP may extend authoritative requirements but must never silently omit, replace, weaken, reinterpret, or contradict them.

## Repository scope

This repository contains Agentic AI Engineering Program Modules 6.5 through 10.

Each module is standalone. Work on one module must not modify, reuse, depend on, import, or otherwise couple itself to another module unless an authoritative source explicitly requires that relationship and the human approves it.

Prior repositories and modules may provide engineering lessons, governance patterns, and historical evidence. Their implementation files are not source material for new modules.

## Default project classification

Unless explicit human-approved documentation declares DEMO-ONLY, engineer toward production-grade quality and production readiness.

Passing tests, successful functionality, or a runnable UI alone does not establish production-grade completion.

## Mandatory policy

1. Preserve authoritative source fidelity and traceability.
2. Prefer the smallest sufficient architecture.
3. Establish architecture before substantial implementation.
4. Freeze approved architecture and reopen it only for a genuine design flaw, source conflict, or human-approved amendment.
5. Keep UI and presentation concerns separate from domain logic.
6. Provide an appropriate runnable and self-explanatory user or reviewer interface for each completed module.
7. Prefer genuine functionality where practical, secure, fiscally responsible, and source-faithful.
8. Keep deterministic, mocked, adapter, local-integration, live-provider, and deployment evidence explicitly distinct.
9. Treat external, model, tool, retrieved, MCP, memory, and agent output as untrusted until validated.
10. Never allow LLM or agent output to grant itself privileged application authority.
11. Enforce least privilege, explicit capability boundaries, and human approval where consequential authority requires it.
12. Never expose, commit, log, or unnecessarily propagate credentials or sensitive values.
13. Bound retries, loops, concurrency, latency, external calls, resource use, and cost exposure.
14. Credential presence alone must never authorize a paid or consequential external operation.
15. Do not weaken tests, security controls, requirements, quality gates, or acceptance criteria to obtain green status.
16. Make engineering and production claims only to the extent supported by current evidence.
17. Preserve standalone module boundaries.
18. Escalate genuine requirement, architecture, security, authority, release, or material-cost decisions to the human.
19. Do not block deterministic work on unnecessary approval after authority has already been granted.
20. Keep temporary engineering evidence outside the repository under the parent TECHADEMY/EVIDENCE directory.

## Python implementation standard

Use type hints throughout public interfaces and Google-style docstrings where appropriate.
Use intentional exception handling at real failure boundaries.
Preserve causal context with exception chaining where appropriate.
Provide specific actionable errors and test expected failure paths.
Avoid blanket exception swallowing.

## Quality gates

Use stronger module-specific gates when defined.

Otherwise use fail-fast:

1. ruff check .
2. pytest.
3. python -m compileall against the relevant source, application, and test directories.

A later passing gate never overrides an earlier failure.
Ruff safe fixes may be used mechanically. Never apply unsafe fixes automatically.
Self-repair must be bounded. After repair, rerun the failed gate and then the complete fail-fast sequence.

## Completion

Before recommending release or declaring a major milestone complete, explicitly evaluate:

Requirements -> Product Experience -> Real Functionality -> Reliability -> Security -> Cost -> Evidence -> Deployment

Functional completion may be reported separately from production-grade completion.

## Provider-neutral alignment

AGENTS.md and CLAUDE.md must remain semantically aligned on mandatory engineering policy.
Repeated procedures may move into provider-neutral SKILL.md workflows only when real repetition demonstrates that abstraction is useful.

# ADR-009-001: Module 9 Is Standalone and Source-Faithful

## Status

Accepted (human-approved, 2026-10-14)

## Context

The repository holds Modules 6.5 through 10. Repository policy requires each module to be
independently source-faithful and isolated. Earlier modules contain useful conventions but are not
Module 9 source material.

## Decision

Module 9 is a standalone Python project under `module-09/`. The authoritative Module 9 source is
the highest functional contract. Other modules may inspire engineering conventions, but their
implementation, tests, fixtures, configuration, and runtime state are not dependencies.

## Consequences

- `module-09` has its own `pyproject.toml`, package (`multimodal_voice_platform`), tests, and docs.
- No Module 9 code imports or copies another module's package. A governance test enforces this.
- Every source requirement is traced in `REQUIREMENTS.md` and `TRACEABILITY.md`. None may be
  omitted, weakened, reinterpreted, or claimed before evidence exists.

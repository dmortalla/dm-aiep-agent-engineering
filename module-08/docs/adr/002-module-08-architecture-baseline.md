# ADR 002 - Module 8 Architecture Baseline

## Status

Accepted and frozen on 2026-10-12.

## Decision Authority

The human reviewer approved the Module 8 architecture after detailed discussion of MCP interoperability, enterprise integration, Streamlit presentation, and reviewer-visible working-result requirements.

## Decision

1. Use MCP as the vendor-neutral enterprise capability plane.
2. Use the official MCP SDK for genuine MCP server/client behavior.
3. Use Streamable HTTP as the primary reviewer-visible MCP transport.
4. Give OpenAI SDK and Google ADK genuine integrations with the shared MCP capability plane.
5. Use the smallest sufficient local enterprise integrations for database, API, and internal-system capabilities.
6. Keep capability discovery distinct from application-owned execution authorization.
7. Use Streamlit as the unified reviewer, demonstration, and evidence presentation layer.
8. Require reviewer-visible real working results for material capabilities rather than declarations alone.
9. Keep authoritative business and security logic outside Streamlit.
10. Preserve deterministic zero-paid-call normal tests and reviewer demonstrations.
11. Classify evidence accurately and distinguish local/deterministic evidence from optional live-provider evidence.
12. Keep A2A bounded and complementary to MCP if implemented.
13. Preserve Module 8 isolation from other modules.

## Reviewer Evidence Decision

Recruiters and reviewers are expected users. The architecture therefore requires the unified presentation layer to expose real execution outputs and supporting evidence for material capabilities including database connectivity, API orchestration, internal-system integration, MCP discovery and invocation, heterogeneous agent integration, authorization behavior, and the interoperable workflow.

Tests and documentation alone do not satisfy this architectural requirement.

## Consequences

Implementation stories, traceability, acceptance tests, Definition of Done, and release evidence must preserve the reviewer-visible working-results invariant.

Material architecture changes require explicit human approval.

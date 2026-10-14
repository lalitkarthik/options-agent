# P1 traces go to Langfuse Cloud

Status: accepted (2026-10-14)

When the agent gets a question wrong, its full recording (tool calls, inputs, outputs, tokens) is needed to see why. Self-hosting Langfuse means running four databases beside the work.

**Decision.** P1 sends OpenTelemetry traces to Langfuse Cloud's free tier. Self-hosting moves to P4 as an infra exercise.

## Considered options

- Self-host now: rejected; database operations are not P1's subject.

## Consequences

- Traces leave the machine; questions and figures are not secret.
- Langfuse's Python SDK is v4; older examples use the v3 API.

## Why

*Lalit writes this section, in plain words, as part of ticket 10. Answer: what would you look for in a trace when an exam question fails?*

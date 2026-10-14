# The MCP server offers about seven high-level tools that serve engine figures

Status: accepted (2026-10-14)

The agent could be given many small tools (raw quotes, a forward fit, an IV solver) or a few that each return a finished set of engine figures. Anthropic's tool-writing guidance and the SWE-agent results both favour few, high-level tools with short outputs.

**Decision.** About seven tools, named verb_noun: `list_dates`, `list_expiries`, `get_chain`, `get_skew`, `get_realised_vol`, `get_implied_move`, `get_gamma_exposure`. Every result carries provenance, units and figure ids. A wrong input is a tool error listing the valid values; a figure that does not exist is a normal result saying so. `get_chain` output is capped. Tools are marked read-only and closed-world.

## Considered options

- Many low-level primitives the agent chains together: rejected; the agent would rebuild the engine's pipeline and make mistakes.

## Consequences

- Tool descriptions are prompt engineering and are written by Lalit (ticket 4).
- Comparisons such as the implied-realised gap come from tools, not from the agent's arithmetic.

## Why

*Lalit writes this section, in plain words, as part of ticket 4. Answer: why should the agent get finished figures instead of building blocks?*

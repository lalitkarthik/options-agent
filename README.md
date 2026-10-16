# options-agent

An agent that answers options questions in plain English (implied vs realised volatility, spread
pricing, stress scenarios) by calling MCP tools over frozen market data, scored by an eval
harness whose reference answers are computed by plain Python from the same data.

Run the MCP server over stdio, against the snapshots in `./snapshots` (or a folder given as its
argument):

```bash
uv run mcp-server
```

Status: in design. See [docs/roadmap.md](docs/roadmap.md).

import asyncio
import ssl
import sys
from dataclasses import dataclass, field
from typing import Any, Literal

from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient
from mcp import Client, StdioServerParameters

MODEL = "claude-sonnet-5-5"

# Claude Sonnet 5.5 prices, dollars per million tokens.
PRICE_INPUT = 2.00
PRICE_OUTPUT = 10.00
PRICE_CACHE_WRITE = 2.50
PRICE_CACHE_READ = 0.20

SYSTEM_PROMPT = """You answer questions about S&P 500 index options (SPXW) on a few frozen \
trading days. Every question is about 15:45 New York time on its day.

Use the tools to get every number; never estimate or compute one yourself. If a tool says a \
figure is missing, or the day is not in list_dates, say the question cannot be answered and \
why. In your answer give each number with its unit and the figure id the tool returned."""

SERVER = StdioServerParameters(command="uv", args=["run", "mcp-server"])

Stop = Literal[
    "answered",
    "refused",
    "max_tokens",
    "out_of_turns",
    "out_of_tokens",
    "out_of_money",
    "unexpected_stop",
]


@dataclass(frozen=True)
class Budget:
    turns: int = 12
    tokens: int = 300_000
    dollars: float = 0.50


@dataclass
class Spend:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, usage: Any) -> None:
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_input_tokens or 0
        self.cache_write_tokens += usage.cache_creation_input_tokens or 0

    @property
    def tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_read_tokens
            + self.cache_write_tokens
        )

    @property
    def dollars(self) -> float:
        return (
            self.input_tokens * PRICE_INPUT
            + self.output_tokens * PRICE_OUTPUT
            + self.cache_write_tokens * PRICE_CACHE_WRITE
            + self.cache_read_tokens * PRICE_CACHE_READ
        ) / 1_000_000


DEFAULT_BUDGET = Budget()


@dataclass
class Outcome:
    stop: Stop
    text: str
    turns: int
    spend: Spend
    messages: list = field(repr=False)


async def list_tools(mcp: Client) -> list[dict]:
    """The MCP server's tools as Messages API tool definitions, in the server's order."""
    result = await mcp.list_tools()
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in result.tools
    ]


async def run_tool(mcp: Client, call: Any) -> dict:
    """Call one tool and turn its result, or its error, into a tool_result block."""
    result = await mcp.call_tool(call.name, call.input)
    text = "\n".join(block.text for block in result.content if block.type == "text")
    return {
        "type": "tool_result",
        "tool_use_id": call.id,
        "content": text,
        "is_error": result.is_error,
    }


def final_text(response: Any) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text")


def check_stop(response: Any, spend: Spend, budget: Budget) -> Stop | None:
    """Why the run ends after this reply, or None to run the tools and carry on."""
    if response.stop_reason == "end_turn":
        return "answered"
    if response.stop_reason == "refusal":
        return "refused"
    if response.stop_reason == "max_tokens":
        return "max_tokens"
    if response.stop_reason != "tool_use":
        return "unexpected_stop"
    if spend.tokens > budget.tokens:
        return "out_of_tokens"
    if spend.dollars > budget.dollars:
        return "out_of_money"
    return None


async def run_agent(
    question: str,
    *,
    claude: AsyncAnthropic,
    mcp: Client,
    budget: Budget = DEFAULT_BUDGET,
) -> Outcome:
    """Question in, outcome out: loop until Claude stops calling tools or a budget runs out."""
    tools = await list_tools(mcp)
    system = [{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]
    messages: list = [{"role": "user", "content": question}]
    spend = Spend()

    for turns in range(1, budget.turns + 1):
        response = await claude.messages.create(
            model=MODEL,
            max_tokens=16_000,
            output_config={"effort": "medium"},
            system=system,
            tools=tools,
            messages=messages,
        )
        spend.add(response.usage)
        messages.append({"role": "assistant", "content": response.content})

        stop = check_stop(response, spend, budget)
        if stop is not None:
            text = final_text(response) if stop == "answered" else ""
            return Outcome(stop, text, turns, spend, messages)

        calls = [block for block in response.content if block.type == "tool_use"]
        results = await asyncio.gather(*(run_tool(mcp, call) for call in calls))
        messages.append({"role": "user", "content": results})

    return Outcome("out_of_turns", "", budget.turns, spend, messages)


async def ask(
    question: str, *, claude: AsyncAnthropic, server: StdioServerParameters = SERVER
) -> Outcome:
    """Start the MCP server over stdio, answer one question, and stop the server."""
    async with Client(server) as mcp:
        return await run_agent(question, claude=claude, mcp=mcp)


def main() -> None:
    """Answer the question given on the command line: uv run ask "..."."""
    question = " ".join(sys.argv[1:])
    # databento's pip-system-certs patches ssl on Windows, which sends httpx2's own
    # truststore context into endless recursion; a context from ssl itself works.
    http_client = DefaultAsyncHttpxClient(verify=ssl.create_default_context())
    outcome = asyncio.run(ask(question, claude=AsyncAnthropic(http_client=http_client)))
    spend = outcome.spend
    print(outcome.text)
    print(f"\n{outcome.stop} after {outcome.turns} turns, ${spend.dollars:.4f}")
    print(
        f"tokens: {spend.input_tokens} in, {spend.output_tokens} out, "
        f"{spend.cache_write_tokens} cache write, {spend.cache_read_tokens} cache read"
    )

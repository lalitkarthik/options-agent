import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import Message, TextBlock, ThinkingBlock, ToolUseBlock, Usage
from mcp import Client, StdioServerParameters

from options_agent.agent import SYSTEM_PROMPT, Budget, Spend, ask, run_agent
from options_agent.server import build_server

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"


class FakeMessages:
    """Stands in for claude.messages: replays scripted replies and records every request."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    async def create(self, **request):
        self.requests.append({**request, "messages": list(request["messages"])})
        return self.replies.pop(0)


def fake_claude(*replies):
    return SimpleNamespace(messages=FakeMessages(replies))


def reply(stop_reason, *content, usage=None):
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="claude-sonnet-5-5",
        content=list(content),
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=usage or Usage(input_tokens=100, output_tokens=20),
    )


def call(id, name, **input):
    return ToolUseBlock(type="tool_use", id=id, name=name, input=input)


async def test_a_tool_call_then_an_answer_runs_the_tool_and_returns_the_answer():
    claude = fake_claude(
        reply("tool_use", ToolUseBlock(type="tool_use", id="toolu_1", name="list_dates", input={})),
        reply("end_turn", TextBlock(type="text", text="One day: 2025-11-20.")),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days can you answer about?", claude=claude, mcp=mcp)

    assert outcome.stop == "answered"
    assert outcome.text == "One day: 2025-11-20."
    assert outcome.turns == 2
    first, second = claude.messages.requests
    assert [tool["name"] for tool in first["tools"]] == [
        "list_dates",
        "list_expiries",
        "get_chain",
        "get_skew",
        "get_realised_vol",
        "get_implied_move",
        "get_gamma_exposure",
    ]
    result = second["messages"][-1]["content"][0]
    assert result["tool_use_id"] == "toolu_1"
    assert result["is_error"] is False
    assert json.loads(result["content"])["dates"][0]["date"] == "2025-11-20"


async def test_parallel_tool_calls_go_back_together_in_one_message_in_call_order():
    claude = fake_claude(
        reply(
            "tool_use",
            call("toolu_1", "list_dates"),
            call("toolu_2", "list_expiries", date="2025-11-20"),
        ),
        reply("end_turn", TextBlock(type="text", text="One day, with its expiries.")),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        await run_agent("Which days and expiries?", claude=claude, mcp=mcp)

    question, assistant, tool_results = claude.messages.requests[1]["messages"]
    assert tool_results["role"] == "user"
    assert [result["tool_use_id"] for result in tool_results["content"]] == ["toolu_1", "toolu_2"]
    assert [result["is_error"] for result in tool_results["content"]] == [False, False]


async def test_a_tool_error_goes_back_to_claude_marked_as_an_error():
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "get_skew", date="2025-11-21", expiry="2025-11-21")),
        reply("end_turn", TextBlock(type="text", text="There is no snapshot for 2025-11-21.")),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("What is the skew on 2025-11-21?", claude=claude, mcp=mcp)

    assert outcome.stop == "answered"
    result = claude.messages.requests[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert result["content"] == (
        "Error executing tool get_skew: "
        "No snapshot for date 2025-11-21. Available dates: 2025-11-20."
    )


async def test_thinking_blocks_go_back_to_claude_unchanged():
    thinking = ThinkingBlock(type="thinking", thinking="", signature="sig-from-the-api")
    first = reply("tool_use", thinking, call("toolu_1", "list_dates"))
    claude = fake_claude(first, reply("end_turn", TextBlock(type="text", text="One day.")))
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        await run_agent("Which days?", claude=claude, mcp=mcp)

    assistant = claude.messages.requests[1]["messages"][1]
    assert assistant == {"role": "assistant", "content": first.content}
    assert assistant["content"][0] is thinking


@pytest.mark.parametrize(
    ("budget", "stop"),
    [
        (Budget(turns=1), "out_of_turns"),
        (Budget(tokens=50), "out_of_tokens"),
        (Budget(dollars=0.0001), "out_of_money"),
    ],
)
async def test_the_loop_stops_when_a_budget_runs_out(budget, stop):
    claude = fake_claude(*[reply("tool_use", call("toolu_1", "list_dates"))] * 3)
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp, budget=budget)

    assert outcome.stop == stop
    assert outcome.turns == 1
    assert len(claude.messages.requests) == 1


@pytest.mark.parametrize(
    ("stop_reason", "stop"),
    [("refusal", "refused"), ("max_tokens", "max_tokens"), ("pause_turn", "unexpected_stop")],
)
async def test_a_stop_reason_other_than_tool_use_or_end_turn_ends_the_run(stop_reason, stop):
    claude = fake_claude(reply(stop_reason, TextBlock(type="text", text="Partial")))
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp)

    assert outcome.stop == stop
    assert outcome.text == ""
    assert outcome.turns == 1


async def test_spend_adds_up_the_usage_of_every_turn_and_prices_it():
    claude = fake_claude(
        reply(
            "tool_use",
            call("toolu_1", "list_dates"),
            usage=Usage(input_tokens=1_000, output_tokens=200, cache_creation_input_tokens=3_000),
        ),
        reply(
            "end_turn",
            TextBlock(type="text", text="One day."),
            usage=Usage(input_tokens=500, output_tokens=100, cache_read_input_tokens=3_000),
        ),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        outcome = await run_agent("Which days?", claude=claude, mcp=mcp)

    assert outcome.spend == Spend(
        input_tokens=1_500, output_tokens=300, cache_read_tokens=3_000, cache_write_tokens=3_000
    )
    assert outcome.spend.tokens == 7_800
    assert outcome.spend.dollars == pytest.approx(0.0141)


async def test_the_tool_list_and_system_prompt_are_cached_and_the_same_every_turn():
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "list_dates")),
        reply("end_turn", TextBlock(type="text", text="One day.")),
    )
    async with Client(build_server(FIXTURES), raise_exceptions=True) as mcp:
        await run_agent("Which days?", claude=claude, mcp=mcp)

    first, second = claude.messages.requests
    assert first["system"] == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    assert second["system"] == first["system"]
    assert second["tools"] == first["tools"]


async def test_ask_starts_the_mcp_server_over_stdio_and_answers():
    claude = fake_claude(
        reply("tool_use", call("toolu_1", "list_dates")),
        reply("end_turn", TextBlock(type="text", text="One day: 2025-11-20.")),
    )
    server = StdioServerParameters(command="uv", args=["run", "mcp-server", str(FIXTURES)])

    outcome = await ask("Which days?", claude=claude, server=server)

    assert outcome.stop == "answered"
    result = claude.messages.requests[1]["messages"][-1]["content"][0]
    assert json.loads(result["content"])["dates"][0]["date"] == "2025-11-20"

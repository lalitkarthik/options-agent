from pathlib import Path

import pytest
from mcp import Client

from options_agent.server import build_server

pytestmark = pytest.mark.anyio

FIXTURES = Path(__file__).parent / "fixtures" / "snapshots"


async def test_list_dates_returns_each_day_with_provenance():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("list_dates")

    assert result.is_error is False
    assert result.structured_content == {
        "dates": [
            {
                "date": "2025-11-20",
                "snapshot": "2025-11-20.json",
                "as_of": "2025-11-20T15:45:00-05:00",
                "engine_commit": "345539eaef2caee1fd94d773d2eefe71de33ac9a",
            }
        ]
    }


async def test_get_skew_for_a_day_with_no_snapshot_is_a_tool_error_listing_the_valid_dates():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-21", "expiry": "2025-11-21"})

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool get_skew: "
        "No snapshot for date 2025-11-21. Available dates: 2025-11-20."
    )


async def test_get_skew_returns_each_figure_with_its_unit_and_id_and_the_provenance():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-20", "expiry": "2025-11-20"})

    skew = result.structured_content
    figures = {figure["id"]: figure for figure in skew["figures"]}
    assert result.is_error is False
    assert skew["snapshot"] == "2025-11-20.json"
    assert skew["as_of"] == "2025-11-20T15:45:00-05:00"
    assert skew["engine_commit"] == "345539eaef2caee1fd94d773d2eefe71de33ac9a"
    assert figures["skew:2025-11-20:2025-11-20:atm_iv"] == {
        "id": "skew:2025-11-20:2025-11-20:atm_iv",
        "value": 0.2415,
        "unit": "decimal_vol",
    }
    assert figures["skew:2025-11-20:2025-11-20:put_25_strike"]["unit"] == "index_points"
    risk_reversal = figures["skew:2025-11-20:2025-11-20:risk_reversal_25"]
    assert risk_reversal["unit"] == "vol_points"
    assert risk_reversal["value"] == pytest.approx(-0.8)


async def test_get_skew_lists_a_point_the_engine_could_not_compute_as_missing():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-20", "expiry": "2025-11-20"})

    skew = result.structured_content
    ids = [figure["id"] for figure in skew["figures"]]
    assert result.is_error is False
    assert "skew:2025-11-20:2025-11-20:put_10_iv" in ids
    assert "skew:2025-11-20:2025-11-20:call_10_iv" not in ids
    assert skew["missing"] == [
        "skew:2025-11-20:2025-11-20:call_10_iv",
        "skew:2025-11-20:2025-11-20:call_10_strike",
        "skew:2025-11-20:2025-11-20:call_10_skew",
        "skew:2025-11-20:2025-11-20:risk_reversal_10",
        "skew:2025-11-20:2025-11-20:butterfly_10",
    ]


async def test_get_skew_for_an_unknown_expiry_is_a_tool_error_listing_the_valid_expiries():
    async with Client(build_server(FIXTURES), raise_exceptions=True) as client:
        result = await client.call_tool("get_skew", {"date": "2025-11-20", "expiry": "2025-11-21"})

    assert result.is_error is True
    assert result.content[0].text == (
        "Error executing tool get_skew: "
        "No expiry 2025-11-21 on 2025-11-20. Available expiries: 2025-11-20."
    )

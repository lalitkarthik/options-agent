import json
from pathlib import Path
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)

Unit = Literal["decimal_vol", "vol_points", "index_points"]


class SnapshotDate(BaseModel):
    date: str
    snapshot: str
    as_of: str
    engine_commit: str


class DateList(BaseModel):
    dates: list[SnapshotDate]


class Figure(BaseModel):
    id: str
    value: float
    unit: Unit


class Skew(BaseModel):
    date: str
    expiry: str
    snapshot: str
    as_of: str
    engine_commit: str
    figures: list[Figure]
    missing: list[str]


def load_snapshots(snapshot_dir: Path) -> dict[str, dict]:
    """Read every snapshot file in the folder, keyed by its day, in date order."""
    snapshots = {}
    for path in sorted(snapshot_dir.glob("*.json")):
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["file"] = path.name
        snapshots[snapshot["day"]] = snapshot
    return snapshots


def to_vol_points(value: float | None) -> float | None:
    """Turn a decimal volatility difference (0.008) into vol points (0.8)."""
    return None if value is None else value * 100


def build_server(snapshot_dir: Path) -> MCPServer:
    server = MCPServer("options-agent")

    @server.tool(annotations=READ_ONLY)
    def list_dates() -> DateList:
        """List the snapshot days the other tools can answer about.

        Each day comes with its provenance: the snapshot file, the as-of time (15:45 New York,
        with its UTC offset) and the engine commit that built it. Call this first to find a
        valid `date` for the other tools.
        """
        dates = [
            SnapshotDate(
                date=day,
                snapshot=snapshot["file"],
                as_of=snapshot["as_of"],
                engine_commit=snapshot["engine_commit"],
            )
            for day, snapshot in load_snapshots(snapshot_dir).items()
        ]
        return DateList(dates=dates)

    @server.tool(annotations=READ_ONLY)
    def get_skew(date: str, expiry: str) -> Skew:
        """Get one expiry's skew figures on one snapshot day, as of 15:45 New York.

        `date` is a snapshot day from list_dates; `expiry` is one of that day's expiries, both
        as YYYY-MM-DD. Returns the forward, the ATM implied volatility, and at the 25, 10, 5
        and 1 delta points the put and call IV, their strikes, each side's skew against ATM,
        the risk reversal (call IV minus put IV) and the butterfly. Delta is forward delta.
        IVs are yearly decimals (0.2415 is 24.15%); skews, risk reversals and butterflies are
        in vol points; the forward and strikes are in index points. A figure the engine could
        not compute is listed in `missing` by its id instead of being returned.
        """
        snapshots = load_snapshots(snapshot_dir)
        if date not in snapshots:
            available = ", ".join(snapshots)
            raise ToolError(f"No snapshot for date {date}. Available dates: {available}.")
        snapshot = snapshots[date]

        skews = {skew["expiry"]: skew for skew in snapshot["skews"]}
        if expiry not in skews:
            available = ", ".join(sorted(skews))
            raise ToolError(f"No expiry {expiry} on {date}. Available expiries: {available}.")
        skew = skews[expiry]

        figures = []
        missing = []

        def add(name: str, value: float | None, unit: Unit) -> None:
            figure_id = f"skew:{date}:{expiry}:{name}"
            if value is None:
                missing.append(figure_id)
            else:
                figures.append(Figure(id=figure_id, value=value, unit=unit))

        add("forward", skew["forward"], "index_points")
        add("atm_iv", skew["atm_iv"], "decimal_vol")
        for point in skew["points"]:
            delta = point["delta"]
            for side in ("put", "call"):
                add(f"{side}_{delta}_iv", point[f"{side}_iv"], "decimal_vol")
                add(f"{side}_{delta}_strike", point[f"{side}_strike"], "index_points")
                add(f"{side}_{delta}_skew", to_vol_points(point[f"{side}_skew"]), "vol_points")
            add(f"risk_reversal_{delta}", to_vol_points(point["risk_reversal"]), "vol_points")
            add(f"butterfly_{delta}", to_vol_points(point["butterfly"]), "vol_points")

        return Skew(
            date=date,
            expiry=expiry,
            snapshot=snapshot["file"],
            as_of=snapshot["as_of"],
            engine_commit=snapshot["engine_commit"],
            figures=figures,
            missing=missing,
        )

    return server

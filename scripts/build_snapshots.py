"""Build one snapshot per snapshot day: the engine's own figures at 15:45 New York time.

Nothing here computes a figure: the engine replays the day's Databento files and its
published messages are saved as they are; realised volatility comes from the engine's own
functions over the index candles (decisions 0001 and 0002).

Runs inside the engine's environment, which needs Python 3.12:

    uv run --project "$ENGINE_DIR" python scripts/build_snapshots.py

ENGINE_DIR   a plain copy of the engine at the commit used, with that commit in a COMMIT file:
                 git -C <engine repo> archive origin/main | tar -x -C <dir>
                 git -C <engine repo> rev-parse origin/main > <dir>/COMMIT
BACKTEST_DATA  the Backtest-Engine data folder, for the index candles and the stored IV.

Writes snapshots/<day>.json, and prints how the 0DTE IV compares with the stored IV.
"""

import asyncio
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time as timer
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from convex_trading_engine.bus import InMemoryBus
from convex_trading_engine.chain import ChainEngine
from convex_trading_engine.chain.history import StoredCandle
from convex_trading_engine.chain.readings import readings_hours
from convex_trading_engine.chain.realised import (
    PastSession,
    close_to_close_volatility,
    implied_realised_gap,
    realised_variance,
    time_of_day_profile,
    yearly_volatility,
)
from convex_trading_engine.datafeed.adapters.databento.files import DatabentoFileAdapter
from convex_trading_engine.datafeed.clock import datetime_to_ns, seconds_to_ns
from convex_trading_engine.messages import MessageKind
from convex_trading_engine.settings import load_settings
from convex_trading_engine.trading_calendar.calendars import load_calendar

REPO = Path(__file__).resolve().parent.parent

# The snapshot days and file names come from our fetch module, loaded from its file: our
# package is not installed in the engine's environment.
_spec = importlib.util.spec_from_file_location("fetch", REPO / "src/options_agent/fetch.py")
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)

NEW_YORK = ZoneInfo("America/New_York")
AS_OF = time(15, 45)
QUOTES_FROM = time(15, 30)  # where the downloaded quotes start
MINUTE = 60_000_000_000
DRAIN_EVERY_SECONDS = 5  # of market time; see replay()
PAST_SESSIONS = 30  # sessions the time-of-day profile learns from, as the engine's history keeps


def calendar_folder(engine_dir: Path) -> Path:
    """The engine's shipped calendars plus our 2025 one, which the engine does not ship."""
    folder = Path(tempfile.mkdtemp(prefix="calendars-"))
    shipped = engine_dir / "src/convex_trading_engine/trading_calendar/data"
    for path in [*shipped.glob("cboe-*.toml"), REPO / "config/calendars/cboe-2025.toml"]:
        shutil.copy(path, folder)
    return folder


async def replay(settings, files: list[Path], quotes_from_ns: int, cutoff_ns: int) -> dict:
    """Step the engine through the files on their own clock up to ``cutoff_ns``, as the
    engine's stepped hosts do (its tests/end_to_end/test_stepped_day.py), and return what it
    published.

    Nothing ticks before the quotes start at ``quotes_from_ns``: the adapter republishes every
    definition each time new ones are flushed, and the day's 20,000 definitions arrive spread
    over the morning, so ticking through them republishes millions. Held back, they and the
    morning's statistics go out once, at the first tick."""
    clock = None
    bus = InMemoryBus(clock_ns=lambda: clock() if clock else 0, latest_value_seconds=86400)
    adapter = DatabentoFileAdapter(settings, "databento-spxw", bus, files, fast=True)
    clock = adapter.file_clock
    engine = ChainEngine(
        bus,
        settings.chain,
        settings.markets,
        clock_ns=clock,
        floor_clock_ns=clock,
        block_ms=0,
        replays=True,
    )
    await engine.open()
    await adapter.start()

    # The adapter's own read loop (files.py, _read), stopped at the cutoff, with the engine
    # drained at each tick. A tick every 5 s of market time rather than the adapter's 0.25 s:
    # only the state at the cutoff is kept, and the drain there recomputes every expiry from
    # the newest quotes either way, so the figures are the same at a 20th of the work.
    tick_ns = seconds_to_ns(DRAIN_EVERY_SECONDS)
    next_tick = clock.now_ns + tick_ns
    for record in adapter.files:
        at = max(record.ts_index, clock.now_ns)
        if at > cutoff_ns:
            break
        if at >= next_tick and at >= quotes_from_ns:
            await adapter.publish_held_statistics()
            clock.now_ns = at
            next_tick = at + tick_ns
            await adapter.manager.tick()
            await adapter.flush()
            await engine.drain()
            # The in-memory bus keeps every entry; drop those the engine has read.
            for kind in MessageKind:
                bus.trim_before(kind, await bus.last_id(kind))
        else:
            clock.now_ns = at
        await adapter.handle(record)
    clock.now_ns = cutoff_ns
    await adapter.publish_held_statistics()
    await adapter.flush()
    await engine.drain()
    # Skew and gamma are published at most once a second; one more second lets out any held
    # back. No record after the cutoff is read.
    clock.now_ns = cutoff_ns + seconds_to_ns(1)
    await engine.drain()

    events = await bus.latest_values(MessageKind.CHAIN_EVENT)
    strikes = {}
    for event in events:
        newest = await bus.newest_snapshot(event.root, event.expiry)
        if newest is not None:
            snap = newest.snapshot
            strikes[str(event.expiry)] = {"fields": dict(snap.fields), "columns": snap.columns}
    return {
        "chain_events": dump(events),
        "skews": dump(await bus.latest_values(MessageKind.SKEW)),
        "gamma": dump(await bus.latest_values(MessageKind.GAMMA_EXPOSURE)),
        "strikes": strikes,
    }


def dump(messages) -> list[dict]:
    rows = [m.model_dump(mode="json") for m in messages]
    return sorted(rows, key=lambda row: str(row.get("expiry")))


def index_candles(data_dir: Path) -> dict[date, list[StoredCandle]]:
    """The one-minute index candles by day. Their DateTime is New York time at the bar's end,
    so a candle's start is a minute earlier."""
    frame = pd.read_parquet(data_dir / "index/asset=SPXW/index.parquet")
    days: dict[date, list[StoredCandle]] = {}
    for row in frame.itertuples():
        end = row.DateTime.to_pydatetime().replace(tzinfo=NEW_YORK)
        start = datetime_to_ns(end - timedelta(minutes=1))
        candle = StoredCandle("SPXW", end.date(), start, row.Open, row.High, row.Low, row.Close)
        days.setdefault(end.date(), []).append(candle)
    return days


def realised(day: date, candles, calendar, volatility, cutoff_ns: int) -> dict:
    """Realised volatility since the open and over 20 sessions close to close, as the engine's
    readings work them out (chain/readings.py), from the candles inside the readings' hours,
    which end at the 16:00 expiry time."""

    def session(d):
        open_ns, end_ns = readings_hours(calendar, d, time(16))
        inside = [c for c in candles[d] if open_ns <= c.start and c.start + MINUTE <= end_ns]
        return open_ns, end_ns, sorted(inside, key=lambda c: c.start)

    past = [d for d in sorted(candles) if d < day and calendar.is_trading_day(d)]
    past_sessions = [PastSession(*session(d)) for d in past[-PAST_SESSIONS:]]
    open_ns, end_ns, today = session(day)
    profile = time_of_day_profile(
        past_sessions,
        (end_ns - open_ns) // MINUTE,
        bucket_minutes=volatility.bucket_minutes,
        min_sessions=volatility.min_sessions,
        first_within=volatility.first_candle_limit_minutes,
        coverage=volatility.minutes_present_share,
    )
    stretch = realised_variance(
        today, open_ns, cutoff_ns, sampling=volatility.sampling_for("SPXW"), close_ns=end_ns
    )
    since_open = yearly_volatility(stretch.variance, profile.share_of(stretch, open_ns))
    closes = [session(d)[2][-1].close for d in past]
    close_to_close, sessions = close_to_close_volatility(closes)
    return {
        "since_open": since_open,
        "since_open_sampling_minutes": volatility.sampling_for("SPXW"),
        "profile_sessions": profile.sessions,
        "close_to_close_20": close_to_close,
        "close_to_close_sessions": sessions,
    }


def compare_stored_iv(day: date, snapshot: dict, data_dir: Path) -> None:
    """Print how the engine's 0DTE IV at 15:45 compares with the Backtest-Engine's stored IV,
    whose timestamps run 5h30 behind New York (15:45 is stored as 10:15)."""
    strikes = snapshot["strikes"].get(str(day))
    path = data_dir / f"greeks_v7/asset=SPXW/date={day}/expiry={day}/greeks.parquet"
    if strikes is None or not path.exists():
        why = "no 0DTE snapshot" if strikes is None else f"no file {path}"
        print(f"  stored IV: nothing to compare ({why})")
        return
    stored = pd.read_parquet(path)
    stored = stored[stored["timestamp_utc"].dt.strftime("%H:%M") == "10:15"]
    stored = {(row.strike, row.option_type): row.iv for row in stored.itertuples()}
    cols = strikes["columns"]
    diffs = []
    for strike, iv, leg in zip(cols["strike"], cols["iv"], cols["iv_leg"], strict=True):
        theirs = stored.get((strike, "CE" if leg == "C" else "PE"))
        if iv is not None and theirs is not None and theirs == theirs:  # NaN is not equal to itself
            diffs.append((strike, (iv - theirs) * 100))
    if not diffs:
        print("  stored IV: no strike priced by both")
        return
    big = [(k, round(d, 2)) for k, d in diffs if abs(d) > 1]
    worst = max(diffs, key=lambda kd: abs(kd[1]))
    print(
        f"  stored IV: {len(diffs)} strikes compared, largest gap {worst[1]:+.2f} vol points "
        f"at {worst[0]}, {len(big)} over 1 vol point{': ' + str(big) if big else ''}"
    )


def main() -> None:
    engine_dir = Path(os.environ["ENGINE_DIR"])
    data_dir = Path(os.environ["BACKTEST_DATA"])
    commit = (engine_dir / "COMMIT").read_text().strip()
    settings = load_settings(REPO / "config/engine-replay.toml")
    folder = calendar_folder(engine_dir)
    settings = settings.model_copy(
        update={"chain": settings.chain.model_copy(update={"calendar_directory": folder})}
    )
    calendar = load_calendar("CBOE", folder)
    candles = index_candles(data_dir)
    out = REPO / "snapshots"
    out.mkdir(exist_ok=True)
    days = sys.argv[1:] or fetch.SNAPSHOT_DAYS
    for day in days:
        started = timer.monotonic()
        d = date.fromisoformat(day)
        as_of = datetime.combine(d, AS_OF, NEW_YORK)
        cutoff_ns = datetime_to_ns(as_of)
        quotes_from_ns = datetime_to_ns(datetime.combine(d, QUOTES_FROM, NEW_YORK))
        files = [REPO / fetch.DATA_DIR / f.name for f in fetch.plan_day(day)]
        snapshot = {
            "day": day,
            "as_of": as_of.isoformat(),
            "engine_commit": commit,
            **asyncio.run(replay(settings, files, quotes_from_ns, cutoff_ns)),
            "realised": realised(d, candles, calendar, settings.chain.volatility, cutoff_ns),
        }
        since_open = snapshot["realised"]["since_open"]
        snapshot["gaps"] = {
            s["expiry"]: implied_realised_gap(s["atm_iv"], since_open) for s in snapshot["skews"]
        }
        (out / f"{day}.json").write_text(json.dumps(snapshot, indent=1, default=str))
        print(
            f"{day}: {len(snapshot['chain_events'])} expiries, {len(snapshot['skews'])} skews, "
            f"{len(snapshot['gamma'])} gamma, in {timer.monotonic() - started:.0f}s"
        )
        compare_stored_iv(d, snapshot, data_dir)


if __name__ == "__main__":
    main()

"""Download the raw Databento files for the snapshot days, or check that they are all there."""

import argparse
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import databento

# The six snapshot days and why each was picked: docs/roadmap.md, "Data rules".
SNAPSHOT_DAYS = ["2026-06-02", "2025-11-20", "2026-03-18", "2026-03-20", "2025-11-26", "2026-05-04"]
DATA_DIR = Path("data/raw")
DATASET = "OPRA.PILLAR"
NEW_YORK = ZoneInfo("America/New_York")
ATTEMPTS = 5
KEY_VARIABLE = "DATABENTO_API_KEY"


@dataclass(frozen=True)
class RawFile:
    """One file to download: its name on disk, the Databento schema, and the time range."""

    name: str
    schema: str
    start: str
    end: str


def plan_day(day: str) -> list[RawFile]:
    """The three files a snapshot day needs: the day's definitions and statistics, and the
    quotes from 15:30 to 15:46 New York time."""
    d = date.fromisoformat(day)
    next_day = str(d + timedelta(days=1))
    window_start = datetime(d.year, d.month, d.day, 15, 30, tzinfo=NEW_YORK)
    window_end = datetime(d.year, d.month, d.day, 15, 46, tzinfo=NEW_YORK)
    return [
        RawFile(f"spxw-{day}.definition.dbn.zst", "definition", day, next_day),
        RawFile(f"spxw-{day}.statistics.dbn.zst", "statistics", day, next_day),
        RawFile(
            f"spxw-{day}.cbbo-1s.dbn.zst",
            "cbbo-1s",
            window_start.isoformat(),
            window_end.isoformat(),
        ),
    ]


def download_with_retries(
    raw_file: RawFile,
    path: Path,
    download: Callable[[RawFile, Path], None],
    sleep: Callable[[float], None] = time.sleep,
) -> str | None:
    """Download one file, retrying Databento server errors (5xx, such as 504 timeouts) with a
    longer wait each time. Returns a problem line if every attempt failed, else None.

    The download goes to a `.part` file that is renamed only once it is complete, so a file
    under its real name is never half-written. Client errors (4xx, such as a bad key) are not
    retried: trying again cannot fix them."""
    part = path.with_name(path.name + ".part")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            download(raw_file, part)
        except databento.BentoServerError as err:
            part.unlink(missing_ok=True)
            print(
                f"{path.name}: attempt {attempt} of {ATTEMPTS} failed ({err.http_status})",
                flush=True,
            )
            if attempt < ATTEMPTS:
                sleep(20 * attempt)
            continue
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        part.replace(path)
        print(f"{path.name}: downloaded, {path.stat().st_size / 1e6:.1f} MB", flush=True)
        return None
    return f"failed: {path.name} (gave up after {ATTEMPTS} attempts)"


def databento_download(raw_file: RawFile, path: Path) -> None:
    """Download one file from Databento: every SPXW contract (the `SPXW.OPT` parent symbol).
    The client reads the key from the DATABENTO_API_KEY environment variable itself, so this
    code never holds the key."""
    databento.Historical().timeseries.get_range(
        dataset=DATASET,
        symbols=["SPXW.OPT"],
        stype_in="parent",
        schema=raw_file.schema,
        start=raw_file.start,
        end=raw_file.end,
        path=path,
    )


def main(
    argv: list[str] | None = None,
    download: Callable[[RawFile, Path], None] = databento_download,
    data_dir: Path = DATA_DIR,
) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch-data",
        description="Download the snapshot days' raw Databento files into data/raw.",
    )
    parser.add_argument(
        "--verify", action="store_true", help="only check every file is there, download nothing"
    )
    args = parser.parse_args(argv)

    planned = [f for day in SNAPSHOT_DAYS for f in plan_day(day)]
    missing = [f for f in planned if not (data_dir / f.name).exists()]

    if args.verify:
        problems = [f"missing: {f.name}" for f in missing]
    elif missing and KEY_VARIABLE not in os.environ:
        print(
            f"{KEY_VARIABLE} is not set; it is needed to download {len(missing)} missing "
            "file(s). Set it in your shell, never in a committed file.",
            file=sys.stderr,
        )
        return 2
    else:
        data_dir.mkdir(parents=True, exist_ok=True)
        results = (download_with_retries(f, data_dir / f.name, download) for f in missing)
        problems = [p for p in results if p is not None]

    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} problem(s) found")
        return 1
    print(f"all {len(planned)} files are in {data_dir}")
    return 0

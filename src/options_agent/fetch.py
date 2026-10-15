"""Download the raw Databento files for the snapshot days and check them against a manifest."""

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import databento
import zstandard

# The six snapshot days and why each was picked: docs/roadmap.md, "Data rules".
SNAPSHOT_DAYS = ["2026-06-02", "2025-11-20", "2026-03-18", "2026-03-20", "2025-11-26", "2026-05-04"]
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


class DamagedFile(Exception):
    """The file cannot be read as a complete DBN file."""


def read_exactly(stream, n: int) -> bytes:
    data = stream.read(n)
    if len(data) != n:
        raise DamagedFile
    return data


def records_sha256(path: Path) -> str:
    """The SHA-256 of the file's records: decompressed, without the DBN header.

    The header is left out on purpose. It lists the symbol mappings, and Databento writes them
    in a different order on every download, so two downloads of the same data differ as files
    while their records are identical byte for byte. The file is read 1 MB at a time, so a
    300 MB file never sits in memory whole."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as f, zstandard.ZstdDecompressor().stream_reader(f) as stream:
            if read_exactly(stream, 3) != b"DBN":
                raise DamagedFile
            stream.read(1)  # the DBN version
            header_length = int.from_bytes(read_exactly(stream, 4), "little")
            read_exactly(stream, header_length)
            while chunk := stream.read(1 << 20):
                digest.update(chunk)
    except zstandard.ZstdError as err:
        raise DamagedFile from err
    return digest.hexdigest()


def check_file(path: Path, expected: dict) -> str | None:
    """What is wrong with one file against its manifest entry, or None if it matches."""
    if not path.exists():
        return f"missing: {path.name}"
    try:
        actual = records_sha256(path)
    except DamagedFile:
        return f"damaged: {path.name} (not a complete DBN file)"
    if actual != expected["records_sha256"]:
        return f"changed: {path.name} (its records differ from the manifest)"
    return None


def verify(data_dir: Path, manifest: dict) -> list[str]:
    """Every problem with the files the manifest lists, one line each; empty if all match."""
    problems = (check_file(data_dir / name, e) for name, e in manifest["files"].items())
    return [p for p in problems if p is not None]


def download_with_retries(
    raw_file: RawFile,
    path: Path,
    download: Callable[[RawFile, Path], None],
    sleep: Callable[[float], None],
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


def fetch(
    data_dir: Path,
    manifest: dict,
    days: list[str],
    download: Callable[[RawFile, Path], None],
    sleep: Callable[[float], None] = time.sleep,
) -> list[str]:
    """Make sure every file the days need is in `data_dir`, downloading only the missing ones.

    A file already on disk is checked against its manifest entry and never downloaded again.
    A downloaded file not yet in the manifest is added to `manifest` (the caller saves it).
    Returns every problem found, one line each; empty if all is well."""
    problems = []
    for raw_file in (f for day in days for f in plan_day(day)):
        path = data_dir / raw_file.name
        expected = manifest["files"].get(raw_file.name)
        if not path.exists():
            failure = download_with_retries(raw_file, path, download, sleep)
            if failure:
                problems.append(failure)
                continue
        if expected is None:
            try:
                checksum = records_sha256(path)
            except DamagedFile:
                problems.append(f"damaged: {path.name} (not a complete DBN file)")
                continue
            manifest["files"][raw_file.name] = {
                "start": raw_file.start,
                "end": raw_file.end,
                "records_sha256": checksum,
            }
        elif problem := check_file(path, expected):
            problems.append(problem)
    return problems


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


def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {
        "dataset": DATASET,
        "symbols": "SPXW.OPT (parent)",
        "window_et": "15:30-15:46",
        "files": {},
    }


def main(
    argv: list[str] | None = None,
    download: Callable[[RawFile, Path], None] = databento_download,
) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch-data",
        description="Download the snapshot days' raw Databento files and check their checksums.",
    )
    parser.add_argument("--verify", action="store_true", help="only check files, download nothing")
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--manifest", type=Path, default=Path("data/manifest.json"))
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    if args.verify:
        problems = verify(args.data_dir, manifest)
    else:
        missing = [
            f.name
            for day in SNAPSHOT_DAYS
            for f in plan_day(day)
            if not (args.data_dir / f.name).exists()
        ]
        if missing and KEY_VARIABLE not in os.environ:
            print(
                f"{KEY_VARIABLE} is not set; it is needed to download {len(missing)} missing "
                "file(s). Set it in your shell, never in a committed file.",
                file=sys.stderr,
            )
            return 2
        args.data_dir.mkdir(parents=True, exist_ok=True)
        problems = fetch(args.data_dir, manifest, SNAPSHOT_DAYS, download)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, indent=2) + "\n")

    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} problem(s) found")
        return 1
    print(f"all {len(manifest['files'])} files match the manifest")
    return 0

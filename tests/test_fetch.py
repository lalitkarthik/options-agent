import json

import pytest
import zstandard
from databento import BentoClientError, BentoServerError

from options_agent.fetch import SNAPSHOT_DAYS, fetch, main, plan_day, verify

# SHA-256 of b"hello", from any sha256 tool; an independent check on our hashing.
HELLO_SHA256 = "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"


def dbn(records=b"hello", header=b"symbol mappings", level=3) -> bytes:
    """A file shaped like Databento's: zstd-compressed "DBN", a version byte, the header's
    length (4 bytes, little-endian), the header, then the records."""
    raw = b"DBN" + len(header).to_bytes(4, "little") + header + records
    return zstandard.ZstdCompressor(level=level).compress(raw)


def entry(records_sha256: str = HELLO_SHA256) -> dict:
    return {"start": "s", "end": "e", "records_sha256": records_sha256}


def test_a_summer_day_needs_three_files_with_the_quote_window_in_new_york_summer_time():
    files = plan_day("2026-06-02")

    assert [(f.name, f.schema, f.start, f.end) for f in files] == [
        ("spxw-2026-06-02.definition.dbn.zst", "definition", "2026-06-02", "2026-06-03"),
        ("spxw-2026-06-02.statistics.dbn.zst", "statistics", "2026-06-02", "2026-06-03"),
        (
            "spxw-2026-06-02.cbbo-1s.dbn.zst",
            "cbbo-1s",
            "2026-06-02T15:30:00-04:00",
            "2026-06-02T15:46:00-04:00",
        ),
    ]


def test_a_winter_day_puts_the_quote_window_in_new_york_winter_time():
    quotes = plan_day("2025-11-20")[2]

    assert (quotes.start, quotes.end) == ("2025-11-20T15:30:00-05:00", "2025-11-20T15:46:00-05:00")


def test_verify_finds_nothing_wrong_when_every_file_matches(tmp_path):
    (tmp_path / "a.dbn.zst").write_bytes(dbn())
    manifest = {"files": {"a.dbn.zst": entry()}}

    assert verify(tmp_path, manifest) == []


def test_verify_names_a_missing_file_and_a_changed_file(tmp_path):
    (tmp_path / "changed.dbn.zst").write_bytes(dbn(records=b"hellO"))
    (tmp_path / "fine.dbn.zst").write_bytes(dbn())
    manifest = {
        "files": {
            "fine.dbn.zst": entry(),
            "changed.dbn.zst": entry(),
            "gone.dbn.zst": entry(),
        }
    }

    assert verify(tmp_path, manifest) == [
        "changed: changed.dbn.zst (its records differ from the manifest)",
        "missing: gone.dbn.zst",
    ]


def test_verify_accepts_the_same_records_under_a_different_header_and_compression(tmp_path):
    # Databento lists the symbol mappings in a different order on every download, so two
    # downloads of the same data differ as files; only the records are compared.
    (tmp_path / "a.dbn.zst").write_bytes(dbn(header=b"mappings, other order", level=19))
    manifest = {"files": {"a.dbn.zst": entry()}}

    assert verify(tmp_path, manifest) == []


def test_verify_reports_a_file_that_cannot_be_read(tmp_path):
    (tmp_path / "cut.dbn.zst").write_bytes(dbn()[:-4])
    (tmp_path / "plain.dbn.zst").write_bytes(zstandard.ZstdCompressor().compress(b"not dbn"))
    manifest = {"files": {"cut.dbn.zst": entry(), "plain.dbn.zst": entry()}}

    assert verify(tmp_path, manifest) == [
        "damaged: cut.dbn.zst (not a complete DBN file)",
        "damaged: plain.dbn.zst (not a complete DBN file)",
    ]


class FakeDatabento:
    """Stands in for the Databento download: writes `content` to the path it is given,
    after raising each error in `errors` in turn."""

    def __init__(self, content=None, errors=()):
        self.content = content or dbn()
        self.errors = list(errors)
        self.calls = []

    def __call__(self, raw_file, path):
        self.calls.append(raw_file.name)
        if self.errors:
            path.write_bytes(b"hel")  # a download cut off half way
            raise self.errors.pop(0)
        path.write_bytes(self.content)


def test_fetch_downloads_nothing_when_every_file_is_already_there_and_matches(tmp_path):
    manifest = {"files": {}}
    for f in plan_day("2026-06-02"):
        (tmp_path / f.name).write_bytes(dbn())
        manifest["files"][f.name] = entry()
    download = FakeDatabento()

    problems = fetch(tmp_path, manifest, ["2026-06-02"], download)

    assert (problems, download.calls) == ([], [])


def test_fetch_downloads_a_missing_file_and_records_it_in_the_manifest(tmp_path):
    manifest = {"files": {}}
    download = FakeDatabento()

    problems = fetch(tmp_path, manifest, ["2026-06-02"], download)

    assert problems == []
    assert len(download.calls) == 3
    assert (tmp_path / "spxw-2026-06-02.statistics.dbn.zst").read_bytes() == dbn()
    assert manifest["files"]["spxw-2026-06-02.statistics.dbn.zst"] == {
        "start": "2026-06-02",
        "end": "2026-06-03",
        "records_sha256": HELLO_SHA256,
    }


def timeout():
    return BentoServerError(504, message="Gateway Timeout")


def test_fetch_retries_a_server_timeout_with_longer_waits_and_leaves_no_partial_file(tmp_path):
    manifest = {"files": {}}
    download = FakeDatabento(errors=[timeout(), timeout()])
    waits = []

    problems = fetch(tmp_path, manifest, ["2026-06-02"], download, sleep=waits.append)

    assert problems == []
    assert waits == [20, 40]
    assert (tmp_path / "spxw-2026-06-02.definition.dbn.zst").read_bytes() == dbn()
    assert list(tmp_path.glob("*.part")) == []


def test_fetch_gives_up_on_a_file_after_five_timeouts_and_carries_on(tmp_path):
    manifest = {"files": {}}
    download = FakeDatabento(errors=[timeout()] * 5)

    problems = fetch(tmp_path, manifest, ["2026-06-02"], download, sleep=lambda s: None)

    assert problems == ["failed: spxw-2026-06-02.definition.dbn.zst (gave up after 5 attempts)"]
    assert not (tmp_path / "spxw-2026-06-02.definition.dbn.zst").exists()
    assert "spxw-2026-06-02.definition.dbn.zst" not in manifest["files"]
    assert (tmp_path / "spxw-2026-06-02.statistics.dbn.zst").exists()


def test_fetch_does_not_retry_a_client_error_such_as_a_bad_key(tmp_path):
    download = FakeDatabento(errors=[BentoClientError(401, message="Unauthorized")])

    with pytest.raises(BentoClientError):
        fetch(tmp_path, {"files": {}}, ["2026-06-02"], download, sleep=lambda s: None)
    assert download.calls == ["spxw-2026-06-02.definition.dbn.zst"]


def test_fetch_reports_a_downloaded_file_that_differs_from_the_manifest(tmp_path):
    name = "spxw-2026-06-02.definition.dbn.zst"
    manifest = {"files": {name: entry()}}

    problems = fetch(tmp_path, manifest, ["2026-06-02"], FakeDatabento(content=dbn(b"jello")))

    assert problems == [f"changed: {name} (its records differ from the manifest)"]
    assert manifest["files"][name]["records_sha256"] == HELLO_SHA256


def write_complete_data(data_dir, manifest_path):
    """Every file of every snapshot day on disk, and a manifest that matches them."""
    data_dir.mkdir()
    files = {}
    for day in SNAPSHOT_DAYS:
        for f in plan_day(day):
            (data_dir / f.name).write_bytes(dbn())
            files[f.name] = entry()
    manifest_path.write_text(json.dumps({"files": files}))


def run(tmp_path, *args, download=None):
    data_dir, manifest = tmp_path / "raw", tmp_path / "manifest.json"
    argv = ["--data-dir", str(data_dir), "--manifest", str(manifest), *args]
    return main(argv, download=download or FakeDatabento())


def test_verify_mode_passes_on_complete_data_without_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    write_complete_data(tmp_path / "raw", tmp_path / "manifest.json")

    assert run(tmp_path, "--verify") == 0
    assert "all 18 files match the manifest" in capsys.readouterr().out


def test_verify_mode_fails_and_names_a_missing_file(tmp_path, capsys):
    write_complete_data(tmp_path / "raw", tmp_path / "manifest.json")
    (tmp_path / "raw" / "spxw-2026-03-18.statistics.dbn.zst").unlink()

    assert run(tmp_path, "--verify") == 1
    assert "missing: spxw-2026-03-18.statistics.dbn.zst" in capsys.readouterr().out


def test_fetch_mode_on_complete_data_downloads_nothing_and_needs_no_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    write_complete_data(tmp_path / "raw", tmp_path / "manifest.json")
    download = FakeDatabento()

    assert run(tmp_path, download=download) == 0
    assert download.calls == []


def test_fetch_mode_stops_before_downloading_when_the_key_is_not_set(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    download = FakeDatabento()

    assert run(tmp_path, download=download) == 2
    assert download.calls == []
    assert "DATABENTO_API_KEY is not set" in capsys.readouterr().err


def test_fetch_mode_downloads_everything_into_an_empty_folder_and_never_shows_the_key(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DATABENTO_API_KEY", "db-SECRET-KEY-VALUE")

    assert run(tmp_path) == 0
    manifest_text = (tmp_path / "manifest.json").read_text()
    assert len(json.loads(manifest_text)["files"]) == 18
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err + manifest_text

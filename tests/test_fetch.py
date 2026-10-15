import pytest
from databento import BentoClientError, BentoServerError

from options_agent.fetch import SNAPSHOT_DAYS, download_with_retries, main, plan_day


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


class FakeDatabento:
    """Stands in for the Databento download: writes b"data" to the path it is given,
    after raising each error in `errors` in turn."""

    def __init__(self, errors=()):
        self.errors = list(errors)
        self.calls = []

    def __call__(self, raw_file, path):
        self.calls.append(raw_file.name)
        if self.errors:
            path.write_bytes(b"da")  # a download cut off half way
            raise self.errors.pop(0)
        path.write_bytes(b"data")


def timeout():
    return BentoServerError(504, message="Gateway Timeout")


DEFINITION = plan_day("2026-06-02")[0]


def test_a_server_timeout_is_retried_with_longer_waits_and_leaves_no_partial_file(tmp_path):
    path = tmp_path / DEFINITION.name
    waits = []

    problem = download_with_retries(
        DEFINITION, path, FakeDatabento(errors=[timeout(), timeout()]), sleep=waits.append
    )

    assert problem is None
    assert waits == [20, 40]
    assert path.read_bytes() == b"data"
    assert list(tmp_path.glob("*.part")) == []


def test_a_file_is_given_up_after_five_timeouts(tmp_path):
    path = tmp_path / DEFINITION.name

    problem = download_with_retries(
        DEFINITION, path, FakeDatabento(errors=[timeout()] * 5), sleep=lambda s: None
    )

    assert problem == f"failed: {DEFINITION.name} (gave up after 5 attempts)"
    assert list(tmp_path.iterdir()) == []


def test_a_client_error_such_as_a_bad_key_is_not_retried(tmp_path):
    download = FakeDatabento(errors=[BentoClientError(401, message="Unauthorized")])

    with pytest.raises(BentoClientError):
        download_with_retries(DEFINITION, tmp_path / DEFINITION.name, download, sleep=print)
    assert download.calls == [DEFINITION.name]


def write_every_file(data_dir):
    for day in SNAPSHOT_DAYS:
        for f in plan_day(day):
            (data_dir / f.name).write_bytes(b"data")


def test_verify_passes_when_every_file_is_there_without_a_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    write_every_file(tmp_path)

    assert main(["--verify"], data_dir=tmp_path) == 0
    assert "all 18 files are in" in capsys.readouterr().out


def test_verify_fails_and_names_a_missing_file(tmp_path, capsys):
    write_every_file(tmp_path)
    (tmp_path / "spxw-2026-03-18.statistics.dbn.zst").unlink()

    assert main(["--verify"], data_dir=tmp_path) == 1
    assert "missing: spxw-2026-03-18.statistics.dbn.zst" in capsys.readouterr().out


def test_fetch_downloads_nothing_and_needs_no_key_when_every_file_is_there(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    write_every_file(tmp_path)
    download = FakeDatabento()

    assert main([], download=download, data_dir=tmp_path) == 0
    assert download.calls == []


def test_fetch_stops_before_downloading_when_the_key_is_not_set(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    download = FakeDatabento()

    assert main([], download=download, data_dir=tmp_path / "raw") == 2
    assert download.calls == []
    assert "DATABENTO_API_KEY is not set" in capsys.readouterr().err


def test_fetch_downloads_every_file_into_an_empty_folder_and_never_shows_the_key(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setenv("DATABENTO_API_KEY", "db-SECRET-KEY-VALUE")

    assert main([], download=FakeDatabento(), data_dir=tmp_path / "raw") == 0
    assert len(list((tmp_path / "raw").iterdir())) == 18
    out = capsys.readouterr()
    assert "SECRET" not in out.out + out.err

import sys
from datetime import date
from pathlib import Path

import pyarrow.dataset as ds
import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
import fx_rates_to_bronze as fx  # noqa: E402


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Returns queued responses in order and records the URLs requested."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def api_payload(rates):
    return {"amount": 1.0, "base": "EUR", "rates": rates}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(fx.time, "sleep", lambda s: None)


def read_bronze(lake):
    return ds.dataset(lake / "bronze" / "fx" / "rates", format="parquet", partitioning="hive").to_table()


def test_writes_one_partition_per_rate_date_with_raw_json(tmp_path):
    session = FakeSession(FakeResponse(200, api_payload({
        "2024-12-30": {"GBP": 0.8295, "USD": 1.0444},
        "2024-12-31": {"GBP": 0.82918, "USD": 1.0389},
    })))
    result = fx.ingest(tmp_path, date(2024, 12, 30), date(2025, 1, 1), session)

    assert result["dates_loaded"] == ["2024-12-30", "2024-12-31"]
    rows = sorted(read_bronze(tmp_path).to_pylist(), key=lambda r: str(r["rate_date"]))
    assert rows[1]["rates_json"] == '{"GBP": 0.82918, "USD": 1.0389}'


def test_incremental_run_starts_after_watermark(tmp_path):
    fx.ingest(tmp_path, date(2024, 12, 30), date(2024, 12, 30),
              FakeSession(FakeResponse(200, api_payload({"2024-12-30": {"GBP": 0.8, "USD": 1.0}}))))

    session = FakeSession(FakeResponse(200, api_payload({"2024-12-31": {"GBP": 0.8, "USD": 1.0}})))
    fx.ingest(tmp_path, end=date(2024, 12, 31), session=session)

    assert "2024-12-31..2024-12-31" in session.urls[0]
    assert read_bronze(tmp_path).num_rows == 2


def test_up_to_date_makes_no_request(tmp_path):
    fx.ingest(tmp_path, date(2024, 12, 31), date(2024, 12, 31),
              FakeSession(FakeResponse(200, api_payload({"2024-12-31": {"GBP": 0.8, "USD": 1.0}}))))
    session = FakeSession()  # any request would fail: no responses queued
    assert fx.ingest(tmp_path, end=date(2024, 12, 31), session=session)["dates_loaded"] == []


def test_reload_overwrites_instead_of_duplicating(tmp_path):
    for _ in range(2):
        fx.ingest(tmp_path, date(2024, 12, 31), date(2024, 12, 31),
                  FakeSession(FakeResponse(200, api_payload({"2024-12-31": {"GBP": 0.8, "USD": 1.0}}))))
    assert read_bronze(tmp_path).num_rows == 1


def test_retries_transient_errors_then_succeeds(tmp_path):
    session = FakeSession(
        requests.Timeout(),
        FakeResponse(503),
        FakeResponse(200, api_payload({"2024-12-31": {"GBP": 0.8, "USD": 1.0}})),
    )
    fx.ingest(tmp_path, date(2024, 12, 31), date(2024, 12, 31), session)
    assert len(session.urls) == 3


def test_gives_up_after_max_attempts(tmp_path):
    session = FakeSession(*[FakeResponse(503)] * fx.MAX_ATTEMPTS)
    with pytest.raises(RuntimeError, match="failed after"):
        fx.ingest(tmp_path, date(2024, 12, 31), date(2024, 12, 31), session)


def test_client_errors_are_not_retried(tmp_path):
    session = FakeSession(FakeResponse(404))
    with pytest.raises(requests.HTTPError):
        fx.ingest(tmp_path, date(2024, 12, 31), date(2024, 12, 31), session)
    assert len(session.urls) == 1

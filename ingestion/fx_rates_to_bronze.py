"""Ingest daily FX rates from the Frankfurter API (ECB reference rates) into bronze.

Bronze rules followed here:
  * The API response for each date is stored as received (raw JSON string).
  * Incremental: by default each run starts the day after the latest date already
    in the lake (the watermark), so only new days are requested.
  * Idempotent: one file per rate date, overwritten on re-load - never duplicated.
  * Resilient: timeouts, 5xx and 429 responses are retried with exponential backoff.

The ECB publishes no rates on weekends and holidays; those gaps are expected here
and filled in silver (docs/requirements.md §8).

Output layout:
  <lake>/bronze/fx/rates/rate_date=YYYY-MM-DD/rates.parquet
"""

import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import requests

API_URL = "https://api.frankfurter.dev/v1/{start}..{end}"
BASE_CURRENCY = "EUR"
QUOTE_CURRENCIES = ["USD", "GBP"]

# Transactions start on 2025-01-01, an ECB holiday. Starting a week earlier
# guarantees a previous rate exists to carry forward.
DEFAULT_START = date(2024, 12, 23)

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 5


def fetch_rates(start: date, end: date, session: requests.Session | None = None) -> dict:
    """Call the API for a date range, retrying transient failures."""
    session = session or requests.Session()
    url = API_URL.format(start=start.isoformat(), end=end.isoformat())
    params = {"base": BASE_CURRENCY, "symbols": ",".join(QUOTE_CURRENCIES)}

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, params=params, timeout=30)
            if response.status_code not in RETRY_STATUS:
                response.raise_for_status()  # 4xx (except 429) = our mistake, don't retry
                return response.json()
            reason = f"HTTP {response.status_code}"
        except (requests.ConnectionError, requests.Timeout) as exc:
            reason = type(exc).__name__
        if attempt == MAX_ATTEMPTS:
            raise RuntimeError(f"FX API failed after {MAX_ATTEMPTS} attempts ({reason}): {url}")
        wait = 2 ** attempt  # 2, 4, 8, 16 seconds
        print(f"Attempt {attempt} failed ({reason}); retrying in {wait}s")
        time.sleep(wait)
    raise AssertionError("unreachable")


def latest_loaded_date(table_dir: Path) -> date | None:
    """The watermark: the most recent rate_date partition already in the lake."""
    dates = [
        date.fromisoformat(p.name.split("=", 1)[1])
        for p in table_dir.glob("rate_date=*")
        if (p / "rates.parquet").exists()
    ]
    return max(dates, default=None)


def ingest(lake: Path, start: date | None = None, end: date | None = None,
           session: requests.Session | None = None) -> dict:
    table_dir = lake / "bronze" / "fx" / "rates"
    end = end or date.today()
    if start is None:
        watermark = latest_loaded_date(table_dir)
        start = watermark + timedelta(days=1) if watermark else DEFAULT_START
    if start > end:
        print(f"Up to date: nothing to load after {start - timedelta(days=1)}")
        return {"start": start.isoformat(), "end": end.isoformat(), "dates_loaded": []}

    payload = fetch_rates(start, end, session)
    ingested_at = datetime.now(timezone.utc)
    request = f"{API_URL.format(start=start, end=end)}?base={BASE_CURRENCY}&symbols={','.join(QUOTE_CURRENCIES)}"

    loaded = []
    for rate_date, rates in sorted(payload.get("rates", {}).items()):
        if not start.isoformat() <= rate_date <= end.isoformat():
            continue  # the API may return the previous working day for a range starting on a holiday
        table = pa.table({
            "rate_date": [rate_date],
            "base_currency": [payload["base"]],
            "rates_json": [json.dumps(rates, sort_keys=True)],
            "_source_url": [request],
            "_ingested_at": pa.array([ingested_at], pa.timestamp("us", tz="UTC")),
        })
        out = table_dir / f"rate_date={rate_date}" / "rates.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        pq.write_table(table, tmp)
        tmp.replace(out)  # atomic overwrite
        loaded.append(rate_date)

    print(f"Loaded {len(loaded)} rate dates for {start}..{end}")
    return {"start": start.isoformat(), "end": end.isoformat(), "dates_loaded": loaded}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--lake", type=Path, default=Path("data/dev/lake"), help="lake root")
    p.add_argument("--start", type=date.fromisoformat, help="first date (default: day after watermark)")
    p.add_argument("--end", type=date.fromisoformat, help="last date (default: today)")
    args = p.parse_args()
    ingest(args.lake, args.start, args.end)


if __name__ == "__main__":
    main()

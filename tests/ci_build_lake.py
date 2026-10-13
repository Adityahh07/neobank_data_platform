"""Build the `ci` environment's bronze lake from committed fixtures.

Runs the real ingestion code on small, fixed test data so CI needs neither the
471 MB PaySim file nor the live FX API (an outage there must not fail every PR).

Usage (from the project root):
  python tests/ci_build_lake.py
  cd transform && dbt build --profiles-dir . --target ci
"""

import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion import fx_rates_to_bronze, paysim_to_bronze  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"
CI_DATA = ROOT / "data" / "ci"


class FixtureSession:
    """Stands in for requests.Session: returns the saved Frankfurter API response."""

    def __init__(self, payload: dict):
        self.payload = payload

    def get(self, url, params=None, timeout=None):
        payload = self.payload

        class Response:
            status_code = 200

            def json(self):
                return payload

            def raise_for_status(self):
                pass

        return Response()


def main() -> None:
    shutil.rmtree(CI_DATA, ignore_errors=True)  # always start from a clean environment
    lake = CI_DATA / "lake"

    paysim_to_bronze.ingest(FIXTURES / "paysim_ci_sample.csv", lake)

    payload = json.loads((FIXTURES / "fx_rates_ci.json").read_text())
    fx_rates_to_bronze.ingest(lake, date(2024, 12, 23), date(2025, 1, 31), FixtureSession(payload))


if __name__ == "__main__":
    main()

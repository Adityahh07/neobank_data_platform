"""Run the daily pipeline: PaySim -> bronze, FX API -> bronze, dbt build (silver + gold).

Each step is recorded in ops.pipeline_runs. The run stops at the first failing step,
sends ONE critical alert, and exits with code 1 so a scheduler (Airflow, Phase 2)
sees the failure. A successful run sends a daily info summary.

Usage:
  python run_pipeline.py --env dev
  python run_pipeline.py --env prod
  python run_pipeline.py --env dev --alerts --simulate-failure fx_rates_to_bronze   # test alerting
"""

import argparse
import json
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import duckdb

from common.alerts import Alert, send_alert
from common.config import ROOT, EnvConfig, discord_webhook_url, env_config
from common.run_log import RunLog, utc_now
from ingestion import fx_rates_to_bronze, paysim_to_bronze

PIPELINE = "daily_pipeline"
# PaySim is a simulation of January 2025, so FX rates are loaded up to its last day.
FX_END_DATE = date(2025, 1, 31)
TRANSFORM_DIR = ROOT / "transform"

# "What to check" text in alerts - details in docs/runbook.md
HINTS = {
    "paysim_to_bronze": "Source file present in data/landing? Disk space? "
                        "See docs/runbook.md#paysim_to_bronze",
    "fx_rates_to_bronze": "Is api.frankfurter.dev reachable? Re-run the pipeline - the watermark "
                          "resumes where it stopped. See docs/runbook.md#fx_rates_to_bronze",
    "dbt_build": "Read the failing test, then query the table to find the bad rows. Never loosen "
                 "a test to make it pass. See docs/runbook.md#dbt_build",
}


@dataclass
class StepResult:
    rows_in: int | None = None
    rows_out: int | None = None
    message: str = ""
    warnings: list[str] = field(default_factory=list)


class StepFailed(Exception):
    """A step finished but its result is unacceptable (e.g. an incomplete load)."""


# ---------------------------------------------------------------- steps

def step_paysim(cfg: EnvConfig) -> StepResult:
    manifest = paysim_to_bronze.ingest(cfg.paysim_source, cfg.lake)
    expected = manifest["total_rows"]
    pattern = (cfg.lake / "bronze/paysim/transactions/*/*.parquet").as_posix()
    loaded = duckdb.sql(
        f"select count(*) from read_parquet('{pattern}', hive_partitioning = true) "
        f"where _source_sha256 = '{manifest['source_sha256']}'"
    ).fetchone()[0]
    # Load completeness check (requirements §11): never empty, nothing missing
    if expected == 0:
        raise StepFailed(f"{manifest['source_file']} contains 0 rows")
    if loaded != expected:
        raise StepFailed(f"Incomplete load: {loaded:,} rows in bronze, {expected:,} in source file")
    return StepResult(rows_in=expected, rows_out=loaded,
                      message=f"{manifest['source_file']}: {loaded:,} rows in bronze")


def step_fx(cfg: EnvConfig) -> StepResult:
    result = fx_rates_to_bronze.ingest(cfg.lake, end=FX_END_DATE)
    loaded = len(result["dates_loaded"])
    return StepResult(rows_out=loaded,
                      message=f"{loaded} new rate dates" if loaded else "up to date")


def dbt_executable() -> str:
    exe = shutil.which("dbt", path=str(ROOT / ".venv" / "Scripts")) or shutil.which("dbt")
    if not exe:
        raise StepFailed("dbt executable not found - is the virtual environment set up?")
    return exe


def summarise_dbt_results(run_results: dict) -> tuple[list[str], list[str], dict[str, int]]:
    """Return (failures, warnings, counts by status) from dbt's target/run_results.json."""
    failures, warnings, counts = [], [], {}
    for r in run_results.get("results", []):
        status = r.get("status")
        counts[status] = counts.get(status, 0) + 1
        name = r.get("unique_id", "?").split(".", 2)[-1]
        if status in ("fail", "error"):
            detail = r.get("message") or f"{r.get('failures')} failing rows"
            failures.append(f"{name}: {detail}")
        elif status == "warn":
            warnings.append(f"{name}: {r.get('failures')} rows")
    return failures, warnings, counts


def step_dbt(cfg: EnvConfig) -> StepResult:
    proc = subprocess.run(
        [dbt_executable(), "build", "--profiles-dir", ".", "--target", cfg.name],
        cwd=TRANSFORM_DIR, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    results_file = TRANSFORM_DIR / "target" / "run_results.json"
    if not results_file.exists():
        raise StepFailed(f"dbt produced no results (exit {proc.returncode}):\n{proc.stdout[-1500:]}")
    failures, warnings, counts = summarise_dbt_results(json.loads(results_file.read_text()))
    if failures or proc.returncode != 0:
        listed = "\n".join(f"- {f}" for f in failures[:10]) or proc.stdout[-1500:]
        raise StepFailed(f"{len(failures)} dbt node(s) failed:\n{listed}")
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    return StepResult(rows_out=sum(counts.values()), message=f"dbt build: {summary}",
                      warnings=warnings)


STEPS: list[tuple[str, Callable[[EnvConfig], StepResult]]] = [
    ("paysim_to_bronze", step_paysim),
    ("fx_rates_to_bronze", step_fx),
    ("dbt_build", step_dbt),
]


# ---------------------------------------------------------------- runner

def run(cfg: EnvConfig, steps, run_log: RunLog, notify: Callable[[Alert], object],
        simulate_failure: str | None = None) -> bool:
    """Run steps in order; stop and alert on the first failure. Returns True on success."""
    run_started = utc_now()
    done = []

    def alert(severity, title, message="", step=None, details=None):
        notify(Alert(severity, title, PIPELINE, cfg.name, run_log.run_id, message, step,
                     HINTS.get(step) if severity == "critical" else None, details or {}))

    for name, fn in steps:
        print(f"\n=== {name} ===")
        started = utc_now()
        try:
            if simulate_failure == name:
                raise StepFailed("Simulated failure (--simulate-failure) to test alerting")
            result = fn(cfg)
        except Exception as exc:  # any error in a step must stop the run and alert
            error = f"{type(exc).__name__}: {exc}"
            run_log.record(name, "failed", started, error_message=error)
            run_log.record("pipeline", "failed", run_started,
                           message=f"stopped at {name}", error_message=error)
            alert("critical", f"{PIPELINE} failed at {name}", error, step=name,
                  details={"Completed steps": ", ".join(done) or "none"})
            return False

        run_log.record(name, "success", started, result.rows_in, result.rows_out, result.message)
        print(f"OK - {result.message}")
        for warning in result.warnings:
            alert("warning", f"Data quality warning in {name}", warning, step=name)
        done.append(name)

    duration = (utc_now() - run_started).total_seconds()
    run_log.record("pipeline", "success", run_started, message=f"{len(done)} steps")
    alert("info", f"{PIPELINE} succeeded", f"All {len(done)} steps completed in {duration:.0f}s.",
          details={"Steps": ", ".join(done)})
    return True


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--env", choices=["dev", "prod"], default="dev")
    p.add_argument("--alerts", action="store_true",
                   help="send alerts to Discord even outside prod (for testing)")
    p.add_argument("--simulate-failure", choices=[name for name, _ in STEPS],
                   help="make this step fail on purpose, to test alerting")
    args = p.parse_args()

    cfg = env_config(args.env)
    run_id = f"{args.env}-{utc_now():%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    webhook = discord_webhook_url()
    alerts_on = args.env == "prod" or args.alerts  # dev never alerts unless asked (architecture §7)

    ok = run(cfg, STEPS, RunLog(cfg.warehouse, run_id, PIPELINE, args.env),
             lambda a: send_alert(a, webhook, alerts_on), args.simulate_failure)
    print(f"\nRun {run_id}: {'SUCCESS' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

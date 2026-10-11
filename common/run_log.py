"""Record every pipeline step in the warehouse table ops.pipeline_runs.

One row per step per run, plus one row for the run as a whole (step = 'pipeline').
Feeds the Operations status view and gives an audit trail of what ran when.
"""

from datetime import datetime, timezone
from pathlib import Path

import duckdb

DDL = """
create schema if not exists ops;
create table if not exists ops.pipeline_runs (
    run_id        varchar     not null,
    pipeline      varchar     not null,
    env           varchar     not null,
    step          varchar     not null,
    status        varchar     not null,   -- success / failed
    started_at    timestamptz not null,
    finished_at   timestamptz not null,
    duration_s    double,
    rows_in       bigint,
    rows_out      bigint,
    message       varchar,
    error_message varchar
);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RunLog:
    def __init__(self, warehouse: Path, run_id: str, pipeline: str, env: str):
        self.warehouse = warehouse
        self.run_id = run_id
        self.pipeline = pipeline
        self.env = env

    def record(self, step: str, status: str, started_at: datetime, rows_in: int | None = None,
               rows_out: int | None = None, message: str | None = None,
               error_message: str | None = None) -> None:
        finished_at = utc_now()
        self.warehouse.parent.mkdir(parents=True, exist_ok=True)
        # Short-lived connection: DuckDB allows one writer, and dbt needs the file too.
        with duckdb.connect(str(self.warehouse)) as con:
            con.execute(DDL)
            con.execute(
                "insert into ops.pipeline_runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [self.run_id, self.pipeline, self.env, step, status, started_at, finished_at,
                 (finished_at - started_at).total_seconds(), rows_in, rows_out, message,
                 error_message],
            )

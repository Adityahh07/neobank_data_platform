"""Read-only access to the warehouse for the dashboards.

Each query opens a short-lived read-only connection and closes it again, so the
dashboard never blocks the pipeline from writing (DuckDB allows one writer).
Results are cached for 5 minutes.
"""

import duckdb
import pandas as pd
import streamlit as st

from common.config import env_config


class WarehouseUnavailable(Exception):
    pass


@st.cache_data(ttl=300, show_spinner=False)
def query(env: str, sql: str, params: tuple = ()) -> pd.DataFrame:
    path = env_config(env).warehouse
    if not path.exists():
        raise WarehouseUnavailable(f"No warehouse for '{env}' yet - run: python run_pipeline.py --env {env}")
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            return con.execute(sql, list(params)).df()
    except duckdb.IOException as exc:
        raise WarehouseUnavailable(
            "The warehouse is busy (the pipeline is probably writing to it). Try again in a minute."
        ) from exc

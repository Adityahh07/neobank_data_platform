"""Neobank Data Platform dashboards: Risk, Finance and Operations views on the gold layer.

Run from the project root:
  streamlit run dashboards/app.py
"""

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # project root, for `common`

from dashboards import charts  # noqa: E402
from dashboards.data import WarehouseUnavailable, query  # noqa: E402

st.set_page_config(page_title="Neobank Data Platform", page_icon="🏦", layout="wide")


# ---------------------------------------------------------------- helpers

def theme_mode() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except AttributeError:
        return "light"


def money_m(value) -> str:
    """Compact money: 1,144,392,944,759.77 -> '1,144.39 bn'; 77,785,563.69 -> '77.8 m'."""
    value = float(value or 0)
    return f"{value / 1e9:,.2f} bn" if abs(value) >= 1e9 else f"{value / 1e6:,.1f} m"


def utc(ts) -> pd.Timestamp:
    """DuckDB returns timestamptz in local time; show everything in UTC."""
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def pct(value, decimals=2) -> str:
    return "n/a" if value is None or pd.isna(value) else f"{value:.{decimals}f}%"


def table_view(df: pd.DataFrame, label: str = "Show data") -> None:
    """Every chart has a table twin - values never depend on hover or colour alone."""
    with st.expander(label):
        st.dataframe(df, hide_index=True, width="stretch")


def date_filter(env: str) -> tuple[date, date]:
    bounds = query(env, "select min(date_key) as lo, max(date_key) as hi from gold.dim_date")
    lo, hi = bounds.lo[0].date(), bounds.hi[0].date()
    picked = st.date_input("Date range", value=(lo, hi), min_value=lo, max_value=hi,
                           format="DD/MM/YYYY")
    if isinstance(picked, tuple) and len(picked) == 2:
        return picked
    return (picked[0], picked[0]) if isinstance(picked, tuple) else (picked, picked)


# ---------------------------------------------------------------- Risk

def risk_view(env: str, mode: str) -> None:
    st.header("Risk - fraud monitoring")
    start, end = date_filter(env)
    rng = (start, end)

    k = query(env, """
        select count(*) filter (where rule_outcome = 'caught')      as caught,
               count(*) filter (where rule_outcome = 'missed')      as missed,
               count(*) filter (where rule_outcome = 'false_alarm') as false_alarms,
               coalesce(sum(amount_eur) filter (where rule_outcome = 'missed'), 0) as lost_eur
        from gold.fact_transactions where event_date between ? and ?""", rng).iloc[0]
    caught, missed, false_alarms = int(k.caught), int(k.missed), int(k.false_alarms)
    fraud = caught + missed
    catch_rate = 100 * caught / fraud if fraud else None
    precision = 100 * caught / (caught + false_alarms) if caught + false_alarms else None

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rule catch rate", pct(catch_rate),
              help="Of all real fraud, the share the core-system rule blocked (caught / (caught + missed)).")
    c2.metric("Rule precision", pct(precision),
              help="When the rule fires, how often it is real fraud. n/a = the rule never fired.")
    c3.metric("Fraud transactions", f"{fraud:,}", help=f"{caught:,} caught, {missed:,} missed")
    c4.metric("Fraud value lost (EUR)", money_m(k.lost_eur), help="Fraud the rule did not block.")

    left, right = st.columns(2)
    with left:
        st.subheader("Fraud rate by type - count vs value")
        st.caption("Only types where fraud occurs. Count and value can rank types differently.")
        by_type = query(env, """
            select a.txn_type,
                   100.0 * sum(a.fraud_count) / sum(a.txn_count)          as "By count",
                   100.0 * sum(a.fraud_value_eur) / sum(a.txn_value_eur)  as "By value"
            from gold.agg_daily_by_type a
            join gold.dim_txn_type t using (txn_type)
            where t.can_be_fraud and a.event_date between ? and ?
            group by a.txn_type order by a.txn_type desc""", rng)
        long = by_type.melt(id_vars="txn_type", var_name="measure", value_name="fraud_rate_pct")
        st.altair_chart(charts.grouped_bar(long, "txn_type", "measure", "fraud_rate_pct",
                                           "Fraud rate (%)", mode, measures=["By count", "By value"],
                                           label_suffix="%"), width="stretch")
        table_view(by_type.round(4))

    with right:
        st.subheader("Weekly rule catch rate")
        st.caption("Headline metric. Weeks start on Monday; first and last weeks are partial.")
        weekly = query(env, """
            select week_start, caught, missed, false_alarms, catch_rate_pct, precision_pct
            from gold.agg_rule_performance order by week_start""")
        st.altair_chart(charts.line(weekly, "week_start", "catch_rate_pct", "Catch rate (%)", mode,
                                    y_format=".2f"), width="stretch")
        table_view(weekly)

    daily = query(env, """
        select event_date, fraud_count, fraud_value_lost_eur / 1e6 as fraud_value_lost_eur_m
        from gold.agg_daily_fraud where event_date between ? and ? order by event_date""", rng)
    left, right = st.columns(2)
    with left:
        st.subheader("Fraud transactions per day")
        st.altair_chart(charts.line(daily, "event_date", "fraud_count", "Fraud transactions", mode),
                        width="stretch")
    with right:
        st.subheader("Fraud value lost per day")
        st.altair_chart(charts.line(daily, "event_date", "fraud_value_lost_eur_m",
                                    "Fraud value lost (EUR m)", mode, y_format=",.1f"), width="stretch")
    table_view(daily, "Show daily data")

    st.subheader("Morning review list")
    st.warning("RISK ONLY - this list shows real (unmasked) customer IDs.", icon="🔒")
    days = query(env, "select distinct review_date from gold.rpt_suspicious_transactions order by 1 desc")
    review = st.selectbox("Review date", days.review_date.dt.date.tolist())
    morning = query(env, """
        select review_rank as "#", event_ts as "time", txn_type as "type", amount_eur, amount_usd,
               rule_outcome, sender_customer_id, receiver_id, receiver_type
        from gold.rpt_suspicious_transactions where review_date = ? order by review_rank""", (review,))
    st.caption(f"{len(morning)} transactions to review, largest first.")
    st.dataframe(morning, hide_index=True, width="stretch", height=380, column_config={
        "time": st.column_config.DatetimeColumn("Time (UTC)", format="DD MMM HH:mm"),
        "amount_eur": st.column_config.NumberColumn("Amount (EUR)", format="euro"),
        "amount_usd": st.column_config.NumberColumn("Amount (USD)", format="dollar"),
    })


# ---------------------------------------------------------------- Finance

def finance_view(env: str, mode: str) -> None:
    st.header("Finance - volumes and value")
    start, end = date_filter(env)
    rng = (start, end)

    k = query(env, """
        select sum(txn_count) as n, sum(txn_value_eur) as eur, sum(txn_value_usd) as usd
        from gold.agg_daily_by_type where event_date between ? and ?""", rng).iloc[0]
    lost = query(env, """select sum(fraud_value_lost_eur) as lost from gold.agg_daily_fraud
                         where event_date between ? and ?""", rng).lost[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Transactions", f"{int(k.n or 0):,}")
    c2.metric("Value (EUR)", money_m(k.eur))
    c3.metric("Value (USD)", money_m(k.usd), help="Converted per transaction at that day's ECB rate.")
    c4.metric("Fraud value lost (EUR)", money_m(lost))

    st.subheader("Daily volume by transaction type")
    measure = st.radio("Measure", ["Value (EUR m)", "Value (USD m)", "Transaction count"],
                       horizontal=True, label_visibility="collapsed")
    column, y_format = {"Value (EUR m)": ("txn_value_eur / 1e6", ",.0f"),
                        "Value (USD m)": ("txn_value_usd / 1e6", ",.0f"),
                        "Transaction count": ("txn_count", ",.0f")}[measure]
    daily = query(env, f"""
        select event_date, txn_type, {column} as value
        from gold.agg_daily_by_type where event_date between ? and ? order by event_date""", rng)
    st.altair_chart(charts.line(daily, "event_date", "value", measure, mode, series="txn_type",
                                domain=charts.TXN_TYPES, y_format=y_format, height=320),
                    width="stretch")
    st.caption("Volumes drop sharply after 17 Jan and on 3-4 Jan. This comes from the PaySim "
               "simulation itself (seen in source profiling), not from the pipeline - all rows "
               "are reconciled bronze to gold.")
    table_view(daily.pivot(index="event_date", columns="txn_type", values="value").reset_index())

    st.subheader("Monthly summary")
    monthly = query(env, """
        select strftime(date_trunc('month', event_date), '%Y-%m') as month, txn_type,
               sum(txn_count) as txn_count, sum(txn_value_eur) as txn_value_eur,
               sum(txn_value_usd) as txn_value_usd, sum(fraud_count) as fraud_count,
               sum(fraud_value_eur) as fraud_value_eur
        from gold.agg_daily_by_type where event_date between ? and ?
        group by all order by month, txn_value_eur desc""", rng)
    st.dataframe(monthly, hide_index=True, width="stretch", column_config={
        "txn_count": st.column_config.NumberColumn("Transactions", format="localized"),
        "txn_value_eur": st.column_config.NumberColumn("Value (EUR)", format="euro"),
        "txn_value_usd": st.column_config.NumberColumn("Value (USD)", format="dollar"),
        "fraud_count": st.column_config.NumberColumn("Fraud", format="localized"),
        "fraud_value_eur": st.column_config.NumberColumn("Fraud value (EUR)", format="euro"),
    })
    st.download_button("Download monthly summary (CSV)", monthly.to_csv(index=False).encode(),
                       file_name=f"monthly_summary_{start}_{end}.csv", mime="text/csv")


# ---------------------------------------------------------------- Operations

def operations_view(env: str) -> None:
    st.header("Operations - pipeline status")
    try:
        runs = query(env, """
            select run_id, status, started_at, finished_at, round(duration_s, 1) as duration_s, message, error_message
            from ops.pipeline_runs where step = 'pipeline' order by finished_at desc limit 50""")
    except Exception:
        st.info(f"No pipeline runs recorded yet. Run: `python run_pipeline.py --env {env}`")
        return
    if runs.empty:
        st.info(f"No pipeline runs recorded yet. Run: `python run_pipeline.py --env {env}`")
        return

    last = runs.iloc[0]
    ok = last.status == "success"
    last_ok = runs[runs.status == "success"]
    data_to = query(env, "select max(event_date) as d from gold.fact_transactions").d[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Last run", "✅ Success" if ok else "❌ Failed")
    c2.metric("Last run finished (UTC)", f"{utc(last.finished_at):%d %b %H:%M}")
    c3.metric("Duration", f"{last.duration_s:.0f} s")
    c4.metric("Data available up to", f"{data_to:%d %b %Y}")
    if not ok:
        st.error(f"Last run failed: {last.error_message}\n\nSee docs/runbook.md", icon="🚨")
    if not last_ok.empty:
        st.caption(f"Last successful run: {utc(last_ok.iloc[0].finished_at):%d %b %Y %H:%M} UTC")

    st.subheader("Recent runs")
    shown = runs.assign(result=runs.status.map({"success": "✅ success", "failed": "❌ failed"}),
                        started_at=runs.started_at.map(lambda t: f"{utc(t):%Y-%m-%d %H:%M:%S} UTC"))
    st.dataframe(shown[["run_id", "result", "started_at", "duration_s", "message", "error_message"]],
                 hide_index=True, width="stretch")

    st.subheader("Steps of a run")
    run_id = st.selectbox("Run", runs.run_id.tolist())
    steps = query(env, """
        select step, status, started_at, round(duration_s, 1) as duration_s, rows_in, rows_out,
               coalesce(error_message, message) as detail
        from ops.pipeline_runs where run_id = ? and step <> 'pipeline' order by started_at""", (run_id,))
    steps["status"] = steps.status.map({"success": "✅ success", "failed": "❌ failed"})
    steps["started_at"] = steps.started_at.map(lambda t: f"{utc(t):%H:%M:%S} UTC")
    st.dataframe(steps, hide_index=True, width="stretch")


# ---------------------------------------------------------------- layout

with st.sidebar:
    st.title("🏦 Neobank")
    env = st.radio("Environment", ["prod", "dev"], horizontal=True)
    roles = ["Risk", "Finance", "Operations"]
    requested = st.query_params.get("view", "Risk")  # bookmarkable: ?view=Finance
    role = st.radio("View as", roles, index=roles.index(requested) if requested in roles else 0)
    st.caption("Access is simulated: each team sees only its own view. Only Risk sees "
               "unmasked customer IDs (requirements §9).")
    if st.button("Refresh data"):
        st.cache_data.clear()

mode = theme_mode()
try:
    if role == "Risk":
        risk_view(env, mode)
    elif role == "Finance":
        finance_view(env, mode)
    else:
        operations_view(env)
except WarehouseUnavailable as exc:
    st.error(str(exc))

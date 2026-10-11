import duckdb

import run_pipeline
from common.config import EnvConfig
from common.run_log import RunLog
from run_pipeline import StepFailed, StepResult, run, summarise_dbt_results


def setup(tmp_path):
    cfg = EnvConfig("dev", tmp_path / "lake", tmp_path / "wh.duckdb", tmp_path / "src.csv")
    return cfg, RunLog(cfg.warehouse, "dev-test", "daily_pipeline", "dev")


def logged(cfg):
    with duckdb.connect(str(cfg.warehouse)) as con:
        return con.execute("select step, status from ops.pipeline_runs order by finished_at").fetchall()


def test_success_runs_all_steps_logs_them_and_sends_summary(tmp_path):
    cfg, log = setup(tmp_path)
    alerts, calls = [], []
    steps = [(n, lambda c, n=n: calls.append(n) or StepResult(rows_out=1, message="ok"))
             for n in ("a", "b")]

    assert run(cfg, steps, log, alerts.append) is True
    assert calls == ["a", "b"]
    assert logged(cfg) == [("a", "success"), ("b", "success"), ("pipeline", "success")]
    assert [a.severity for a in alerts] == ["info"]


def test_failure_stops_the_run_and_sends_one_critical_alert(tmp_path):
    cfg, log = setup(tmp_path)
    alerts, calls = [], []

    def boom(c):
        raise StepFailed("API down")

    steps = [("a", lambda c: calls.append("a") or StepResult()), ("b", boom),
             ("c", lambda c: calls.append("c") or StepResult())]

    assert run(cfg, steps, log, alerts.append) is False
    assert calls == ["a"]                                   # c never ran
    assert logged(cfg) == [("a", "success"), ("b", "failed"), ("pipeline", "failed")]
    assert len(alerts) == 1 and alerts[0].severity == "critical"
    assert alerts[0].step == "b" and "API down" in alerts[0].message


def test_simulated_failure(tmp_path):
    cfg, log = setup(tmp_path)
    alerts = []
    assert run(cfg, [("a", lambda c: StepResult())], log, alerts.append, simulate_failure="a") is False
    assert "Simulated failure" in alerts[0].message


def test_step_warnings_become_warning_alerts(tmp_path):
    cfg, log = setup(tmp_path)
    alerts = []
    run(cfg, [("a", lambda c: StepResult(warnings=["flag rule: 2 rows"]))], log, alerts.append)
    assert [a.severity for a in alerts] == ["warning", "info"]


def test_dbt_results_are_summarised():
    results = {"results": [
        {"unique_id": "model.neobank.transactions", "status": "success"},
        {"unique_id": "test.neobank.unique_txn_id.abc", "status": "fail", "failures": 3, "message": None},
        {"unique_id": "test.neobank.warn_rule.def", "status": "warn", "failures": 2},
        {"unique_id": "test.neobank.not_null.ghi", "status": "pass"},
    ]}
    failures, warnings, counts = summarise_dbt_results(results)
    assert failures == ["unique_txn_id.abc: 3 failing rows"]
    assert warnings == ["warn_rule.def: 2 rows"]
    assert counts == {"success": 1, "fail": 1, "warn": 1, "pass": 1}


def test_steps_are_in_dependency_order():
    assert [name for name, _ in run_pipeline.STEPS] == ["paysim_to_bronze", "fx_rates_to_bronze", "dbt_build"]

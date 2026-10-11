# Runbook – Daily Pipeline

What to do when an alert fires. Alerts link here from their **"What to check"** field.

## How the pipeline runs

```powershell
python run_pipeline.py --env prod
```

Steps run in order and the run **stops at the first failure**:

| # | Step | What it does |
|---|---|---|
| 1 | `paysim_to_bronze` | Loads the PaySim CSV into bronze (skipped if already loaded) and checks every row arrived |
| 2 | `fx_rates_to_bronze` | Loads new FX rates from the Frankfurter API (incremental, retries 5 times) |
| 3 | `dbt_build` | Builds silver and gold and runs all data quality tests |

Every step is recorded in `ops.pipeline_runs`. Exit code `0` = success, `1` = failure.

**Re-running is always safe**: every step is idempotent, so after fixing a problem just run the
pipeline again. Completed work is skipped, nothing is duplicated.

## Alert levels

| Level | Meaning | Response |
|---|---|---|
| 🔴 CRITICAL | A step failed; data for today is **not** ready | Act now – Risk needs data by 08:00 |
| 🟠 WARNING | Pipeline finished, but a warning-level test found something | Investigate today |
| 🟢 INFO | Daily summary – all steps succeeded | None |

## Look at the run log

```python
import duckdb
con = duckdb.connect("data/prod/neobank.duckdb", read_only=True)
print(con.sql("""
    select run_id, step, status, started_at, duration_s, rows_out, error_message
    from ops.pipeline_runs order by finished_at desc limit 10
"""))
```

## paysim_to_bronze

| Symptom | Likely cause | Fix |
|---|---|---|
| `FileNotFoundError` | Source file missing from `data/landing/paysim/` | Ask the core system team to re-deliver the export; place it in the folder |
| `Incomplete load: X rows in bronze, Y in source file` | Crash or disk full during the load | Check disk space, then re-run with `python ingestion/paysim_to_bronze.py --source <file> --lake data/prod/lake --force` |
| `contains 0 rows` | Empty export delivered | Do not continue – contact the core system team |

## fx_rates_to_bronze

| Symptom | Likely cause | Fix |
|---|---|---|
| `FX API failed after 5 attempts (HTTP 5xx / Timeout)` | Frankfurter or the network is down | Check https://api.frankfurter.dev in a browser. Re-run later – the watermark resumes from the last loaded date |
| `HTTP 4xx` (not 429) | Our request is wrong (bad date, API changed) | Check the URL in the error; check the API docs for changes |
| Missing rate test fails in dbt afterwards | A date has no rate even after filling | Load the missing dates with `--start` / `--end`, then re-run |

## dbt_build

The alert lists the failing models/tests.

1. **Read the failing test name** – it says which table, column and check failed
   (e.g. `amount_within_limit_except_transfers`).
2. **Find the bad rows** – run the test's SQL against the table, e.g.
   `cd transform; dbt show --profiles-dir . --target prod --select <test_name>`
   or open `transform/target/compiled/neobank/tests/...` and run that SQL.
3. **Decide: is the data wrong or the rule wrong?**
   - Data wrong → fix at the source and re-run.
   - Rule wrong → confirm with the rule owner (see `docs/requirements.md`), update the test **and**
     the requirements change log.
4. **Never loosen or disable a test just to make the pipeline pass.**

| Common failure | Meaning |
|---|---|
| `assert_silver_row_count_matches_bronze` | Rows lost or duplicated between bronze and silver |
| `assert_fact_reconciles_to_silver` / `assert_aggregates_reconcile_to_fact` | Reports would disagree – do **not** publish dashboards until fixed |
| `assert_fx_rate_for_every_transaction_date` | FX data missing for a transaction date – see FX section |
| `warn_flagged_outside_known_rule` (warning) | Core system flagged transactions outside the known rule – inform Risk |

## Testing the alerts

```powershell
python run_pipeline.py --env dev --alerts --simulate-failure fx_rates_to_bronze
```

`--alerts` sends to Discord outside prod; `--simulate-failure` makes a step fail on purpose.

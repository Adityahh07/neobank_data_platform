# Neobank Data Platform

A local, end-to-end data engineering project that models the data platform of a
small digital bank: batch files, APIs, a core-banking database (CDC), streaming
card payments, reconciliation and fraud monitoring.

## Status

- [x] **Requirements** - stakeholder needs, KPI definitions, data rules: [docs/requirements.md](docs/requirements.md)
- [x] **Source profiling** - PaySim data checked against stakeholder assumptions: [analysis/profile_paysim.py](analysis/profile_paysim.py)
- [x] **Historical transactions (batch CSV -> bronze Parquet)**
- [x] **Architecture and data model design** - layers, tools, table designs, conventions: [docs/architecture.md](docs/architecture.md)
- [ ] FX rates API (Frankfurter)
- [ ] Core banking Postgres + CDC
- [ ] Card-payment stream (Kafka/Redpanda)
- [ ] Settlement file drop + reconciliation
- [ ] Silver/gold models (dbt), orchestration, dashboard

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest
```

## Step 1: PaySim -> bronze

1. Download the PaySim dataset from Kaggle: https://www.kaggle.com/datasets/ealaxi/paysim1
2. Unzip the CSV into `data/landing/paysim/`.
3. Run:

```powershell
python ingestion/paysim_to_bronze.py --source data/landing/paysim/PS_20174392719_1491204439457_log.csv
```

Output:

```
data/lake/bronze/paysim/
├── transactions/event_date=2025-01-01/part-<hash>.parquet   # one folder per day
└── _manifests/<sha256>.json                                  # what was loaded, row counts
```

Design choices:

- **Raw values kept as strings** - no float rounding of money; types are applied in silver.
- **Lineage columns** - `_source_file`, `_source_sha256`, `_source_row`, `_ingested_at`.
  PaySim has no transaction ID, so `(_source_sha256, _source_row)` identifies a row.
- **Idempotent** - a file is identified by its hash; re-runs skip it, `--force` overwrites
  the same files instead of appending duplicates.
- **Atomic publish** - files are written to a staging folder and only moved into the lake
  when the whole file has been processed.
- **Synthetic dates** - PaySim `step` is "hour N of a 30-day simulation"; it is anchored to
  2025-01-01 so the data can be partitioned by day.

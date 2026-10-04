# Requirements – Neobank Data Platform

| | |
|---|---|
| **Status** | Draft v2 – updated after profiling review, awaiting stakeholder sign-off |
| **Owner** | Data Engineering |
| **Stakeholders** | Priya (Head of Risk), Daniel (Finance Manager), Sara (Head of Operations) |
| **Last updated** | 2026-10-05 (see §19 change log) |

## 1. Business goal

Give the bank **one trusted source of transaction data** so that Risk can detect fraud the
next morning instead of a week later, Finance can report numbers that match to the cent, and
Operations knows immediately when data is late or broken.

## 2. Current state and pain points

| Team | How it works today | Pain |
|---|---|---|
| Risk | Analyst exports transactions to Excel every Monday and filters by hand | Fraud found ~1 week late; takes a full day; current rule's performance unknown |
| Finance | Each team writes its own queries; FX converted by hand | Totals differ between reports; no agreed source of truth |
| Operations | Manual exports, no monitoring | Failures go unnoticed until a report is empty |

## 3. Stakeholders and decisions

| Stakeholder | Decisions made with the data |
|---|---|
| Risk | Which accounts to block or investigate; whether fraud rules are good enough |
| Finance | Cash planning (liquidity for cash-outs); volume reporting to management and board |
| Operations | Whether data and reports are reliable and on time |

## 4. Business questions

1. What is the fraud rate per transaction type?
2. How much real fraud does the current rule block, and how much does it miss?
3. Is fraud rising or falling day by day? Are there spikes?
4. Which transactions from yesterday look suspicious and should be reviewed this morning?
5. What is the daily transaction count and value per type?
6. How much money moved in total, expressed in USD?
7. How much value was lost to fraud (fraud that was not blocked)?
8. Did today's data load complete, on time and with the expected number of rows?

## 5. Definitions

Agreed terms. Every report must use these exact definitions.

| Term | Definition |
|---|---|
| **Transaction count** | Number of transactions |
| **Transaction value** | Sum of `amount`. In management reports "volume" means **value**; reports must always label count vs. value |
| **Fraud transaction** (ground truth) | `isFraud = 1` – confirmed fraud |
| **Flagged transaction** | `isFlaggedFraud = 1` – the current rule fired at transaction time **and the core system blocked the transfer** (sender balance unchanged) |
| **Current fraud rule** | A single `TRANSFER` with `amount > 200,000` (local currency) that the core system **blocks**; set by the core system. *Verified in profiling: all 16 flagged rows match; 3 similar unflagged rows logged as exceptions (§16).* |
| **Fraud rate (by count)** | fraud transactions ÷ all transactions × 100 |
| **Fraud rate (by value)** | fraud value ÷ total value × 100 |
| **Caught** (true positive) | `isFlaggedFraud = 1` and `isFraud = 1` |
| **Missed** (false negative) | `isFlaggedFraud = 0` and `isFraud = 1` |
| **False alarm** (false positive) | `isFlaggedFraud = 1` and `isFraud = 0` |
| **Catch rate** (recall) | caught ÷ (caught + missed) |
| **Precision** | caught ÷ (caught + false alarms) |
| **Fraud value attempted** | Sum of `amount` where `isFraud = 1` |
| **Fraud value lost** | Sum of `amount` where `isFraud = 1` and `isFlaggedFraud = 0` (blocked fraud lost no money) |
| **Customer** | Account ID starting with `C` in `nameOrig` / `nameDest`. *Verified: IDs are unique, but 99.9% of senders appear only once – there is no per-customer history.* |
| **Merchant** | Account ID starting with `M`. Merchants have no balance data (zeros are expected) |
| **Day** | Calendar day derived from `step` (hour 1 = 2025-01-01 00:00 UTC) |

## 6. KPIs

| KPI | Definition | Audience | Frequency |
|---|---|---|---|
| Fraud rate by type | §5, by count and by value, split by `type` | Risk | Daily |
| Rule performance | Caught / missed / false alarms, catch rate, precision – **headline metric** | Risk | Weekly |
| Daily fraud trend | Fraud count, fraud value and fraud rate per day | Risk | Daily |
| Suspicious transactions | All flagged or confirmed-fraud transactions from the previous day, largest amount first | Risk | Daily by 08:00 |
| Daily count and value by type | §5 | Finance | Daily |
| Total value in USD | Value converted with that day's FX rate | Finance | Daily, monthly summary |
| Fraud value attempted / lost | §5 | Finance, Risk | Daily, monthly summary |
| Pipeline health | Load status, row counts, delivery time | Operations | Every run |

## 7. Data sources

| Source | Provided as | Frequency | Phase |
|---|---|---|---|
| Historical transactions (PaySim) | One-time CSV export from core system (~6.3M rows) | One-time | 1 |
| FX rates (Frankfurter API, ECB rates) | REST API, JSON | Every working day | 1 |
| Core banking database | Direct read access (Postgres) | Continuous (CDC) | 2 |
| Card-payment feed | Event stream | Live | 3 |
| Processor settlement files | File drop (CSV) | Daily | 3 |

## 8. Business rules for data handling

| Rule | Source |
|---|---|
| Money is stored as exact decimals; no floating-point rounding. Totals must match to the cent across all reports | Finance |
| All money totals are calculated from `amount` only – **never from balance columns** | Finance |
| Merchant (`M…`) zero balances are valid, not errors | Operations |
| Rows where balances don't add up are **kept and flagged** (`balance_mismatch`), never deleted or corrected | Operations, Finance |
| Zero-amount transactions are valid (fraud attempts on emptied accounts) and kept | Risk |
| Per-transaction limit is **10,000,000**; any `amount` above it is a data error and fails quality checks | Finance |
| `amount` must never be negative | Data Engineering |
| Raw data is never modified; all corrections happen in later layers (audit trail) | Data Engineering |
| Re-running a pipeline must never create duplicate transactions | Data Engineering |
| On weekends/holidays (no ECB rate), the most recent previous rate is used | Data Engineering – *to confirm with Finance* |

## 9. Access and privacy

| Group | Access |
|---|---|
| Risk | Full detail, including customer IDs |
| Finance, management | Aggregated data only – no customer IDs |
| Engineers | Masked customer IDs; unmasked only with approval for debugging |

- Customer IDs are pseudonymous codes but are classed as **personal data** and treated as sensitive.
- Merchant IDs are not sensitive.

## 10. Non-functional requirements

| Area | Requirement |
|---|---|
| Freshness | Daily data ready by **08:00** |
| Accuracy | Totals reconcile to the cent between layers and reports |
| Retention | Transaction history kept for **5 years** (regulatory) |
| Reliability | Pipelines are idempotent and can be re-run or backfilled for any past date |
| Auditability | Every row traceable to its source file and load time |

## 11. Monitoring and alerting

The team must know about problems **before** stakeholders do.

| Alert | Trigger | Severity |
|---|---|---|
| Pipeline failure | Any pipeline step fails after retries | Critical |
| Late data | Daily load not finished by **07:30** (30 min before the 08:00 deadline) | Critical |
| Data quality failure | Any data quality test fails (e.g. null amounts, duplicate IDs, amount > 10,000,000) | Critical / Warning per test |
| Empty or incomplete load | A load finishes with 0 rows, or rows loaded ≠ rows in the source file | Critical |
| Volume anomaly | Daily row count far from normal. **Disabled for the historical PaySim file** (daily volume ranges from 272 to 574,255 rows); threshold to be tuned once live data arrives | Warning |
| Reconciliation break | Row count or total value differs between layers (Phase 3: ledger vs. settlement) | Critical |
| Daily summary | Run status, rows loaded, duration | Info |

Alert requirements:

- Every alert states: pipeline, step, time, run ID, error message and what to check.
- Critical alerts are sent immediately; Info is a single daily message.
- The same failure must not re-alert on every retry (no alert spam).
- Every run (success or failure) is logged in a run-history table for the Operations status view.

## 12. Deliverables

| Deliverable | For |
|---|---|
| Trusted transaction tables (bronze → silver → gold) | All |
| Fraud dashboard: rule performance (headline), fraud rate by type, daily trend | Risk |
| Daily suspicious-transactions table | Risk |
| Finance dashboard: daily count and value by type, USD totals, fraud value attempted/lost, exportable monthly view | Finance |
| Pipeline status view + alerts | Operations |
| Documentation: data dictionary, lineage, runbook | All |

## 13. Priority (proposed – for approval)

Risk and Finance both requested first delivery. Proposal: build the shared foundation first,
since both depend on it.

1. **Foundation** – trusted transaction data (bronze/silver), data quality tests, failure alerts
2. **Risk** – fraud dashboard and daily suspicious-transactions table
3. **Finance** – FX rates, USD totals, finance dashboard
4. **Operations** – status view, full alerting
5. **Later phases** – core banking CDC, card stream, settlement reconciliation

## 14. Success criteria

| Stakeholder | The project worked if... |
|---|---|
| Risk | Fraud is visible the **next morning** instead of a week later |
| Finance | Finance and Risk totals **match to the cent** – one agreed number |
| Operations | Data ready by 08:00 daily, and failures are alerted before anyone notices |

## 15. Assumptions

- PaySim `step` = hour of a 30-day simulation; anchored to 2025-01-01 (synthetic dates).
- PaySim amounts are in the local currency, assumed to be **EUR** so ECB rates can convert to USD/GBP.
- All fraud labels in the historical file are **final** (all cases closed).
- `isFlaggedFraud` is set by the source system; the pipeline receives it, not calculates it.
- Unflagged fraud is assumed to be money lost; blocked (flagged) fraud lost nothing.
- Balance columns are unreliable in the source and are not used for any financial figure.

## 16. Open items

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Verify that one customer ID = one customer | Data Engineering | ✅ Closed – IDs unique; customers almost never repeat (6,353,307 distinct senders in 6,362,620 rows) |
| 2 | Verify flags match the stated rule | Data Engineering | ✅ Closed – rule redefined as "blocked TRANSFER > 200,000" (§5) |
| 3 | Define the daily suspicious list | Risk | ✅ Closed – suspicious **transactions**, not accounts (§6) |
| 4 | Confirm weekend/holiday FX rate handling | Finance | Open |
| 5 | Confirm local currency (assumed EUR) | Finance | Open |
| 6 | Choose alert channel | Operations | ✅ Closed – Discord (set up in the alerting step) |
| 7 | 3 TRANSFERs > 200,000 with unchanged sender balance were **not** flagged – why? | Risk → core system team | Open |

## 17. Out of scope / stretch goals

**Out of scope (now):**

- Building machine-learning fraud models (data science work).
- Blocking accounts automatically.

**Stretch goals:**

- **Own fraud rule** – "account emptied": a `TRANSFER` or `CASH_OUT` where the sender's new balance becomes 0
  and `amount > 100,000`, written in SQL. (A TRANSFER → CASH_OUT linking rule is not possible: profiling
  showed accounts almost never reappear, so the two steps can't be joined by account ID.)
  - Predictions stored in a `fraud_predictions` table with `rule_version` and `predicted_at`.
  - Designed on days 1–20, evaluated on days 21–31 (time split, no data leakage).
  - Compared with the current rule on the fraud dashboard.
- **Late-arriving labels** – with live data, fraud labels arrive up to 60 days late. The pipeline must allow
  labels to be updated afterwards and mark fraud metrics for recent days as provisional.

## 18. Sign-off

| Stakeholder | Role | Approved | Date |
|---|---|---|---|
| Priya | Head of Risk | ☐ | |
| Daniel | Finance Manager | ☐ | |
| Sara | Head of Operations | ☐ | |

## 19. Change log

| Version | Date | Change | Reason |
|---|---|---|---|
| v1 | 2026-10-04 | Initial draft from stakeholder interviews | – |
| v2 | 2026-10-05 | Fraud rule redefined as *blocked* TRANSFER > 200,000 | Profiling: 409,094 transfers > 200,000 were not flagged; flagged rows have unchanged balances |
| v2 | 2026-10-05 | "Fraud value" split into *attempted* and *lost* | Blocked fraud loses no money (Risk) |
| v2 | 2026-10-05 | Suspicious accounts → suspicious transactions | Profiling: customers almost never repeat |
| v2 | 2026-10-05 | Stretch rule changed to "account emptied" | TRANSFER → CASH_OUT can't be linked by account ID |
| v2 | 2026-10-05 | Added rules: totals from `amount` only, 10M limit, zero amounts valid | Profiling: unreliable balances, 10M cap, 16 zero-amount fraud cash-outs |
| v2 | 2026-10-05 | Row-count alert replaced by load-completeness check; volume anomaly disabled for PaySim | Profiling: daily rows range from 272 to 574,255 |

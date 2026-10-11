-- Every report table must add up to the fact table, so Finance and Risk numbers always
-- agree (the "one number" success criterion, docs/requirements.md §14).
with fact as (
    select count(*) as txn_count, sum(amount_eur) as value_eur, sum(amount_usd) as value_usd,
           count(*) filter (where is_fraud) as fraud_count
    from {{ ref('fact_transactions') }}
),
by_type as (
    select sum(txn_count) as txn_count, sum(txn_value_eur) as value_eur,
           sum(txn_value_usd) as value_usd, sum(fraud_count) as fraud_count
    from {{ ref('agg_daily_by_type') }}
),
daily_fraud as (
    select sum(txn_count) as txn_count, sum(fraud_count) as fraud_count
    from {{ ref('agg_daily_fraud') }}
),
rule as (
    select sum(txn_count) as txn_count, sum(caught + missed) as fraud_count
    from {{ ref('agg_rule_performance') }}
)
select 'agg_daily_by_type' as report, b.txn_count, b.value_eur, b.value_usd, b.fraud_count
from by_type b, fact f
where b.txn_count <> f.txn_count or b.value_eur <> f.value_eur
   or b.value_usd <> f.value_usd or b.fraud_count <> f.fraud_count
union all
select 'agg_daily_fraud', d.txn_count, null, null, d.fraud_count
from daily_fraud d, fact f
where d.txn_count <> f.txn_count or d.fraud_count <> f.fraud_count
union all
select 'agg_rule_performance', r.txn_count, null, null, r.fraud_count
from rule r, fact f
where r.txn_count <> f.txn_count or r.fraud_count <> f.fraud_count

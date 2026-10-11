-- One row per day: Risk's daily fraud trend and Finance's fraud value.
-- Fraud value lost excludes flagged (blocked) fraud (docs/requirements.md §5).

select
    event_date,
    count(*)                                                       as txn_count,
    count(*) filter (where is_fraud)                               as fraud_count,
    count(*) filter (where is_flagged)                             as flagged_count,
    round(100.0 * count(*) filter (where is_fraud) / count(*), 4)  as fraud_rate_count_pct,
    coalesce(sum(amount_eur) filter (where is_fraud), 0)           as fraud_value_attempted_eur,
    coalesce(sum(amount_eur) filter (where is_fraud and not is_flagged), 0) as fraud_value_lost_eur,
    coalesce(sum(amount_usd) filter (where is_fraud and not is_flagged), 0) as fraud_value_lost_usd
from {{ ref('fact_transactions') }}
group by event_date

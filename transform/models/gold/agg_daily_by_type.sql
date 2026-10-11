-- One row per day per transaction type: Finance volumes and Risk fraud rate by type.
-- "Count" and "value" are always reported separately (docs/requirements.md §5).

select
    event_date,
    txn_type,
    count(*)                                            as txn_count,
    sum(amount_eur)                                     as txn_value_eur,
    sum(amount_usd)                                     as txn_value_usd,
    count(*) filter (where is_fraud)                    as fraud_count,
    coalesce(sum(amount_eur) filter (where is_fraud), 0) as fraud_value_eur,
    round(100.0 * count(*) filter (where is_fraud) / count(*), 4)            as fraud_rate_count_pct,
    round(100.0 * coalesce(sum(amount_eur) filter (where is_fraud), 0)
          / nullif(sum(amount_eur), 0), 4)                                   as fraud_rate_value_pct
from {{ ref('fact_transactions') }}
group by event_date, txn_type

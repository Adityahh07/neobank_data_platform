-- Risk's morning review list: every flagged or confirmed-fraud transaction,
-- listed for review the morning after it happened, largest amount first.
-- Joins the restricted pii.customer_map - Risk-only report (docs/requirements.md §9).

select
    cast(f.event_date + interval 1 day as date)  as review_date,
    f.event_ts,
    f.txn_id,
    f.txn_type,
    f.amount_eur,
    f.amount_usd,
    f.rule_outcome,
    s.customer_id                                as sender_customer_id,
    coalesce(r.customer_id, f.receiver_key)      as receiver_id,
    f.receiver_type,
    row_number() over (
        partition by f.event_date order by f.amount_eur desc, f.txn_id
    )                                            as review_rank
from {{ ref('fact_transactions') }} f
left join {{ ref('customer_map') }} s on s.customer_key = f.sender_key
left join {{ ref('customer_map') }} r on r.customer_key = f.receiver_key
where f.is_flagged or f.is_fraud

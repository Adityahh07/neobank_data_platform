-- One row per transaction, enriched with the USD amount and the fraud-rule outcome.
-- Definitions: docs/requirements.md §5.

with transactions as (
    select * from {{ ref('transactions') }}
),

usd_rates as (
    select rate_date, rate from {{ ref('fx_rates') }} where quote_currency = 'USD'
)

select
    t.txn_id,
    t.event_ts,
    t.event_date,
    t.txn_type,
    t.amount_eur,
    r.rate                                              as eur_usd_rate,
    -- converted per transaction and rounded to the cent (half away from zero)
    cast(round(t.amount_eur * r.rate, 2) as decimal(18, 2)) as amount_usd,
    t.is_fraud,
    t.is_flagged,
    case
        when t.is_fraud and t.is_flagged then 'caught'
        when t.is_fraud                  then 'missed'
        when t.is_flagged                then 'false_alarm'
        else 'clean'
    end                                                 as rule_outcome,
    t.balance_mismatch,
    t.sender_key,
    t.receiver_key,
    t.receiver_type
from transactions t
left join usd_rates r on r.rate_date = t.event_date

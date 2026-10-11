-- One row per week (Monday start): how the core-system fraud rule performed.
-- Risk's headline metric (docs/requirements.md §6).

with weekly as (
    select
        d.week_start,
        count(*) filter (where f.rule_outcome = 'caught')      as caught,
        count(*) filter (where f.rule_outcome = 'missed')      as missed,
        count(*) filter (where f.rule_outcome = 'false_alarm') as false_alarms,
        count(*) filter (where f.is_fraud)                     as total_fraud,
        count(*)                                               as txn_count
    from {{ ref('fact_transactions') }} f
    join {{ ref('dim_date') }} d on d.date_key = f.event_date
    group by d.week_start
)

select
    week_start,
    caught,
    missed,
    false_alarms,
    total_fraud,
    txn_count,
    -- of all real fraud, how much did the rule find?
    round(100.0 * caught / nullif(caught + missed, 0), 2)       as catch_rate_pct,
    -- when the rule fires, how often is it right? (null when it never fired)
    round(100.0 * caught / nullif(caught + false_alarms, 0), 2) as precision_pct
from weekly

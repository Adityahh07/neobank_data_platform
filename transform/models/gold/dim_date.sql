-- One row per calendar day covered by the transactions.

with bounds as (
    select min(event_date) as first_day, max(event_date) as last_day
    from {{ ref('transactions') }}
),

days as (
    select cast(day as date) as date_key
    from bounds, range(first_day, last_day + interval 1 day, interval 1 day) as t(day)
)

select
    date_key,
    year(date_key)                          as year,
    month(date_key)                         as month,
    monthname(date_key)                     as month_name,
    weekofyear(date_key)                    as iso_week,
    cast(date_trunc('week', date_key) as date) as week_start,
    isodow(date_key)                        as day_of_week,
    dayname(date_key)                       as day_name,
    isodow(date_key) in (6, 7)              as is_weekend
from days

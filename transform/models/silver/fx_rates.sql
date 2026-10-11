-- One row per calendar day per quote currency. The ECB publishes no rates on
-- weekends and holidays; those days carry forward the last published rate and
-- are marked is_filled (docs/requirements.md §8, agreed with Finance).

with published as (
    select
        cast(rate_date as date)                                         as rate_date,
        base_currency,
        quote_currency,
        cast(json_extract_string(rates_json, '$.' || quote_currency) as decimal(18, 8)) as rate
    from {{ source('bronze_fx', 'rates') }}
    cross join unnest({{ var('fx_quote_currencies') }}) as q(quote_currency)
),

calendar as (
    select cast(day as date) as rate_date
    from range(
        (select min(rate_date) from published),
        (select max(rate_date) from published) + interval 1 day,
        interval 1 day
    ) as t(day)
),

spine as (
    select c.rate_date, q.quote_currency
    from calendar c
    cross join unnest({{ var('fx_quote_currencies') }}) as q(quote_currency)
)

select
    s.rate_date,
    'EUR'                                                               as base_currency,
    s.quote_currency,
    last_value(p.rate ignore nulls) over (
        partition by s.quote_currency order by s.rate_date
        rows between unbounded preceding and current row
    )                                                                   as rate,
    p.rate is null                                                      as is_filled
from spine s
left join published p
    on p.rate_date = s.rate_date and p.quote_currency = s.quote_currency

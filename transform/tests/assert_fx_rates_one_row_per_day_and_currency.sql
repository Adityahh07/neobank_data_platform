-- Grain check: exactly one rate per calendar day per currency.
select rate_date, quote_currency, count(*) as n
from {{ ref('fx_rates') }}
group by 1, 2
having count(*) > 1

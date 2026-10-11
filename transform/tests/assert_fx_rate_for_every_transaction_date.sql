-- Every transaction date must have a rate in every quote currency, otherwise
-- USD/GBP totals would silently drop transactions (docs/architecture.md §5).
select t.event_date, q.quote_currency
from (select distinct event_date from {{ ref('transactions') }}) t
cross join unnest({{ var('fx_quote_currencies') }}) as q(quote_currency)
left join {{ ref('fx_rates') }} f
    on f.rate_date = t.event_date and f.quote_currency = q.quote_currency
where f.rate is null

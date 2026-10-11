-- Gold must contain exactly the silver transactions: same row count and the same
-- EUR total to the cent (docs/architecture.md §5). Returns a row when they differ.
select s.n as silver_rows, f.n as fact_rows, s.total as silver_eur, f.total as fact_eur
from (select count(*) as n, sum(amount_eur) as total from {{ ref('transactions') }}) s
cross join (select count(*) as n, sum(amount_eur) as total from {{ ref('fact_transactions') }}) f
where s.n <> f.n or s.total <> f.total

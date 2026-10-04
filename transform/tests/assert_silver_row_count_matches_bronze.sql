-- Silver must contain exactly one row per bronze row: nothing dropped, nothing duplicated.
-- Returns a row (= test failure) when the counts differ.
select b.n as bronze_rows, s.n as silver_rows
from (select count(*) as n from {{ source('bronze_paysim', 'transactions') }}) b
cross join (select count(*) as n from {{ ref('transactions') }}) s
where b.n <> s.n

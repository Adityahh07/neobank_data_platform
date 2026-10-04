-- Restricted lookup from masked key back to the real customer ID.
-- Only Risk-facing reports may join to this (docs/requirements.md §9).

select distinct {{ mask_id('nameOrig') }} as customer_key, nameOrig as customer_id
from {{ source('bronze_paysim', 'transactions') }}

union

select distinct {{ mask_id('nameDest') }}, nameDest
from {{ source('bronze_paysim', 'transactions') }}
where nameDest like 'C%'

-- One row per transaction type. Reference data maintained by hand in
-- seeds/txn_types.csv (can_be_fraud: fraud only occurs on TRANSFER and CASH_OUT).

select
    txn_type,
    direction,
    cast(can_be_fraud as boolean) as can_be_fraud,
    description
from {{ ref('txn_types') }}

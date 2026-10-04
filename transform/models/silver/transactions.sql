-- One row per transaction: typed, masked, flagged. Rows are never dropped here;
-- quality problems are flagged (docs/requirements.md §8, docs/architecture.md §4.2).

with bronze as (
    select * from {{ source('bronze_paysim', 'transactions') }}
),

typed as (
    select
        cast(step as integer)                     as step,
        type                                      as txn_type,
        cast(amount as decimal(18, 2))            as amount_eur,
        nameOrig                                  as sender_id,
        nameDest                                  as receiver_id,
        cast(oldbalanceOrg as decimal(18, 2))     as sender_balance_before,
        cast(newbalanceOrig as decimal(18, 2))    as sender_balance_after,
        cast(oldbalanceDest as decimal(18, 2))    as receiver_balance_before,
        cast(newbalanceDest as decimal(18, 2))    as receiver_balance_after,
        isFraud = '1'                             as is_fraud,
        isFlaggedFraud = '1'                      as is_flagged,
        _source_file,
        _source_sha256,
        _source_row,
        _ingested_at
    from bronze
)

select
    sha256(_source_sha256 || ':' || cast(_source_row as varchar))         as txn_id,
    timestamp '{{ var("simulation_start") }}' + to_hours(step - 1)        as event_ts,
    cast(timestamp '{{ var("simulation_start") }}' + to_hours(step - 1) as date) as event_date,
    txn_type,
    amount_eur,
    {{ mask_id('sender_id') }}                                            as sender_key,
    case when receiver_id like 'M%' then receiver_id
         else {{ mask_id('receiver_id') }} end                            as receiver_key,
    case when receiver_id like 'M%' then 'merchant' else 'customer' end   as receiver_type,
    sender_balance_before,
    sender_balance_after,
    receiver_balance_before,
    receiver_balance_after,
    is_fraud,
    is_flagged,
    case
        when txn_type = 'CASH_IN'
            then sender_balance_before + amount_eur <> sender_balance_after
        else sender_balance_before - amount_eur <> sender_balance_after
    end                                                                   as balance_mismatch,
    _source_file,
    _source_sha256,
    _source_row,
    _ingested_at
from typed

{{ config(severity = 'warn') }}

-- Flagged transactions should follow the core-system rule: TRANSFER over 200,000
-- (docs/requirements.md §5). A warning, not an error: the rule is owned by another team.
select txn_id, txn_type, amount_eur
from {{ ref('transactions') }}
where is_flagged
  and not (txn_type = 'TRANSFER' and amount_eur > {{ var('flag_rule_min_amount') }})

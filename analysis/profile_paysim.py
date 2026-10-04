"""Profile the raw PaySim CSV before building pipelines on it.

Answers: size, nulls, duplicates, value ranges, and checks the stakeholders'
claims (open items in docs/requirements.md) against the actual data.

Usage:
  python analysis/profile_paysim.py [path/to/paysim.csv]
"""

import sys

import duckdb

CSV = sys.argv[1] if len(sys.argv) > 1 else (
    "data/landing/paysim/PS_20174392719_1491204439457_log.csv"
)

con = duckdb.connect()
# Money is read as exact DECIMAL so balance checks aren't fooled by float rounding.
con.execute(f"""
    CREATE VIEW tx AS SELECT * FROM read_csv('{CSV}', header = true, columns = {{
        'step': 'INTEGER', 'type': 'VARCHAR', 'amount': 'DECIMAL(18,2)',
        'nameOrig': 'VARCHAR', 'oldbalanceOrg': 'DECIMAL(18,2)', 'newbalanceOrig': 'DECIMAL(18,2)',
        'nameDest': 'VARCHAR', 'oldbalanceDest': 'DECIMAL(18,2)', 'newbalanceDest': 'DECIMAL(18,2)',
        'isFraud': 'INTEGER', 'isFlaggedFraud': 'INTEGER'
    }})
""")
con.execute("CREATE TABLE t AS SELECT * FROM tx")  # load once, query many times

CHECKS = {
    "1. Size and time range": """
        SELECT count(*) AS rows, min(step) AS first_step, max(step) AS last_step,
               count(DISTINCT step) AS distinct_steps
        FROM t""",
    "2. Null values per column": """
        SELECT count(*) - count(step) AS step, count(*) - count(type) AS type,
               count(*) - count(amount) AS amount, count(*) - count(nameOrig) AS nameOrig,
               count(*) - count(nameDest) AS nameDest, count(*) - count(isFraud) AS isFraud
        FROM t""",
    "3. Exact duplicate rows": """
        SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM t)) AS duplicate_rows
        FROM t""",
    "4. Transaction types: count, value, fraud": """
        SELECT type, count(*) AS tx_count, sum(amount) AS tx_value,
               sum(isFraud) AS fraud_count,
               round(100.0 * sum(isFraud) / count(*), 4) AS fraud_rate_pct
        FROM t GROUP BY type ORDER BY tx_count DESC""",
    "5. Amount ranges": """
        SELECT min(amount) AS min_amount, max(amount) AS max_amount,
               round(avg(amount), 2) AS avg_amount,
               count(*) FILTER (WHERE amount = 0) AS zero_amounts,
               count(*) FILTER (WHERE amount < 0) AS negative_amounts
        FROM t""",
    "6. Rows per day (first and last days)": """
        WITH d AS (
            SELECT DATE '2025-01-01' + CAST((step - 1) // 24 AS INTEGER) AS day, count(*) AS rows
            FROM t GROUP BY day
        )
        SELECT count(*) AS days, min(rows) AS min_rows_per_day, max(rows) AS max_rows_per_day,
               arg_min(day, rows) AS quietest_day, arg_max(day, rows) AS busiest_day
        FROM d""",
    "7. OPEN ITEM 1 - Customer ID uniqueness (senders)": """
        SELECT count(*) AS rows, count(DISTINCT nameOrig) AS distinct_senders,
               count(*) - count(DISTINCT nameOrig) AS repeat_sender_rows,
               max(n) AS max_tx_by_one_sender
        FROM t JOIN (SELECT nameOrig AS id, count(*) AS n FROM t GROUP BY 1) c ON c.id = t.nameOrig""",
    "7b. Account prefixes (C = customer, M = merchant)": """
        SELECT 'sender' AS side, left(nameOrig, 1) AS prefix, count(*) AS rows FROM t GROUP BY 1, 2
        UNION ALL
        SELECT 'receiver', left(nameDest, 1), count(*) FROM t GROUP BY 1, 2
        ORDER BY side, prefix""",
    "7c. Accounts that both send and receive": """
        SELECT count(*) AS ids_seen_as_sender_and_receiver
        FROM (SELECT DISTINCT nameOrig AS id FROM t) s
        JOIN (SELECT DISTINCT nameDest AS id FROM t) r USING (id)""",
    "8. OPEN ITEM 2 - Does the flag follow 'TRANSFER and amount > 200,000'?": """
        SELECT
            count(*) FILTER (WHERE isFlaggedFraud = 1) AS flagged_rows,
            count(*) FILTER (WHERE isFlaggedFraud = 1 AND type = 'TRANSFER' AND amount > 200000)
                AS flagged_matching_rule,
            count(*) FILTER (WHERE type = 'TRANSFER' AND amount > 200000) AS rows_matching_rule,
            count(*) FILTER (WHERE type = 'TRANSFER' AND amount > 200000 AND isFlaggedFraud = 0)
                AS matching_rule_but_not_flagged
        FROM t""",
    "8b. Flagged transactions: details": """
        SELECT type, min(amount) AS min_amount, max(amount) AS max_amount, count(*) AS n,
               sum(isFraud) AS really_fraud,
               min(oldbalanceOrg) AS min_old_bal, max(oldbalanceOrg) AS max_old_bal,
               count(*) FILTER (WHERE oldbalanceOrg = newbalanceOrig) AS balance_unchanged
        FROM t WHERE isFlaggedFraud = 1 GROUP BY type""",
    "9. Rule performance (confusion matrix)": """
        SELECT
            count(*) FILTER (WHERE isFlaggedFraud = 1 AND isFraud = 1) AS caught,
            count(*) FILTER (WHERE isFlaggedFraud = 0 AND isFraud = 1) AS missed,
            count(*) FILTER (WHERE isFlaggedFraud = 1 AND isFraud = 0) AS false_alarms,
            round(100.0 * count(*) FILTER (WHERE isFlaggedFraud = 1 AND isFraud = 1)
                  / count(*) FILTER (WHERE isFraud = 1), 2) AS catch_rate_pct
        FROM t""",
    "10. Balance consistency (sender side)": """
        SELECT type, count(*) AS rows,
               count(*) FILTER (WHERE oldbalanceOrg - amount <> newbalanceOrig
                                AND type IN ('PAYMENT','TRANSFER','CASH_OUT','DEBIT'))
                   AS debit_mismatch,
               count(*) FILTER (WHERE oldbalanceOrg + amount <> newbalanceOrig AND type = 'CASH_IN')
                   AS credit_mismatch,
               count(*) FILTER (WHERE oldbalanceOrg = 0 AND newbalanceOrig = 0) AS both_balances_zero
        FROM t GROUP BY type ORDER BY type""",
    "10b. Merchant receivers: are balances always zero?": """
        SELECT count(*) AS merchant_rows,
               count(*) FILTER (WHERE oldbalanceDest = 0 AND newbalanceDest = 0) AS zero_balances
        FROM t WHERE nameDest LIKE 'M%'""",
}

for title, sql in CHECKS.items():
    print(f"\n=== {title} ===")
    print(con.sql(sql))

import sys
from pathlib import Path

import pyarrow.dataset as ds

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingestion"))
from paysim_to_bronze import ingest  # noqa: E402

SAMPLE = """step,type,amount,nameOrig,oldbalanceOrg,newbalanceOrig,nameDest,oldbalanceDest,newbalanceDest,isFraud,isFlaggedFraud
1,PAYMENT,9839.64,C1231006815,170136.0,160296.36,M1979787155,0.0,0.0,0,0
1,TRANSFER,181.0,C1305486145,181.0,0.0,C553264065,0.0,0.0,1,0
25,CASH_OUT,229133.94,C905080434,15325.0,0.0,C476402209,5083.0,51513.44,0,0
"""


def make_sample(tmp_path: Path) -> Path:
    src = tmp_path / "paysim_sample.csv"
    src.write_text(SAMPLE)
    return src


def read_bronze(lake: Path):
    return ds.dataset(
        lake / "bronze" / "paysim" / "transactions", format="parquet", partitioning="hive"
    ).to_table()


def test_partitions_rows_by_day_and_keeps_raw_values(tmp_path):
    lake = tmp_path / "lake"
    manifest = ingest(make_sample(tmp_path), lake)

    # step 1 -> day 1, step 25 -> day 2 (steps are hours)
    assert manifest["partitions"] == {"2025-01-01": 2, "2025-01-02": 1}
    table = read_bronze(lake)
    assert table.num_rows == 3
    rows = sorted(table.to_pylist(), key=lambda r: r["_source_row"])
    assert rows[0]["amount"] == "9839.64"  # untouched string, no float rounding
    assert [r["_source_row"] for r in rows] == [1, 2, 3]


def test_rerun_is_skipped_and_force_does_not_duplicate(tmp_path):
    lake = tmp_path / "lake"
    src = make_sample(tmp_path)
    first = ingest(src, lake)

    assert ingest(src, lake) == first  # same file -> skipped
    ingest(src, lake, force=True)      # forced -> overwrites, no duplicates
    assert read_bronze(lake).num_rows == 3

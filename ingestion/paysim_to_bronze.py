"""Ingest the PaySim transactions CSV into the bronze layer of the data lake.

Bronze rules followed here:
  * Keep source values as they arrived (all strings) - typing happens in silver.
    This also means money is never silently turned into a float.
  * Add lineage metadata: source file, file hash, source row number, ingest time.
  * Idempotent: the same file (by SHA-256) is ingested once; re-runs are skipped
    unless --force, and a forced re-run overwrites the same output files.

Output layout (Hive-style partitions, readable by DuckDB/Spark/pandas):
  <lake>/bronze/paysim/transactions/event_date=YYYY-MM-DD/part-<hash8>.parquet
  <lake>/bronze/paysim/_manifests/<sha256>.json
"""

import argparse
import hashlib
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pv
import pyarrow.parquet as pq

SOURCE_COLUMNS = [
    "step", "type", "amount",
    "nameOrig", "oldbalanceOrg", "newbalanceOrig",
    "nameDest", "oldbalanceDest", "newbalanceDest",
    "isFraud", "isFlaggedFraud",
]

# PaySim's `step` is "hour N of a 30-day simulation" with no real calendar date.
# We anchor it to a fixed synthetic date so data can be partitioned by day.
SIMULATION_START = date(2025, 1, 1)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def step_to_date(step: str) -> str:
    return (SIMULATION_START + timedelta(hours=int(step) - 1)).isoformat()


def ingest(source: Path, lake: Path, force: bool = False) -> dict:
    file_hash = sha256_of(source)
    table_dir = lake / "bronze" / "paysim" / "transactions"
    manifest_path = lake / "bronze" / "paysim" / "_manifests" / f"{file_hash}.json"

    if manifest_path.exists() and not force:
        print(f"Skipping {source.name}: already ingested ({manifest_path.name})")
        return json.loads(manifest_path.read_text())

    reader = pv.open_csv(
        source,
        read_options=pv.ReadOptions(block_size=64 << 20),
        convert_options=pv.ConvertOptions(
            column_types={c: pa.string() for c in SOURCE_COLUMNS},
            include_columns=SOURCE_COLUMNS,
        ),
    )

    ingested_at = datetime.now(timezone.utc)
    part_name = f"part-{file_hash[:8]}.parquet"
    staging_dir = table_dir.parent / f"_staging_{file_hash[:8]}"
    shutil.rmtree(staging_dir, ignore_errors=True)

    writers: dict[str, pq.ParquetWriter] = {}
    rows_per_date: dict[str, int] = {}
    next_row = 1  # 1-based data row number in the source file (header excluded)

    try:
        for batch in reader:
            n = batch.num_rows
            if n == 0:
                continue
            dates = pa.array([step_to_date(s) for s in batch.column("step").to_pylist()])
            table = pa.Table.from_batches([batch])
            table = table.append_column(
                "_source_row", pa.array(range(next_row, next_row + n), pa.int64())
            )
            table = table.append_column("_source_file", pa.array([source.name] * n))
            table = table.append_column("_source_sha256", pa.array([file_hash] * n))
            table = table.append_column(
                "_ingested_at", pa.array([ingested_at] * n, pa.timestamp("us", tz="UTC"))
            )
            next_row += n

            for d in sorted(set(dates.to_pylist())):
                chunk = table.filter(pc.equal(dates, d))
                if d not in writers:
                    out = staging_dir / f"event_date={d}" / part_name
                    out.parent.mkdir(parents=True, exist_ok=True)
                    writers[d] = pq.ParquetWriter(out, chunk.schema, compression="zstd")
                writers[d].write_table(chunk)
                rows_per_date[d] = rows_per_date.get(d, 0) + chunk.num_rows
    finally:
        for w in writers.values():
            w.close()

    # Publish: move each staged partition file over the final one, so a crash
    # mid-run never leaves half-written data in the lake.
    for d in rows_per_date:
        final = table_dir / f"event_date={d}" / part_name
        final.parent.mkdir(parents=True, exist_ok=True)
        (staging_dir / f"event_date={d}" / part_name).replace(final)
    shutil.rmtree(staging_dir, ignore_errors=True)

    manifest = {
        "source_file": source.name,
        "source_sha256": file_hash,
        "ingested_at": ingested_at.isoformat(),
        "total_rows": next_row - 1,
        "partitions": dict(sorted(rows_per_date.items())),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Ingested {manifest['total_rows']:,} rows into {len(rows_per_date)} partitions")
    return manifest


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", type=Path, required=True, help="PaySim CSV file")
    p.add_argument("--lake", type=Path, default=Path("data/lake"), help="lake root")
    p.add_argument("--force", action="store_true", help="re-ingest an already seen file")
    args = p.parse_args()
    ingest(args.source, args.lake, args.force)


if __name__ == "__main__":
    main()

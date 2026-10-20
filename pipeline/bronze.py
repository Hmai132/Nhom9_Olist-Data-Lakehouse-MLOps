"""Load immutable CSV snapshots into the local DuckDB Bronze layer.

Each source file is identified by its SHA-256 digest. A repeated run reuses the
existing snapshot; a changed file creates a new snapshot and repoints its
stable Bronze view. Previous snapshots remain available for audit or replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_database(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS bronze")
    connection.execute("CREATE SCHEMA IF NOT EXISTS bronze_snapshots")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS bronze.ingestion_manifest (
            dataset VARCHAR NOT NULL,
            source_file VARCHAR NOT NULL,
            source_sha256 VARCHAR NOT NULL,
            source_bytes BIGINT NOT NULL,
            snapshot_table VARCHAR NOT NULL,
            row_count BIGINT NOT NULL,
            ingested_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
            is_current BOOLEAN NOT NULL,
            PRIMARY KEY (dataset, source_sha256)
        )
        """
    )


def load_source(
    connection: duckdb.DuckDBPyConnection, dataset: str, path: Path
) -> dict[str, str | int | bool]:
    source_hash = sha256_file(path)
    snapshot_name = f"{dataset}_{source_hash}"
    snapshot_ref = f'bronze_snapshots."{snapshot_name}"'
    current = connection.execute(
        """
        SELECT source_sha256, row_count
        FROM bronze.ingestion_manifest
        WHERE dataset = ? AND is_current
        """,
        [dataset],
    ).fetchone()

    if current is not None and current[0] == source_hash:
        return {"dataset": dataset, "rows": current[1], "changed": False}

    connection.execute("BEGIN TRANSACTION")
    try:
        existing = connection.execute(
            """
            SELECT row_count FROM bronze.ingestion_manifest
            WHERE dataset = ? AND source_sha256 = ?
            """,
            [dataset, source_hash],
        ).fetchone()
        if existing is None:
            # Keep every source column as text in Bronze. Types and business
            # rules belong to Silver; the snapshot is never updated in place.
            connection.execute(
                f"CREATE TABLE {snapshot_ref} AS "
                "SELECT * FROM read_csv(?, header = true, all_varchar = true)",
                [str(path)],
            )
            row_count = connection.execute(
                f"SELECT count(*) FROM {snapshot_ref}"
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO bronze.ingestion_manifest
                    (dataset, source_file, source_sha256, source_bytes,
                     snapshot_table, row_count, is_current)
                VALUES (?, ?, ?, ?, ?, ?, true)
                """,
                [
                    dataset,
                    path.name,
                    source_hash,
                    path.stat().st_size,
                    snapshot_name,
                    row_count,
                ],
            )
        else:
            row_count = existing[0]

        connection.execute(
            "UPDATE bronze.ingestion_manifest SET is_current = false "
            "WHERE dataset = ? AND source_sha256 <> ?",
            [dataset, source_hash],
        )
        connection.execute(
            f'CREATE OR REPLACE VIEW bronze."{dataset}" AS '
            f"SELECT * FROM {snapshot_ref}"
        )
        connection.execute("COMMIT")
    except Exception:
        connection.execute("ROLLBACK")
        raise

    return {"dataset": dataset, "rows": row_count, "changed": True}


def run(raw_dir: Path, database: Path) -> list[dict[str, str | int | bool]]:
    missing = [name for name in SOURCE_FILES.values() if not (raw_dir / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing source files: " + ", ".join(missing))

    database.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(database))
    try:
        prepare_database(connection)
        return [
            load_source(connection, dataset, raw_dir / filename)
            for dataset, filename in SOURCE_FILES.items()
        ]
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=PROJECT_ROOT / "data" / "raw")
    parser.add_argument(
        "--database", type=Path, default=PROJECT_ROOT / "data" / "warehouse" / "olist.duckdb"
    )
    args = parser.parse_args()
    print(json.dumps(run(args.raw_dir, args.database), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

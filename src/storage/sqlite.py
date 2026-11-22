
import sqlite3

from src.extraction.schemas import CompetitorOffer


DB_PATH = "data/monitoring.db"


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_url TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)


def save_snapshot(snapshot: CompetitorOffer) -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO snapshots (source_url, snapshot_json)
            VALUES (?, ?)
            """,
            (
                str(snapshot.source_url),
                snapshot.model_dump_json(),
            ),
        )


def get_latest_snapshot(source_url: str) -> CompetitorOffer | None:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT snapshot_json
            FROM snapshots
            WHERE source_url = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (source_url,),
        ).fetchone()

    if row is None:
        return None

    return CompetitorOffer.model_validate_json(row[0])

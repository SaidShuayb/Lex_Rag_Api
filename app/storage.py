import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional


class BatchStorage:
    """Small persistent SQLite store for idempotent batch records."""

    def __init__(self, db_path: Optional[str] = None):
        configured_path = db_path or os.getenv("BATCH_DB_PATH", "data/batches.sqlite3")
        self.db_path = Path(configured_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS batches ("
                "batch_id TEXT PRIMARY KEY, request_json TEXT NOT NULL, "
                "response_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(batches)")}
            if "status" not in columns:
                connection.execute("ALTER TABLE batches ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'")

    def _connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT request_json, response_json, status FROM batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        if row is None:
            return None
        return {"request": json.loads(row["request_json"]), "response": json.loads(row["response_json"]), "status": row["status"]}

    def create_batch(self, batch_id: str, request_data: Dict[str, Any]):
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO batches (batch_id, request_json, response_json, status) VALUES (?, ?, ?, ?)",
                (batch_id, json.dumps(request_data, ensure_ascii=False, sort_keys=True), "{}", "processing"),
            )

    def save_batch(self, batch_id: str, request_data: Dict[str, Any], response_data: Dict[str, Any]):
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO batches (batch_id, request_json, response_json, status) VALUES (?, ?, ?, 'completed') "
                "ON CONFLICT(batch_id) DO UPDATE SET response_json=excluded.response_json, status='completed'",
                (
                    batch_id,
                    json.dumps(request_data, ensure_ascii=False, sort_keys=True),
                    json.dumps(response_data, ensure_ascii=False, sort_keys=True),
                ),
            )

    def complete_batch(self, batch_id: str, response_data: Dict[str, Any]):
        with self._connect() as connection:
            connection.execute(
                "UPDATE batches SET response_json = ?, status = 'completed' WHERE batch_id = ?",
                (json.dumps(response_data, ensure_ascii=False, sort_keys=True), batch_id),
            )

    def list_processing(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT batch_id, request_json FROM batches WHERE status = 'processing'"
            ).fetchall()
        return [(row["batch_id"], json.loads(row["request_json"])) for row in rows]


batch_storage = BatchStorage()

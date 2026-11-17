import sqlite3
from contextlib import contextmanager
from pathlib import Path

class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute('''CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT NOT NULL,
                operator TEXT NOT NULL,
                offer_code TEXT NOT NULL,
                offer_label TEXT NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )''')

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def create_order(self, values: tuple) -> int:
        with self.connect() as con:
            cur = con.execute('''INSERT INTO orders
                (user_id, username, full_name, operator, offer_code, offer_label, amount)
                VALUES (?, ?, ?, ?, ?, ?, ?)''', values)
            return int(cur.lastrowid)

    def get_order(self, order_id: int):
        with self.connect() as con:
            return con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    def set_status(self, order_id: int, status: str, expected_status: str = "pending") -> bool:
        with self.connect() as con:
            cur = con.execute(
                "UPDATE orders SET status=? WHERE id=? AND status=?",
                (status, order_id, expected_status)
            )
            return cur.rowcount == 1

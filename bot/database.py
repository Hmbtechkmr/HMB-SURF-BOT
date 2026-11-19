import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL, username TEXT, full_name TEXT NOT NULL,
                operator TEXT NOT NULL, offer_code TEXT NOT NULL, offer_label TEXT NOT NULL,
                amount INTEGER NOT NULL, payment_method TEXT, status TEXT NOT NULL DEFAULT 'awaiting_proof',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS customers (
                user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
                first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, id)")

    @contextmanager
    def connect(self):
        # Une connexion par appel : sûr avec les traitements concurrents.
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA busy_timeout=30000")
            con.execute("PRAGMA synchronous=NORMAL")
            yield con
            con.commit()
        finally:
            con.close()

    def register_customer(self, user):
        with self.connect() as con:
            con.execute("""INSERT INTO customers(user_id,username,full_name)
                VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                last_seen=CURRENT_TIMESTAMP""",
                (user.id, user.username, user.full_name))

    def create_order(self, values):
        with self.connect() as con:
            cur = con.execute("""INSERT INTO orders
                (user_id,username,full_name,operator,offer_code,offer_label,amount)
                VALUES(?,?,?,?,?,?,?)""", values)
            return cur.lastrowid

    def set_payment_method(self, order_id, method):
        with self.connect() as con:
            con.execute("UPDATE orders SET payment_method=? WHERE id=? AND status='awaiting_proof'",
                        (method, order_id))

    def get_order(self, order_id):
        with self.connect() as con:
            return con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    def set_status(self, order_id, status, expected=None):
        with self.connect() as con:
            if expected:
                cur = con.execute("UPDATE orders SET status=? WHERE id=? AND status=?",
                                  (status, order_id, expected))
            else:
                cur = con.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
            return cur.rowcount == 1

    def recent_orders(self, limit=10):
        with self.connect() as con:
            return con.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def stats(self):
        with self.connect() as con:
            customers = con.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            total = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            pending = con.execute("SELECT COUNT(*) FROM orders WHERE status IN ('awaiting_proof','pending')").fetchone()[0]
            approved = con.execute("SELECT COUNT(*) FROM orders WHERE status IN ('approved','delivered')").fetchone()[0]
            revenue = con.execute("SELECT COALESCE(SUM(amount),0) FROM orders WHERE status IN ('approved','delivered')").fetchone()[0]
            return {"customers": customers, "orders": total, "pending": pending,
                    "approved": approved, "revenue": revenue}

    def customer_ids(self):
        with self.connect() as con:
            return [r[0] for r in con.execute("SELECT user_id FROM customers")]

    def add_message(self, user_id, role, content):
        with self.connect() as con:
            con.execute("INSERT INTO conversations(user_id,role,content) VALUES(?,?,?)",
                        (user_id, role, content[:8000]))

    def history(self, user_id, limit=12):
        with self.connect() as con:
            rows = con.execute("""SELECT role,content FROM conversations
                WHERE user_id=? ORDER BY id DESC LIMIT ?""", (user_id, limit)).fetchall()
            return list(reversed(rows))

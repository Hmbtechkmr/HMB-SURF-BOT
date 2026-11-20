import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STATUSES = ("awaiting_proof", "pending", "approved", "delivered",
            "rejected", "cancelled", "refunded", "expired")


def normalize_question(text):
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = "".join(c if c.isalnum() or c.isspace() else " " for c in text)
    return " ".join(text.split())


class Database:
    def __init__(self, path):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    @contextmanager
    def connect(self):
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

    def _columns(self, con, table):
        return {row["name"] for row in con.execute(f"PRAGMA table_info({table})")}

    def _migrate(self):
        with self.connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT, user_id INTEGER NOT NULL, username TEXT, full_name TEXT NOT NULL,
                operator TEXT NOT NULL, offer_code TEXT NOT NULL, offer_label TEXT NOT NULL,
                amount INTEGER NOT NULL, payment_method TEXT, status TEXT NOT NULL DEFAULT 'awaiting_proof',
                note TEXT, stock_code TEXT, reminded_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS customers (
                user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT, lang TEXT,
                first_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                role TEXT NOT NULL, content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT, offer_code TEXT NOT NULL, code TEXT NOT NULL,
                order_id INTEGER, used_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS faq (
                id INTEGER PRIMARY KEY AUTOINCREMENT, question TEXT NOT NULL UNIQUE,
                answer TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            con.execute("""CREATE TABLE IF NOT EXISTS seen_updates (
                update_id INTEGER PRIMARY KEY, seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")

            order_columns = self._columns(con, "orders")
            for name, ddl in (
                ("code", "TEXT"), ("note", "TEXT"), ("stock_code", "TEXT"), ("reminded_at", "TEXT"),
            ):
                if name not in order_columns:
                    con.execute(f"ALTER TABLE orders ADD COLUMN {name} {ddl}")
            if "lang" not in self._columns(con, "customers"):
                con.execute("ALTER TABLE customers ADD COLUMN lang TEXT")

            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_code ON orders(code)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_stock_offer ON stock(offer_code, used_at)")

    # --- updates ---
    def mark_update(self, update_id):
        with self.connect() as con:
            cur = con.execute("INSERT OR IGNORE INTO seen_updates(update_id) VALUES(?)", (update_id,))
            return cur.rowcount == 1

    # --- clients ---
    def register_customer(self, user, lang=None):
        with self.connect() as con:
            con.execute("""INSERT INTO customers(user_id,username,full_name,lang)
                VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username, full_name=excluded.full_name,
                lang=COALESCE(customers.lang, excluded.lang),
                last_seen=CURRENT_TIMESTAMP""",
                (user.id, user.username, user.full_name, lang))

    def set_lang(self, user_id, lang):
        with self.connect() as con:
            con.execute("UPDATE customers SET lang=? WHERE user_id=?", (lang, user_id))

    def get_lang(self, user_id):
        with self.connect() as con:
            row = con.execute("SELECT lang FROM customers WHERE user_id=?", (user_id,)).fetchone()
        return row["lang"] if row else None

    def customer_ids(self):
        with self.connect() as con:
            return [r[0] for r in con.execute("SELECT user_id FROM customers")]

    def client_summary(self, user_id):
        with self.connect() as con:
            client = con.execute("SELECT * FROM customers WHERE user_id=?", (user_id,)).fetchone()
            orders = con.execute(
                "SELECT code, offer_label, amount, status, created_at FROM orders "
                "WHERE user_id=? ORDER BY id DESC LIMIT 10", (user_id,)).fetchall()
            revenue = con.execute(
                "SELECT COALESCE(SUM(amount),0) FROM orders WHERE user_id=? "
                "AND status IN ('approved','delivered')", (user_id,)).fetchone()[0]
        return client, orders, revenue

    # --- commandes ---
    def _new_code(self, con):
        for _ in range(10):
            code = "HMB-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if not con.execute("SELECT 1 FROM orders WHERE code=?", (code,)).fetchone():
                return code
        raise RuntimeError("Code de commande impossible à générer.")

    def create_order(self, values):
        with self.connect() as con:
            code = self._new_code(con)
            cur = con.execute("""INSERT INTO orders
                (code,user_id,username,full_name,operator,offer_code,offer_label,amount)
                VALUES(?,?,?,?,?,?,?,?)""", (code, *values))
            return cur.lastrowid, code

    def active_order(self, user_id, offer_code):
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM orders WHERE user_id=? AND offer_code=? "
                "AND status IN ('awaiting_proof','pending') ORDER BY id DESC LIMIT 1",
                (user_id, offer_code)).fetchone()

    def get_order(self, order_id):
        with self.connect() as con:
            return con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()

    def get_order_by_code(self, code):
        with self.connect() as con:
            return con.execute("SELECT * FROM orders WHERE code=?", (code.strip().upper(),)).fetchone()

    def set_payment_method(self, order_id, method):
        with self.connect() as con:
            con.execute("UPDATE orders SET payment_method=? WHERE id=? AND status='awaiting_proof'",
                        (method, order_id))

    def set_status(self, order_id, status, expected=None):
        with self.connect() as con:
            if expected:
                cur = con.execute("UPDATE orders SET status=? WHERE id=? AND status=?",
                                  (status, order_id, expected))
            else:
                cur = con.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
            return cur.rowcount == 1

    def add_note(self, order_id, note):
        with self.connect() as con:
            con.execute("UPDATE orders SET note=? WHERE id=?", (note[:1000], order_id))

    def set_stock_code(self, order_id, code):
        with self.connect() as con:
            con.execute("UPDATE orders SET stock_code=? WHERE id=?", (code, order_id))

    def recent_orders(self, limit=10):
        with self.connect() as con:
            return con.execute("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def expired_orders(self, minutes):
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM orders WHERE status='awaiting_proof' "
                "AND created_at <= datetime('now', ?)", (f"-{int(minutes)} minutes",)).fetchall()

    def orders_to_remind(self, minutes):
        with self.connect() as con:
            return con.execute(
                "SELECT * FROM orders WHERE status='awaiting_proof' AND reminded_at IS NULL "
                "AND created_at <= datetime('now', ?)", (f"-{int(minutes)} minutes",)).fetchall()

    def mark_reminded(self, order_id):
        with self.connect() as con:
            con.execute("UPDATE orders SET reminded_at=CURRENT_TIMESTAMP WHERE id=?", (order_id,))

    def stats(self):
        with self.connect() as con:
            customers = con.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            total = con.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            pending = con.execute("SELECT COUNT(*) FROM orders WHERE status IN ('awaiting_proof','pending')").fetchone()[0]
            approved = con.execute("SELECT COUNT(*) FROM orders WHERE status IN ('approved','delivered')").fetchone()[0]
            revenue = con.execute("SELECT COALESCE(SUM(amount),0) FROM orders WHERE status IN ('approved','delivered')").fetchone()[0]
        return {"customers": customers, "orders": total, "pending": pending,
                "approved": approved, "revenue": revenue}

    # --- stock ---
    def add_stock(self, offer_code, codes):
        added = 0
        with self.connect() as con:
            for code in codes:
                code = code.strip()
                if code:
                    con.execute("INSERT INTO stock(offer_code, code) VALUES(?,?)", (offer_code, code))
                    added += 1
        return added

    def stock_count(self, offer_code):
        with self.connect() as con:
            return con.execute(
                "SELECT COUNT(*) FROM stock WHERE offer_code=? AND used_at IS NULL",
                (offer_code,)).fetchone()[0]

    def low_stock(self, threshold):
        with self.connect() as con:
            return con.execute(
                "SELECT offer_code, COUNT(*) AS n FROM stock WHERE used_at IS NULL "
                "GROUP BY offer_code HAVING n <= ?", (threshold,)).fetchall()

    def reserve_stock(self, offer_code, order_id):
        with self.connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(
                "SELECT id, code FROM stock WHERE offer_code=? AND used_at IS NULL "
                "ORDER BY id LIMIT 1", (offer_code,)).fetchone()
            if not row:
                return None
            cur = con.execute(
                "UPDATE stock SET used_at=CURRENT_TIMESTAMP, order_id=? "
                "WHERE id=? AND used_at IS NULL", (order_id, row["id"]))
            return row["code"] if cur.rowcount == 1 else None

    # --- FAQ ---
    def faq_lookup(self, text):
        key = normalize_question(text)
        if not key:
            return None
        with self.connect() as con:
            row = con.execute("SELECT id, answer FROM faq WHERE question=?", (key,)).fetchone()
            if not row:
                return None
            con.execute("UPDATE faq SET hits=hits+1 WHERE id=?", (row["id"],))
        return row["answer"]

    def faq_add(self, question, answer):
        key = normalize_question(question)
        if not key:
            return False
        with self.connect() as con:
            con.execute("""INSERT INTO faq(question, answer) VALUES(?,?)
                ON CONFLICT(question) DO UPDATE SET answer=excluded.answer""",
                (key, answer[:1500]))
        return True

    def faq_count(self):
        with self.connect() as con:
            return con.execute("SELECT COUNT(*) FROM faq").fetchone()[0]

    # --- conversation ---
    def add_message(self, user_id, role, content):
        with self.connect() as con:
            con.execute("INSERT INTO conversations(user_id,role,content) VALUES(?,?,?)",
                        (user_id, role, content[:8000]))

    def history(self, user_id, limit=6):
        with self.connect() as con:
            rows = con.execute("""SELECT role,content FROM conversations
                WHERE user_id=? ORDER BY id DESC LIMIT ?""", (user_id, limit)).fetchall()
        return list(reversed(rows))

    def checkpoint(self):
        with self.connect() as con:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")

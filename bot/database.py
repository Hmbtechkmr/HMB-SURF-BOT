import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from pathlib import Path

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STATUSES = ("awaiting_proof", "pending", "approved", "delivered",
            "rejected", "cancelled", "refunded", "expired")
REPLY_MODES = ("text", "voice")


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
                user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
                lang TEXT, reply_mode TEXT DEFAULT 'text',
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

            # Colonnes ajoutées après coup : ALTER idempotent pour les bases existantes.
            order_columns = self._columns(con, "orders")
            for name in ("code", "note", "stock_code", "reminded_at"):
                if name not in order_columns:
                    con.execute(f"ALTER TABLE orders ADD COLUMN {name} TEXT")
            customer_columns = self._columns(con, "customers")
            if "lang" not in customer_columns:
                con.execute("ALTER TABLE customers ADD COLUMN lang TEXT")
            if "reply_mode" not in customer_columns:
                con.execute("ALTER TABLE customers ADD COLUMN reply_mode TEXT DEFAULT 'text'")

            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_code ON orders(code)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status, created_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, id)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_stock_offer ON stock(offer_code, used_at)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_seen_updates ON seen_updates(seen_at)")

    # --- déduplication ---
    def mark_update(self, update_id):
        with self.connect() as con:
            cur = con.execute("INSERT OR IGNORE INTO seen_updates(update_id) VALUES(?)", (update_id,))
            return cur.rowcount == 1

    def purge_seen_updates(self, days=7):
        with self.connect() as con:
            cur = con.execute(
                "DELETE FROM seen_updates WHERE seen_at <= datetime('now', ?)",
                (f"-{int(days)} days",))
            return cur.rowcount

    # --- clients ---
    def register_customer(self, user, lang=None):
        with self.connect() as con:
            con.execute("""INSERT INTO customers(user_id,username,full_name,lang,reply_mode)
                VALUES(?,?,?,?,'text') ON CONFLICT(user_id) DO UPDATE SET
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

    def set_reply_mode(self, user_id, mode):
        if mode not in REPLY_MODES:
            mode = "text"
        with self.connect() as con:
            con.execute("UPDATE customers SET reply_mode=? WHERE user_id=?", (mode, user_id))

    def get_reply_mode(self, user_id):
        with self.connect() as con:
            row = con.execute("SELECT reply_mode FROM customers WHERE user_id=?", (user_id,)).fetchone()
        return (row["reply_mode"] if row else None) or "text"

    def customer_ids(self):
        with self.connect() as con:
            return [r[0] for r in con.execute("SELECT user_id FROM customers")]

    def client_summary(self, user_id):
        with self.connect() as con:
            client = con.execute("SELECT * FROM customers WHERE user_id=?", (user_id,)).fetchone()
            orders = con.execute(
                "SELECT code, offer_label, amount, status, created_at FROM orders "
                "WHERE user_id=? ORDER BY id DESC LIMIT 

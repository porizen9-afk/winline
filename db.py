import sqlite3
import time
from pathlib import Path
from config import DB_PATH, OWNER_ID, ADMIN_IDS

Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

class _Con(sqlite3.Connection):
    """with connect() as c: — коммит/откат и ЗАКРЫТИЕ соединения (раньше соединения копились)."""
    def __exit__(self, et, ev, tb):
        try:
            return super().__exit__(et, ev, tb)
        finally:
            self.close()

def connect():
    con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15, factory=_Con)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    return con

def init():
    with connect() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, coins REAL NOT NULL DEFAULT 0,
              gems INTEGER NOT NULL DEFAULT 0, username TEXT DEFAULT '',
              banned INTEGER NOT NULL DEFAULT 0,
              upgrade_win_streak INTEGER DEFAULT 0, upgrade_lose_streak INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS admins(user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', granted_by INTEGER, created INTEGER);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inventory(
              rowid_ INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, gift_id TEXT, name TEXT, image TEXT, price REAL, status TEXT DEFAULT 'won');
            CREATE TABLE IF NOT EXISTS gift_queue(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, gift_id TEXT, inv_row INTEGER,
              status TEXT DEFAULT 'pending', error TEXT DEFAULT '', created INTEGER, updated INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS withdrawals(
              request_id TEXT PRIMARY KEY, user_id INTEGER, stars INTEGER, status TEXT, error TEXT, created INTEGER);
            CREATE TABLE IF NOT EXISTS chest_rounds(
              user_id INTEGER PRIMARY KEY, bet REAL, empties INTEGER, bad TEXT, opened TEXT, mult REAL, active INTEGER, created INTEGER);
            CREATE TABLE IF NOT EXISTS user_stats(user_id INTEGER PRIMARY KEY, turnover_ton REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS casino_day(day TEXT PRIMARY KEY, intake REAL DEFAULT 0, payout REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS spin_log(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, chance REAL, cost REAL, win INTEGER, created INTEGER);
        """)
    _migrate()

def _migrate():
    """Старые базы без новых колонок не падают."""
    with connect() as c:
        have = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        for col, typ in [("username", "TEXT DEFAULT ''"), ("banned", "INTEGER NOT NULL DEFAULT 0"),
                         ("upgrade_win_streak", "INTEGER DEFAULT 0"), ("upgrade_lose_streak", "INTEGER DEFAULT 0")]:
            if col not in have:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")

def spend(uid, amount):
    """Атомарно списать монеты. True, если хватило. Защита от двойной траты и отрицательных сумм."""
    amount = float(amount)
    if not (amount > 0) or amount != amount or amount == float("inf"):
        return False
    ensure_user(uid)
    with connect() as c:
        cur = c.execute("UPDATE users SET coins=coins-? WHERE id=? AND coins>=?", (amount, uid, amount))
        return cur.rowcount == 1

def ensure_user(uid, username=""):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO users(id) VALUES(?)", (uid,))
        if username:
            c.execute("UPDATE users SET username=? WHERE id=?", (username.lstrip("@"), uid))

def is_owner(uid):
    return bool(OWNER_ID and int(uid) == int(OWNER_ID))

def is_admin(uid):
    if is_owner(uid) or int(uid) in ADMIN_IDS:
        return True
    with connect() as c:
        return bool(c.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone())

def get_setting(key, default=""):
    with connect() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default

def set_setting(key, value):
    with connect() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

def get_coins(uid):
    ensure_user(uid)
    with connect() as c:
        return float(c.execute("SELECT coins FROM users WHERE id=?", (uid,)).fetchone()["coins"])

def add_coins(uid, delta):
    ensure_user(uid)
    with connect() as c:
        c.execute("UPDATE users SET coins=coins+? WHERE id=?", (delta, uid))
        return float(c.execute("SELECT coins FROM users WHERE id=?", (uid,)).fetchone()["coins"])

def add_turnover(uid, amount):
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO user_stats(user_id,turnover_ton) VALUES(?,0)", (uid,))
        c.execute("UPDATE user_stats SET turnover_ton=turnover_ton+? WHERE user_id=?", (amount, uid))

def turnover(uid):
    with connect() as c:
        r = c.execute("SELECT turnover_ton FROM user_stats WHERE user_id=?", (uid,)).fetchone()
    return float(r["turnover_ton"]) if r else 0.0

def day_pnl():
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with connect() as c:
        r = c.execute("SELECT intake,payout FROM casino_day WHERE day=?", (day,)).fetchone()
    if not r:
        return 0.0
    return float(r["intake"] or 0) - float(r["payout"] or 0)

def ledger(intake, payout):
    day = time.strftime("%Y-%m-%d", time.gmtime())
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO casino_day(day) VALUES(?)", (day,))
        c.execute("UPDATE casino_day SET intake=intake+?, payout=payout+? WHERE day=?", (intake, payout, day))

def parse_user_ref(ref):
    ref = (ref or "").strip().lstrip("@")
    if ref.isdigit():
        return int(ref)
    with connect() as c:
        r = c.execute("SELECT id FROM users WHERE lower(username)=lower(?) LIMIT 1", (ref,)).fetchone()
    return int(r["id"]) if r else None

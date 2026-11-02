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
            CREATE TABLE IF NOT EXISTS upgrade_gifts(
              id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT UNIQUE, name TEXT, image TEXT DEFAULT '',
              price REAL NOT NULL DEFAULT 10, enabled INTEGER NOT NULL DEFAULT 1, relayer_id TEXT DEFAULT '',
              sort INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS deposits(
              order_id TEXT PRIMARY KEY, user_id INTEGER, stars INTEGER, amount REAL,
              status TEXT DEFAULT 'pending', charge_id TEXT DEFAULT '', created INTEGER);
            CREATE TABLE IF NOT EXISTS catalog_gifts(
              slug TEXT PRIMARY KEY, name TEXT, image TEXT, price REAL NOT NULL DEFAULT 20,
              enabled INTEGER NOT NULL DEFAULT 1, sort INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS user_kv(user_id INTEGER, k TEXT, v TEXT, PRIMARY KEY(user_id,k));
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
        _col(c, "gift_queue", "fee", "REAL DEFAULT 0")
        _col(c, "catalog_gifts", "sg_id", "TEXT DEFAULT ''")

def _col(c, table, col, typ):
    have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    if col not in have:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")

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


def kv_get(uid, key, default=None):
    import json as _j
    with connect() as c:
        r = c.execute("SELECT v FROM user_kv WHERE user_id=? AND k=?", (uid, key)).fetchone()
    if not r:
        return default
    try:
        return _j.loads(r["v"])
    except Exception:
        return default

def kv_set(uid, key, value):
    import json as _j
    with connect() as c:
        c.execute("INSERT INTO user_kv(user_id,k,v) VALUES(?,?,?) ON CONFLICT(user_id,k) DO UPDATE SET v=excluded.v",
                  (uid, key, _j.dumps(value, ensure_ascii=False)))

def count_games(uid):
    with connect() as c:
        n = c.execute("SELECT COUNT(*) FROM spin_log WHERE user_id=?", (uid,)).fetchone()[0]
    return int(n or 0)


# ---------- каталог подарков апгрейда (админ включает/выключает и меняет цену) ----------
def catalog_seed(items):
    """items: [(slug, name, image, price)] — добавляет только новые, существующие (цены/вкл) не трогает."""
    with connect() as c:
        n = c.execute("SELECT COALESCE(MAX(sort),0) FROM catalog_gifts").fetchone()[0]
        for slug, name, image, price in items:
            cur = c.execute("INSERT OR IGNORE INTO catalog_gifts(slug,name,image,price,enabled,sort) VALUES(?,?,?,?,1,?)",
                            (slug, name, image, float(price), n + 1))
            if cur.rowcount:
                n += 1

def catalog_list(enabled_only=False):
    q = "SELECT slug,name,image,price,enabled,COALESCE(sg_id,'') AS sg_id FROM catalog_gifts"
    if enabled_only:
        q += " WHERE enabled=1"
    q += " ORDER BY sort,slug"
    with connect() as c:
        return [dict(r) for r in c.execute(q)]

def catalog_get(slug):
    with connect() as c:
        r = c.execute("SELECT slug,name,image,price,enabled,COALESCE(sg_id,'') AS sg_id FROM catalog_gifts WHERE slug=?", (slug,)).fetchone()
    return dict(r) if r else None

def catalog_set(slug, enabled=None, price=None, name=None):
    with connect() as c:
        if enabled is not None:
            c.execute("UPDATE catalog_gifts SET enabled=? WHERE slug=?", (1 if enabled else 0, slug))
        if price is not None:
            c.execute("UPDATE catalog_gifts SET price=? WHERE slug=?", (float(price), slug))
        if name is not None:
            c.execute("UPDATE catalog_gifts SET name=? WHERE slug=?", (name, slug))


# ---------- пополнение звёздами ----------
def deposit_create(order_id, uid, stars, amount):
    import time as _t
    with connect() as c:
        c.execute("INSERT INTO deposits(order_id,user_id,stars,amount,status,created) VALUES(?,?,?,?,'pending',?)",
                  (order_id, uid, int(stars), float(amount), int(_t.time())))

def deposit_get(order_id):
    with connect() as c:
        r = c.execute("SELECT * FROM deposits WHERE order_id=?", (order_id,)).fetchone()
    return dict(r) if r else None

def deposit_credit(order_id, stars, charge_id=""):
    """Зачислить монеты ровно один раз. Возвращает (user_id, amount) или None, если уже зачислено/не найдено/сумма не сошлась."""
    with connect() as c:
        r = c.execute("SELECT user_id,amount,stars FROM deposits WHERE order_id=?", (order_id,)).fetchone()
        if not r or int(r["stars"]) != int(stars):
            return None
        cur = c.execute("UPDATE deposits SET status='credited', charge_id=? WHERE order_id=? AND status='pending'", (charge_id, order_id))
        if cur.rowcount != 1:
            return None
        uid, amount = int(r["user_id"]), float(r["amount"])
    add_coins(uid, amount)
    ledger(float(amount), 0)
    return uid, amount

# ---------- алмазы ----------
def get_gems(uid):
    ensure_user(uid)
    with connect() as c:
        return int(c.execute("SELECT gems FROM users WHERE id=?", (uid,)).fetchone()["gems"] or 0)

def add_gems(uid, delta):
    ensure_user(uid)
    with connect() as c:
        c.execute("UPDATE users SET gems=gems+? WHERE id=?", (int(delta), uid))
        return int(c.execute("SELECT gems FROM users WHERE id=?", (uid,)).fetchone()["gems"] or 0)

def spend_gems(uid, n):
    n = int(n)
    if n <= 0:
        return False
    ensure_user(uid)
    with connect() as c:
        return c.execute("UPDATE users SET gems=gems-? WHERE id=? AND gems>=?", (n, uid, n)).rowcount == 1


def streak_update(uid, win):
    ensure_user(uid)
    with connect() as c:
        if win:
            c.execute("UPDATE users SET upgrade_win_streak=COALESCE(upgrade_win_streak,0)+1, upgrade_lose_streak=0 WHERE id=?", (uid,))
        else:
            c.execute("UPDATE users SET upgrade_win_streak=0, upgrade_lose_streak=COALESCE(upgrade_lose_streak,0)+1 WHERE id=?", (uid,))

def get_streak(uid):
    ensure_user(uid)
    with connect() as c:
        r = c.execute("SELECT upgrade_win_streak FROM users WHERE id=?", (uid,)).fetchone()
    return int(r["upgrade_win_streak"] or 0)


def catalog_add(slug, name, image, price, sg_id="", enabled=1):
    """Добавить/обновить подарок. sg_id — настоящий gift_id StaticGram (для автоотправки через sendGift)."""
    with connect() as c:
        n = c.execute("SELECT COALESCE(MAX(sort),0) FROM catalog_gifts").fetchone()[0]
        c.execute("INSERT OR IGNORE INTO catalog_gifts(slug,name,image,price,enabled,sort,sg_id) VALUES(?,?,?,?,?,?,?)",
                  (slug, name, image, float(price), 1 if enabled else 0, n + 1, sg_id or ""))

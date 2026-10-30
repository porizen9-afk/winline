"""WinLine — админ-бот и юзербот релеера (запускаются из server.py, отдельные процессы не нужны).

Админ-бот: кнопки, OWNER_ID + таблица admins (BOT_TOKEN и OWNER_ID в окружении).
Юзербот:   снимает подарки со склада релеера и передаёт игрокам (USERBOT_API_ID / USERBOT_API_HASH; нужны telethon и pillow).
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
API_BASE = os.getenv("STATICGRAM_API", "https://api.staticgram.top").rstrip("/")
DB_PATH = os.getenv("DB_PATH", "data/app.db")
RELAYER_JSON = Path(os.getenv("RELAYER_JSON", "data/relayer_gifts.json"))
OWNER_ID = int(os.getenv("OWNER_ID") or "0")
POLL = float(os.getenv("ADMIN_BOT_POLL", "1.5"))

# state: user_id -> {mode, target, msg_id, chat_id}
STATE: dict[int, dict] = {}


def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_admin_tables():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users(
              id INTEGER PRIMARY KEY, coins REAL NOT NULL DEFAULT 0,
              gems INTEGER NOT NULL DEFAULT 0, username TEXT DEFAULT '',
              banned INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS admins(
              user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '',
              granted_by INTEGER, created INTEGER);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS inventory(
              rowid_ INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
              gift_id TEXT, name TEXT, image TEXT, price REAL, status TEXT DEFAULT 'won');
            CREATE TABLE IF NOT EXISTS gift_queue(
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, gift_id TEXT,
              inv_row INTEGER, status TEXT, error TEXT DEFAULT '',
              created INTEGER, updated INTEGER DEFAULT 0);
            """
        )
        for col, typ in [("username", "TEXT DEFAULT ''"), ("banned", "INTEGER NOT NULL DEFAULT 0")]:
            try:
                c.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                pass


def is_owner(uid: int) -> bool:
    return bool(OWNER_ID and uid == OWNER_ID)


def is_admin(uid: int) -> bool:
    if is_owner(uid):
        return True
    with db() as c:
        return bool(c.execute("SELECT 1 FROM admins WHERE user_id=?", (uid,)).fetchone())


def get_setting(key: str, default: str = "") -> str:
    with db() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_setting(key: str, value: str) -> None:
    with db() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def maintenance_on() -> bool:
    return get_setting("maintenance", "0") == "1"


async def api(method: str, **params):
    url = f"{API_BASE}/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=60) as h:
        r = await h.post(url, json=params)
        try:
            return r.json()
        except Exception:
            return {"ok": False, "description": r.text[:200]}


async def send(chat_id: int, text: str, reply_markup=None) -> dict:
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        p["reply_markup"] = reply_markup
    return await api("sendMessage", **p)


async def edit(chat_id: int, message_id: int, text: str, reply_markup=None) -> dict:
    p = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_markup is not None:
        p["reply_markup"] = reply_markup
    data = await api("editMessageText", **p)
    # если не изменилось — ок
    return data


async def answer_cb(cb_id: str, text: str = "") -> None:
    await api("answerCallbackQuery", callback_query_id=cb_id, text=text[:200])


def kb(rows: list[list[tuple[str, str]]]) -> dict:
    """rows: list of list of (text, callback_data)"""
    return {
        "inline_keyboard": [
            [{"text": t, "callback_data": d[:64]} for t, d in row] for row in rows
        ]
    }


def main_menu_text() -> str:
    m = "🛠 ВКЛ" if maintenance_on() else "✅ выкл"
    return (
        f"🛡 <b>Админка WinLine</b>\n"
        f"Техперерыв: {m}\n\n"
        f"Жми кнопки — это же сообщение обновится."
    )


def main_menu_kb() -> dict:
    return kb(
        [
            [("🔍 Игрок", "u:ask"), ("🏆 Топ", "top")],
            [("📦 Склад", "stock"), ("📋 Очередь", "queue")],
            [("⭐ Выдать ★", "gs:ask"), ("⭐ Забрать ★", "ts:ask")],
            [("🎁 Выдать гифт", "gg:ask"), ("🗑 Забрать гифт", "tg:ask")],
            [("⛔ Бан", "ban:ask"), ("✅ Разбан", "unban:ask")],
            [("🛠 Техперерыв", "maint:toggle"), ("📊 Стата", "stats")],
            [("👤 Выдать админку", "ga:ask"), ("👤 Снять админку", "ra:ask")],
        ]
    )


def resolve_user(token: str) -> int | None:
    token = (token or "").strip().lstrip("@")
    if not token:
        return None
    if token.isdigit():
        return int(token)
    with db() as c:
        r = c.execute(
            "SELECT id FROM users WHERE lower(username)=lower(?) LIMIT 1", (token,)
        ).fetchone()
    return int(r["id"]) if r else None


def profile_text(uid: int) -> str:
    with db() as c:
        u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if not u:
            return f"Игрок <code>{uid}</code> не в БД."
        inv = c.execute(
            "SELECT rowid_, name, gift_id, status, price FROM inventory WHERE user_id=? ORDER BY rowid_ DESC LIMIT 12",
            (uid,),
        ).fetchall()
    lines = [
        f"👤 <b>{u['username'] or '—'}</b> id <code>{uid}</code>",
        f"⭐ {u['coins']:.2f}  💎 {u['gems']}",
        f"{'⛔ БАН' if u['banned'] else '✅ ок'} · админ: {'да' if is_admin(uid) else 'нет'}",
        "Инвентарь:",
    ]
    if not inv:
        lines.append("— пусто")
    for r in inv:
        lines.append(f"#{r['rowid_']} {r['name']} [{r['status']}] {r['price']}★")
    return "\n".join(lines)


def back_kb(extra: list[list[tuple[str, str]]] | None = None) -> dict:
    rows = list(extra or [])
    rows.append([("« Меню", "menu")])
    return kb(rows)


async def show_menu(chat_id: int, message_id: int | None, uid: int):
    text, markup = main_menu_text(), main_menu_kb()
    if message_id:
        data = await edit(chat_id, message_id, text, markup)
        if not data.get("ok"):
            data = await send(chat_id, text, markup)
    else:
        data = await send(chat_id, text, markup)
    mid = (data.get("result") or {}).get("message_id")
    if mid:
        STATE[uid] = {"mode": None, "msg_id": mid, "chat_id": chat_id}
    return mid


async def patch(uid: int, text: str, markup=None, toast: str = ""):
    st = STATE.get(uid) or {}
    chat_id = st.get("chat_id")
    mid = st.get("msg_id")
    if not chat_id or not mid:
        data = await send(chat_id or uid, text, markup or back_kb())
        mid = (data.get("result") or {}).get("message_id")
        STATE.setdefault(uid, {})["msg_id"] = mid
        STATE[uid]["chat_id"] = chat_id or uid
        return
    data = await edit(chat_id, mid, text, markup if markup is not None else back_kb())
    if not data.get("ok"):
        # сообщение слишком старое — новое и запоминаем
        data = await send(chat_id, text, markup if markup is not None else back_kb())
        mid = (data.get("result") or {}).get("message_id")
        STATE[uid]["msg_id"] = mid


async def on_callback(cq: dict):
    uid = int(cq.get("from", {}).get("id") or 0)
    data = cq.get("data") or ""
    cq_id = cq.get("id")
    msg = cq.get("message") or {}
    chat_id = int((msg.get("chat") or {}).get("id") or uid)
    mid = msg.get("message_id")
    STATE.setdefault(uid, {})
    STATE[uid]["chat_id"] = chat_id
    STATE[uid]["msg_id"] = mid

    if not is_admin(uid):
        await answer_cb(cq_id, "Нет доступа")
        return

    await answer_cb(cq_id)

    if data == "menu":
        STATE[uid]["mode"] = None
        await show_menu(chat_id, mid, uid)
        return

    if data == "maint:toggle":
        if not (is_owner(uid) or is_admin(uid)):
            await patch(uid, "Нельзя")
            return
        set_setting("maintenance", "0" if maintenance_on() else "1")
        await show_menu(chat_id, mid, uid)
        return

    if data == "top":
        with db() as c:
            rows = c.execute(
                "SELECT id, username, coins FROM users ORDER BY coins DESC LIMIT 15"
            ).fetchall()
        lines = ["🏆 <b>Топ</b>"] + [
            f"{i}. {r['username'] or r['id']} — {r['coins']:.1f}★"
            for i, r in enumerate(rows, 1)
        ]
        await patch(uid, "\n".join(lines) or "Пусто", back_kb())
        return

    if data == "stock":
        if not RELAYER_JSON.exists():
            await patch(uid, "Склад пуст (нет JSON)", back_kb())
            return
        j = json.loads(RELAYER_JSON.read_text("utf-8"))
        lines = [f"📦 @{j.get('relayer',{}).get('username','relayer')}"]
        for it in j.get("stock") or []:
            lines.append(
                f"• {it.get('name')} id={it.get('id')} ×{it.get('count')} {it.get('price')}★"
            )
        await patch(uid, "\n".join(lines)[:3500], back_kb())
        return

    if data == "queue":
        with db() as c:
            rows = c.execute(
                "SELECT id,user_id,gift_id,status,error FROM gift_queue ORDER BY id DESC LIMIT 20"
            ).fetchall()
        if not rows:
            await patch(uid, "Очередь пуста", back_kb())
            return
        lines = ["📋 <b>Очередь</b>"]
        for r in rows:
            lines.append(
                f"#{r['id']} u={r['user_id']} g={r['gift_id']} [{r['status']}] {r['error'][:30]}"
            )
        await patch(uid, "\n".join(lines), back_kb())
        return

    if data == "stats":
        with db() as c:
            users = c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"]
            inv = c.execute(
                "SELECT COUNT(*) n FROM inventory WHERE status='won'"
            ).fetchone()["n"]
            q = c.execute(
                "SELECT COUNT(*) n FROM gift_queue WHERE status='pending'"
            ).fetchone()["n"]
        await patch(
            uid,
            f"📊 Юзеров: {users}\nИнвентарь won: {inv}\nPending: {q}\n"
            f"Техперерыв: {'ВКЛ' if maintenance_on() else 'выкл'}",
            back_kb(),
        )
        return

    # modes that wait for text
    modes = {
        "u:ask": ("user", "Пришли @username или id игрока:"),
        "gs:ask": ("give_stars", "Формат: @user|id и число ★\nПример: <code>123456 50</code>"),
        "ts:ask": ("take_stars", "Формат: @user|id и число ★\nПример: <code>@nick 10</code>"),
        "gg:ask": ("give_gift", "Формат: @user|id gift_id [имя]\nПример: <code>123456 42 Кубок</code>"),
        "tg:ask": ("take_gift", "Пришли номер строки инвентаря (row id):"),
        "ban:ask": ("ban", "Кого забанить? @user или id:"),
        "unban:ask": ("unban", "Кого разбанить? @user или id:"),
        "ga:ask": ("grant", "Кому выдать админку? @user или id (только владелец):"),
        "ra:ask": ("revoke", "С кого снять админку? @user или id:"),
    }
    if data in modes:
        mode, prompt = modes[data]
        if mode in ("grant", "revoke") and not is_owner(uid):
            await patch(uid, "Только владелец.", back_kb())
            return
        STATE[uid]["mode"] = mode
        await patch(uid, prompt, back_kb())
        return

    await patch(uid, "Неизвестная кнопка", back_kb())


async def on_text(chat_id: int, uid: int, text: str):
    if not is_admin(uid):
        await send(chat_id, "Нет доступа. /admin")
        return

    if text.strip() in ("/admin", "/start", "админ"):
        await show_menu(chat_id, STATE.get(uid, {}).get("msg_id"), uid)
        return

    mode = (STATE.get(uid) or {}).get("mode")
    if not mode:
        await show_menu(chat_id, STATE.get(uid, {}).get("msg_id"), uid)
        return

    st = STATE.setdefault(uid, {})
    st["chat_id"] = chat_id

    if mode == "user":
        target = resolve_user(text)
        if not target:
            await patch(uid, "Не найден. Ещё раз @user или id:", back_kb())
            return
        st["mode"] = None
        await patch(uid, profile_text(target), back_kb([[("🔄 Обновить", f"u:show:{target}")]]))
        return

    if mode in ("give_stars", "take_stars"):
        parts = text.split()
        if len(parts) < 2:
            await patch(uid, "Нужно: id|@user число", back_kb())
            return
        target = resolve_user(parts[0])
        try:
            amount = float(parts[1])
        except ValueError:
            await patch(uid, "Число ★ не распознано", back_kb())
            return
        if not target:
            await patch(uid, "Юзер не найден", back_kb())
            return
        with db() as c:
            c.execute("INSERT OR IGNORE INTO users(id) VALUES(?)", (target,))
            if mode == "give_stars":
                c.execute("UPDATE users SET coins=coins+? WHERE id=?", (amount, target))
            else:
                c.execute(
                    "UPDATE users SET coins=MAX(0,coins-?) WHERE id=?", (amount, target)
                )
        st["mode"] = None
        sign = "+" if mode == "give_stars" else "−"
        await patch(uid, f"{sign}{amount}★ → {target}\n\n" + profile_text(target), back_kb())
        return

    if mode == "give_gift":
        parts = text.split(maxsplit=2)
        if len(parts) < 2:
            await patch(uid, "Формат: id|@user gift_id [имя]", back_kb())
            return
        target = resolve_user(parts[0])
        gift_id = parts[1]
        name = parts[2] if len(parts) > 2 else f"Gift {gift_id}"
        if not target:
            await patch(uid, "Юзер не найден", back_kb())
            return
        with db() as c:
            c.execute(
                "INSERT INTO inventory(user_id,gift_id,name,image,price,status) VALUES(?,?,?,?,?,?)",
                (target, gift_id, name, "", 0, "won"),
            )
        st["mode"] = None
        await patch(uid, f"🎁 {name} → инвентарь {target}", back_kb())
        return

    if mode == "take_gift":
        if not text.strip().isdigit():
            await patch(uid, "Нужен номер строки инвентаря", back_kb())
            return
        rid = int(text.strip())
        with db() as c:
            r = c.execute("SELECT * FROM inventory WHERE rowid_=?", (rid,)).fetchone()
            if not r:
                await patch(uid, "Нет записи", back_kb())
                return
            c.execute("UPDATE inventory SET status='taken' WHERE rowid_=?", (rid,))
        st["mode"] = None
        await patch(uid, f"🗑 #{rid} taken (user {r['user_id']})", back_kb())
        return

    if mode in ("ban", "unban"):
        target = resolve_user(text)
        if not target:
            await patch(uid, "Не найден", back_kb())
            return
        with db() as c:
            c.execute("INSERT OR IGNORE INTO users(id) VALUES(?)", (target,))
            c.execute(
                "UPDATE users SET banned=? WHERE id=?",
                (1 if mode == "ban" else 0, target),
            )
        st["mode"] = None
        await patch(uid, f"{'⛔ Бан' if mode == 'ban' else '✅ Разбан'} {target}", back_kb())
        return

    if mode == "grant":
        if not is_owner(uid):
            await patch(uid, "Только владелец", back_kb())
            return
        target = resolve_user(text)
        if not target:
            await patch(uid, "Не найден (пусть зайдёт в аппку или укажи id)", back_kb())
            return
        with db() as c:
            c.execute(
                "INSERT OR REPLACE INTO admins(user_id,username,granted_by,created) VALUES(?,?,?,?)",
                (target, text.strip().lstrip("@"), uid, int(time.time())),
            )
        st["mode"] = None
        await patch(uid, f"🛡 Админ выдан {target}", back_kb())
        return

    if mode == "revoke":
        if not is_owner(uid):
            await patch(uid, "Только владелец", back_kb())
            return
        target = resolve_user(text)
        if not target:
            await patch(uid, "Не найден", back_kb())
            return
        with db() as c:
            c.execute("DELETE FROM admins WHERE user_id=?", (target,))
        st["mode"] = None
        await patch(uid, f"Админ снят {target}", back_kb())
        return

    st["mode"] = None
    await show_menu(chat_id, st.get("msg_id"), uid)


async def loop_admin():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN required")
    init_admin_tables()
    offset = 0
    print("admin bot (buttons) on", API_BASE, "owner", OWNER_ID)
    while True:
        try:
            data = await api(
                "getUpdates",
                offset=offset,
                timeout=30,
                allowed_updates=["message", "callback_query"],
            )
            for upd in data.get("result") or []:
                offset = max(offset, upd["update_id"] + 1)
                if "callback_query" in upd:
                    await on_callback(upd["callback_query"])
                    continue
                msg = upd.get("message") or {}
                if not msg:
                    continue
                user = msg.get("from") or {}
                uid = int(user.get("id") or 0)
                un = user.get("username") or ""
                if uid and un:
                    with db() as c:
                        c.execute("INSERT OR IGNORE INTO users(id) VALUES(?)", (uid,))
                        c.execute("UPDATE users SET username=? WHERE id=?", (un, uid))
                text = msg.get("text") or ""
                chat_id = int((msg.get("chat") or {}).get("id") or uid)
                if text:
                    await on_text(chat_id, uid, text)
        except Exception as e:
            print("poll error", e)
            await asyncio.sleep(3)
        await asyncio.sleep(POLL)




# ================= юзербот релеера =================

import io
import httpx
from PIL import Image
try:
    from telethon import TelegramClient, events, functions
    HAVE_TELETHON = True
except Exception:          # telethon не установлен — юзербот просто выключен
    HAVE_TELETHON = False
try:
    import staticgram  # noqa: F401
except ImportError:
    pass

API_ID = int(os.getenv("USERBOT_API_ID") or os.getenv("API_ID") or "0")
API_HASH = os.getenv("USERBOT_API_HASH") or os.getenv("API_HASH") or ""
SESSION = os.getenv("USERBOT_SESSION", "data/relayer")
OUT = Path(os.getenv("RELAYER_JSON", "data/relayer_gifts.json"))
IMG_DIR = Path(os.getenv("GIFTS_IMG_DIR", "data/gifts"))
IMG_URL = os.getenv("GIFTS_IMG_URL", "/static/gifts")
USERNAME = os.getenv("RELAYER_USERNAME", "relayer")
PERIOD = int(os.getenv("USERBOT_PERIOD", "60"))
ADMIN_IDS = [
    int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()
]
MINIAPP_URL = os.getenv("MINIAPP_URL", "")  # https://staticgram.top/bot/app


async def bot_send(chat_id: int, text: str) -> None:
    if not BOT_TOKEN or not chat_id:
        print("bot_send skip", chat_id, text[:80])
        return
    url = f"{API_BASE}/bot{BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=30) as h:
            r = await h.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            if not r.is_success:
                print("bot_send fail", r.status_code, r.text[:200])
    except Exception as e:
        print("bot_send error", e)


async def save_png(client, gift) -> str | None:
    key = str(gift.id)
    png = IMG_DIR / f"{key}.png"
    if png.exists():
        return f"{IMG_URL}/{key}.png"
    doc = getattr(gift, "sticker", None)
    if doc is None:
        return None
    raw = await client.download_media(doc, file=bytes)
    mime = getattr(doc, "mime_type", "") or ""
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if mime == "application/x-tgsticker":
            from lottie.parsers.tgs import parse_tgs
            from lottie.exporters.cairo import export_png

            anim = parse_tgs(io.BytesIO(raw))
            export_png(anim, str(png), frame=0, dpi=96)
        else:
            Image.open(io.BytesIO(raw)).convert("RGBA").resize((256, 256)).save(png)
        return f"{IMG_URL}/{key}.png"
    except Exception as e:
        print("image error", key, e)
        return None


async def snapshot(client) -> dict:
    res = await client(
        functions.payments.GetSavedStarGiftsRequest(peer="me", offset="", limit=200)
    )
    stock: dict[str, dict] = {}
    for g in res.gifts:
        gift = g.gift
        key = str(gift.id)
        it = stock.get(key)
        if not it:
            it = stock[key] = {
                "id": key,
                "name": getattr(gift, "title", None) or f"Gift {key}",
                "price": getattr(gift, "stars", 0) or 0,
                "image": await save_png(client, gift),
                "count": 0,
                "saved_ids": [],
            }
        it["count"] += 1
        it["saved_ids"].append(getattr(g, "msg_id", None))
    return {
        "relayer": {"username": USERNAME, "updated_at": int(time.time())},
        "stock": list(stock.values()),
    }


async def transfer_one(client, user_id: int, gift_id: str, saved_msg_id: int | None) -> tuple[bool, str]:
    """Пытается передать один сохранённый гифт игроку.
    Точный MTProto-метод зависит от версии слоя StaticGram; при ошибке — текст в error.
    """
    try:
        # Telegram/StaticGram: TransferStarGift (имя может отличаться на форке)
        # Пробуем через payments.TransferStarGiftRequest если есть в telethon.
        Transfer = getattr(functions.payments, "TransferStarGiftRequest", None) or getattr(
            functions.payments, "TransferGiftRequest", None
        )
        if Transfer is None:
            return False, "TransferStarGiftRequest not in telethon — обновите клиент/staticgram"
        kwargs = {"to_id": user_id}
        # разные сигнатуры в разных слоях
        try:
            await client(Transfer(stargift=saved_msg_id, to_id=user_id))
        except TypeError:
            await client(Transfer(gift_id=int(gift_id), user_id=user_id))
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


async def process_queue(client) -> None:
    if not Path(DB_PATH).exists():
        return
    con = db()
    try:
        rows = con.execute(
            "SELECT * FROM gift_queue WHERE status='pending' ORDER BY id ASC LIMIT 5"
        ).fetchall()
    except sqlite3.OperationalError:
        con.close()
        return
    if not rows:
        con.close()
        return

    # актуальный склад для saved_ids
    try:
        snap = await snapshot(client)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(snap, ensure_ascii=False), "utf-8")
        by_id = {str(x["id"]): x for x in snap["stock"]}
    except Exception as e:
        print("snapshot in queue", e)
        by_id = {}

    for row in rows:
        qid = row["id"]
        uid = row["user_id"]
        gift_id = str(row["gift_id"])
        inv_row = row["inv_row"]
        con.execute(
            "UPDATE gift_queue SET status='sending', updated=? WHERE id=?",
            (int(time.time()), qid),
        )
        con.commit()

        item = by_id.get(gift_id)
        if not item or int(item.get("count") or 0) < 1:
            err = "нет на складе релеера"
            con.execute(
                "UPDATE gift_queue SET status='failed', error=?, updated=? WHERE id=?",
                (err, int(time.time()), qid),
            )
            if inv_row:
                con.execute(
                    "UPDATE inventory SET status='won' WHERE rowid_=?", (inv_row,)
                )
            con.commit()
            await bot_send(
                uid,
                f"⏳ Подарка сейчас <b>нет на складе</b> релеера.\n"
                f"Подождите пополнения и нажмите «Забрать» ещё раз.",
            )
            continue

        saved_ids = [x for x in (item.get("saved_ids") or []) if x]
        saved = saved_ids[0] if saved_ids else None
        ok, err = await transfer_one(client, uid, gift_id, saved)
        if ok:
            con.execute(
                "UPDATE gift_queue SET status='done', error='', updated=? WHERE id=?",
                (int(time.time()), qid),
            )
            if inv_row:
                con.execute(
                    "UPDATE inventory SET status='sent' WHERE rowid_=?", (inv_row,)
                )
            con.commit()
            link = MINIAPP_URL or f"https://staticgram.top/{USERNAME}"
            await bot_send(
                uid,
                f"✅ Подарок <b>{item.get('name', gift_id)}</b> отправлен в ваш профиль.\n"
                f"Открыть: {link}",
            )
        else:
            con.execute(
                "UPDATE gift_queue SET status='failed', error=?, updated=? WHERE id=?",
                (err, int(time.time()), qid),
            )
            if inv_row:
                con.execute(
                    "UPDATE inventory SET status='won' WHERE rowid_=?", (inv_row,)
                )
            con.commit()
            await bot_send(
                uid,
                f"⚠️ Не удалось отправить подарок: {err[:200]}\nПопробуйте позже.",
            )
    con.close()


async def on_new_gift_notify(client, gift_title: str, from_id: int | None) -> None:
    text = (
        f"🎁 На склад релеера пришёл подарок: <b>{gift_title}</b>\n"
        f"От: <code>{from_id or '—'}</code>\n"
        f"Склад обновляется автоматически."
    )
    targets = list(ADMIN_IDS)
    for t in targets:
        await bot_send(t, text)


async def userbot_main():
    if not API_ID or not API_HASH:
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(SESSION, API_ID, API_HASH)

    @client.on(events.NewMessage(incoming=True))
    async def _incoming(ev):
        """Грубый детектор входящего подарка (сервисное сообщение)."""
        msg = ev.message
        # разные клиенты помечают gift по-разному
        action = getattr(msg, "action", None)
        raw = str(msg.message or "") + str(type(action))
        if action is not None and (
            "Gift" in type(action).__name__ or "StarGift" in type(action).__name__
        ):
            title = getattr(action, "gift", None)
            name = getattr(title, "title", None) or type(action).__name__
            from_id = None
            try:
                from_id = ev.sender_id
            except Exception:
                pass
            await on_new_gift_notify(client, str(name), from_id)
            try:
                snap = await snapshot(client)
                OUT.write_text(json.dumps(snap, ensure_ascii=False), "utf-8")
            except Exception as e:
                print("resnap", e)
        elif "подарок" in raw.lower() or "gift" in raw.lower():
            # текстовый фолбэк
            await on_new_gift_notify(client, raw[:80], ev.sender_id)

    async with client:
        print("relayer userbot online")
        while True:
            try:
                snap = await snapshot(client)
                OUT.write_text(json.dumps(snap, ensure_ascii=False), "utf-8")
                print("stock", len(snap["stock"]), "items")
            except Exception as e:
                print("snapshot error:", e)
            try:
                await process_queue(client)
            except Exception as e:
                print("queue error:", e)
            await asyncio.sleep(PERIOD)




def start():
    """Вызывается из server.py на старте: запускает то, что настроено в окружении."""
    loop = asyncio.get_event_loop()
    async def guard(name, coro_fn):
        while True:
            try:
                await coro_fn()
                return
            except asyncio.CancelledError:
                raise
            except BaseException as e:
                print(f"[{name}] упал: {e!r} — перезапуск через 15 с")
                await asyncio.sleep(15)
    if BOT_TOKEN and OWNER_ID:
        loop.create_task(guard("admin_bot", loop_admin))
    else:
        print("admin_bot выключен: нужны BOT_TOKEN и OWNER_ID")
    if API_ID and API_HASH and HAVE_TELETHON:
        loop.create_task(guard("userbot", userbot_main))
    else:
        print("userbot выключен: нужны USERBOT_API_ID, USERBOT_API_HASH и telethon")

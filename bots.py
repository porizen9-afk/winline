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


def _upg_flags():
    try:
        nft = dbm.limit("upg_nft_on") >= 1
        stars = dbm.limit("upg_stars_on") >= 1
    except Exception:
        nft, stars = True, True
    return nft, stars


def main_menu_text() -> str:
    m = "ВКЛ" if maintenance_on() else "выкл"
    nft, stars = _upg_flags()
    lines = [
        "<b>Админка WinLine</b>",
        f"Техперерыв: {m}",
        f"Апгрейд подарки/NFT: <b>{'открыт' if nft else 'ЗАКРЫТ'}</b>",
        f"Апгрейд звезды: <b>{'открыт' if stars else 'ЗАКРЫТ'}</b>",
        "",
        "Жми кнопки — это же сообщение обновится.",
    ]
    return chr(10).join(lines)

def main_menu_kb() -> dict:
    nft, stars = _upg_flags()
    return kb(
        [
            [("Игрок", "u:ask"), ("Топ", "top:menu")],
            [("Подарки апгрейда", "ug:list:0"), ("Лимиты", "lim:list")],
            [(f"NFT: {'ВКЛ' if nft else 'ВЫКЛ'}", "upg:toggle:nft"),
             (f"Звезды: {'ВКЛ' if stars else 'ВЫКЛ'}", "upg:toggle:stars")],
            [("Склад", "stock"), ("Очередь", "queue")],
            [("Выдать звезды", "gs:ask"), ("Забрать звезды", "ts:ask")],
            [("Выдать гифт", "gg:ask"), ("Забрать гифт", "tg:ask")],
            [("Бан", "ban:ask"), ("Разбан", "unban:ask")],
            [("Техперерыв", "maint:toggle"), ("Текст техперерыва", "maint:text")],
            [("Стата", "stats")],
            [("Выдать админку", "ga:ask"), ("Снять админку", "ra:ask")],
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
    return chr(10).join(lines)


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


import db as dbm
UG_PAGE = 8


async def on_pre_checkout(q: dict):
    """Перед списанием звёзд: подтверждаем только известный неоплаченный заказ с точной суммой."""
    ok, err = False, "Заказ не найден"
    try:
        d = dbm.deposit_get(q.get("invoice_payload") or "")
        if d and d["status"] == "pending" and int(q.get("total_amount") or 0) == int(d["stars"]) \
                and q.get("currency") == "XTR" and int(q["from"]["id"]) == int(d["user_id"]):
            ok = True
        else:
            err = "Счёт устарел или уже оплачен"
    except Exception as e:
        print("pre_checkout error", e)
    p = {"pre_checkout_query_id": q["id"], "ok": ok}
    if not ok:
        p["error_message"] = err
    await api("answerPreCheckoutQuery", **p)


async def on_payment(uid: int, chat_id: int, pay: dict):
    """Звёзды пришли — начисляем монеты ровно один раз."""
    res = dbm.deposit_credit(pay.get("invoice_payload") or "", int(pay.get("total_amount") or 0),
                             pay.get("telegram_payment_charge_id") or "")
    if res:
        who, amount = res
        print(f"deposit credited: user {who} +{amount}")
        await send(chat_id, f"✅ Зачислено <b>{amount:g}</b> монет. Открой игру и играй!")
        for aid in set(ADMIN_IDS) | ({int(OWNER_ID)} if OWNER_ID else set()):
            await send(aid, f"💰 Пополнение: игрок <code>{who}</code> +{amount:g} монет ({pay.get('total_amount')}★)")
    else:
        print("payment ignored/duplicate", pay)


async def fetch_image(file_id: str, slug: str):
    """Скачивает картинку из StaticGram и кладёт PNG 256×256 в папку подарков. Возвращает URL или None."""
    r = await api("getFile", file_id=file_id)
    path = (r.get("result") or {}).get("file_path")
    if not path:
        return None
    out_dir = Path(os.getenv("GIFTS_IMG_DIR", "data/gifts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        async with httpx.AsyncClient(timeout=60) as h:
            resp = await h.get(f"{API_BASE}/file/bot{BOT_TOKEN}/{path}")
        if not resp.is_success or not resp.content:
            return None
        raw = resp.content
        try:
            Image.open(io.BytesIO(raw)).convert("RGBA").resize((256, 256)).save(out_dir / f"{slug}.png")
        except Exception:
            (out_dir / f"{slug}.png").write_bytes(raw)
        return f"/static/gifts/{slug}.png?v={int(time.time())}"
    except Exception as e:
        print("fetch_image", slug, e)
        return None


async def ug_import(uid: int):
    """Подарки StaticGram (getAvailableGifts) → каталог апгрейда. Новые добавляются ВЫКЛЮЧЕННЫМИ."""
    r = await api("getAvailableGifts")
    gifts = ((r.get("result") or {}).get("gifts")) or []
    if not gifts:
        return 0, 0, (r.get("description") or "StaticGram не вернул подарки")
    added = skipped = 0
    for g in gifts:
        gid = str(g.get("id") or "")
        stars = int(g.get("star_count") or 0)
        if not gid or stars <= 0:
            continue
        slug = ("sg_" + gid)[:30]
        if dbm.catalog_get(slug):
            skipped += 1
            continue
        st = g.get("sticker") or {}
        emoji = st.get("emoji") or "🎁"
        fid = (st.get("thumbnail") or {}).get("file_id") or (st.get("file_id") if not (st.get("is_animated") or st.get("is_video")) else None)
        image = (await fetch_image(fid, slug)) if fid else None
        dbm.catalog_add(slug, f"{emoji} Подарок {stars}★", image or "/static/img/gift.png", stars, sg_id=gid, enabled=0)
        added += 1
    return added, skipped, ""


async def on_photo(chat_id: int, uid: int, msg: dict):
    """Админ шлёт фото с подписью «Название | цена» — подарок появляется в апгрейде."""
    if not is_admin(uid):
        await send_app(chat_id)
        return
    cap = (msg.get("caption") or "").strip()
    if "|" not in cap:
        await send(chat_id, "Чтобы добавить подарок, пришли фото с подписью:\n<code>Название | цена</code>\nнапример: <code>Plush Pepe | 120</code>")
        return
    name, _, price_s = cap.partition("|")
    name = name.strip()[:40]
    try:
        price = float(price_s.replace(",", ".").strip())
        if not (price > 0) or price > 1_000_000:
            raise ValueError
    except ValueError:
        await send(chat_id, "Цена должна быть числом больше 0, например <code>Plush Pepe | 120</code>")
        return
    file_id = (msg.get("photo") or [{}])[-1].get("file_id") if msg.get("photo") else (msg.get("document") or {}).get("file_id")
    import re as _re2
    slug = ("up_" + _re2.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_"))[:28] or "up_gift"
    image = await fetch_image(file_id, slug)
    if not image:
        await send(chat_id, "Не удалось скачать картинку у StaticGram. Попробуй ещё раз.")
        return
    with dbm.connect() as c:
        c.execute("DELETE FROM catalog_gifts WHERE slug=?", (slug,))
    dbm.catalog_seed([(slug, name, image, price)])
    ext = "png"
    await send(chat_id, f"✅ Подарок <b>{name}</b> ({price:g}★) добавлен в апгрейд.\n«🎁 Подарки апгрейда» → там можно выключить или изменить цену.")


def lim_view():
    rows, lines = [], ["⚙️ <b>Лимиты и настройки</b>", "Нажми на пункт, чтобы изменить значение.\n"]
    for key, (label, env, default) in dbm.LIMITS.items():
        val = dbm.limit(key)
        lines.append(f"• {label}: <b>{val:g}</b>")
        rows.append([(f"{label}: {val:g}", f"lim:e:{key}")])
    rows.append([("« Меню", "menu")])
    return chr(10).join(lines), kb(rows)


async def lim_callback(uid: int, chat_id: int, mid, data: str):
    parts = data.split(":")
    act = parts[1] if len(parts) > 1 else ""
    if act == "list":
        STATE[uid]["mode"] = None
        text, markup = lim_view()
        await patch(uid, text, markup)
        return
    key = parts[2] if len(parts) > 2 else ""
    if key not in dbm.LIMITS:
        return
    if act == "e":
        STATE[uid]["mode"] = "lim_set"
        STATE[uid]["lim_key"] = key
        label, env, default = dbm.LIMITS[key]
        await patch(uid, f"✏️ <b>{label}</b>\nСейчас: <b>{dbm.limit(key):g}</b> (по умолчанию {float(default):g})\n\nПришли новое число:",
                    kb([[("↩️ Вернуть по умолчанию", f"lim:r:{key}")], [("« Отмена", "lim:list")]]))
        return
    if act == "r":
        dbm.set_setting(key, "")
        STATE[uid]["mode"] = None
        text, markup = lim_view()
        await patch(uid, "↩️ Возвращено значение по умолчанию.\n\n" + text, markup)
        return


def _prettify_slug(slug: str) -> str:
    import re as _r
    base, _, num = slug.rpartition("-")
    if not base:
        base, num = slug, ""
    base = _r.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base).replace("_", " ").strip()
    return f"{base} #{num}" if num.isdigit() else base


async def add_gift_from_link(url: str, price: float, name=None):
    """Берёт картинку подарка по ссылке (страница t.me/nft/..., StaticGram или прямая ссылка на картинку) и кладёт в каталог."""
    import re as _r
    from urllib.parse import urljoin, urlparse
    headers = {"User-Agent": "Mozilla/5.0 (compatible; WinLineBot/1.0)"}
    img_bytes, title = None, None
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as h:
            r = await h.get(url)
            ctype = (r.headers.get("content-type") or "").lower()
            if not r.is_success:
                return False, f"ссылка не открывается (HTTP {r.status_code})"
            if ctype.startswith("image/"):
                img_bytes = r.content
            else:
                html = r.text
                m = _r.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, _r.I) or \
                    _r.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, _r.I) or \
                    _r.search(r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)', html, _r.I)
                t = _r.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', html, _r.I)
                title = t.group(1).strip() if t else None
                if not m:
                    return False, "на странице нет картинки (og:image)"
                ir = await h.get(urljoin(url, m.group(1).replace("&amp;", "&")))
                if not ir.is_success or not ir.content:
                    return False, f"картинка не скачалась (HTTP {ir.status_code})"
                img_bytes = ir.content
    except Exception as e:
        return False, f"ошибка загрузки: {str(e)[:100]}"
    tail = urlparse(url).path.rstrip("/").split("/")[-1] or "gift"
    slug = "lk_" + _r.sub(r"[^a-z0-9]+", "_", tail.lower()).strip("_")[:24]
    out_dir = Path(os.getenv("GIFTS_IMG_DIR", "data/gifts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        Image.open(io.BytesIO(img_bytes)).convert("RGBA").resize((256, 256)).save(out_dir / f"{slug}.png")
    except Exception:
        return False, "по ссылке не картинка, которую можно открыть"
    gname = (name or title or _prettify_slug(tail))[:40]
    with dbm.connect() as c:
        c.execute("DELETE FROM catalog_gifts WHERE slug=?", (slug,))
    dbm.catalog_add(slug, gname, f"/static/gifts/{slug}.png?v={int(time.time())}", price, enabled=1)
    return True, gname


def ug_view(page: int):
    items = dbm.catalog_list()
    pages = max(1, (len(items) + UG_PAGE - 1) // UG_PAGE)
    page = max(0, min(page, pages - 1))
    chunk = items[page * UG_PAGE:(page + 1) * UG_PAGE]
    on = sum(1 for i in items if i["enabled"])
    text = (f"🎁 <b>Подарки апгрейда</b> ({on} из {len(items)} включено)\n"
            f"Страница {page + 1}/{pages}\n\n"
            "Нажми на название — включить/выключить в игре.\n✏️ — изменить цену (в ★).")
    rows = []
    for it in chunk:
        mark = "✅" if it["enabled"] else "🚫"
        price = f"{it['price']:g}"
        rows.append([(f"{mark} {it['name'][:18]} · {price}★", f"ug:t:{it['slug']}:{page}"), ("✏️", f"ug:p:{it['slug']}:{page}")])
    nav = []
    if page > 0:
        nav.append(("◀️", f"ug:list:{page - 1}"))
    if page < pages - 1:
        nav.append(("▶️", f"ug:list:{page + 1}"))
    if nav:
        rows.append(nav)
    fee = dbm.get_setting("gift_withdraw_fee", os.getenv("GIFT_WITHDRAW_FEE", "5"))
    rows.append([("🔗 Подарок по ссылке", "ug:link")])
    rows.append([("📥 Импорт подарков StaticGram", "ug:imp")])
    rows.append([(f"💸 Комиссия вывода подарка: {fee}★", "ug:fee")])
    rows.append([("« Меню", "menu")])
    text += "\n\n➕ Новый подарок: пришли сюда фото с подписью <code>Название | цена</code>."
    return text, kb(rows)


async def ug_callback(uid: int, chat_id: int, mid, data: str):
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    if action == "list":
        text, markup = ug_view(int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0)
        STATE[uid]["mode"] = None
        await patch(uid, text, markup)
        return
    if action == "imp":
        await patch(uid, "⏳ Загружаю подарки StaticGram…", kb([[("« Подарки", "ug:list:0")]]))
        added, skipped, err = await ug_import(uid)
        bal = ""
        try:
            br = await api("getMyStarBalance")
            bal = f"\n⭐ Баланс звёзд бота: <b>{(br.get('result') or {}).get('amount', '?')}</b> (с него идёт вывод монет игрокам; подарки отправляет юзербот из своего банка)"
        except Exception:
            pass
        if err:
            await patch(uid, f"Не вышло: {err}", kb([[("« Подарки", "ug:list:0")]]))
        else:
            await patch(uid, f"✅ Добавлено подарков: <b>{added}</b>, уже были: {skipped}.\nНовые <b>выключены</b> — включи нужные в списке.{bal}",
                        kb([[("🎁 К списку", "ug:list:0")]]))
        return
    if action == "fee":
        STATE[uid]["mode"] = "ug_fee"
        cur = dbm.get_setting("gift_withdraw_fee", os.getenv("GIFT_WITHDRAW_FEE", "5"))
        await patch(uid, f"💸 Комиссия за вывод подарка сейчас: <b>{cur}★</b>.\nПришли новую сумму числом (0 — бесплатно):",
                    kb([[("« Отмена", "ug:list:0")]]))
        return
    slug = parts[2] if len(parts) > 2 else ""
    page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
    g = dbm.catalog_get(slug)
    if not g:
        await patch(uid, "Подарок не найден.", back_kb())
        return
    if action == "t":
        dbm.catalog_set(slug, enabled=not g["enabled"])
        text, markup = ug_view(page)
        await patch(uid, text, markup)
        return
    if action == "p":
        STATE[uid]["mode"] = "ug_price"
        STATE[uid]["ug_slug"] = slug
        STATE[uid]["ug_page"] = page
        await patch(uid, f"✏️ <b>{g['name']}</b>\nСейчас: <b>{g['price']:g}★</b>\nПришли новую цену числом (например <code>35</code>):",
                    kb([[("« Отмена", f"ug:list:{page}")]]))
        return


async def wd_callback(uid: int, chat_id: int, mid, data: str):
    parts = data.split(":")
    if len(parts) < 3 or not parts[2].isdigit():
        return
    qid = int(parts[2])
    with db() as c:
        q = c.execute("SELECT * FROM gift_queue WHERE id=?", (qid,)).fetchone()
        if not q or q["status"] != "manual":
            await edit(chat_id, mid, f"Заявка #{qid} уже обработана.", None)
            return
        if parts[1] == "ok":
            c.execute("UPDATE gift_queue SET status='done', updated=? WHERE id=?", (int(time.time()), qid))
            if q["inv_row"]:
                c.execute("UPDATE inventory SET status='sent' WHERE rowid_=?", (q["inv_row"],))
            note, msg = f"✅ Заявка #{qid}: выдан (отметил {uid}).", "✅ Твой подарок выдан! Проверь Telegram."
        else:
            c.execute("UPDATE gift_queue SET status='rejected', updated=? WHERE id=?", (int(time.time()), qid))
            fee = float(q["fee"] or 0)
            if fee > 0:
                c.execute("UPDATE users SET coins=coins+? WHERE id=?", (fee, int(q["user_id"])))
            if q["inv_row"]:
                c.execute("UPDATE inventory SET status='won' WHERE rowid_=?", (q["inv_row"],))
            note, msg = f"↩️ Заявка #{qid}: возвращена игроку (отметил {uid}).", "↩️ Вывод подарка отклонён, он снова в твоих призах" + (f", комиссия {fee:g}★ возвращена." if fee > 0 else ".")
        c.commit()
    await edit(chat_id, mid, note, None)
    await send(int(q["user_id"]), msg)


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

    if data == "maint:text":
        STATE[uid]["mode"] = "maint_text"
        cur = dbm.get_setting("maintenance_text", "") or "Сервис на технических работах. Скоро вернёмся."
        await patch(uid, f"✏️ Текст, который видят игроки во время техперерыва.\nСейчас:\n<i>{cur}</i>\n\nПришли новый текст (или <code>-</code>, чтобы вернуть стандартный):",
                    kb([[("« Меню", "menu")]]))
        return

    if data.startswith("lim:"):
        await lim_callback(uid, chat_id, mid, data)
        return

    if data == "maint:toggle":
        if not (is_owner(uid) or is_admin(uid)):
            await patch(uid, "Нельзя")
            return
        set_setting("maintenance", "0" if maintenance_on() else "1")
        await show_menu(chat_id, mid, uid)
        return

    if data in ("upg:toggle:nft", "upg:toggle:stars"):
        key = "upg_nft_on" if data.endswith("nft") else "upg_stars_on"
        cur = dbm.limit(key) >= 1
        dbm.set_limit(key, 0 if cur else 1)
        await show_menu(chat_id, mid, uid)
        return

    if data in ("top:menu", "top"):
        board = dbm.leaderboard("turnover", 15)
        lines = ["<b>Топ по обороту</b>"]
        if not board:
            lines.append("Пусто")
        for i, r in enumerate(board, 1):
            lines.append(f"{i}. {r['username'] or r['user_id']} — {r['score']:.1f}")
        await patch(
            uid,
            "\n".join(lines),
            kb([
                [("Обновить", "top:menu")],
                [("Обнулить весь топ (оборот)", "top:clear:all")],
                [("Обнулить игрока", "top:zero:ask")],
                [("Меню", "menu")],
            ]),
        )
        return

    if data == "top:clear:all":
        with dbm.connect() as c:
            c.execute("UPDATE user_stats SET turnover_ton=0")
        await patch(uid, "Весь топ по обороту обнулен.", kb([[("К топу", "top:menu")], [("Меню", "menu")]]))
        return

    if data == "top:zero:ask":
        STATE[uid]["mode"] = "top_zero"
        await patch(uid, "Кого убрать из топа? @username или id.", kb([[("Отмена", "top:menu")]]))
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

    if data == "ug:link":
        STATE[uid]["mode"] = "ug_link"
        await patch(uid, "🔗 <b>Подарок по ссылке</b>\nПришли ссылку на подарок и цену через пробел, например:\n"
                    "<code>https://t.me/nft/PlushPepe-1 120</code>\n"
                    "Можно добавить своё название в конце: <code>… 120 Плюш Пепе</code>.\n"
                    "Я возьму картинку со страницы ссылки и добавлю подарок в апгрейд.",
                    kb([[("« Отмена", "ug:list:0")]]))
        return

    # ---- подарки апгрейда: вкл/выкл и цена ----
    if data.startswith("ug:"):
        await ug_callback(uid, chat_id, mid, data)
        return

    # ---- заявки на вывод подарка ----
    if data.startswith("wd:"):
        await wd_callback(uid, chat_id, mid, data)
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


APP_URL = (os.getenv("WEBAPP_URL") or os.getenv("MINIAPP_URL") or "").strip()
# Прямую ссылку staticgram.top/<бот>/<апп> в кнопки не ставим: внутри клиента она открывается как сайт и staticgram.top отказывает в соединении.
HELLO = os.getenv("START_TEXT", "🎃 <b>WinLine</b> — лучший дроп!\nНажми кнопку ниже, чтобы открыть игру.")


async def send_app(chat_id: int, extra: str = "") -> None:
    """Отправляет приветствие с кнопкой, открывающей мини-апп."""
    text = HELLO + (("\n\n" + extra) if extra else "")
    if not APP_URL:
        await send(chat_id, text + "\n\n⚠️ Адрес мини-аппа не задан (WEBAPP_URL).")
        return
    r = await send(chat_id, text, {"inline_keyboard": [[{"text": "🎮 Открыть WinLine", "web_app": {"url": APP_URL}}]]})
    if not r.get("ok"):   # если клиент не принимает web_app-кнопку — обычная ссылка
        print("web_app button failed:", r.get("description"))
        r = await send(chat_id, text, {"inline_keyboard": [[{"text": "🎮 Открыть WinLine", "url": APP_URL}]]})
        if not r.get("ok"):
            await send(chat_id, text + f"\n\n{APP_URL}")


async def setup_menu_button() -> None:
    """Кнопка «Играть» слева от поля ввода в чате бота + команды."""
    if not APP_URL:
        return
    try:
        await api("deleteWebhook", drop_pending_updates=False)
    except Exception as e:
        print("deleteWebhook:", e)
    try:
        r = await api("setChatMenuButton", menu_button={"type": "web_app", "text": "Играть", "web_app": {"url": APP_URL}})
        print("menu button:", "ok" if r.get("ok") else r.get("description"))
        await api("setMyCommands", commands=[{"command": "start", "description": "Открыть игру"}, {"command": "admin", "description": "Админ-панель"}, {"command": "id", "description": "Мой Telegram ID"}])
    except Exception as e:
        print("menu button error:", e)


async def on_text(chat_id: int, uid: int, text: str):
    t = text.strip()
    cmd = t.split()[0].split("@")[0].lower() if t else ""

    # любой может узнать свой id
    if cmd == "/id":
        await send(chat_id, f"Ваш ID: <code>{uid}</code>\nOWNER_ID сейчас: <code>{OWNER_ID}</code>")
        return

    # /start — только приветствие и кнопка игры (без спама админкой на каждый чих)
    if cmd == "/start" or t.startswith("/start"):
        parts = t.split()
        if len(parts) > 1 and parts[1].startswith("ref") and parts[1][3:].isdigit():
            try:                                       # пришёл по реферальной ссылке бота
                dbm.ensure_user(uid)
                if dbm.ref_of(uid) is None and dbm.turnover(uid) == 0:
                    dbm.ref_attach(uid, int(parts[1][3:]))
            except Exception as e:
                print("ref attach error", e)
        extra = "Админ-панель: /admin" if is_admin(uid) else ""
        await send_app(chat_id, extra)
        return

    # /admin или «админ»
    if cmd in ("/admin", "админ") or t.lower() == "админ":
        if not is_admin(uid):
            await send(chat_id, "Нет доступа.")
            return
        await show_menu(chat_id, STATE.get(uid, {}).get("msg_id"), uid)
        return

    # не админ — на обычные сообщения НЕ отвечаем (антиспам)
    if not is_admin(uid):
        return

    # админ без активного режима ввода — игнор случайного текста (меню только по /admin)
    mode = (STATE.get(uid) or {}).get("mode")
    if not mode:
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

    if mode == "maint_text":
        dbm.set_setting("maintenance_text", "" if t == "-" else t[:300])
        st["mode"] = None
        await patch(uid, "✅ Текст техперерыва сохранён.", kb([[("« Меню", "menu")]]))
        return

    if mode == "top_zero":
        target = resolve_user(text)
        if not target:
            await send(chat_id, "Игрок не найден.")
            return
        with dbm.connect() as c:
            c.execute("INSERT OR IGNORE INTO user_stats(user_id, turnover_ton) VALUES(?,0)", (target,))
            c.execute("UPDATE user_stats SET turnover_ton=0 WHERE user_id=?", (target,))
            c.execute("DELETE FROM spin_log WHERE user_id=?", (target,))
        STATE[uid]["mode"] = None
        await send(chat_id, f"Игрок {target} убран из топа.", kb([[("К топу", "top:menu")], [("Меню", "menu")]]))
        return

    if mode == "lim_set":
        key = st.get("lim_key")
        try:
            val = float(t.replace(",", ".").replace(" ", ""))
            if val < 0 or val > 10**9:
                raise ValueError
        except ValueError:
            await patch(uid, "Нужно число, например <code>75000</code>.", kb([[("« Отмена", "lim:list")]]))
            return
        dbm.set_limit(key, val)
        st["mode"] = None
        text, markup = lim_view()
        await patch(uid, f"✅ {dbm.LIMITS[key][0]}: <b>{val:g}</b>\n\n" + text, markup)
        return

    if mode == "ug_link":
        parts = t.split()
        if len(parts) < 2 or not parts[0].lower().startswith("http"):
            await patch(uid, "Формат: <code>ссылка цена [название]</code>, например <code>https://t.me/nft/PlushPepe-1 120</code>",
                        kb([[("« Отмена", "ug:list:0")]]))
            return
        try:
            price = float(parts[1].replace(",", "."))
            if not (price > 0):
                raise ValueError
        except ValueError:
            await patch(uid, "Цена должна быть числом больше 0.", kb([[("« Отмена", "ug:list:0")]]))
            return
        await patch(uid, "⏳ Загружаю картинку по ссылке…", kb([[("« Отмена", "ug:list:0")]]))
        ok, info = await add_gift_from_link(parts[0], price, " ".join(parts[2:]).strip() or None)
        st["mode"] = None
        if ok:
            tt, mm = ug_view(0)
            await patch(uid, f"✅ Подарок <b>{info}</b> добавлен в апгрейд за {price:g}★.\n\n" + tt, mm)
        else:
            await patch(uid, f"❌ Не получилось: {info}", kb([[("🔗 Ещё раз", "ug:link")], [("« Подарки", "ug:list:0")]]))
        return

    if mode == "ug_fee":
        try:
            fee = float(text.replace(",", ".").strip())
            if fee < 0 or fee > 100000:
                raise ValueError
        except ValueError:
            await patch(uid, "Нужно число от 0, например <code>5</code>.", kb([[("« Отмена", "ug:list:0")]]))
            return
        dbm.set_setting("gift_withdraw_fee", f"{fee:g}")
        st["mode"] = None
        t, m = ug_view(0)
        await patch(uid, f"Комиссия обновлена: <b>{fee:g}★</b>\n\n" + t, m)
        return

    if mode == "ug_price":
        slug = st.get("ug_slug")
        try:
            price = float(text.replace(",", ".").strip())
            if not (price > 0) or price > 1_000_000:
                raise ValueError
        except ValueError:
            await patch(uid, "Нужно число больше 0, например <code>35</code>.", kb([[("« Отмена", f"ug:list:{st.get('ug_page', 0)}")]]))
            return
        dbm.catalog_set(slug, price=price)
        st["mode"] = None
        t, m = ug_view(int(st.get("ug_page") or 0))
        await patch(uid, f"Цена обновлена: <b>{price:g}★</b>\n\n" + t, m)
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
    await setup_menu_button()
    offset = 0
    print("admin bot (buttons) on", API_BASE, "owner", OWNER_ID)
    while True:
        try:
            data = await api(
                "getUpdates",
                offset=offset,
                timeout=30,
                allowed_updates=["message", "callback_query", "pre_checkout_query"],
            )
            for upd in data.get("result") or []:
                offset = max(offset, upd["update_id"] + 1)
                if "callback_query" in upd:
                    await on_callback(upd["callback_query"])
                    continue
                if "pre_checkout_query" in upd:
                    await on_pre_checkout(upd["pre_checkout_query"])
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
                if msg.get("successful_payment"):
                    await on_payment(uid, chat_id, msg["successful_payment"])
                    continue
                if msg.get("photo") or (msg.get("document") or {}).get("mime_type", "").startswith("image/"):
                    await on_photo(chat_id, uid, msg)
                    continue
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
PERIOD = int(os.getenv("USERBOT_PERIOD", "15"))
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


def _all_admin_ids():
    ids = set(ADMIN_IDS)
    if OWNER_ID:
        ids.add(int(OWNER_ID))
    try:
        with db() as c:
            ids.update(int(r["user_id"]) for r in c.execute("SELECT user_id FROM admins"))
    except Exception:
        pass
    return ids


async def transfer_one(client, user_id: int, gift_id: str, saved_msg_id: int | None) -> tuple[bool, str]:
    """Передаёт игроку подарок, который уже лежит у релеера (сохранённый)."""
    try:
        Transfer = getattr(functions.payments, "TransferStarGiftRequest", None) or getattr(
            functions.payments, "TransferGiftRequest", None
        )
        if Transfer is None:
            return False, "TransferStarGiftRequest not in telethon — обновите клиент/staticgram"
        try:
            await client(Transfer(stargift=saved_msg_id, to_id=user_id))
        except TypeError:
            await client(Transfer(gift_id=int(gift_id), user_id=user_id))
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


async def buy_and_send(client, user_id: int, username: str, gift_id: str) -> tuple[bool, str]:
    """Как в Telegram: юзербот покупает подарок за звёзды СВОЕГО банка и отправляет игроку."""
    try:
        from telethon.tl import types as tl_types
        inv_cls = getattr(tl_types, "InputInvoiceStarGift", None)
        if inv_cls is None:
            return False, "telethon слишком старый для отправки подарков (pip install -U telethon)"
        peer, last = None, None
        for ref in (("@" + username.lstrip("@")) if username else None, user_id):
            if not ref:
                continue
            try:
                peer = await client.get_input_entity(ref)
                break
            except Exception as e:
                last = e
        if peer is None:
            return False, f"no_peer: {str(last)[:120]}"
        inv = inv_cls(peer=peer, gift_id=int(gift_id), hide_name=False, include_upgrade=False)
        form = await client(functions.payments.GetPaymentFormRequest(invoice=inv))
        await client(functions.payments.SendStarsFormRequest(form_id=form.form_id, invoice=inv))
        return True, ""
    except Exception as e:
        return False, str(e)[:300]


def _why(err: str):
    """(текст игроку, текст админам)"""
    e = err or ""
    if "BALANCE_TOO_LOW" in e or "BALANCE" in e.upper():
        return "Подарок скоро выдадим, попробуй чуть позже.", "⚠️ В банке юзербота не хватает звёзд на подарок. Пополни баланс звёзд аккаунта-юзербота."
    if e.startswith("no_peer") or "PEER_ID_INVALID" in e or "USERNAME" in e.upper():
        return "Не получилось найти тебя для отправки. Задай username в настройках Telegram и напиши аккаунту релеера, потом попробуй снова.", f"⚠️ Юзербот не нашёл получателя: {e[:100]}"
    return "Не удалось отправить подарок, попробуй позже.", f"⚠️ Ошибка отправки подарка: {e[:160]}"


async def process_queue(client) -> None:
    if not Path(DB_PATH).exists():
        return
    con = db()
    try:
        rows = con.execute("SELECT * FROM gift_queue WHERE status='pending' ORDER BY id ASC LIMIT 5").fetchall()
    except sqlite3.OperationalError:
        con.close()
        return
    if not rows:
        con.close()
        return

    # актуальный склад (сохранённые подарки релеера) — вдруг нужный уже лежит у юзербота
    try:
        snap = await snapshot(client)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(snap, ensure_ascii=False), "utf-8")
        by_id = {str(x["id"]): x for x in snap["stock"]}
    except Exception as e:
        print("snapshot in queue", e)
        by_id = {}

    for row in rows:
        qid, uid = row["id"], row["user_id"]
        gift_id = str(row["gift_id"])
        inv_row = row["inv_row"]
        fee = float(row["fee"] or 0) if "fee" in row.keys() else 0.0
        con.execute("UPDATE gift_queue SET status='sending', updated=? WHERE id=?", (int(time.time()), qid))
        con.commit()

        u = con.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        username = (u["username"] if u else "") or ""
        cat = None
        try:
            cat = con.execute("SELECT name FROM catalog_gifts WHERE sg_id=? LIMIT 1", (gift_id,)).fetchone()
        except sqlite3.OperationalError:
            pass
        item = by_id.get(gift_id)
        name = (cat["name"] if cat else None) or (item or {}).get("name") or gift_id

        if item and int(item.get("count") or 0) >= 1:
            saved_ids = [x for x in (item.get("saved_ids") or []) if x]
            ok, err = await transfer_one(client, uid, gift_id, saved_ids[0] if saved_ids else None)
            if not ok:                               # не вышло передать — купим и отправим
                ok, err = await buy_and_send(client, uid, username, gift_id)
        else:
            ok, err = await buy_and_send(client, uid, username, gift_id)

        if ok:
            con.execute("UPDATE gift_queue SET status='done', error='', updated=? WHERE id=?", (int(time.time()), qid))
            if inv_row:
                con.execute("UPDATE inventory SET status='sent' WHERE rowid_=?", (inv_row,))
            con.commit()
            await bot_send(uid, f"✅ Подарок <b>{name}</b> отправлен тебе в Telegram!")
            for aid in _all_admin_ids():
                await bot_send(aid, f"✅ Юзербот отправил «{name}» игроку <code>{uid}</code> (заявка #{qid}).")
        else:
            con.execute("UPDATE gift_queue SET status='failed', error=?, updated=? WHERE id=?", (err[:300], int(time.time()), qid))
            if inv_row:
                con.execute("UPDATE inventory SET status='won' WHERE rowid_=?", (inv_row,))
            if fee > 0:                               # вывод не удался — комиссию возвращаем
                con.execute("UPDATE users SET coins=coins+? WHERE id=?", (fee, uid))
            con.commit()
            print("gift send failed:", qid, err)
            to_user, to_admin = _why(err)
            await bot_send(uid, f"⚠️ {to_user}" + (f"\nКомиссия {fee:g}★ возвращена." if fee > 0 else ""))
            for aid in _all_admin_ids():
                await bot_send(aid, f"{to_admin}\nЗаявка #{qid}, игрок <code>{uid}</code>, подарок «{name}».")
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
        last_snap = 0.0
        while True:
            if time.time() - last_snap >= 60:
                try:
                    snap = await snapshot(client)
                    OUT.write_text(json.dumps(snap, ensure_ascii=False), "utf-8")
                    print("stock", len(snap["stock"]), "items")
                except Exception as e:
                    print("snapshot error:", e)
                last_snap = time.time()
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
    if BOT_TOKEN:
        loop.create_task(guard("admin_bot", loop_admin))
        if not OWNER_ID:
            print("бот запущен без OWNER_ID: /start работает, админ-панель недоступна")
    else:
        print("бот выключен: нужен BOT_TOKEN")
    if API_ID and API_HASH and HAVE_TELETHON:
        loop.create_task(guard("userbot", userbot_main))
    else:
        print("userbot выключен: нужны USERBOT_API_ID, USERBOT_API_HASH и telethon")

"""
Winline Halloween — один server.py (как старый).
Запуск: uvicorn server:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations
import hashlib, hmac, json, math, os, random, time, uuid
from pathlib import Path
from urllib.parse import parse_qsl

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))   # import db / config / bots работает из любой папки

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import db

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID") or "0")
STATICGRAM_API = os.getenv("STATICGRAM_API", "https://api.staticgram.top").rstrip("/")
RELAYER_JSON = os.getenv("RELAYER_JSON", "data/relayer_gifts.json")
WITHDRAW_STEP = int(float(os.getenv("WITHDRAW_STEP") or "25"))
DAILY_WITHDRAW_CAP = int(float(os.getenv("DAILY_WITHDRAW_CAP") or "75000"))
MIN_BET = float(os.getenv("MIN_BET") or "0.1")
MAX_BET = float(os.getenv("MAX_BET") or "50000")
MINES_HOUSE = float(os.getenv("MINES_HOUSE") or "0.05")
DEV_USER_ID = os.getenv("DEV_USER_ID", "")
WEBAPP_URL = os.getenv("WEBAPP_URL") or os.getenv("MINIAPP_URL") or ""
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()]

db.init()
app = FastAPI(title="Winline")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class InitDataFromBody:
    """Мини-аппка шлёт POST {initData, ...} — переносим initData в заголовок X-Init-Data."""
    def __init__(self, app): self.app = app
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        chunks, more = [], True
        while more:
            m = await receive()
            chunks.append(m.get("body", b"")); more = m.get("more_body", False)
        body = b"".join(chunks)
        headers = list(scope["headers"])
        if not any(k == b"x-init-data" for k, _ in headers):
            try:
                init = (json.loads(body or b"{}") or {}).get("initData")
                if isinstance(init, str) and init:
                    headers.append((b"x-init-data", init.encode()))
                    scope = {**scope, "headers": headers}
            except Exception:
                pass
        sent = False
        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()
        await self.app(scope, replay, send)

app.add_middleware(InitDataFromBody)


@app.exception_handler(StarletteHTTPException)
async def _http_err(request, exc):
    """Фронт читает data.error / e.code — приводим все ошибки к такому виду."""
    d = exc.detail
    if isinstance(d, dict):
        body = {"error": d.get("code") or "error", "message": d.get("message") or d.get("code") or "error", **d}
    else:
        msg = str(d)
        if exc.status_code == 503 and msg == "maintenance":
            msg = db.get_setting("maintenance_text", "") or "Сервис на технических работах. Скоро вернёмся."
            body = {"error": "maintenance", "message": msg}
        else:
            body = {"error": msg, "message": msg}
    return JSONResponse(body, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _val_err(request, exc):
    return JSONResponse({"error": "bad_request", "message": "bad request"}, status_code=422)

# Раскладка репозитория: server.py, config.py, db.py, static/ (внутри index.html, /images и все файлы фронта)
ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
ASSETS = STATIC / "static" if (STATIC / "static").is_dir() else STATIC      # /static/...  (если файлы лежат во вложенной static/static — тоже работает)
IMAGES = next((p for p in (STATIC / "images", ASSETS / "images", ROOT / "images") if p.is_dir()), None)

MINES_MULT = {
    3: [1.0,1.12,1.28,1.47,1.7,2.0,2.35,2.8,3.4,4.2,5.2,6.5,8.2,10.5,13.5,17.5,23.0,30.0,40.0,55.0,75.0,100.0],
    5: [1.0,1.2,1.45,1.8,2.25,2.9,3.7,4.8,6.3,8.4,11.5,15.5,21.0,29.0,40.0,56.0,80.0,115.0,170.0,250.0],
    8: [1.0,1.35,1.85,2.6,3.7,5.3,7.8,11.5,17.5,27.0,42.0,65.0,105.0,170.0,280.0,480.0,850.0],
}
UPGRADE_BASE = {2: 0.48, 5: 0.15, 10: 0.05}
UPGRADE_LOSS = {2:{2:0.04,3:0.07,4:0.09,5:0.11},5:{3:0.015,4:0.025,5:0.035},10:{3:0.008,4:0.012,5:0.018}}
CELLS = 25
HAT_VALUE = float(os.getenv("HAT_VALUE", "12"))        # во сколько GRAM оценивается обычная шляпа
MINES_RTP = float(os.getenv("MINES_RTP", "0.95"))
MINES_MAX_MULT = float(os.getenv("MINES_MAX_MULT", "1000"))      # потолок множителя (защита банка от x50000 на 20 минах)       # возврат игрокам в минах (0.95 = комиссия 5%)
CX_CHOICES = [1, 3, 5, 10, 15, 20]
CHANCE_GRID = [{"chance": round(p / 100, 2), "cost_ton": round(HAT_VALUE * p / 100, 2)} for p in range(5, 71)]


def _mult_at(empties: int, k: int) -> float:
    """Честный множитель после k безопасных клеток при `empties` минах из 25 (с комиссией 1-RTP)."""
    surv = 1.0
    for i in range(k):
        surv *= (CELLS - empties - i) / (CELLS - i)
    return min(db.limit("mines_max_mult"), round(MINES_RTP / surv, 2)) if surv > 0 else 0.0


def _ladder() -> dict:
    return {str(e): [_mult_at(e, k) for k in range(1, CELLS - e + 1)] for e in CX_CHOICES}

# ---------- auth ----------
def verify_init(raw: str) -> int:
    if not raw:
        if DEV_USER_ID:
            return int(DEV_USER_ID)
        print("AUTH 401: initData пустой (открыто не из бота?)")
        raise HTTPException(401, "no initData")
    if raw.lower().startswith("tma "):
        raw = raw[4:].strip()
    if not BOT_TOKEN:
        raise HTTPException(503, "server misconfigured: BOT_TOKEN is empty")
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    got = pairs.pop("hash", "")
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()

    def _calc(p):
        chk = "\n".join(f"{k}={p[k]}" for k in sorted(p))
        return hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest()

    # StaticGram (как и Telegram): в data_check_string входят ВСЕ поля кроме hash, включая signature.
    # На случай старых клиентов пробуем ещё и вариант без signature.
    ok = bool(got) and hmac.compare_digest(_calc(pairs), got)
    if not ok and "signature" in pairs:
        ok = bool(got) and hmac.compare_digest(_calc({k: v for k, v in pairs.items() if k != "signature"}), got)
    if not ok:
        print("AUTH 401: bad signature; token_len=%d, keys=%s" % (len(BOT_TOKEN), sorted(pairs)))
        raise HTTPException(401, "bad signature")
    if time.time() - int(pairs.get("auth_date") or 0) > 86400:
        print("AUTH 401: expired")
        raise HTTPException(401, "expired")
    return int(json.loads(pairs["user"])["id"])

def uid_from(request: Request, x_init: str | None = None) -> int:
    raw = x_init or request.headers.get("x-init-data") or request.headers.get("authorization") or ""
    if raw.lower().startswith("tma "):
        raw = raw[4:]
    uid = verify_init(raw.strip())
    if db.get_setting("maintenance") == "1" and not db.is_admin(uid):
        raise HTTPException(503, "maintenance")
    uname = ""
    try:
        uname = (json.loads(dict(parse_qsl(raw.strip())).get("user") or "{}").get("username") or "")
    except Exception:
        pass
    db.ensure_user(uid, uname)
    try:                                              # игрок пришёл по реферальной ссылке (startapp=ref123) — запоминаем, если он ещё не играл
        sp = dict(parse_qsl(raw.strip())).get("start_param") or ""
        if sp.startswith("ref") and sp[3:].isdigit() and db.ref_of(uid) is None and db.turnover(uid) == 0:
            db.ref_attach(uid, int(sp[3:]))
    except Exception as e:
        print("ref attach error", e)
    with db.connect() as c:
        r = c.execute("SELECT banned FROM users WHERE id=?", (uid,)).fetchone()
        if r and r["banned"]:
            raise HTTPException(403, "banned")
    return uid

def stock():
    p = Path(RELAYER_JSON)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text("utf-8")).get("stock") or []
    except Exception:
        return []

GIFT_MARGIN = float(os.getenv("GIFT_MARGIN", "0.08"))    # наценка на подарки (видна в цене: цена = подарок×шанс/(1-наценка))
HOUSE_EDGE = float(os.getenv("HOUSE_EDGE", "0.08"))      # комиссия обычной шляпы


import re as _re
_DEFAULT_PRICES = {"dragon": 60, "frost": 50, "thunder": 50, "crystal": 45, "sun": 45, "rainbow": 40, "trident": 40, "sword": 35,
                   "skeleton hand": 80, "hall ember poker": 70, "hall emerald scepter": 90, "hall host axe": 70, "basement wrench": 40}


def _gift_name(stem: str) -> str:
    n = _re.sub(r"[-_]?(icon|pixel)\b", "", stem)
    n = _re.sub(r"[-_]v\d+$", "", n)
    n = _re.sub(r"[-_]+", " ", n).strip()
    return n.title() or stem


def seed_catalog():
    """Подарки апгрейда берём из картинок static/gifts/* (имя файла = название подарка).
    Новые файлы добавляются сами; цены и «вкл/выкл» меняются в админ-боте и не перезатираются.
    Подарки можно добавлять и из бота: админ шлёт фото с подписью «Название | цена»."""
    items = []
    seen = set()
    for folder, urlbase in ((ASSETS / "gifts", "/static/gifts"),):
        if not folder.is_dir():
            continue
        for f in sorted(folder.iterdir()):
            if f.suffix.lower() not in (".png", ".webp"):
                continue
            if "pixel" in f.stem:                       # дубль иконки
                continue
            slug = _re.sub(r"[^a-z0-9]+", "_", _re.sub(r"[-_]?icon", "", f.stem.lower())).strip("_")[:28]
            if not slug or slug in seen:
                continue
            seen.add(slug)
            name = _gift_name(f.stem)
            price = _DEFAULT_PRICES.get(name.lower(), 20)
            items.append((slug, name, f"{urlbase}/{f.name}", price))
    if items:
        db.catalog_seed(items)


def available_stock():
    """Подарки апгрейда = включённые в каталоге + шляпа с PNG (всегда первая)."""
    out = [{
        "id": "hat",
        "name": "Шляпа волшебника",
        "image": "/images/hat.png",
        "price": HAT_VALUE,
        "count": 9999,
        "sg_id": "",
    }]
    for g in db.catalog_list(enabled_only=True):
        if g["price"] <= 0:
            continue
        if str(g["slug"]) == "hat":
            continue
        out.append({
            "id": g["slug"],
            "name": g["name"],
            "image": g["image"],
            "price": g["price"],
            "count": 9999,
            "sg_id": g.get("sg_id", ""),
        })
    return out


def _old_available_stock():
    """Склад релеера минус подарки, которые уже выиграны игроками и ждут отправки."""
    st = stock()
    try:
        with db.connect() as c:
            held = {r["gift_id"]: r["n"] for r in c.execute(
                "SELECT gift_id, COUNT(*) AS n FROM inventory WHERE status IN ('won','sending') GROUP BY gift_id")}
    except Exception:
        held = {}
    out = []
    for x in st:
        left = int(x.get("count") or 0) - int(held.get(str(x.get("id")), 0))
        if left > 0:
            out.append({**x, "count": left})
    return out


async def bot_api(method: str, payload: dict):
    if not BOT_TOKEN:
        return False, "no token"
    url = f"{STATICGRAM_API}/bot{BOT_TOKEN}/{method}"
    try:
        async with httpx.AsyncClient(timeout=20) as h:
            r = await h.post(url, json=payload)
        j = r.json()
        return bool(j.get("ok")), "" if j.get("ok") else str(j.get("description", ""))[:200]
    except Exception as e:
        return False, str(e)[:200]

async def bot_raw(method: str, payload: dict) -> dict:
    if not BOT_TOKEN:
        return {"ok": False, "description": "no token"}
    try:
        async with httpx.AsyncClient(timeout=20) as h:
            r = await h.post(f"{STATICGRAM_API}/bot{BOT_TOKEN}/{method}", json=payload)
        return r.json()
    except Exception as e:
        return {"ok": False, "description": str(e)[:200]}

# ---------- models ----------
class SpinIn(BaseModel):
    chance: float = Field(ge=0.01, le=0.70)
    tier: str = "random"
    gift: str | None = None
    cost: float | None = None

class ChestStart(BaseModel):
    empties: int = Field(ge=1, le=24)
    bet: float

class ChestOpen(BaseModel):
    cell: int = Field(ge=0, le=24)

class UpgradeIn(BaseModel):
    amount: float
    mult: int

class IdIn(BaseModel):
    id: str

class PrizeWdIn(BaseModel):
    prize_id: int = 0
    fee_ton: float = 0


async def _notify_admins(text: str, markup=None):
    ids = set(ADMIN_IDS)
    if OWNER_ID:
        ids.add(int(OWNER_ID))
    try:
        with db.connect() as c:
            ids.update(int(r["user_id"]) for r in c.execute("SELECT user_id FROM admins"))
    except Exception:
        pass
    for aid in ids:
        payload = {"chat_id": aid, "text": text, "parse_mode": "HTML"}
        if markup:
            payload["reply_markup"] = markup
        try:
            await bot_api("sendMessage", payload)
        except Exception as e:
            print("notify admin fail", aid, e)


@app.post("/api/withdraw/chat")
async def withdraw_chat(body: PrizeWdIn, request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    return {"ok": True}


async def prize_withdraw(uid: int, prize_id: int):
    fee = gift_withdraw_fee()
    with db.connect() as c:
        row = c.execute("SELECT gift_id,name,price FROM inventory WHERE rowid_=? AND user_id=?", (prize_id, uid)).fetchone()
        if not row or c.execute("SELECT status FROM inventory WHERE rowid_=?", (prize_id,)).fetchone()["status"] != "won":
            raise HTTPException(400, detail={"code": "not_sellable"})
        if str(row["gift_id"]) == "hat":
            raise HTTPException(400, detail={"code": "not_withdrawable", "message": "Шляпу можно только продать"})
    if fee > 0 and not db.spend(uid, fee):                      # комиссия за вывод подарка
        raise HTTPException(400, detail={"code": "insufficient_funds"})
    if fee > 0:
        db.ledger(fee, 0)
    with db.connect() as c:
        cur = c.execute("UPDATE inventory SET status='withdraw_pending' WHERE rowid_=? AND user_id=? AND status='won'", (prize_id, uid))
        if cur.rowcount != 1:
            if fee > 0:
                db.add_coins(uid, fee)
            raise HTTPException(400, detail={"code": "not_sellable"})
        c.execute("INSERT INTO gift_queue(user_id,gift_id,inv_row,status,created,updated,fee) VALUES(?,?,?,?,?,?,?)",
                  (uid, row["gift_id"], prize_id, "manual", int(time.time()), int(time.time()), fee))
        qid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    uname = ""
    with db.connect() as c:
        u = c.execute("SELECT username FROM users WHERE id=?", (uid,)).fetchone()
        uname = (u["username"] if u else "") or ""
    who = f"@{uname}" if uname else f"id {uid}"
    cat = db.catalog_get(str(row["gift_id"]))
    userbot_on = bool(os.getenv("USERBOT_API_ID"))
    mode = os.getenv("GIFT_DELIVERY", "userbot").lower()          # userbot — шлёт юзербот из своего банка; bot — шлёт бот со своего баланса звёзд
    if cat and cat.get("sg_id") and mode != "bot" and userbot_on:
        with db.connect() as c:                       # юзербот заберёт заявку, отправит подарок и сам уведомит игрока
            c.execute("UPDATE gift_queue SET status='pending', gift_id=?, updated=? WHERE id=?", (cat["sg_id"], int(time.time()), qid))
        return {"ok": True, "queued": True, "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "prizes": _my_prizes(uid)}
    if cat and cat.get("sg_id") and mode == "bot":    # отправка ботом с баланса звёзд бота
        res = await bot_raw("sendGift", {"user_id": uid, "gift_id": cat["sg_id"], "text": "Подарок из WinLine 🎁"})
        if res.get("ok"):
            with db.connect() as c:
                c.execute("UPDATE gift_queue SET status='done', updated=? WHERE id=?", (int(time.time()), qid))
                c.execute("UPDATE inventory SET status='sent' WHERE rowid_=?", (prize_id,))
            await bot_api("sendMessage", {"chat_id": uid, "text": f"🎁 Подарок «{row['name']}» отправлен тебе в Telegram!"})
            await _notify_admins(f"✅ Авто-выдача #{qid}: {who} получил «{row['name']}» ({row['price']}★), комиссия {fee:g}★.")
            return {"ok": True, "sent": True, "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "prizes": _my_prizes(uid)}
        why = str(res.get("description", ""))[:160]
        print("sendGift failed:", why)
        extra = f"\n⚠️ Авто-отправка не удалась: {why}\nПроверь баланс звёзд бота и выдай вручную."
    else:
        extra = ""
    await _notify_admins(
        f"🎁 <b>Заявка на вывод подарка #{qid}</b>\nИгрок: {who} (<code>{uid}</code>)\nПодарок: {row['name']} · {row['price']}★\nКомиссия: {fee:g}★ (оплачена)" + extra,
        {"inline_keyboard": [[{"text": "✅ Выдан", "callback_data": f"wd:ok:{qid}"}, {"text": "↩️ Вернуть игроку", "callback_data": f"wd:no:{qid}"}]]})
    return {"ok": True, "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "prizes": _my_prizes(uid)}


class StarsIn(BaseModel):
    stars: int = 0
    prize_id: int = 0
    fee_ton: float = 0


# ---------- пополнение звёздами StaticGram ----------
class StarsDepIn(BaseModel):
    amount: float = 0
    order_id: str = ""


@app.post("/api/stars/deposit/create")
async def stars_deposit_create(body: StarsDepIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    if not BOT_TOKEN:
        raise HTTPException(400, detail={"code": "stars_disabled"})
    amount = float(body.amount or 0)
    if not (amount == amount) or amount < db.limit("deposit_min") or amount > db.limit("deposit_max"):
        raise HTTPException(400, detail={"code": "bad_amount"})
    amount = round(amount, 2)
    stars = int(math.ceil(amount * STARS_PER_COIN))
    if stars < 1:
        raise HTTPException(400, detail={"code": "bad_amount"})
    import uuid
    order_id = uuid.uuid4().hex[:24]
    db.deposit_create(order_id, uid, stars, amount)
    res = await bot_raw("createInvoiceLink", {
        "title": "Пополнение WinLine", "description": f"{amount:g} монет за {stars}★", "payload": order_id,
        "currency": "XTR", "provider_token": "", "prices": [{"label": "Монеты", "amount": stars}]})
    if not res.get("ok") or not res.get("result"):
        print("createInvoiceLink failed:", res.get("description"))
        raise HTTPException(502, detail={"code": "invoice_failed"})
    return {"invoice_url": res["result"], "order_id": order_id, "amount": amount, "stars": stars}


@app.post("/api/stars/deposit/status")
async def stars_deposit_status(body: StarsDepIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    d = db.deposit_get(body.order_id)
    if not d or int(d["user_id"]) != uid:
        raise HTTPException(404, detail={"code": "not_found"})
    return {"status": d["status"], "amount": d["amount"]}


# ---------- награды (алмазы) ----------
GEM_TIERS = [(10, 1.0), (25, 1.1), (50, 1.2), (100, 1.3)]      # (алмазов, множитель монет)


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def rewards_view(uid: int) -> dict:
    turn = db.turnover(uid)
    claimed = db.kv_get(uid, "rw_claimed", []) or []
    daily_done = db.kv_get(uid, "rw_daily", "") == _today()
    tasks = [
        {"id": "daily", "title": "Ежедневный вход", "desc": "Заходи каждый день и забирай алмаз", "reward": 1,
         "progress": 0 if daily_done else 1, "goal": 1, "claimed": daily_done},
        {"id": "streak3", "title": "Серия апгрейдов", "desc": "Выиграй 3 апгрейда подряд", "reward": 1,
         "progress": min(3, db.get_streak(uid)), "goal": 3, "claimed": "streak3" in claimed},
        {"id": "mines10", "title": "Кладбище", "desc": "Открой 10 гробов в «Минах»", "reward": 1,
         "progress": min(10, int(db.kv_get(uid, "mines_opened", 0) or 0)), "goal": 10, "claimed": "mines10" in claimed},
        {"id": "turn500", "title": "Оборот 500 монет", "desc": "Крути апгрейд и мины", "reward": 2,
         "progress": min(500, int(turn)), "goal": 500, "claimed": "turn500" in claimed},
        {"id": "friend", "title": "Позови друга", "desc": "Друг зашёл по твоей ссылке", "reward": 3,
         "progress": min(1, int(db.kv_get(uid, "ref_count", 0) or 0)), "goal": 1, "claimed": "friend" in claimed},
    ]
    return {"gems": db.get_gems(uid), "tasks": tasks,
            "exchange": [{"gems": g, "coins": int(g * m)} for g, m in GEM_TIERS],
            "balance_ton": db.get_coins(uid),
            "withdraw": {"min": db.limit("withdraw_min"), "max": db.limit("withdraw_max"), "daily": db.limit("withdraw_daily")}}


class RewardIn(BaseModel):
    id: str = ""
    gems: int = 0


@app.api_route("/api/rewards", methods=["GET", "POST"])
async def rewards(request: Request, x_init_data: str | None = Header(None)):
    return rewards_view(uid_from(request, x_init_data))


@app.post("/api/rewards/claim")
async def rewards_claim(body: RewardIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    view = rewards_view(uid)
    task = next((t for t in view["tasks"] if t["id"] == body.id), None)
    if not task or task["claimed"] or task["progress"] < task["goal"]:
        raise HTTPException(400, detail={"code": "not_ready"})
    if task["id"] == "daily":
        if db.kv_get(uid, "rw_daily", "") == _today():
            raise HTTPException(400, detail={"code": "not_ready"})
        db.kv_set(uid, "rw_daily", _today())
    else:
        done = list(db.kv_get(uid, "rw_claimed", []) or [])
        if task["id"] in done:
            raise HTTPException(400, detail={"code": "not_ready"})
        done.append(task["id"])
        db.kv_set(uid, "rw_claimed", done)
    db.add_gems(uid, int(task["reward"]))
    return rewards_view(uid)


@app.post("/api/rewards/exchange")
async def rewards_exchange(body: RewardIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    tier = next(((g, m) for g, m in GEM_TIERS if g == int(body.gems)), None)
    if not tier:
        raise HTTPException(400, detail={"code": "bad_amount"})
    if not db.spend_gems(uid, tier[0]):
        raise HTTPException(400, detail={"code": "insufficient_gems"})
    coins = int(tier[0] * tier[1])
    db.add_coins(uid, coins)
    db.ledger(0, coins)
    return rewards_view(uid)


# ---------- мелочи, которые зовёт фронт ----------
@app.post("/api/theme/set")
async def theme_set(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    try:
        data = await request.json()
    except Exception:
        data = {}
    if isinstance(data, dict) and data.get("theme"):
        db.kv_set(uid, "theme", str(data["theme"])[:32])
    return {"ok": True, "theme": db.kv_get(uid, "theme", "halloween")}


@app.api_route("/api/settings", methods=["GET", "POST"])
async def user_settings(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    return {"ok": True, "settings": db.kv_get(uid, "settings", {}) or {}}



# ---------- рефералы и промокоды ----------
import re as _re_ref
_CODE_RE = _re_ref.compile(r"^[A-Za-z0-9_]{3,20}$")


class CodeIn(BaseModel):
    code: str = ""


@app.post("/api/referral/create")
async def ref_create(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    return {"referral": referral_view(uid)}


@app.post("/api/referral/code/check")
async def ref_code_check(body: CodeIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    code = (body.code or "").strip()
    if not _CODE_RE.match(code):
        raise HTTPException(400, detail={"code": "code_invalid", "message": "Код: 3–20 символов, латиница, цифры и _"})
    owner = db.code_owner(code)
    return {"available": owner is None or owner == uid}


@app.post("/api/referral/code/create")
@app.post("/api/referral/code/rename")
async def ref_code_save(body: CodeIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    code = (body.code or "").strip()
    if not _CODE_RE.match(code):
        raise HTTPException(400, detail={"code": "code_invalid", "message": "Код: 3–20 символов, латиница, цифры и _"})
    if not db.code_set(uid, code):
        raise HTTPException(400, detail={"code": "code_taken", "message": "Код уже занят"})
    return {"referral": referral_view(uid)}


@app.post("/api/referral/withdraw")
async def ref_withdraw(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    bal = float(db.kv_get(uid, "ref_balance", 0) or 0)
    if bal < 1:
        raise HTTPException(400, detail={"code": "below_minimum"})
    db.kv_set(uid, "ref_balance", 0)
    db.add_coins(uid, round(bal, 2))
    db.ledger(0, round(bal, 2))
    return {"referral": referral_view(uid), "balance_ton": db.get_coins(uid)}


@app.post("/api/promo")
async def promo(body: CodeIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    code = (body.code or "").strip()
    owner = db.code_owner(code) if code else None
    if not owner:
        raise HTTPException(400, detail={"code": "not_found"})
    if owner == uid:
        raise HTTPException(400, detail={"code": "promo_inactive", "message": "Свой код активировать нельзя"})
    if db.ref_of(uid) is not None or not db.ref_attach(uid, owner):
        raise HTTPException(400, detail={"code": "promo_inactive", "message": "Ты уже активировал код друга"})
    return {"balance_ton": db.get_coins(uid), "amount_ton": 0, "rewards": [{"name": "Код друга активирован"}]}


# ---------- pages ----------
@app.get("/")
async def index():
    for base in (STATIC, ASSETS, ROOT):
        path = base / "index.html"
        if path.is_file():
            return FileResponse(path, headers={"Cache-Control": "no-cache"})
    return HTMLResponse("<h1>WinLine</h1><p>no index.html</p>")

@app.get("/api/health")
def health():
    return {"ok": True, "maintenance": db.get_setting("maintenance") == "1"}

@app.api_route("/api/maintenance", methods=["GET", "POST"])
def maint(request: Request, x_init_data: str | None = Header(None)):
    on = db.get_setting("maintenance") == "1"
    blocked = False
    if on:
        try:
            raw = x_init_data or request.headers.get("authorization") or ""
            blocked = not db.is_admin(verify_init(raw[4:].strip() if raw.lower().startswith("tma ") else raw.strip()))
        except HTTPException:
            blocked = True
    return {"maintenance": on, "blocked": blocked, "text": db.get_setting("maintenance_text", "")}

# ---------- state / spin / chests ----------
@app.api_route("/api/state", methods=["GET", "POST"])
def api_state(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    return build_state(uid)


STARS_PER_COIN = float(os.getenv("STARS_PER_COIN", "1"))          # сколько звёзд за 1 монету при пополнении
MIN_DEPOSIT = float(os.getenv("MIN_DEPOSIT", "1"))                  # минимальное пополнение, монет
SELL_RATE = float(os.getenv("SELL_RATE", "0.9"))


def gift_withdraw_fee() -> float:
    """Плата за вывод подарка (в монетах). Меняется в админ-боте: «Подарки апгрейда» → комиссия."""
    return max(0.0, db.limit("gift_withdraw_fee"))      # за сколько от цены подарка можно продать приз за монеты


def _sell_value(gift_id: str, price: float) -> float:
    """Шляпа продаётся за HAT_VALUE минус комиссия, подарки — за SELL_RATE от цены."""
    if str(gift_id) == "hat":
        return round(HAT_VALUE * (1 - HOUSE_EDGE), 2)
    return round(float(price or 0) * SELL_RATE, 2)


def _prize_view(r: dict) -> dict:
    price = float(r.get("price") or 0)
    return {"id": r["id"], "name": r.get("name") or "", "tier": "gift:" + str(r.get("gift_id") or ""),
            "image": r.get("image") or "", "status": "withdraw_pending" if r.get("status") == "withdraw_pending" else "owned",
            "sell_ton": _sell_value(r.get("gift_id"), price), "value_ton": price,
            "withdraw_fee_ton": gift_withdraw_fee()}


def _my_prizes(uid: int) -> list:
    with db.connect() as c:
        return [_prize_view(dict(r)) for r in c.execute(
            "SELECT rowid_ as id,gift_id,name,image,price,status FROM inventory WHERE user_id=? AND status IN ('won','withdraw_pending')", (uid,))]


class SellIn(BaseModel):
    prize_id: int = 0


@app.post("/api/sell")
async def sell(body: SellIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    with db.connect() as c:
        row = c.execute("SELECT price, gift_id FROM inventory WHERE rowid_=? AND user_id=?", (body.prize_id, uid)).fetchone()
        if not row:
            raise HTTPException(400, detail={"code": "not_sellable"})
        cur = c.execute("UPDATE inventory SET status='sold' WHERE rowid_=? AND user_id=? AND status IN ('won','withdraw_pending')",
                        (body.prize_id, uid))
        if cur.rowcount != 1:
            raise HTTPException(400, detail={"code": "not_sellable"})
        c.execute("UPDATE gift_queue SET status='cancelled' WHERE inv_row=? AND status='manual'", (body.prize_id,))
    payout = _sell_value(row["gift_id"], row["price"])
    bal = db.add_coins(uid, payout)
    db.ledger(0, payout)
    return {"payout_ton": payout, "balance_ton": bal, "hatcoin_balance": 0, "prizes": _my_prizes(uid)}


@app.post("/api/sell_all")
async def sell_all(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    total, n = 0.0, 0
    with db.connect() as c:
        rows = c.execute("SELECT rowid_ AS id, price, gift_id FROM inventory WHERE user_id=? AND status='won'", (uid,)).fetchall()
        for r in rows:
            cur = c.execute("UPDATE inventory SET status='sold' WHERE rowid_=? AND status='won'", (r["id"],))
            if cur.rowcount == 1:
                total += _sell_value(r["gift_id"], r["price"])
                n += 1
    bal = db.add_coins(uid, total) if total else db.get_coins(uid)
    if total:
        db.ledger(0, total)
    return {"count": n, "payout_ton": round(total, 2), "balance_ton": bal, "hatcoin_balance": 0, "prizes": _my_prizes(uid)}


REF_APP_LINK = os.getenv("REF_APP_LINK", "https://staticgram.top/winlinebot/winline").rstrip("/")


def referral_view(uid: int) -> dict:
    base = REF_APP_LINK
    bot_base = base.rsplit("/", 1)[0] if base.count("/") > 3 else base
    return {"percent": db.limit("ref_percent"), "code": db.code_of(uid), "code_enabled": True,
            "code_uses": db.ref_count(uid), "code_benefits": {}, "created": True,
            "link": f"{base}?startapp=ref{uid}", "bot_link": f"{bot_base}?start=ref{uid}",
            "count": db.ref_count(uid), "earned_ton": float(db.kv_get(uid, "ref_earned", 0) or 0),
            "balance_ton": float(db.kv_get(uid, "ref_balance", 0) or 0), "min_withdraw_ton": 1, "pending_ton": 0}


def build_state(uid: int) -> dict:
    turn = db.turnover(uid)
    weapons = ["staff"] + (["skeleton"] if turn >= 30000 else [])
    st = available_stock()
    with db.connect() as c:
        prizes = [_prize_view(dict(r)) for r in c.execute(
            "SELECT rowid_ as id,gift_id,name,image,price,status FROM inventory WHERE user_id=? AND status IN ('won','withdraw_pending')", (uid,))]
        rnd = c.execute("SELECT * FROM chest_rounds WHERE user_id=? AND active=1", (uid,)).fetchone()
        wd = c.execute("SELECT COUNT(*), COALESCE(SUM(stars),0) FROM withdrawals WHERE user_id=? AND status IN ('ok','sent','done')", (uid,)).fetchone()
    chest_round = None
    if rnd:
        chest_round = {"empties": int(rnd["empties"]), "bet": float(rnd["bet"]), "opened": json.loads(rnd["opened"] or "[]"),
                       "mult": float(rnd["mult"] or 1), "cells": CELLS}
    gift_upgrade = os.getenv("GIFT_UPGRADE", "auto").lower()
    gifts_on = (len(st) > 0) if gift_upgrade == "auto" else gift_upgrade in ("1", "true", "yes")
    random_tier = {"chances": CHANCE_GRID, "default_chance": 0.5, "prize_name": "Шляпа волшебника", "value_ton": HAT_VALUE}
    tour = db.kv_get(uid, "tour_sections", None)
    if tour is None:       # лавка пока закрыта — обучение не показываем
        tour = ["welcome", "shop", "achievements", "quests"]
    base = db.limit("level_base")
    need = lambda lv: int(base * (lv - 1) ** 1.6)
    lvl = 1
    while lvl < 60 and turn >= need(lvl + 1):
        lvl += 1
    lv = {"level": lvl, "max": lvl >= 60, "turnover_ton": turn, "next_ton": need(min(lvl + 1, 60)),
          "progress": 1.0 if lvl >= 60 else (turn - need(lvl)) / max(1, need(lvl + 1) - need(lvl))}
    return {
        "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "free_spin_coins": 0,
        "user": {"id": uid, "username": ""}, "weapons": weapons, "permanent_weapons": weapons,
        "prizes": prizes, "chest_round": chest_round,
        "config": {
            "chance_min": 0.05, "chance_max": 0.70,
            "sections": {"upgrade": True, "chests": True, "leaders": True, "staking": False},
            "gift_upgrade": gifts_on, "tier_enabled": False,
            "chances": CHANCE_GRID, "default_chance": 0.5, "prize_name": "Шляпа волшебника",
            "tiers": {"random": random_tier},
            "min_bet": db.limit("bet_min"), "max_bet": db.limit("bet_max"), "min_deposit_ton": db.limit("deposit_min"),
            "stars_deposit": {"enabled": bool(BOT_TOKEN), "per_ton": STARS_PER_COIN, "min_ton": db.limit("deposit_min"),
                              "max_ton": db.limit("deposit_max"), "lock_days": 0, "presets": [1000, 5000, 10000]},
            "withdraw": {"min": db.limit("withdraw_min"), "max": db.limit("withdraw_max"), "daily": db.limit("withdraw_daily")},
            "chests": {"min_bet": db.limit("bet_min"), "max_bet": db.limit("bet_max"), "ladder": _ladder()},
            "upgrade_modes": {"nft": db.limit("upg_nft_on") >= 1, "stars": db.limit("upg_stars_on") >= 1},
            "stars_upgrade": {
                "min": db.limit("bet_min"),
                "max": db.limit("stars_up_max"),
                "max_win": db.limit("stars_up_max"),
                "edge": db.limit("stars_up_edge") / 100.0,
                "min_mult": 1.1,
                "max_mult": 15.0,
                "mults": [2, 5, 10, 15],
            },
            "ui_texts": {},
        },
        "stats": {"turnover_ton": turn, "withdrawn_ton": float(wd[1] or 0), "withdrawn_count": int(wd[0] or 0),
                  "games": db.count_games(uid), "best": db.best_drop(uid)},
        "turnover_ton": turn, "level": lv, "level_table": [{"level": i + 1, "need": need(i + 1), "reward": False, "claimed": False} for i in range(60)], "tour_sections": tour, "tour_done": bool(tour),
        "lavka_hidden": {"shop": True, "achievements": True, "quests": True},
        "theme": "halloween", "server_time": int(time.time()), "relayer_stock": st,
        "referral": referral_view(uid), "is_admin": db.is_admin(uid), "halloween_enabled": os.getenv("HALLOWEEN_ENABLED", "1") == "1",
    }


class TourIn(BaseModel):
    sections: list = []


@app.post("/api/tour/complete")
async def tour_complete(body: TourIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    seen = set(db.kv_get(uid, "tour_sections", []) or [])
    seen.update(str(x) for x in (body.sections or []))
    seen.add("welcome")
    db.kv_set(uid, "tour_sections", sorted(seen))
    return {"tour_sections": sorted(seen), "tour_done": True}


@app.post("/api/state/personal-boss")
async def personal_boss_state(request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    return {}


@app.post("/api/spin")
async def api_spin(body: SpinIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    if db.limit("upg_nft_on") < 1:
        raise HTTPException(400, detail={"code": "upgrade_closed", "message": "Апгрейд на подарки сейчас закрыт"})
    show = max(0.01, min(0.70, float(body.chance)))
    st = available_stock()
    prize = 0.0
    meta = None
    show = round(show, 2)
    if body.tier == "gift" and body.gift:
        meta = next((x for x in st if str(x.get("id")) == str(body.gift)), None)
        prize = float((meta or {}).get("price") or 0)
    if body.tier == "gift" and body.gift:
        if not prize:
            raise HTTPException(400, detail={"code": "gift_unavailable"})
        cost = round(prize * show / (1 - GIFT_MARGIN), 2)      # цену диктует сервер (та же формула, что у фронта)
    else:
        cost = round(HAT_VALUE * show, 2)
    if not (cost == cost) or cost < db.limit("bet_min") or cost > db.limit("bet_max"):
        raise HTTPException(400, detail={"code": "bad_bet", "min_ton": db.limit("bet_min"), "max_ton": db.limit("bet_max")})
    real = show        # показанный шанс = настоящий; комиссия заложена в цену/выплату
    if not db.spend(uid, cost):
        raise HTTPException(400, detail={"code": "insufficient_funds"})
    win = random.random() < real
    db.streak_update(uid, win)
    gift_row = None
    payout = 0.0
    if win and body.tier == "gift" and body.gift:
        payout = prize or cost / show
        with db.connect() as c:
            c.execute(
                "INSERT INTO inventory(user_id,gift_id,name,image,price,status) VALUES(?,?,?,?,?,?)",
                (uid, str(body.gift), (meta or {}).get("name") or body.gift, (meta or {}).get("image") or "", payout, "won"),
            )
        gift_row = {"id": body.gift, "name": (meta or {}).get("name"), "price": payout}
    elif win:
        payout = _sell_value("hat", HAT_VALUE)           # шляпа попадает в «Мои призы», продать её можно за монеты
        with db.connect() as c:
            c.execute("INSERT INTO inventory(user_id,gift_id,name,image,price,status) VALUES(?,?,?,?,?,?)",
                      (uid, "hat", "Шляпа волшебника", "/images/hat.png", HAT_VALUE, "won"))
        gift_row = {"id": "hat", "name": "Шляпа волшебника", "price": HAT_VALUE, "image": "/images/hat.png"}
    db.ledger(cost, payout if win else 0)
    db.add_turnover(uid, cost)
    tgt = (gift_row or {}).get("name") or ("Шляпа волшебника" if win else "")
    img = (gift_row or {}).get("image") or ("/images/hat.png" if win else "")
    db.log_game(uid, "upgrade", win, cost, payout if win else 0, target=tgt, image=img, chance=show)
    return {"balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "win": win, "chance": show, "cost_ton": cost, "gift": gift_row}

def _mult(opened, empties):
    return _mult_at(int(empties), int(opened)) if opened > 0 else 1.0

@app.post("/api/chests/start")
async def chests_start(body: ChestStart, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    bet, empties = float(body.bet), int(body.empties)
    if not (bet == bet) or bet < db.limit("bet_min") or bet > db.limit("bet_max"):
        raise HTTPException(400, detail={"code": "bad_bet", "min_ton": db.limit("bet_min"), "max_ton": db.limit("bet_max")})
    if empties not in CX_CHOICES:
        raise HTTPException(400, detail={"code": "bad_empties"})
    if not db.spend(uid, bet): raise HTTPException(400, detail={"code": "insufficient_funds"})
    bad = sorted(random.sample(range(CELLS), min(empties, CELLS-1)))
    with db.connect() as c:                          # новый раунд только если нет идущего
        cur = c.execute("""INSERT INTO chest_rounds(user_id,bet,empties,bad,opened,mult,active,created)
                     VALUES(?,?,?,?,?,?,1,?)
                     ON CONFLICT(user_id) DO UPDATE SET bet=excluded.bet,empties=excluded.empties,
                     bad=excluded.bad,opened='[]',mult=1,active=1,created=excluded.created
                     WHERE chest_rounds.active=0""",
                  (uid, bet, empties, json.dumps(bad), "[]", 1.0, int(time.time())))
        started = cur.rowcount == 1
        if not started:
            c.execute("UPDATE users SET coins=coins+? WHERE id=?", (bet, uid))     # раунд уже идёт — ставку возвращаем
    if not started:
        raise HTTPException(409, detail={"code": "round_active", "message": "Сначала закончи текущий раунд"})
    db.add_turnover(uid, bet)
    db.ledger(bet, 0)
    return {"balance_ton": db.get_coins(uid), "hatcoin_balance": 0,
            "round": {"empties": empties, "bet": bet, "opened": [], "mult": 1.0, "cells": CELLS}}

@app.post("/api/chests/open")
async def chests_open(body: ChestOpen, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    cell = int(body.cell)
    with db.connect() as c:
        row = c.execute("SELECT * FROM chest_rounds WHERE user_id=? AND active=1", (uid,)).fetchone()
        if not row: raise HTTPException(400, detail={"code": "no_round"})
        opened = json.loads(row["opened"] or "[]")
        bad = json.loads(row["bad"] or "[]")
        if cell in opened: raise HTTPException(400, "already")
        is_bomb = cell in bad
        if is_bomb:
            if cell not in bad: bad.append(cell)
            opened.append(cell)
            c.execute("UPDATE chest_rounds SET active=0,opened=?,bad=? WHERE user_id=?",
                      (json.dumps(opened), json.dumps(bad), uid))
            bal = float(c.execute("SELECT coins FROM users WHERE id=?", (uid,)).fetchone()["coins"])   # тот же коннект: иначе "database is locked"
            db.log_game(uid, "chests", False, bet, 0, target="Кладбище")
            return {"finished": True, "balance_ton": bal, "hatcoin_balance": 0, "safe": False, "win": False, "cell": cell,
                    "bad": bad, "opened": opened, "mult": 0, "payout_ton": 0}
        opened.append(cell)
        db.kv_set(uid, "mines_opened", int(db.kv_get(uid, "mines_opened", 0) or 0) + 1)
        empties = int(row["empties"])
        mult = _mult(len(opened), empties)
        bet = float(row["bet"])
        done = len(opened) >= CELLS - empties          # открыты все безопасные клетки — забираем автоматически
        c.execute("UPDATE chest_rounds SET opened=?,mult=?,active=? WHERE user_id=?", (json.dumps(opened), mult, 0 if done else 1, uid))
        payout = round(bet * mult, 4) if done else 0
        if done:
            c.execute("UPDATE users SET coins=coins+? WHERE id=?", (payout, uid))
    if done:
        db.ledger(0, payout)
        return {"finished": True, "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "safe": True, "win": True, "cell": cell,
                "bad": bad, "opened": opened, "mult": mult, "payout_ton": payout}
    return {"finished": False, "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "safe": True, "cell": cell, "mult": mult,
            "round": {"empties": empties, "bet": bet, "opened": opened, "mult": mult, "cells": CELLS}}

@app.post("/api/chests/cashout")
async def chests_cash(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    with db.connect() as c:
        row = c.execute("SELECT * FROM chest_rounds WHERE user_id=? AND active=1", (uid,)).fetchone()
        if not row: raise HTTPException(400, detail={"code": "no_round"})
        opened = json.loads(row["opened"] or "[]")
        bad = json.loads(row["bad"] or "[]")
        if not opened: raise HTTPException(400, "open first")
        mult = float(row["mult"] or 1)
        payout = round(float(row["bet"]) * mult, 4)
        cur = c.execute("UPDATE chest_rounds SET active=0 WHERE user_id=? AND active=1", (uid,))
        if cur.rowcount != 1:                    # второй параллельный cashout — выплаты нет
            raise HTTPException(400, detail={"code": "no_round"})
        c.execute("UPDATE users SET coins=coins+? WHERE id=?", (payout, uid))
    db.ledger(0, payout)
    db.log_game(uid, "chests", True, float(row["bet"]), payout, target="Кладбище x%.2f" % mult)
    return {"finished": True, "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "safe": True, "win": True,
            "payout_ton": payout, "mult": mult, "opened": opened, "bad": bad}

class StarsUpIn(BaseModel):
    amount: float = 0
    mult: float = 2


STARS_UP_MIN_MULT, STARS_UP_MAX_MULT = 1.1, 15.0


@app.post("/api/upgrade/stars")
async def stars_upgrade(body: StarsUpIn, request: Request, x_init_data: str | None = Header(None)):
    """Апгрейд звёзд: выигрыш за раз не больше stars_up_max (250000), множитель 1.1–15."""
    uid = uid_from(request, x_init_data)
    if db.limit("upg_stars_on") < 1:
        raise HTTPException(400, detail={"code": "upgrade_closed", "message": "Апгрейд звёзд сейчас закрыт"})
    amount, mult = float(body.amount), float(body.mult)
    lo, cap = db.limit("bet_min"), db.limit("stars_up_max")
    if not (STARS_UP_MIN_MULT <= mult <= STARS_UP_MAX_MULT):
        raise HTTPException(400, detail={"code": "bad_mult", "message": f"Множитель от {STARS_UP_MIN_MULT:g} до {STARS_UP_MAX_MULT:g}x"})
    mult = round(mult, 2)
    hi = math.floor(cap / mult * 100) / 100
    if not (amount == amount) or amount < lo or amount > hi:
        raise HTTPException(400, detail={"code": "bad_bet", "min_ton": lo, "max_ton": hi,
                                         "message": f"Ставка от {lo:g} до {hi:g} ★ при x{mult:g} (выигрыш за раз не больше {cap:g} ★)"})
    amount = round(amount, 2)
    edge = min(0.5, max(0.0, db.limit("stars_up_edge") / 100.0))
    chance = round((1 - edge) / mult, 4)
    if not db.spend(uid, amount):
        raise HTTPException(400, detail={"code": "insufficient_funds"})
    win = random.SystemRandom().random() < chance
    payout = min(round(amount * mult, 2), cap) if win else 0.0
    if win:
        db.add_coins(uid, payout)
    db.ledger(amount, payout)
    db.add_turnover(uid, amount)
    db.log_game(uid, "stars", win, amount, payout, target=f"★ x{mult:g}", image="/images/star-px.png", chance=chance)
    return {"win": win, "mult": mult, "bet": amount, "payout": payout, "chance": chance, "balance_ton": db.get_coins(uid)}


@app.post("/api/upgrade")
async def classic_up(body: UpgradeIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    amount, mult = float(body.amount), int(body.mult)
    if mult not in UPGRADE_BASE: raise HTTPException(400, "mult 2/5/10")
    if not (amount == amount) or amount < db.limit("bet_min") or amount > db.limit("bet_max"):   # отрицательная сумма раньше давала деньги
        raise HTTPException(400, detail={"code": "bad_bet", "min_ton": db.limit("bet_min"), "max_ton": db.limit("bet_max")})
    with db.connect() as c:
        r = c.execute("SELECT upgrade_win_streak,upgrade_lose_streak FROM users WHERE id=?", (uid,)).fetchone()
        ws, ls = int(r["upgrade_win_streak"] or 0), int(r["upgrade_lose_streak"] or 0)
    base = UPGRADE_BASE[mult]
    if amount >= 2500: base = {2:0.46,5:0.13,10:0.04}[mult]
    add = 0.0
    for k,v in sorted((UPGRADE_LOSS.get(mult) or {}).items()):
        if ls >= k: add = v
    chance = min({2:0.59,5:0.18,10:0.07}[mult], base + add)
    if not db.spend(uid, amount): raise HTTPException(400, detail={"code": "insufficient_funds"})
    win = False if ws >= 3 else (random.random() < chance)
    payout = amount * mult if win else 0
    if win:
        db.add_coins(uid, payout); ws, ls = ws+1, 0
    else:
        ws, ls = 0, ls+1
    with db.connect() as c:
        c.execute("UPDATE users SET upgrade_win_streak=?,upgrade_lose_streak=? WHERE id=?", (ws, ls, uid))
    db.ledger(amount, payout)
    db.add_turnover(uid, amount)
    db.log_game(uid, "upgrade", win, amount, payout, target=f"x{mult}", chance=chance)
    return {"win": win, "mult": mult, "bet": amount, "payout": payout, "chance": chance, "balance_ton": db.get_coins(uid)}

# ---------- inventory / withdraw ----------
@app.api_route("/api/relayer/gifts", methods=["GET", "POST"])
async def relayer(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    with db.connect() as c:
        mine = [dict(id=str(r["rowid_"]), name=r["name"], image=r["image"], price=r["price"])
                for r in c.execute("SELECT * FROM inventory WHERE user_id=? AND status='won'", (uid,))]
    return {"relayer": {}, "stock": stock(), "mine": mine}

@app.post("/api/inventory/claim")
async def claim(body: IdIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    inv_id = int(body.id)
    st = {str(x["id"]): x for x in stock()}
    with db.connect() as c:
        row = c.execute("SELECT * FROM inventory WHERE rowid_=? AND user_id=? AND status='won'", (inv_id, uid)).fetchone()
        if not row: raise HTTPException(404, "not found")
        gid = str(row["gift_id"])
        if int((st.get(gid) or {}).get("count") or 0) < 1:
            raise HTTPException(409, "Нет на складе релеера, подождите")
        cur = c.execute("UPDATE inventory SET status='sending' WHERE rowid_=? AND status='won'", (inv_id,))
        if cur.rowcount != 1: raise HTTPException(409, "already queued")
        c.execute("INSERT INTO gift_queue(user_id,gift_id,inv_row,status,created) VALUES(?,?,?,'pending',?)",
                  (uid, gid, inv_id, int(time.time())))
    return {"ok": True, "queued": True, "message": "В очереди на отправку"}

@app.post("/api/withdraw")
async def withdraw(body: StarsIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    if getattr(body, "prize_id", 0):                 # фронт зовёт этот же путь для вывода подарка
        return await prize_withdraw(uid, int(body.prize_id))
    amount = int(body.stars or 0)
    wmin, wmax, wday = int(db.limit("withdraw_min")), int(db.limit("withdraw_max")), int(db.limit("withdraw_daily"))
    if amount < wmin:
        raise HTTPException(400, detail={"code": "below_min", "message": f"Минимум для вывода — {wmin}★"})
    if amount > wmax:
        raise HTTPException(400, detail={"code": "above_max", "message": f"Максимум за один вывод — {wmax}★"})
    rid = uuid.uuid4().hex
    with db.connect() as c:
        since = int(time.time()) - 86400
        already = c.execute(
            "SELECT COALESCE(SUM(stars),0) s FROM withdrawals WHERE user_id=? AND status IN ('pending','done') AND created>=?",
            (uid, since)).fetchone()["s"]
        if int(already) + amount > wday:
            raise HTTPException(400, detail={"code": "daily_cap", "message": f"Дневной лимит вывода — {wday}★ (осталось {max(0, wday - int(already))}★)"})
    if not db.spend(uid, amount):
        raise HTTPException(400, detail={"code": "insufficient_funds"})
    with db.connect() as c:
        c.execute("INSERT INTO withdrawals VALUES(?,?,?,?,?,?)", (rid, uid, amount, "pending", "", int(time.time())))
    res = await bot_raw("withdrawStarBalance", {"user_id": uid, "star_count": amount, "request_id": rid})
    ok, err = bool(res.get("ok")), str(res.get("description", ""))
    with db.connect() as c:
        c.execute("UPDATE withdrawals SET status=? WHERE request_id=?", ("done" if ok else "failed", rid))
    if not ok:
        db.add_coins(uid, amount)
        print("withdrawStarBalance failed:", err)
        if "BALANCE_TOO_LOW" in err:
            await _notify_admins("⚠️ Вывод звёзд игроку не прошёл: на балансе бота не хватает звёзд. Пополни баланс бота.")
            raise HTTPException(502, detail={"code": "bot_balance", "message": "Вывод временно недоступен, попробуй позже"})
        if "STAR_WITHDRAWAL_DISABLED" in err:
            raise HTTPException(502, detail={"code": "withdraw_disabled", "message": "Вывод звёзд сейчас отключён StaticGram"})
        if "user not found" in err or "USER_FROZEN" in err:
            raise HTTPException(502, detail={"code": "user_unavailable", "message": "Твой аккаунт не может получить звёзды"})
        raise HTTPException(502, detail={"code": "withdraw_failed", "message": "Не удалось вывести, попробуй позже"})
    return {"ok": True, "balance_ton": db.get_coins(uid)}

@app.post("/api/gifts/catalog")
async def catalog(request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    items = [{"slug": str(i.get("id")), "name": i.get("name"), "image": i.get("image"), "price_ton": float(i.get("price") or 0),
              "price": float(i.get("price") or 0), "count": i.get("count"), "popular": int(i.get("count") or 0)}
             for i in available_stock()]
    return {"items": items, "margin": GIFT_MARGIN, "price_steps": [], "price_base": 1}


class SlugIn(BaseModel):
    slug: str = ""


@app.post("/api/gifts/models")
async def gift_models(body: SlugIn, request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    g = next((x for x in available_stock() if str(x.get("id")) == str(body.slug)), None)
    if not g:
        return {"slug": body.slug, "models": [], "status": "failed"}
    price = float(g.get("price") or 0)
    return {"slug": body.slug, "name": g.get("name"), "title": g.get("name"), "image": g.get("image"), "floor": price, "status": "ready",
            "models": [{"model": g.get("name") or body.slug, "price_ton": price, "image": g.get("image")}]}


# ---------- ЗАГЛУШКИ: пути, которые зовёт фронт, но настоящей логики пока нет ----------
# Возвращают пустые данные, чтобы мини-аппка не падала с «Нет связи с сервером».
# Когда будешь писать настоящую логику — заменяй заглушку на нормальный обработчик.
@app.post("/api/quests")
async def quests_stub(request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    return {"enabled": True, "rows": [], "server_time": int(time.time())}

@app.post("/api/shop")
async def shop_stub(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    return {"offers": [], "balance_ton": db.get_coins(uid), "hatcoin_balance": 0}

@app.post("/api/history")
async def history_api(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    return {"rows": db.history(uid, 50)}

@app.post("/api/leaderboard")
async def leaderboard_api(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    mode = "turnover"
    try:
        raw = await request.json()
        mode = str((raw or {}).get("mode") or "turnover").lower()
    except Exception:
        mode = "turnover"
    if mode not in ("turnover", "deposits", "wins", "players"):
        mode = "turnover"
    board = db.leaderboard(mode, 50)
    my_score = db.leaderboard_score(uid, mode)
    rows = []
    me_rank = None
    for i, r in enumerate(board, 1):
        is_me = int(r["user_id"]) == int(uid)
        if is_me:
            me_rank = i
        name = r["username"] or ("Игрок " + str(r["user_id"]))
        rows.append({
            "rank": i,
            "key": str(r["user_id"]),
            "name": name,
            "total_ton": r["score"],
            "me": is_me,
            "avatar": "",
        })
    if me_rank is None and my_score > 0:
        # игрок есть, но не в топ-50 — посчитаем грубый ранг
        all_board = db.leaderboard(mode, 500)
        for i, r in enumerate(all_board, 1):
            if int(r["user_id"]) == int(uid):
                me_rank = i
                break
    now = int(time.time())
    me = None
    if me_rank is not None or my_score > 0:
        me = {"rank": me_rank, "total_ton": my_score, "excluded": False}
    labels = {
        "turnover": "по обороту за всё время",
        "deposits": "по депозитам за всё время",
        "wins": "по выигрышам за всё время",
        "players": "по числу игр (участники)",
    }
    return {
        "since": 0, "now": now, "ends": 0, "season": "", "alltime": True,
        "endless": True, "finished": False,
        "mode": mode,
        "subtitle": labels.get(mode, labels["turnover"]),
        "me": me, "rows": rows,
    }

@app.post("/api/wallet")
async def wallet_stub(request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    return {"ok": True}

@app.post("/api/boss/status")
async def boss_status_stub(request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    return {}

# картинки подарков от юзербота лежат на постоянном томе (data/gifts), а не внутри образа
GIFTS_DIR = os.getenv("GIFTS_IMG_DIR", "data/gifts")
os.makedirs(GIFTS_DIR, exist_ok=True)
app.mount("/static/gifts", StaticFiles(directory=GIFTS_DIR), name="gifts")   # раньше общего /static

# app.js: берём из static/, а если лежит в корне репозитория — оттуда
@app.get("/static/app.js")
async def app_js():
    for p in (ASSETS / "app.js", ROOT / "app.js"):
        if p.is_file():
            return FileResponse(p, media_type="application/javascript", headers={"Cache-Control": "no-cache"})
    raise HTTPException(404, "app.js not found")


# статика: /static/*, /images/* — и всё
if ASSETS.is_dir():
    app.mount("/static", StaticFiles(directory=ASSETS), name="assets")
if IMAGES:
    app.mount("/images", StaticFiles(directory=IMAGES), name="images")
if (ASSETS / "img").is_dir():
    app.mount("/img", StaticFiles(directory=ASSETS / "img"), name="img")


# админ-бот и юзербот (bots.py) стартуют вместе с сервером — отдельные процессы не нужны
@app.on_event("startup")
async def _start_bots():
    try:
        seed_catalog()
    except Exception as e:
        print("seed_catalog:", e)
    try:
        import bots
        bots.start()
    except Exception as e:
        print("bots не запущены:", e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

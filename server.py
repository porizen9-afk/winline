"""
Winline Halloween — один server.py (как старый).
Запуск: uvicorn server:app --host 0.0.0.0 --port $PORT
"""
from __future__ import annotations
import hashlib, hmac, json, os, random, time, uuid
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
from config import (
    BOT_TOKEN, OWNER_ID, STATICGRAM_API, RELAYER_JSON, WITHDRAW_STEP,
    DAILY_WITHDRAW_CAP, MIN_BET, MAX_BET, MINES_HOUSE, DEV_USER_ID, WEBAPP_URL,
)

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
        body = {"error": "maintenance" if (exc.status_code == 503 and msg == "maintenance") else msg, "message": msg}
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
MINES_RTP = float(os.getenv("MINES_RTP", "0.95"))       # возврат игрокам в минах (0.95 = комиссия 5%)
CX_CHOICES = [1, 3, 5, 10, 15, 20]
CHANCE_GRID = [{"chance": round(p / 100, 2), "cost_ton": round(HAT_VALUE * p / 100, 2)} for p in range(5, 71)]


def _mult_at(empties: int, k: int) -> float:
    """Честный множитель после k безопасных клеток при `empties` минах из 25 (с комиссией 1-RTP)."""
    surv = 1.0
    for i in range(k):
        surv *= (CELLS - empties - i) / (CELLS - i)
    return round(MINES_RTP / surv, 2) if surv > 0 else 0.0


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
    db.ensure_user(uid)
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


def available_stock():
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

class StarsIn(BaseModel):
    stars: int = WITHDRAW_STEP

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
    return {"maintenance": on, "blocked": blocked}

# ---------- state / spin / chests ----------
@app.api_route("/api/state", methods=["GET", "POST"])
def api_state(request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    return build_state(uid)


def build_state(uid: int) -> dict:
    turn = db.turnover(uid)
    weapons = ["staff"] + (["skeleton"] if turn >= 30000 else [])
    st = available_stock()
    with db.connect() as c:
        prizes = [dict(r) for r in c.execute(
            "SELECT rowid_ as id,name,image,price,status FROM inventory WHERE user_id=? AND status='won'", (uid,))]
        for p in prizes:
            p["price_ton"] = p.get("price") or 0
            p["slug"] = p.get("name") or ""
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
    need = lambda lv: (lv - 1) ** 2 * 5
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
            "sections": {"upgrade": True, "chests": True, "leaders": False, "staking": False},
            "gift_upgrade": gifts_on, "tier_enabled": False,
            "chances": CHANCE_GRID, "default_chance": 0.5, "prize_name": "Шляпа волшебника",
            "tiers": {"random": random_tier},
            "min_bet": MIN_BET, "max_bet": MAX_BET, "min_deposit_ton": 1,
            "chests": {"min_bet": MIN_BET, "max_bet": MAX_BET, "ladder": _ladder()},
            "ui_texts": {},
        },
        "stats": {"turnover_ton": turn, "withdrawn_ton": float(wd[1] or 0), "withdrawn_count": int(wd[0] or 0),
                  "games": db.count_games(uid)},
        "turnover_ton": turn, "level": lv, "level_table": [{"level": i + 1, "need": need(i + 1), "reward": False, "claimed": False} for i in range(60)], "tour_sections": tour, "tour_done": bool(tour),
        "lavka_hidden": {"shop": True, "achievements": True, "quests": True},
        "theme": "halloween", "server_time": int(time.time()), "relayer_stock": st,
        "is_admin": db.is_admin(uid), "halloween_enabled": os.getenv("HALLOWEEN_ENABLED", "1") == "1",
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
    if not (cost == cost) or cost < MIN_BET or cost > MAX_BET:
        raise HTTPException(400, detail={"code": "bad_bet", "min_ton": MIN_BET, "max_ton": MAX_BET})
    real = show        # показанный шанс = настоящий; комиссия заложена в цену/выплату
    if not db.spend(uid, cost):
        raise HTTPException(400, detail={"code": "insufficient_funds"})
    win = random.random() < real
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
        payout = round(HAT_VALUE * (1 - HOUSE_EDGE), 2)
        db.add_coins(uid, payout)
    db.ledger(cost, payout if win else 0)
    db.add_turnover(uid, cost)
    with db.connect() as c:
        c.execute("INSERT INTO spin_log(user_id,chance,cost,win,created) VALUES(?,?,?,?,?)",
                  (uid, show, cost, 1 if win else 0, int(time.time())))
    return {"balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "win": win, "chance": show, "cost_ton": cost, "gift": gift_row}

def _mult(opened, empties):
    return _mult_at(int(empties), int(opened)) if opened > 0 else 1.0

@app.post("/api/chests/start")
async def chests_start(body: ChestStart, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    bet, empties = float(body.bet), int(body.empties)
    if not (bet == bet) or bet < MIN_BET or bet > MAX_BET:
        raise HTTPException(400, detail={"code": "bad_bet", "min_ton": MIN_BET, "max_ton": MAX_BET})
    if not db.spend(uid, bet): raise HTTPException(400, detail={"code": "insufficient_funds"})
    bad = sorted(random.sample(range(CELLS), min(empties, CELLS-1)))
    with db.connect() as c:
        c.execute("""INSERT INTO chest_rounds(user_id,bet,empties,bad,opened,mult,active,created)
                     VALUES(?,?,?,?,?,?,1,?)
                     ON CONFLICT(user_id) DO UPDATE SET bet=excluded.bet,empties=excluded.empties,
                     bad=excluded.bad,opened='[]',mult=1,active=1,created=excluded.created""",
                  (uid, bet, empties, json.dumps(bad), "[]", 1.0, int(time.time())))
    db.add_turnover(uid, bet)
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
            return {"finished": True, "balance_ton": bal, "hatcoin_balance": 0, "safe": False, "win": False, "cell": cell,
                    "bad": bad, "opened": opened, "mult": 0, "payout_ton": 0}
        opened.append(cell)
        empties = int(row["empties"])
        mult = _mult(len(opened), empties)
        bet = float(row["bet"])
        done = len(opened) >= CELLS - empties          # открыты все безопасные клетки — забираем автоматически
        c.execute("UPDATE chest_rounds SET opened=?,mult=?,active=? WHERE user_id=?", (json.dumps(opened), mult, 0 if done else 1, uid))
    if done:
        payout = round(bet * mult, 4)
        db.add_coins(uid, payout)
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
    db.add_coins(uid, payout)
    db.ledger(0, payout)
    return {"finished": True, "balance_ton": db.get_coins(uid), "hatcoin_balance": 0, "safe": True, "win": True,
            "payout_ton": payout, "mult": mult, "opened": opened, "bad": bad}

@app.post("/api/upgrade")
async def classic_up(body: UpgradeIn, request: Request, x_init_data: str | None = Header(None)):
    uid = uid_from(request, x_init_data)
    amount, mult = float(body.amount), int(body.mult)
    if mult not in UPGRADE_BASE: raise HTTPException(400, "mult 2/5/10")
    if not (amount == amount) or amount < MIN_BET or amount > MAX_BET:   # отрицательная сумма раньше давала деньги
        raise HTTPException(400, detail={"code": "bad_bet", "min_ton": MIN_BET, "max_ton": MAX_BET})
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
    if body.stars != WITHDRAW_STEP:
        raise HTTPException(400, f"only {WITHDRAW_STEP}")
    rid = uuid.uuid4().hex
    with db.connect() as c:
        since = int(time.time()) - 86400
        already = c.execute(
            "SELECT COALESCE(SUM(stars),0) s FROM withdrawals WHERE user_id=? AND status IN ('pending','done') AND created>=?",
            (uid, since)).fetchone()["s"]
        if int(already) + WITHDRAW_STEP > DAILY_WITHDRAW_CAP:
            raise HTTPException(400, f"лимит {DAILY_WITHDRAW_CAP}/сутки")
        if not db.spend(uid, WITHDRAW_STEP):
            raise HTTPException(400, detail={"code": "insufficient_funds"})
        c.execute("INSERT INTO withdrawals VALUES(?,?,?,?,?,?)",
                  (rid, uid, WITHDRAW_STEP, "pending", "", int(time.time())))
    ok, err = await bot_api("withdrawStarBalance", {"user_id": uid, "star_count": WITHDRAW_STEP, "request_id": rid})
    with db.connect() as c:
        c.execute("UPDATE withdrawals SET status=? WHERE request_id=?", ("done" if ok else "failed", rid))
    if not ok:
        db.add_coins(uid, WITHDRAW_STEP)
        raise HTTPException(502, err or "fail")
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
async def history_stub(request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    return {"rows": []}

@app.post("/api/leaderboard")
async def leaderboard_stub(request: Request, x_init_data: str | None = Header(None)):
    uid_from(request, x_init_data)
    now = int(time.time())
    return {"since": now, "now": now, "ends": now, "season": "", "alltime": True,
            "endless": True, "finished": False, "me": {"rank": None, "excluded": False}, "rows": []}

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


# админ-бот и юзербот (bots.py) стартуют вместе с сервером — отдельные процессы не нужны
@app.on_event("startup")
async def _start_bots():
    try:
        import bots
        bots.start()
    except Exception as e:
        print("bots не запущены:", e)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))

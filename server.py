"""
Winline Mini App + Admin Bot
Railway: uvicorn server:app --host 0.0.0.0 --port $PORT
"""
import asyncio
import logging
import math
import os
import random
import time
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)
from fastapi import FastAPI, Header, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from config import (
    BANK,
    BOT_TOKEN,
    CATUP_API,
    MIN_BET,
    OWNER_ID,
    OWNER2_ID,
    WEBAPP_URL,
    WITHDRAW_FEE,
)
try:
    from config import BOT_USERNAME
except ImportError:
    BOT_USERNAME = "winlinebot"
try:
    from config import REQUIRED_CHANNEL, MOD_GIVE_MAX, MIN_WITHDRAW
except ImportError:
    REQUIRED_CHANNEL = ""
    MOD_GIVE_MAX = 2500
    MIN_WITHDRAW = 1000


logging.basicConfig(level=logging.INFO)
log = logging.getLogger("winline")

# ---------- Telegram bot ----------
session = AiohttpSession(api=TelegramAPIServer.from_base(CATUP_API))
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()
router = Router()
dp.include_router(router)

app = FastAPI(title="Winline")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
STATIC = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(STATIC):
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


def uid_from(x) -> int:
    return int(x)


# ---------- helpers ----------
def public_user(uid: int) -> dict:
    try:
        u = db.ensure_user(uid) or {}
    except Exception as e:
        log.exception("ensure_user")
        u = {"balance": 0, "wager": 0, "deposited": 0, "username": str(uid)}
    try:
        admin = db.is_admin(uid)
    except Exception:
        admin = False
    try:
        owner = db.is_owner(uid)
    except Exception:
        owner = False
    try:
        mod = bool(getattr(db, "is_moderator", lambda _x: False)(uid))
    except Exception:
        mod = False
    return {
        "id": int(uid),
        "username": u.get("username") or "",
        "first_name": u.get("first_name") or "",
        "photo_url": u.get("photo_url") or "",
        "balance": int(u.get("balance") or 0),
        "wager": int(u.get("wager") or 0),
        "deposited": int(u.get("deposited") or 0),
        "is_admin": bool(admin),
        "is_owner": bool(owner),
        "is_moderator": bool(mod),
    }


def change_balance(uid: int, delta: int, reason: str = "") -> int:
    db.ensure_user(uid)
    u = db.get_users()
    if not isinstance(u, dict):
        u = {}
    k = str(uid)
    if k not in u or not isinstance(u.get(k), dict):
        db.ensure_user(uid)
        u = db.get_users()
    bal = int(u[k].get("balance") or 0) + int(delta)
    if bal < 0:
        raise ValueError("insufficient")
    u[k]["balance"] = bal
    if delta < 0:
        u[k]["wager"] = int(u[k].get("wager") or 0) + abs(delta)
    db.save_users(u)
    if reason:
        try:
            db.add_history({"uid": uid, "type": "balance", "delta": delta, "reason": reason, "bal": bal})
        except Exception:
            pass
    return bal


# ---------- AUTH (simple: tg id header from webapp) ----------
def require_uid(x_uid: Optional[str] = None, q_uid: Optional[str] = None) -> int:
    raw = x_uid or q_uid
    if not raw:
        raise HTTPException(401, "no uid — открой из Telegram")
    try:
        return int(str(raw).strip())
    except Exception:
        raise HTTPException(401, "bad uid")


# множители: индекс = число открытых клеток (режимы 3/5/8)
MINES_MULT = {
    3: [1.0, 1.12, 1.28, 1.47, 1.7, 2.0, 2.35, 2.8, 3.4, 4.2, 5.2, 6.5, 8.2, 10.5, 13.5, 17.5, 23.0, 30.0, 40.0, 55.0, 75.0, 100.0],
    5: [1.0, 1.2, 1.45, 1.8, 2.25, 2.9, 3.7, 4.8, 6.3, 8.4, 11.5, 15.5, 21.0, 29.0, 40.0, 56.0, 80.0, 115.0, 170.0, 250.0],
    8: [1.0, 1.35, 1.85, 2.6, 3.7, 5.3, 7.8, 11.5, 17.5, 27.0, 42.0, 65.0, 105.0, 170.0, 280.0, 480.0, 850.0],
}
# бомбы не раскладываются заранее: на каждом open сервер «подставляет» с завышенным шансом
MINES_HOUSE = 1.45  # x к честному шансу бомбы на клетке


# ---------- API models ----------
class BetIn(BaseModel):
    amount: int


class MinesStart(BaseModel):
    amount: int
    mines: int  # 3,5,8


class MinesOpen(BaseModel):
    cell: int


class ArenaJoin(BaseModel):
    amount: int = 0
    gift_id: Optional[str] = None


class UpgradeIn(BaseModel):
    amount: int
    mult: int  # 2, 5, 10


class CheckCreate(BaseModel):
    amount: int
    uses: int = 1  # сколько раз можно активировать (1 = одноразовый)


class CheckActivate(BaseModel):
    code: str


class GiftSell(BaseModel):
    gift_id: str


class GiftWithdraw(BaseModel):
    gift_id: str


class StarsWithdraw(BaseModel):
    amount: int


class AdminGive(BaseModel):
    user: Optional[str] = None  # @username или id
    uid: Optional[int] = None
    amount: int = 0


class AdminGift(BaseModel):
    user: Optional[str] = None
    uid: Optional[int] = None
    link: str = ""
    price: int = 0
    title: str = "Gift"


class AdminOdds(BaseModel):
    slot_777: Optional[float] = None
    slot_triple: Optional[float] = None


class AdminForce(BaseModel):
    user: Optional[str] = None
    uid: Optional[int] = None  # None = clear


class AdminOwner2(BaseModel):
    user: Optional[str] = None
    uid: Optional[int] = None


def resolve_target(body) -> int:
    """user (@ник / id) или uid → int id."""
    ref = getattr(body, "user", None) or ""
    if not ref and getattr(body, "uid", None) is not None:
        ref = str(body.uid)
    ref = str(ref or "").strip()
    if not ref:
        raise HTTPException(400, "укажи @username или id")
    tid = db.parse_user_ref(ref)
    if not tid:
        raise HTTPException(404, "игрок не найден: " + ref + " (должен зайти в аппку хоть раз)")
    return int(tid)



class AdminTakeGift(BaseModel):
    uid: int
    gift_id: str


class ConfirmDep(BaseModel):
    note: str = ""


# ---------- routes static ----------
@app.get("/")
async def index():
    return FileResponse(
        os.path.join(STATIC, "index.html"),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@app.get("/api/health")
async def api_health():
    return {"ok": True}


@app.get("/api/me")
async def api_me(
    request: Request,
    x_telegram_id: Optional[str] = Header(None, alias="X-Telegram-Id"),
    tg_id: Optional[str] = Query(None),
):
    try:
        h2 = (
            request.headers.get("x-telegram-id")
            or request.headers.get("X-Telegram-Id")
            or request.headers.get("x-telegram-userid")
        )
        uid = require_uid(x_telegram_id or h2, tg_id)
        un = (request.query_params.get("username") or "").lstrip("@")
        first = request.query_params.get("first_name") or ""
        photo = request.query_params.get("photo_url") or ""
        db.ensure_user(uid, un or first or "")
        users = db.get_users()
        k = str(uid)
        if k in users:
            if un:
                users[k]["username"] = un.lower()
            if first:
                users[k]["first_name"] = first
            if photo:
                users[k]["photo_url"] = photo
            db.save_users(users)
        return {
            "user": public_user(uid),
            "bank": BANK,
            "min_bet": MIN_BET,
            "withdraw_fee": WITHDRAW_FEE,
            "min_withdraw": MIN_WITHDRAW,
            "mod_give_max": MOD_GIVE_MAX,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("api_me failed")
        raise HTTPException(500, f"me_error: {type(e).__name__}: {e}")


@app.get("/api/history")
async def api_history(x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    h = [x for x in db.get_history() if int(x.get("uid", 0)) == uid][:50]
    return {"history": h}


@app.get("/api/top")
async def api_top(x_telegram_id: Optional[str] = Header(None)):
    require_uid(x_telegram_id)
    users = db.get_users()
    rows = sorted(
        [{"uid": k, **v} for k, v in users.items()],
        key=lambda x: int(x.get("deposited") or 0),
        reverse=True,
    )
    s = db.get_settings()
    return {
        "top": [
            {
                "username": r.get("username"),
                "deposited": int(r.get("deposited") or 0),
                "wager": int(r.get("wager") or 0),
            }
            for r in rows[:30]
        ],
        "prizes": s.get("top_prizes") or [],
    }


# ---------- SLOTS 777 ----------
@app.post("/api/slots/spin")
async def slots_spin(body: BetIn, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    amount = int(body.amount)
    if amount < MIN_BET:
        raise HTTPException(400, f"min {MIN_BET}")
    try:
        change_balance(uid, -amount, "slots_bet")
    except ValueError:
        raise HTTPException(400, "no balance")

    st = db.get_settings()
    p777 = float(st.get("slot_777") or 0.006)  # редко, казино в плюсе
    # фрукты чуть чаще; 777 редко
    pool = ["🍒", "🍒", "🍒", "🍒", "🍋", "🍋", "🍋", "🔔", "🔔", "⭐", "⭐", "💎", "7️⃣"]
    fruits = ["🍒", "🍋", "🔔", "⭐", "💎"]
    r = random.random()

    if r < p777:
        reels = ["7️⃣", "7️⃣", "7️⃣"]
        mult = 10
    elif r < p777 + 0.09:
        sym = random.choice(fruits)
        reels = [sym, sym, sym]
        mult = 3
    elif r < p777 + 0.09 + 0.22:
        sym = random.choice(fruits)
        other = random.choice([x for x in pool if x != sym])
        reels = [sym, sym, other]
        mult = 1.5
    elif r < p777 + 0.09 + 0.22 + 0.14:
        sym = random.choice(fruits)
        mid = random.choice([x for x in fruits if x != sym])
        reels = [sym, mid, sym]
        mult = 1.2
    else:
        a = random.choice(pool)
        b = random.choice(pool)
        c = random.choice(pool)
        if a == b == c:
            c = random.choice([x for x in fruits if x != a] or fruits)
        if a == "7️⃣" and b == "7️⃣" and c == "7️⃣":
            c = "🍒"
        reels = [a, b, c]
        mult = 0

    win = int(amount * mult) if mult else 0
    if win:
        change_balance(uid, win, "slots_win")
    db.add_history({"uid": uid, "type": "slots", "bet": amount, "reels": reels, "mult": mult, "win": win})
    return {"reels": reels, "mult": mult, "win": win, "balance": public_user(uid)["balance"]}



@app.post("/api/mines/start")
async def mines_start(
    body: MinesStart,
    request: Request,
    x_telegram_id: Optional[str] = Header(None),
    tg_id: Optional[str] = Query(None),
):
    uid = require_uid(x_telegram_id or request.headers.get("x-telegram-id"), tg_id)
    amount = int(body.amount)
    mines_n = int(body.mines)
    if mines_n not in (3, 5, 8):
        raise HTTPException(400, "mines 3/5/8")
    if amount < MIN_BET:
        raise HTTPException(400, f"min {MIN_BET}")
    if amount > 500:
        raise HTTPException(400, "макс ставка в минах 500★")
    try:
        change_balance(uid, -amount, "mines_bet")
    except ValueError:
        raise HTTPException(400, "no balance")

    cells = 25
    # бомбы НЕ загадываем заранее — решаем при каждом open (чаще, чем честно)
    games = db.get_mines()
    games[str(uid)] = {
        "bet": amount,
        "mines": mines_n,
        "bombs": [],
        "opened": [],
        "alive": True,
        "step": 0,
        "dynamic": True,
    }
    db.save_mines(games)
    return {"ok": True, "cells": cells, "mines": mines_n, "balance": public_user(uid)["balance"]}


@app.post("/api/mines/open")
async def mines_open(
    body: MinesOpen,
    request: Request,
    x_telegram_id: Optional[str] = Header(None),
    tg_id: Optional[str] = Query(None),
):
    try:
        uid = require_uid(x_telegram_id or request.headers.get("x-telegram-id"), tg_id)
        games = db.get_mines()
        if not isinstance(games, dict):
            games = {}
        g = games.get(str(uid))
        if not isinstance(g, dict) or not g.get("alive"):
            raise HTTPException(400, "нет активной игры — нажми Начать")
        cell = int(body.cell)
        opened = [int(x) for x in (g.get("opened") or [])]
        bombs = [int(x) for x in (g.get("bombs") or [])]
        if cell in opened:
            raise HTTPException(400, "уже открыто")
        cells = 25
        mines_n = int(g.get("mines") or 3)
        if mines_n not in MINES_MULT:
            mines_n = 3

        # динамическая бомба: шанс выше честного mines/осталось
        left_cells = cells - len(opened)  # включая текущую
        if left_cells < 1:
            left_cells = 1
        fair = float(mines_n) / float(left_cells)
        try:
            house = float(MINES_HOUSE)
        except Exception:
            house = 1.45
        p_bomb = min(0.88, fair * house)
        is_bomb = cell in bombs or (g.get("dynamic") and random.random() < p_bomb)

        if is_bomb:
            # достраиваем карту бомб для показа
            bomb_set = set(bombs)
            bomb_set.add(cell)
            need = max(0, mines_n - len(bomb_set))
            pool = [i for i in range(cells) if i not in opened and i != cell and i not in bomb_set]
            if need and pool:
                bomb_set.update(random.sample(pool, min(need, len(pool))))
            bombs = list(bomb_set)
            g["alive"] = False
            opened.append(cell)
            g["opened"] = opened
            g["bombs"] = bombs
            games[str(uid)] = g
            db.save_mines(games)
            try:
                db.add_history({"uid": uid, "type": "mines", "bet": g.get("bet"), "win": 0, "bust": True})
            except Exception:
                pass
            return {
                "bust": True,
                "cell": cell,
                "bombs": bombs,
                "balance": public_user(uid)["balance"],
            }

        opened.append(cell)
        g["opened"] = opened
        g["bombs"] = bombs
        g["step"] = len(opened)
        games[str(uid)] = g
        db.save_mines(games)
        if mines_n not in MINES_MULT:
            mines_n = 3
        mults = MINES_MULT[mines_n]
        step = min(len(opened), len(mults) - 1)
        mult = float(mults[step])
        bet = int(g.get("bet") or 0)
        can_take = int(bet * mult)
        return {
            "bust": False,
            "cell": cell,
            "step": len(opened),
            "mult": mult,
            "can_take": can_take,
            "bet": bet,
        }
    except HTTPException:
        raise
    except Exception as e:
        log.exception("mines_open")
        raise HTTPException(500, "mines_open: " + str(e)[:120])


@app.post("/api/mines/cashout")
async def mines_cashout(
    request: Request,
    x_telegram_id: Optional[str] = Header(None),
    tg_id: Optional[str] = Query(None),
):
    try:
        uid = require_uid(x_telegram_id or request.headers.get("x-telegram-id"), tg_id)
        games = db.get_mines()
        if not isinstance(games, dict):
            games = {}
        g = games.get(str(uid))
        if not isinstance(g, dict) or not g.get("alive"):
            raise HTTPException(400, "нет активной игры")
        opened = [int(x) for x in (g.get("opened") or [])]
        if not opened:
            raise HTTPException(400, "открой хотя бы 1 клетку")
        mines_n = int(g.get("mines") or 3)
        if mines_n not in MINES_MULT:
            mines_n = 3
        mults = MINES_MULT[mines_n]
        step = min(len(opened), len(mults) - 1)
        mult = float(mults[step])
        bet = int(g.get("bet") or 0)
        win = int(bet * mult)
        g["alive"] = False
        g["opened"] = opened
        games[str(uid)] = g
        db.save_mines(games)
        change_balance(uid, win, "mines_win")
        try:
            db.add_history({"uid": uid, "type": "mines", "bet": bet, "win": win, "mult": mult})
        except Exception:
            pass
        return {"win": win, "mult": mult, "balance": public_user(uid)["balance"]}
    except HTTPException:
        raise
    except Exception as e:
        log.exception("mines_cashout")
        raise HTTPException(500, "mines_cash: " + str(e)[:120])



# ---------- UPGRADE (stars only) ----------
# Исход считает ТОЛЬКО сервер (random). Клиент лишь крутит иглу под win/lose.
UPGRADE_MAX_BET = 2500
# База ниже «честной» → казино в плюсе.
# Клиенту показываем 50/20/10, реально крутим эти %.
UPGRADE_CHANCE_BASE = {
    2: 0.40,   # ×2 — 40% (честно 50%)
    5: 0.08,   # ×5 — 8%  (честно 20%)
    10: 0.025, # ×10 — 2.5% (честно 10%)
}
# Мягкий буст после серии лузов (не форс-вин, edge сохраняется)
# lose_streak → добавка к шансу (абсолютная)
UPGRADE_LOSS_BOOST = {
    2:  {3: 0.03, 4: 0.05, 5: 0.07},   # макс ~47% при 5+ лузах
    5:  {3: 0.015, 4: 0.025, 5: 0.035}, # макс ~11.5%
    10: {3: 0.008, 4: 0.012, 5: 0.018}, # макс ~4.3%
}
UPGRADE_WIN_STREAK_CAP = 3  # 4-я победа подряд = форс-луз


def _upgrade_chance(mult: int, amount: int, lose_streak: int = 0) -> float:
    base = float(UPGRADE_CHANCE_BASE.get(mult, 0))
    if amount >= UPGRADE_MAX_BET:
        if mult == 2:
            base = 0.38
        elif mult == 5:
            base = 0.07
        elif mult == 10:
            base = 0.02
    # soft pity: после 3/4/5 лузов чуть выше шанс, но всегда < fair
    boosts = UPGRADE_LOSS_BOOST.get(mult) or {}
    add = 0.0
    if lose_streak >= 5:
        add = float(boosts.get(5) or 0)
    elif lose_streak >= 4:
        add = float(boosts.get(4) or 0)
    elif lose_streak >= 3:
        add = float(boosts.get(3) or 0)
    # потолок: не выше fair−1% чтобы казик оставался в плюсе
    fair_cap = {2: 0.49, 5: 0.18, 10: 0.09}.get(mult, 0.45)
    return min(fair_cap, base + add)


@app.post("/api/upgrade")
async def api_upgrade(
    body: UpgradeIn,
    request: Request,
    x_telegram_id: Optional[str] = Header(None),
    tg_id: Optional[str] = Query(None),
):
    uid = require_uid(x_telegram_id or request.headers.get("x-telegram-id"), tg_id)
    amount = int(body.amount)
    mult = int(body.mult)
    if mult not in UPGRADE_CHANCE_BASE:
        raise HTTPException(400, "mult 2/5/10")
    if amount < MIN_BET:
        raise HTTPException(400, f"min {MIN_BET}")
    if amount > UPGRADE_MAX_BET:
        raise HTTPException(400, f"макс ставка в апгрейде {UPGRADE_MAX_BET}★")
    try:
        change_balance(uid, -amount, "upgrade_bet")
    except ValueError:
        raise HTTPException(400, "no balance")

    users = db.get_users()
    uk = str(uid)
    if uk not in users or not isinstance(users.get(uk), dict):
        db.ensure_user(uid)
        users = db.get_users()
    win_streak = int(users[uk].get("upgrade_win_streak") or 0)
    lose_streak = int(users[uk].get("upgrade_lose_streak") or 0)

    chance = _upgrade_chance(mult, amount, lose_streak)
    if win_streak >= UPGRADE_WIN_STREAK_CAP:
        win = False  # не более 3 побед подряд
    else:
        win = random.random() < chance

    payout = int(amount * mult) if win else 0
    if payout:
        change_balance(uid, payout, "upgrade_win")
        win_streak = win_streak + 1
        lose_streak = 0
    else:
        win_streak = 0
        lose_streak = lose_streak + 1

    try:
        users = db.get_users()
        if uk in users and isinstance(users.get(uk), dict):
            users[uk]["upgrade_win_streak"] = win_streak
            users[uk]["upgrade_lose_streak"] = lose_streak
            db.save_users(users)
    except Exception:
        pass
    try:
        db.add_history({
            "uid": uid,
            "type": "upgrade_win" if win else "upgrade_lose",
            "bet": amount,
            "mult": mult,
            "win": payout,
            "chance": round(chance, 4),
            "win_streak": win_streak,
            "lose_streak": lose_streak,
        })
    except Exception:
        pass
    return {
        "win": win,
        "mult": mult,
        "bet": amount,
        "payout": payout,
        "chance": chance,  # можно оставить — клиент не показывает
        "balance": public_user(uid)["balance"],
    }


# ---------- ROCKET (crash) ----------
# Жёстче в плюс казика: edge ~9%, выплата макс ×5, визуал до ×8
ROCKET_BETTING_SEC = 5.0
ROCKET_CRASH_HOLD = 2.2
ROCKET_PAUSE_SEC = 1.2
ROCKET_EDGE = 0.09          # базовый edge ~9%
ROCKET_MAX_PAY = 5.0        # макс выплата игроку
ROCKET_MAX_SHOW = 8.0       # иногда выше в истории (когда уже все вышли)
ROCKET_GROWTH_K = 0.07      # плавнее полёт, WebView успевает


def _rocket_gen_crash(house_pnl: int = 0, bank: int = 0) -> tuple:
    """
    ×1.50 не безопасная зона: часть раундов рвётся ДО 1.50 всегда.
    Если касса в минусе — чаще краш 1.08–1.38, чтобы отыграть.
    Большой банк живых ставок — чаще около ×2, но тоже с ранними.
    """
    # house_pnl: плюс = касса заработала, минус = игроки вынесли
    lost = house_pnl < 0
    if house_pnl < -4000:
        heat = 3
    elif house_pnl < -1500:
        heat = 2
    elif house_pnl < -400:
        heat = 1
    else:
        heat = 0

    big = bank >= 2500
    huge = bank >= 8000

    r = random.random()
    # бакеты: 0 ultra-early, 1 до 1.38, 2 вокруг 1.45 (часто НИЖЕ 1.50),
    #         3 ~x2, 4 mid-high, 5 high
    if heat >= 3:
        # касса сильно в минусе — вернуть: чаще до 1.40
        weights = (0.18, 0.40, 0.26, 0.10, 0.04, 0.02)
    elif heat >= 2:
        weights = (0.14, 0.36, 0.28, 0.14, 0.05, 0.03)
    elif heat >= 1:
        weights = (0.10, 0.32, 0.30, 0.16, 0.08, 0.04)
    elif huge:
        # жирный банк: много до 1.45 + пачка около ×2
        weights = (0.10, 0.24, 0.22, 0.32, 0.08, 0.04)
    elif big:
        weights = (0.08, 0.22, 0.24, 0.28, 0.12, 0.06)
    else:
        # обычный — тоже не «всегда 1.50»: ~30%+ рвётся раньше
        weights = (0.08, 0.22, 0.28, 0.20, 0.12, 0.10)

    acc = 0.0
    bucket = 5
    for i, w in enumerate(weights):
        acc += w
        if r < acc:
            bucket = i
            break

    def rnd(a, b):
        return a + random.random() * (b - a)

    if bucket == 0:
        crash = rnd(1.06, 1.16)
    elif bucket == 1:
        crash = rnd(1.16, 1.38)  # не дотягивает до 1.50
    elif bucket == 2:
        # специально рвём И до, И чуть после 1.50 — паттерн «забирай 1.5» ломается
        pick = random.random()
        if lost or heat:
            if pick < 0.62:
                crash = rnd(1.32, 1.47)  # не успели на 1.50
            elif pick < 0.85:
                crash = rnd(1.50, 1.62)
            else:
                crash = rnd(1.62, 1.78)
        else:
            if pick < 0.45:
                crash = rnd(1.32, 1.47)
            elif pick < 0.72:
                crash = rnd(1.50, 1.62)
            else:
                crash = rnd(1.62, 1.80)
    elif bucket == 3:
        crash = rnd(1.82, 2.18)
    elif bucket == 4:
        crash = rnd(2.20, 3.40)
    else:
        crash = rnd(3.40, ROCKET_MAX_PAY)

    crash = max(1.0, min(float(crash), ROCKET_MAX_SHOW))
    crash_pay = min(crash, ROCKET_MAX_PAY)

    # визуал выше для ленты (редко)
    if crash_pay >= 3.0 and random.random() < 0.22:
        display = min(ROCKET_MAX_SHOW, crash_pay + random.uniform(0.6, 2.5))
    else:
        display = crash_pay

    display = max(display, crash_pay)
    crash_pay = round(crash_pay, 2)
    display = round(display, 2)
    return crash_pay, display


def _rocket_mult_at(t: float) -> float:
    """Current multiplier at t seconds after fly start."""
    if t <= 0:
        return 1.0
    return round(math.exp(ROCKET_GROWTH_K * t), 2)


def _rocket_time_to_mult(mult: float) -> float:
    if mult <= 1.0:
        return 0.0
    return math.log(mult) / ROCKET_GROWTH_K


def _rocket_public(r: dict, uid: int = 0) -> dict:
    now = time.time()
    status = r.get("status") or "betting"
    crash_pay = float(r.get("crash_at") or 1.0)
    display_crash = float(r.get("display_crash") or crash_pay)
    fly_started = float(r.get("fly_started_at") or 0)
    betting_ends = float(r.get("betting_ends_at") or 0)

    mult = 1.0
    if status == "flying" and fly_started > 0:
        t = max(0.0, now - fly_started)
        mult = _rocket_mult_at(t)
        # don't reveal past crash to client during fly — clamp display
        if mult >= display_crash:
            mult = display_crash
    elif status == "crashed":
        mult = display_crash

    players = []
    my_bet = None
    for pid, p in (r.get("bets") or {}).items():
        if not isinstance(p, dict):
            continue
        row = {
            "uid": int(pid) if str(pid).isdigit() else pid,
            "username": p.get("username") or ("ID " + str(pid)),
            "amount": int(p.get("amount") or 0),
            "cashed": bool(p.get("cashed")),
            "cashout_mult": p.get("cashout_mult"),
        }
        players.append(row)
        if uid and str(pid) == str(uid):
            my_bet = row
    players.sort(key=lambda x: -x["amount"])

    left = 0.0
    if status == "betting":
        left = max(0.0, betting_ends - now)

    return {
        "status": status,
        "round_id": int(r.get("round_id") or 0),
        "mult": mult,
        "countdown": round(left, 2),
        "history": (r.get("history") or [])[:24],
        "players": players[:40],
        "my_bet": my_bet,
        "server_now": now,
        "fly_started_at": fly_started,
        "crash_at": display_crash if status == "crashed" else None,
    }


def _rocket_start_betting(r: dict) -> dict:
    now = time.time()
    r["status"] = "betting"
    r["round_id"] = int(r.get("round_id") or 0) + 1
    r["betting_ends_at"] = now + ROCKET_BETTING_SEC
    r["fly_started_at"] = 0.0
    r["bets"] = {}
    r["_all_cashed_boost"] = False
    # pre-roll (пересчитаем при старте полёта с учётом банка)
    pnl = int(r.get("house_pnl") or 0)
    crash_pay, display = _rocket_gen_crash(pnl, bank=0)
    r["crash_at"] = crash_pay
    r["display_crash"] = display
    r["seed"] = db.new_id()
    return r


def _rocket_tick() -> None:
    """Advance rocket round state machine. Called from background loop."""
    try:
        r = db.get_rocket()
        now = time.time()
        status = r.get("status") or "betting"

        if status == "betting":
            ends = float(r.get("betting_ends_at") or 0)
            if ends <= 0:
                r = _rocket_start_betting(r)
                db.save_rocket(r)
                return
            # safety: stuck past end by >30s → force new round
            if now - ends > 30:
                r = _rocket_start_betting(r)
                db.save_rocket(r)
                return
            if now >= ends:
                r["status"] = "flying"
                r["fly_started_at"] = now
                bets = r.get("bets") if isinstance(r.get("bets"), dict) else {}
                bank = 0
                for p in bets.values():
                    if isinstance(p, dict):
                        bank += int(p.get("amount") or 0)
                pnl = int(r.get("house_pnl") or 0)
                # пересчёт краша с учётом банка: большой банк → чаще ×2
                crash_pay, display = _rocket_gen_crash(pnl, bank=bank)
                if not bets:
                    # пустой раунд — для визуала можно улететь далеко
                    if random.random() < 0.55:
                        display = round(random.uniform(3.5, ROCKET_MAX_SHOW), 2)
                        crash_pay = min(display, ROCKET_MAX_PAY)
                    else:
                        display = crash_pay
                r["crash_at"] = round(float(crash_pay), 2)
                r["display_crash"] = round(float(display), 2)
                r["_all_cashed_boost"] = False
                db.save_rocket(r)
                return

        elif status == "flying":
            fly_started = float(r.get("fly_started_at") or 0)
            if fly_started <= 0:
                r["fly_started_at"] = now
                db.save_rocket(r)
                return
            display_crash = float(r.get("display_crash") or 1.0)
            t = max(0.0, now - fly_started)
            mult = _rocket_mult_at(t)
            # все забрали — для визуала можно улететь дальше (1 раз)
            if not r.get("_all_cashed_boost"):
                bets = r.get("bets") if isinstance(r.get("bets"), dict) else {}
                if bets and all(isinstance(p, dict) and p.get("cashed") for p in bets.values()):
                    r["_all_cashed_boost"] = True
                    extra = random.uniform(1.5, 4.0)
                    new_d = min(ROCKET_MAX_SHOW, max(display_crash, mult + extra))
                    r["display_crash"] = round(new_d, 2)
                    display_crash = new_d
                    db.save_rocket(r)
            # safety: flying > 60s → force crash
            force = t > 60
            if mult >= display_crash or force:
                if force:
                    display_crash = min(display_crash, max(1.0, mult))
                    r["display_crash"] = round(display_crash, 2)
                r["status"] = "crashed"
                r["crashed_at"] = now
                bets = r.get("bets") or {}
                pnl_delta = 0
                for pid, p in list(bets.items()):
                    if not isinstance(p, dict):
                        continue
                    amt = int(p.get("amount") or 0)
                    if p.get("cashed"):
                        continue
                    pnl_delta += amt
                    try:
                        db.add_history({
                            "uid": int(pid) if str(pid).lstrip("-").isdigit() else 0,
                            "type": "rocket_lose",
                            "bet": amt,
                            "mult": float(r.get("display_crash") or display_crash),
                            "win": 0,
                        })
                    except Exception:
                        pass
                r["house_pnl"] = int(r.get("house_pnl") or 0) + pnl_delta
                hp = int(r.get("house_pnl") or 0)
                if hp > 5000:
                    r["house_pnl"] = int(hp * 0.9)
                elif hp < -8000:
                    r["house_pnl"] = -8000
                hist = list(r.get("history") or [])
                hist.insert(0, float(r.get("display_crash") or display_crash))
                r["history"] = hist[:40]
                db.save_rocket(r)
                return

        elif status == "crashed":
            crashed_at = float(r.get("crashed_at") or 0)
            if crashed_at <= 0:
                r["crashed_at"] = now
                db.save_rocket(r)
                return
            if now - crashed_at >= ROCKET_CRASH_HOLD:
                r["status"] = "pause"
                r["pause_until"] = now + ROCKET_PAUSE_SEC
                db.save_rocket(r)
                return

        elif status == "pause":
            until = float(r.get("pause_until") or 0)
            if until <= 0 or now >= until:
                r = _rocket_start_betting(r)
                db.save_rocket(r)
                return
        else:
            r = _rocket_start_betting(r)
            db.save_rocket(r)
    except Exception:
        log.exception("rocket_tick")


class RocketBetIn(BaseModel):
    amount: int


@app.get("/api/rocket/state")
async def rocket_state(
    request: Request,
    x_telegram_id: Optional[str] = Header(None),
    tg_id: Optional[str] = Query(None),
):
    uid = 0
    try:
        uid = require_uid(x_telegram_id or request.headers.get("x-telegram-id"), tg_id)
    except Exception:
        uid = 0
    # advance state machine on every poll — no wait for background loop
    try:
        _rocket_tick()
    except Exception:
        log.exception("rocket tick on state")
    r = db.get_rocket()
    # lazy init
    if not r.get("betting_ends_at") and r.get("status") == "betting":
        r = _rocket_start_betting(r)
        db.save_rocket(r)
    return _rocket_public(r, uid)


@app.post("/api/rocket/bet")
async def rocket_bet(
    body: RocketBetIn,
    request: Request,
    x_telegram_id: Optional[str] = Header(None),
    tg_id: Optional[str] = Query(None),
):
    uid = require_uid(x_telegram_id or request.headers.get("x-telegram-id"), tg_id)
    amount = int(body.amount)
    if amount < MIN_BET:
        raise HTTPException(400, f"min {MIN_BET}")
    if amount > 50000:
        raise HTTPException(400, "макс 50000★")
    r = db.get_rocket()
    if (r.get("status") or "") != "betting":
        raise HTTPException(400, "приём ставок закрыт")
    bets = r.get("bets") if isinstance(r.get("bets"), dict) else {}
    if str(uid) in bets:
        raise HTTPException(400, "ставка уже сделана в этом раунде")
    # charge first
    try:
        change_balance(uid, -amount, "rocket_bet")
    except ValueError:
        raise HTTPException(400, "no balance")
    # re-read to reduce race with tick (betting→flying)
    r = db.get_rocket()
    if (r.get("status") or "") != "betting":
        # refund
        try:
            change_balance(uid, amount, "rocket_bet_refund")
        except Exception:
            pass
        raise HTTPException(400, "приём ставок закрыт")
    bets = r.get("bets") if isinstance(r.get("bets"), dict) else {}
    if str(uid) in bets:
        try:
            change_balance(uid, amount, "rocket_bet_refund")
        except Exception:
            pass
        raise HTTPException(400, "ставка уже сделана в этом раунде")
    tu = public_user(uid)
    un = tu.get("username") or ""
    bets[str(uid)] = {
        "amount": amount,
        "cashed": False,
        "cashout_mult": None,
        "username": un or ("ID " + str(uid)),
    }
    r["bets"] = bets
    db.save_rocket(r)
    try:
        db.add_history({"uid": uid, "type": "rocket_bet", "bet": amount, "win": 0})
    except Exception:
        pass
    return {
        "ok": True,
        "balance": public_user(uid)["balance"],
        "state": _rocket_public(r, uid),
    }


@app.post("/api/rocket/cashout")
async def rocket_cashout(
    request: Request,
    x_telegram_id: Optional[str] = Header(None),
    tg_id: Optional[str] = Query(None),
):
    uid = require_uid(x_telegram_id or request.headers.get("x-telegram-id"), tg_id)
    r = db.get_rocket()
    if (r.get("status") or "") != "flying":
        raise HTTPException(400, "сейчас нельзя забрать")
    bets = r.get("bets") if isinstance(r.get("bets"), dict) else {}
    p = bets.get(str(uid))
    if not p or not isinstance(p, dict):
        raise HTTPException(400, "нет ставки")
    if p.get("cashed"):
        raise HTTPException(400, "уже забрал")
    now = time.time()
    fly_started = float(r.get("fly_started_at") or 0)
    crash_pay = float(r.get("crash_at") or 1.0)
    display_crash = float(r.get("display_crash") or crash_pay)
    t = max(0.0, now - fly_started)
    mult = _rocket_mult_at(t)
    if mult >= display_crash or mult >= crash_pay:
        raise HTTPException(400, "уже краш")
    pay_mult = min(mult, crash_pay, ROCKET_MAX_PAY)
    amount = int(p.get("amount") or 0)
    payout = int(amount * pay_mult)
    if payout < 1:
        raise HTTPException(400, "слишком рано")
    # re-check after compute (anti double-cashout)
    r = db.get_rocket()
    if (r.get("status") or "") != "flying":
        raise HTTPException(400, "уже краш")
    bets = r.get("bets") if isinstance(r.get("bets"), dict) else {}
    p = bets.get(str(uid))
    if not p or not isinstance(p, dict):
        raise HTTPException(400, "нет ставки")
    if p.get("cashed"):
        raise HTTPException(400, "уже забрал")
    # recompute mult on latest clock
    now = time.time()
    fly_started = float(r.get("fly_started_at") or 0)
    crash_pay = float(r.get("crash_at") or 1.0)
    display_crash = float(r.get("display_crash") or crash_pay)
    t = max(0.0, now - fly_started)
    mult = _rocket_mult_at(t)
    if mult >= display_crash or mult >= crash_pay:
        raise HTTPException(400, "уже краш")
    pay_mult = min(mult, crash_pay, ROCKET_MAX_PAY)
    amount = int(p.get("amount") or 0)
    payout = int(amount * pay_mult)
    if payout < 1:
        raise HTTPException(400, "слишком рано")
    # mark cashed BEFORE balance credit to reduce double-pay window
    p["cashed"] = True
    p["cashout_mult"] = pay_mult
    bets[str(uid)] = p
    r["bets"] = bets
    r["house_pnl"] = int(r.get("house_pnl") or 0) + amount - payout
    db.save_rocket(r)
    try:
        change_balance(uid, payout, "rocket_win")
    except Exception as e:
        # rollback flag if credit failed
        try:
            r2 = db.get_rocket()
            b2 = r2.get("bets") or {}
            if str(uid) in b2 and isinstance(b2[str(uid)], dict):
                b2[str(uid)]["cashed"] = False
                b2[str(uid)]["cashout_mult"] = None
                r2["bets"] = b2
                db.save_rocket(r2)
        except Exception:
            pass
        raise HTTPException(500, "cashout failed")
    # все забрали — иногда чуть улетит, чаще крашится рядом с последним кешаутом
    # (не форсить всегда ×4–7 — это палит «луну после всех»)
    try:
        r3 = db.get_rocket()
        b3 = r3.get("bets") if isinstance(r3.get("bets"), dict) else {}
        still = [p for p in b3.values() if isinstance(p, dict) and not p.get("cashed")]
        if b3 and not still:
            cur = float(r3.get("display_crash") or pay_mult)
            roll = random.random()
            if roll < 0.22 and cur < 5.5:
                # редко — красивая луна
                r3["display_crash"] = round(min(ROCKET_MAX_SHOW, max(cur, random.uniform(3.2, 6.8))), 2)
                db.save_rocket(r3)
            elif roll < 0.55:
                # чуть выше последнего кеша
                bump = pay_mult + random.uniform(0.08, 0.85)
                r3["display_crash"] = round(min(float(r3.get("display_crash") or bump), max(pay_mult, bump)), 2)
                # не выше исходного display, если он уже ниже
                orig = float(r3.get("crash_at") or pay_mult)
                r3["display_crash"] = round(min(max(pay_mult, r3["display_crash"]), max(orig, pay_mult + 0.5)), 2)
                db.save_rocket(r3)
            # иначе оставляем исходный crash — выглядит честно
    except Exception:
        pass
    try:
        db.add_history({
            "uid": uid,
            "type": "rocket_win",
            "bet": amount,
            "mult": pay_mult,
            "win": payout,
        })
    except Exception:
        pass
    return {
        "ok": True,
        "payout": payout,
        "mult": pay_mult,
        "balance": public_user(uid)["balance"],
        "state": _rocket_public(db.get_rocket(), uid),
    }


# ---------- ARENA ----------

def _arena_public(a: dict) -> dict:
    players = []
    total = 0
    for pid, p in (a.get("players") or {}).items():
        val = int(p.get("stars") or 0)
        total += val
        ud = db.get_users().get(str(pid), {}) if isinstance(db.get_users(), dict) else {}
        if not isinstance(ud, dict):
            ud = {}
        players.append(
            {
                "uid": pid,
                "username": p.get("username") or ud.get("username"),
                "stars": val,
                "gift": p.get("gift"),
                "photo_url": ud.get("photo_url") or p.get("photo_url") or "",
                "first_name": ud.get("first_name") or p.get("first_name") or "",
                "color": p.get("color") or "",
            }
        )
    for p in players:
        p["pct"] = round(100.0 * p["stars"] / total, 2) if total else 0
    spin_at = a.get("spin_at")
    left = 0
    if spin_at:
        left = max(0, int(spin_at - time.time()))
    return {
        "status": a.get("status", "open"),
        "total": total,
        "players": players,
        "spin_at": spin_at,
        "countdown": left,
        "need": 2,
    }


def _player_color(uid: str) -> str:
    colors = ["#f97316", "#3b82f6", "#10b981", "#a855f7", "#ef4444", "#eab308", "#06b6d4", "#ec4899", "#84cc16", "#6366f1"]
    try:
        n = int(uid)
    except Exception:
        n = sum(ord(c) for c in str(uid))
    return colors[n % len(colors)]


async def _do_arena_roll(a: dict) -> dict:
    players = a.get("players") or {}
    if len(players) < 2:
        raise HTTPException(400, "need 2+")
    total = sum(int(p.get("stars") or 0) for p in players.values())
    if total <= 0:
        raise HTTPException(400, "empty bank")
    force = a.get("force_uid")
    if force and str(force) in players:
        winner = str(force)
    else:
        r = random.uniform(0, total)
        acc = 0
        winner = list(players.keys())[0]
        for pid, p in players.items():
            acc += int(p.get("stars") or 0)
            if r <= acc:
                winner = pid
                break
    win_user = db.ensure_user(int(winner))
    gifts_won = []
    stars_pool = 0
    pcts = []
    for pid, p in players.items():
        st = int(p.get("stars") or 0)
        pcts.append(
            {
                "uid": pid,
                "username": p.get("username"),
                "pct": round(100.0 * st / total, 2),
                "stars": st,
                "color": p.get("color") or _player_color(str(pid)),
            }
        )
        glist = []
        if p.get("gift"):
            glist.append(p["gift"])
        for gg in p.get("gifts") or []:
            if gg and gg not in glist:
                glist.append(gg)
        if glist:
            gifts_won.extend(glist)
            # гифты уже учтены в stars как цена; stars_pool только чистые ★ без гифтов?
            # сейчас stars включает цену гифта — победителю звёзды + гифты
            pure = st
            for gg in glist:
                pure -= int((gg or {}).get("price") or 0)
            if pure > 0:
                stars_pool += pure
        else:
            stars_pool += st
    if stars_pool:
        change_balance(int(winner), stars_pool, "arena_win")
    if gifts_won:
        inv = db.get_inv()
        if not isinstance(inv, dict):
            inv = {}
        key = str(winner)
        items = inv.get(key)
        if not isinstance(items, list):
            items = []
        for g in gifts_won:
            items.append(g)
        inv[key] = items
        db.save_inv(inv)
    result = {
        "winner": winner,
        "username": win_user.get("username"),
        "first_name": win_user.get("first_name") or "",
        "photo_url": win_user.get("photo_url") or players.get(str(winner), {}).get("photo_url") or "",
        "total": total,
        "stars_won": int(stars_pool),
        "pcts": pcts,
        "gifts": gifts_won,
        "color": players.get(str(winner), {}).get("color") or _player_color(str(winner)),
    }
    db.add_history({"uid": int(winner), "type": "arena_win", "total": total, "result": result})
    result["ts"] = time.time()
    db.save_arena({
        "status": "open",
        "players": {},
        "force_uid": None,
        "started_at": None,
        "spin_at": None,
        "last_result": result,
        "last_result_until": time.time() + 18,
    })
    return result


@app.get("/api/arena")
async def arena_state(x_telegram_id: Optional[str] = Header(None)):
    require_uid(x_telegram_id)
    a = db.get_arena()
    players = a.get("players") or {}
    # авто-ролл по таймеру
    if len(players) >= 2 and a.get("spin_at") and time.time() >= float(a["spin_at"]):
        try:
            result = await _do_arena_roll(a)
            a = db.get_arena()
        except Exception as e:
            log.warning("auto roll: %s", e)
            a = db.get_arena()
    out = _arena_public(a)
    # держим last_result ~18 сек чтобы клиент успел прокрутить анимацию
    until = float(a.get("last_result_until") or 0)
    lr = a.get("last_result")
    if lr and time.time() < until:
        out["last_result"] = lr
    return out


@app.post("/api/arena/join")
async def arena_join(body: ArenaJoin, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    a = db.get_arena()
    if a.get("status") not in (None, "open"):
        a["status"] = "open"
    u = db.ensure_user(uid)
    stars = 0
    gift = None
    if body.gift_id:
        inv = db.get_inv()
        if not isinstance(inv, dict):
            inv = {}
        items = inv.get(str(uid), [])
        if not isinstance(items, list):
            items = []
        item = next((x for x in items if isinstance(x, dict) and x.get("id") == body.gift_id), None)
        if not item:
            raise HTTPException(400, "no gift")
        stars = int(item.get("price") or 0)
        if stars < MIN_BET:
            raise HTTPException(400, f"gift min {MIN_BET}")
        inv[str(uid)] = [x for x in items if x.get("id") != body.gift_id]
        db.save_inv(inv)
        gift = {"id": item["id"], "link": item.get("link"), "title": item.get("title"), "price": stars}
    else:
        stars = int(body.amount)
        if stars < MIN_BET:
            raise HTTPException(400, f"min {MIN_BET}")
        try:
            change_balance(uid, -stars, "arena_bet")
        except ValueError:
            raise HTTPException(400, "no balance")

    a.setdefault("players", {})
    if not isinstance(a["players"], dict):
        a["players"] = {}
    key = str(uid)
    prev = a["players"].get(key)
    gifts_list = []
    if isinstance(prev, dict):
        # докидываем ставку, не затираем
        if prev.get("gift"):
            gifts_list.append(prev["gift"])
        for g in prev.get("gifts") or []:
            if g:
                gifts_list.append(g)
        prev_stars = int(prev.get("stars") or 0)
    else:
        prev_stars = 0
    if gift:
        gifts_list.append(gift)
    total_stars = prev_stars + stars
    a["players"][key] = {
        "username": u.get("username"),
        "stars": total_stars,
        "gift": gifts_list[-1] if gifts_list else None,
        "gifts": gifts_list,
        "photo_url": u.get("photo_url") or "",
        "first_name": u.get("first_name") or "",
        "color": (prev or {}).get("color") if isinstance(prev, dict) else _player_color(key),
    }
    if not a["players"][key]["color"]:
        a["players"][key]["color"] = _player_color(key)
    # таймер 10 сек когда 2+ игрока; каждый новый вход/докид сбрасывает на 15
    if len(a["players"]) >= 2:
        a["spin_at"] = time.time() + 10
        a["status"] = "open"
    else:
        a["spin_at"] = None
    db.save_arena(a)
    return _arena_public(a)


@app.post("/api/arena/roll")
async def arena_roll(x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    if not db.is_admin(uid):
        raise HTTPException(403, "admin only")
    a = db.get_arena()
    result = await _do_arena_roll(a)
    out = _arena_public(db.get_arena())
    out["last_result"] = result
    return out


# ---------- INVENTORY ----------
@app.get("/api/inventory")
async def api_inv(x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    inv = db.get_inv()
    return {"items": inv.get(str(uid), [])}


@app.post("/api/inventory/sell")
async def inv_sell(body: GiftSell, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    inv = db.get_inv()
    items = inv.get(str(uid), [])
    item = next((x for x in items if x["id"] == body.gift_id), None)
    if not item:
        raise HTTPException(400, "no gift")
    price = int(item["price"])
    inv[str(uid)] = [x for x in items if x["id"] != body.gift_id]
    db.save_inv(inv)
    change_balance(uid, price, "sell_gift")
    # notify owners
    for oid in filter(None, [OWNER_ID, OWNER2_ID, db.get_settings().get("owner2")]):
        try:
            await bot.send_message(int(oid), f"💱 @{public_user(uid)['username']} продал гифт {item.get('title')} за {price}★")
        except Exception:
            pass
    return {"ok": True, "balance": public_user(uid)["balance"]}


@app.post("/api/inventory/withdraw")
async def inv_withdraw(body: GiftWithdraw, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    inv = db.get_inv()
    items = inv.get(str(uid), [])
    item = next((x for x in items if x["id"] == body.gift_id), None)
    if not item:
        raise HTTPException(400, "no gift")
    try:
        change_balance(uid, -WITHDRAW_FEE, "withdraw_fee")
    except ValueError:
        raise HTTPException(400, f"need {WITHDRAW_FEE}★ fee")
    inv[str(uid)] = [x for x in items if x["id"] != body.gift_id]
    db.save_inv(inv)
    w = db.get_withdraws()
    req = {
        "id": db.new_id(),
        "uid": uid,
        "username": public_user(uid)["username"],
        "gift": item,
        "status": "pending",
        "ts": int(time.time()),
    }
    w.insert(0, req)
    db.save_withdraws(w)
    text = (
        f"📤 Вывод гифта\n@{req['username']} <code>{uid}</code>\n"
        f"{item.get('title')} | {item.get('price')}★\n{item.get('link')}\n"
        f"Fee {WITHDRAW_FEE}★ списан"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправил", callback_data="wdone:" + str(req["id"])),
                InlineKeyboardButton(text="❌ Отказ", callback_data="wrej:" + str(req["id"])),
            ]
        ]
    )
    for oid in filter(None, [OWNER_ID, OWNER2_ID, db.get_settings().get("owner2")]):
        try:
            await bot.send_message(int(oid), text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    for adm in db.get_settings().get("admins", []):
        try:
            await bot.send_message(int(adm), text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    return {"ok": True, "balance": public_user(uid)["balance"]}




@app.post("/api/withdraw/stars")
async def withdraw_stars(body: StarsWithdraw, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    amount = int(body.amount)
    if amount < MIN_WITHDRAW:
        raise HTTPException(400, f"мин. вывод {MIN_WITHDRAW}★")
    try:
        change_balance(uid, -amount, "stars_withdraw")
    except ValueError:
        raise HTTPException(400, "недостаточно ★")
    gift_value = int(amount * 0.85)
    u = public_user(uid)
    w = db.get_withdraws()
    req = {
        "id": db.new_id(),
        "uid": uid,
        "username": u.get("username") or "",
        "type": "stars",
        "amount": amount,
        "gift_value": gift_value,
        "status": "pending",
        "ts": int(time.time()),
    }
    w.insert(0, req)
    db.save_withdraws(w)
    text = (
        "⭐ Вывод звёзд → гифт\n"
        "@" + str(req["username"] or "—") + " <code>" + str(uid) + "</code>\n"
        "Списал: <b>" + str(amount) + "★</b>\n"
        "Гифт на ~<b>" + str(gift_value) + "★</b> (−15%)\n"
        "Отправить в течение 10 мин"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправил", callback_data="wdone:" + str(req["id"])),
                InlineKeyboardButton(text="❌ Отказ", callback_data="wrej:" + str(req["id"])),
            ]
        ]
    )
    for oid in filter(None, [OWNER_ID, OWNER2_ID, db.get_settings().get("owner2")]):
        try:
            await bot.send_message(int(oid), text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    for adm in db.get_settings().get("admins", []):
        try:
            await bot.send_message(int(adm), text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    try:
        await bot.send_message(
            uid,
            "✅ Заявка принята\n\n"
            "Списано: " + str(amount) + "★\n"
            "Гифт ≈ " + str(gift_value) + "★ (на 15% ниже)\n\n"
            "В течение 10 минут отправим подарок на ваш аккаунт.",
        )
    except Exception:
        pass
    return {
        "ok": True,
        "amount": amount,
        "gift_value": gift_value,
        "balance": public_user(uid)["balance"],
    }


# ---------- CHECKS ----------
# лок против гонок чеков (lazy — не создавать Lock до event loop)
_checks_lock = None
_broadcast_running = False


def _get_checks_lock() -> asyncio.Lock:
    global _checks_lock
    if _checks_lock is None:
        _checks_lock = asyncio.Lock()
    return _checks_lock


@app.post("/api/check/create")
async def check_create(body: CheckCreate, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    amount = int(body.amount)
    uses = max(1, int(getattr(body, "uses", 1) or 1))
    if uses > 50:
        raise HTTPException(400, "макс. 50 использований на чек")
    if amount < 1:
        raise HTTPException(400, "Сумма чека должна быть больше 0")
    # списываем amount * uses (каждый активация = amount ★)
    total = amount * uses
    try:
        change_balance(uid, -total, "check_create")
    except ValueError:
        raise HTTPException(400, f"Недостаточно ★ (нужно {total}★ = {amount}×{uses})")
    code = db.new_id()
    async with _get_checks_lock():
        c = db.get_checks()
        c[code] = {
            "from": uid,
            "amount": amount,
            "uses_left": uses,
            "uses_max": uses,
            "used": False,  # совместимость со старыми чеками
            "used_by": [],
        }
        db.save_checks(c)
    bot_user = BOT_USERNAME.lstrip("@") if "BOT_USERNAME" in dir() else "winlinebot"
    try:
        from config import BOT_USERNAME as _BU
        bot_user = str(_BU or "winlinebot").lstrip("@")
    except Exception:
        bot_user = "winlinebot"
    link = f"https://catup.lol/{bot_user}?start=check_{code}"
    link_tg = f"https://t.me/{bot_user}?start=check_{code}"
    try:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Поделиться", url=link)],
            ]
        )
        await bot.send_message(
            uid,
            "🎫 Чек " + str(amount) + "★\n"
            "Активаций: " + str(uses) + (" (одноразовый)" if uses == 1 else "") + "\n"
            "Списано с баланса: " + str(amount * uses) + "★\n"
            "Код: " + code,
            reply_markup=kb,
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.warning("check notify: %s", e)

    return {
        "code": code,
        "amount": amount,
        "uses": uses,
        "balance": public_user(uid)["balance"],
        "link": link,
        "link_tg": link_tg,
    }


def _check_can_use(row: dict, uid: int) -> tuple[bool, str]:
    """Проверка чека. Возвращает (ok, error_msg)."""
    if not row:
        return False, "Чек не найден"
    # старый формат: used=True
    if row.get("used") and int(row.get("uses_left", 0) or 0) <= 0 and "uses_left" not in row:
        return False, "Чек уже использован"
    uses_left = row.get("uses_left")
    if uses_left is None:
        # старый одноразовый
        if row.get("used"):
            return False, "Чек уже использован"
        uses_left = 1
    if int(uses_left) <= 0:
        return False, "Чек исчерпан (0 использований)"
    used_by = row.get("used_by") or []
    try:
        used_ids = {int(x) for x in used_by}
    except Exception:
        used_ids = set()
    if int(uid) in used_ids:
        return False, "Ты уже активировал этот чек"
    if int(row.get("from") or 0) == int(uid):
        return False, "Нельзя активировать свой чек"
    return True, ""


def _check_consume(row: dict, uid: int) -> dict:
    uses_left = row.get("uses_left")
    if uses_left is None:
        uses_left = 0 if row.get("used") else 1
    uses_left = int(uses_left) - 1
    row["uses_left"] = uses_left
    if uses_left <= 0:
        row["used"] = True
    used_by = list(row.get("used_by") or [])
    used_by.append(int(uid))
    row["used_by"] = used_by
    return row


@app.post("/api/check/activate")
async def check_activate(body: CheckActivate, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    code = (body.code or "").strip()
    if not code:
        raise HTTPException(400, "нет кода")
    async with _get_checks_lock():
        c = db.get_checks()
        row = c.get(code)
        ok, err = _check_can_use(row, uid)
        if not ok:
            raise HTTPException(400, err)
        row = _check_consume(dict(row), uid)
        c[code] = row
        db.save_checks(c)
        amt = int(row["amount"])
    change_balance(uid, amt, "check_activate")
    return {
        "ok": True,
        "amount": amt,
        "uses_left": row.get("uses_left", 0),
        "balance": public_user(uid)["balance"],
    }


# ---------- DEPOSIT CONFIRM ----------
_last_confirm: dict = {}
_dep_pending_amount: dict = {}  # admin_id -> order_id


@app.post("/api/deposit/confirm")
async def dep_confirm(body: ConfirmDep, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    now = time.time()
    if now - _last_confirm.get(uid, 0) < 30:
        raise HTTPException(400, "подожди 30 сек")
    _last_confirm[uid] = now
    u = public_user(uid)
    uname = (u.get("username") or "").lstrip("@")
    first = u.get("first_name") or ""
    if not uname or uname.isdigit():
        try:
            chat = await bot.get_chat(uid)
            if getattr(chat, "username", None):
                uname = str(chat.username).lstrip("@")
            if not first and getattr(chat, "first_name", None):
                first = str(chat.first_name)
            users = db.get_users()
            if str(uid) in users:
                if uname:
                    users[str(uid)]["username"] = uname.lower()
                if first:
                    users[str(uid)]["first_name"] = first
                db.save_users(users)
        except Exception as e:
            log.warning("get_chat %s: %s", uid, e)
    oid_order = db.new_id()
    deps = db.get_deposits()
    deps[oid_order] = {
        "id": oid_order,
        "uid": uid,
        "username": uname or "",
        "first_name": first,
        "note": body.note or "",
        "status": "pending",
        "ts": int(now),
    }
    db.save_deposits(deps)

    if uname and not str(uname).isdigit():
        name_line = "@" + uname
    elif first:
        name_line = first + " (без @)"
    else:
        name_line = "нет username"
    lines = [
        "📥 Заявка на депозит #" + str(oid_order),
        "Игрок: " + name_line,
        "Username: @" + (uname if uname else "нет"),
        "Имя: " + (first if first else "—"),
        "ID: " + str(uid),
        "Заметка: " + (body.note or "—"),
        "Банк: " + str(BANK),
        "",
        "Выбери сумму или гифт:",
    ]
    text = chr(10).join(lines)
    rows = [
        [
            InlineKeyboardButton(text="500★", callback_data=f"depok:{oid_order}:500"),
            InlineKeyboardButton(text="1k★", callback_data=f"depok:{oid_order}:1000"),
            InlineKeyboardButton(text="2.5k★", callback_data=f"depok:{oid_order}:2500"),
        ],
        [
            InlineKeyboardButton(text="5k★", callback_data=f"depok:{oid_order}:5000"),
            InlineKeyboardButton(text="10k★", callback_data=f"depok:{oid_order}:10000"),
            InlineKeyboardButton(text="25k★", callback_data=f"depok:{oid_order}:25000"),
        ],
        [
            InlineKeyboardButton(text="✍️ Своя ★", callback_data=f"depask:{oid_order}"),
            InlineKeyboardButton(text="🎁 Гифт", callback_data=f"depgift:{oid_order}"),
        ],
        [
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"depno:{oid_order}"),
        ],
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    targets = set()
    for oid in [OWNER_ID, OWNER2_ID, int(db.get_settings().get("owner2") or 0)]:
        if oid:
            targets.add(int(oid))
    for adm in db.get_settings().get("admins") or []:
        try:
            targets.add(int(adm))
        except Exception:
            pass
    sent = 0
    for oid in targets:
        try:
            await bot.send_message(oid, text, reply_markup=kb) if kb else await bot.send_message(oid, text)
            sent += 1
        except Exception as e:
            log.warning("dep notify %s: %s", oid, e)
    if not sent:
        log.warning("no admins got deposit notify")
    return {"ok": True}


# ---------- ADMIN API ----------
@app.get("/api/admin/state")
async def admin_state(x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    if not db.is_admin(uid):
        raise HTTPException(403, "admin")
    s = db.get_settings()
    return {
        "settings": s,
        "is_owner": db.is_owner(uid),
        "withdraws": [w for w in db.get_withdraws() if w.get("status") == "pending"][:20],
    }


@app.post("/api/admin/give")
async def admin_give(body: AdminGive, x_telegram_id: Optional[str] = Header(None)):
    admin = require_uid(x_telegram_id)
    if not db.is_admin(admin):
        raise HTTPException(403, "admin")
    target = resolve_target(body)
    db.ensure_user(target)
    change_balance(target, int(body.amount), f"admin_give by {admin}")
    u = db.get_users()
    if body.amount > 0:
        u[str(target)]["deposited"] = int(u[str(target)].get("deposited") or 0) + int(body.amount)
        db.save_users(u)
    try:
        await bot.send_message(target, f"💰 Баланс изменён на {body.amount:+d}★")
    except Exception:
        pass
    return {"ok": True, "uid": target, "balance": public_user(target)["balance"]}


@app.post("/api/admin/gift")
async def admin_gift(body: AdminGift, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    if not db.is_admin(uid):
        raise HTTPException(403, "admin")
    db.ensure_user(body.uid)
    inv = db.get_inv()
    item = {
        "id": db.new_id(),
        "link": body.link,
        "price": int(body.price),
        "title": body.title or "Gift",
    }
    inv.setdefault(str(body.uid), []).append(item)
    db.save_inv(inv)
    try:
        await bot.send_message(
            body.uid,
            f"🎁 Гифт в инвентарь: {item['title']} (~{item['price']}★)\n{item['link']}",
        )
    except Exception:
        pass
    return {"ok": True, "item": item}


@app.post("/api/admin/take_gift")
async def admin_take_gift(body: AdminTakeGift, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    if not db.is_admin(uid):
        raise HTTPException(403, "admin")
    inv = db.get_inv()
    items = inv.get(str(body.uid), [])
    inv[str(body.uid)] = [x for x in items if x["id"] != body.gift_id]
    db.save_inv(inv)
    return {"ok": True}


@app.post("/api/admin/odds")
async def admin_odds(body: AdminOdds, x_telegram_id: Optional[str] = Header(None)):
    uid = require_uid(x_telegram_id)
    if not db.is_owner(uid):
        raise HTTPException(403, "owner")
    s = db.get_settings()
    if body.slot_777 is not None:
        s["slot_777"] = float(body.slot_777)
    if body.slot_triple is not None:
        s["slot_triple"] = float(body.slot_triple)
    db.save_settings(s)
    return {"ok": True, "settings": s}


@app.post("/api/admin/force")
async def admin_force(body: AdminForce, x_telegram_id: Optional[str] = Header(None)):
    admin = require_uid(x_telegram_id)
    if not db.is_owner(admin):
        raise HTTPException(403, "owner")
    a = db.get_arena()
    if body.user or body.uid:
        a["force_uid"] = resolve_target(body)
    else:
        a["force_uid"] = None
    db.save_arena(a)
    return {"ok": True, "force_uid": a.get("force_uid")}


@app.post("/api/admin/owner2")
async def admin_owner2(body: AdminOwner2, x_telegram_id: Optional[str] = Header(None)):
    admin = require_uid(x_telegram_id)
    if not db.is_owner(admin):
        raise HTTPException(403, "owner")
    target = resolve_target(body)
    st = db.get_settings()
    st["owner2"] = int(target)
    db.save_settings(st)
    return {"ok": True, "owner2": target}


# ---------- BOT COMMANDS ----------

def _channel_username() -> str:
    ch = (REQUIRED_CHANNEL or "").strip()
    if not ch:
        return ""
    return ch if ch.startswith("@") else ("@" + ch.lstrip("@"))


def _user_channel_ok(uid: int) -> bool:
    try:
        u = db.get_users().get(str(uid), {}) or {}
        return bool(u.get("channel_ok"))
    except Exception:
        return False


def _set_channel_ok(uid: int) -> None:
    try:
        users = db.get_users()
        k = str(uid)
        if k not in users or not isinstance(users.get(k), dict):
            db.ensure_user(uid)
            users = db.get_users()
        users[k]["channel_ok"] = True
        db.save_users(users)
    except Exception as e:
        log.warning("set channel_ok: %s", e)


async def _is_subscribed(uid: int) -> bool:
    """Только визуал: нажал «Я подписался» → флаг. Без API, без пересылки."""
    ch = _channel_username()
    if not ch:
        return True
    if db.is_moderator(uid):
        return True
    return _user_channel_ok(uid)


def _welcome_kb():
    url = (WEBAPP_URL or os.getenv("RAILWAY_PUBLIC_DOMAIN") or "").strip()
    if url and not url.startswith("http"):
        url = "https://" + url
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Открыть Winline", web_app=WebAppInfo(url=url))],
            [InlineKeyboardButton(text="Банк", url="https://catup.lol/winlinebank")],
        ]
    )


def _sub_keyboard():
    ch = _channel_username()
    rows = []
    if ch:
        rows.append(
            [InlineKeyboardButton(text="📢 Подписаться на канал", url="https://catup.lol/" + ch.lstrip("@"))]
        )
    rows.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="checksub")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_welcome(message: Message, name: str = ""):
    kb = _welcome_kb()
    text = (
        "Привет" + (", " + name if name else "") + "!\n\n"
        "Winline — слоты, мины, PVP-арена.\n"
        "Банк: " + str(BANK) + "\n\n"
        "1. Открой приложение кнопкой\n"
        "2. Пополни через банк\n"
        "3. В аппке нажми Подтвердить — админ зачислит\n\n"
        "Удачи!"
    )
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "checksub")
async def cb_checksub(callback: CallbackQuery):
    """Визуал: ставим флаг и пускаем. Никакой API."""
    uid = callback.from_user.id
    _set_channel_ok(uid)
    await callback.answer("Ок ✅")
    name = callback.from_user.first_name or ""
    try:
        await _send_welcome(callback.message, name)
    except Exception:
        await callback.message.answer("Готово!", reply_markup=_welcome_kb())


@router.message(Command("start"))
async def cmd_start(message: Message):
    try:
        uid = message.from_user.id
        uname = (message.from_user.username or "") or ""
        db.ensure_user(uid, uname)
        try:
            users = db.get_users()
            k = str(uid)
            if k in users:
                if message.from_user.first_name:
                    users[k]["first_name"] = message.from_user.first_name
                if uname:
                    users[k]["username"] = uname.lower()
                db.save_users(users)
        except Exception as e:
            log.warning("start save user: %s", e)

        # активация чека: /start check_CODE
        payload = ""
        try:
            parts = (message.text or "").split(maxsplit=1)
            if len(parts) > 1:
                payload = parts[1].strip()
        except Exception:
            pass
        if payload.startswith("check_"):
            code = payload[6:].strip()
            async with _get_checks_lock():
                checks = db.get_checks()
                row = checks.get(code)
                ok, err = _check_can_use(row, uid)
                if not ok:
                    await message.answer(err)
                    return
                row = _check_consume(dict(row), uid)
                checks[code] = row
                db.save_checks(checks)
                amt = int(row["amount"])
                left = int(row.get("uses_left") or 0)
                from_uid = int(row.get("from") or 0)
            bal = change_balance(uid, amt, "check_activate")
            extra = f"\nОсталось использований: {left}" if left > 0 else ""
            await message.answer(
                "✅ Чек активирован: +" + str(amt) + "★\nБаланс: " + str(bal) + "★" + extra
            )
            if from_uid:
                try:
                    await bot.send_message(
                        from_uid,
                        "Твой чек " + code + " активирован (" + str(amt) + "★), осталось " + str(left),
                    )
                except Exception:
                    pass
            return

        # визуальная «подписка» (без API): один раз кнопка → флаг channel_ok
        if not await _is_subscribed(uid):
            ch = _channel_username() or "@winline"
            await message.answer(
                "Подпишись на канал " + ch + " и нажми «Я подписался»",
                reply_markup=_sub_keyboard(),
            )
            return

        name = message.from_user.first_name or (uname and ("@" + uname)) or "игрок"
        await _send_welcome(message, str(name))
    except Exception as e:
        log.exception("start failed")
        try:
            await message.answer("Winline онлайн. Ошибка старта: " + str(e)[:120])
        except Exception:
            pass


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    await message.answer(
        "Админ-команды:\n"
        "/give ID 5000 — выдать любую сумму ★\n"
        "/take ID 100 — снять ★\n"
        "/gift ID 1500 https://... — гифт в инвентарь\n"
        "/force ID — гарант арены (0=сброс)\n"
        "/odds777 0.005\n"
        "/owner2 ID\n"
        "/addadmin ID\n"
        "/addmod ID|@user — добавить модератора\n"
        "/delmod ID|@user — убрать модератора\n"
        "/mods — список модеров\n"
        "/broadcast текст — рассылка (мод+админ)\n\n"
        "Модеры: /mod · /mgive · /mtake · /mcheck\n"
        "Депозит: кнопки в заявке (★ или гифт)\n"
        "Вывод гифтов: кнопки в ЛС"
    )


@router.message(Command("mod"))
async def cmd_mod(message: Message):
    """Отдельная панель модератора."""
    if not db.is_moderator(message.from_user.id):
        return
    is_full = db.is_admin(message.from_user.id)
    lines = [
        "🛡 Панель модератора",
        "",
        f"/mgive @user 1500 — выдать ★ (макс {MOD_GIVE_MAX})",
        f"/mtake @user 500 — снять ★ (макс {MOD_GIVE_MAX})",
        "/mcheck 5000 3 — чек 5000★ × 3 исп. (со своего баланса)",
        "/broadcast текст — рассылка всем",
        "",
        "Работает и по @username, и по числовому ID",
    ]
    if is_full:
        lines.append("")
        lines.append("(ты админ — полный /admin тоже доступен)")
    await message.answer("\n".join(lines))


def _resolve_mod_target(ref: str):
    """ID или @username → uid. Юзер должен хотя бы раз зайти в аппку."""
    ref = (ref or "").strip()
    if not ref:
        return None
    tuid = db.parse_user_ref(ref)
    if tuid is not None:
        return int(tuid)
    try:
        return int(ref.lstrip("@"))
    except Exception:
        return None


@router.message(Command("mgive"))
async def cmd_mgive(message: Message):
    """Выдача модератором с лимитом MOD_GIVE_MAX. По ID или @username."""
    if not db.is_moderator(message.from_user.id):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            return await message.answer(f"Формат: /mgive @user_или_ID сумма\nМакс {MOD_GIVE_MAX}★")
        tuid = _resolve_mod_target(parts[1])
        if tuid is None:
            return await message.answer(
                "Юзер не найден: " + parts[1] + "\n"
                "Нужен числовой ID или @username (игрок должен зайти в аппку хотя бы раз)"
            )
        try:
            amount = int(parts[2].replace(" ", "").replace("★", "").replace("+", ""))
        except ValueError:
            return await message.answer("Сумма числом. Пример: 1500")
        if amount <= 0:
            return await message.answer("Сумма > 0")
        if db.is_mod_only(message.from_user.id) and amount > MOD_GIVE_MAX:
            return await message.answer(f"Лимит модератора: максимум {MOD_GIVE_MAX}★ за раз")
        db.ensure_user(tuid)
        bal = change_balance(tuid, amount, "mod_give by " + str(message.from_user.id))
        # мод-выдача НЕ крутит deposited/топ
        un = (db.get_users().get(str(tuid), {}) or {}).get("username") or tuid
        await message.answer(
            "✅ Мод-выдача " + str(amount) + "★ → @" + str(un) + " (ID " + str(tuid) + ")\nБаланс: " + str(bal) + "★"
        )
        try:
            await bot.send_message(tuid, "✅ Тебе зачислено +" + str(amount) + "★\nБаланс: " + str(bal) + "★")
        except Exception as e:
            log.warning("notify mgive: %s", e)
    except Exception as e:
        log.exception("mgive failed")
        await message.answer("Ошибка /mgive: " + str(e)[:200])


@router.message(Command("mtake"))
async def cmd_mtake(message: Message):
    """Снятие ★ модератором. Лимит MOD_GIVE_MAX. По ID или @username."""
    if not db.is_moderator(message.from_user.id):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            return await message.answer(f"Формат: /mtake @user_или_ID сумма\nМакс {MOD_GIVE_MAX}★")
        tuid = _resolve_mod_target(parts[1])
        if tuid is None:
            return await message.answer(
                "Юзер не найден: " + parts[1] + "\n"
                "Нужен ID или @username (игрок должен зайти в аппку)"
            )
        try:
            amount = abs(int(parts[2].replace(" ", "").replace("★", "").replace("-", "")))
        except ValueError:
            return await message.answer("Сумма числом. Пример: 500")
        if amount <= 0:
            return await message.answer("Сумма > 0")
        if db.is_mod_only(message.from_user.id) and amount > MOD_GIVE_MAX:
            return await message.answer(f"Лимит модератора: максимум {MOD_GIVE_MAX}★ за раз")
        try:
            bal = change_balance(tuid, -amount, "mod_take by " + str(message.from_user.id))
        except ValueError:
            return await message.answer("Не хватает баланса у игрока")
        un = (db.get_users().get(str(tuid), {}) or {}).get("username") or tuid
        await message.answer(
            "✅ Снято " + str(amount) + "★ с @" + str(un) + " (ID " + str(tuid) + ")\nБаланс: " + str(bal) + "★"
        )
        try:
            await bot.send_message(tuid, "С баланса снято " + str(amount) + "★\nБаланс: " + str(bal) + "★")
        except Exception:
            pass
    except Exception as e:
        log.exception("mtake failed")
        await message.answer("Ошибка /mtake: " + str(e)[:200])


@router.message(Command("mcheck"))
async def cmd_mcheck(message: Message):
    """Мод/админ: создать чек с лимитом использований. Списывает с баланса создателя."""
    if not db.is_moderator(message.from_user.id):
        return
    try:
        parts = (message.text or "").split()
        if len(parts) < 2:
            return await message.answer(
                "Формат: /mcheck сумма [uses]\n"
                "Пример: /mcheck 5000 3  — чек по 5000★, 3 активации (спишет 15000★)\n"
                "Макс uses: 50"
            )
        amount = int(parts[1].replace("★", "").replace(" ", ""))
        uses = int(parts[2]) if len(parts) >= 3 else 1
        uses = max(1, min(50, uses))
        if amount < 1:
            return await message.answer("Сумма > 0")
        uid = message.from_user.id
        total = amount * uses
        try:
            change_balance(uid, -total, "mcheck_create")
        except ValueError:
            return await message.answer(f"Не хватает баланса (нужно {total}★)")
        code = db.new_id()
        async with _get_checks_lock():
            c = db.get_checks()
            c[code] = {
                "from": uid,
                "amount": amount,
                "uses_left": uses,
                "uses_max": uses,
                "used": False,
                "used_by": [],
            }
            db.save_checks(c)
        bot_user = str(BOT_USERNAME or "winlinebot").lstrip("@")
        link = f"https://catup.lol/{bot_user}?start=check_{code}"
        await message.answer(
            f"🎫 Чек создан\n"
            f"Сумма за активацию: {amount}★\n"
            f"Активаций: {uses}" + (" (одноразовый)" if uses == 1 else "") + "\n"
            f"Списано с баланса: {total}★\n"
            f"Код: <code>{code}</code>\n"
            f"{link}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.exception("mcheck")
        await message.answer("Ошибка: " + str(e)[:150])


@router.message(Command("addmod"))
async def cmd_addmod(message: Message):
    if not db.is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer("/addmod ID")
    tid = db.parse_user_ref(parts[1])
    if tid is None:
        try:
            tid = int(parts[1])
        except Exception:
            return await message.answer("Юзер не найден")
    st = db.get_settings()
    mods = st.setdefault("moderators", [])
    if not isinstance(mods, list):
        mods = []
    mods.append(int(tid))
    st["moderators"] = list(set(int(x) for x in mods))
    db.save_settings(st)
    await message.answer("mod ok: " + str(tid))


@router.message(Command("delmod"))
async def cmd_delmod(message: Message):
    if not db.is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer("/delmod ID")
    tid = db.parse_user_ref(parts[1])
    if tid is None:
        try:
            tid = int(parts[1])
        except Exception:
            return await message.answer("Юзер не найден")
    st = db.get_settings()
    mods = [int(x) for x in (st.get("moderators") or []) if int(x) != int(tid)]
    st["moderators"] = mods
    db.save_settings(st)
    await message.answer("mod removed: " + str(tid))


@router.message(Command("mods"))
async def cmd_mods(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    mods = db.get_settings().get("moderators") or []
    await message.answer("Модераторы: " + (", ".join(str(x) for x in mods) if mods else "пусто"))


# состояние рассылки: admin_id -> waiting text
_broadcast_pending: dict = {}


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    """Админ или мод. /broadcast текст — сразу, или /broadcast → следующим сообщением текст."""
    if not db.is_moderator(message.from_user.id):
        return
    global _broadcast_running
    if _broadcast_running:
        return await message.answer("Уже идёт рассылка, подожди")
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        _broadcast_pending[message.from_user.id] = True
        return await message.answer(
            "📢 Рассылка\nПришли следующим сообщением текст (можно с эмодзи).\nОтмена: /cancel"
        )
    await _do_broadcast(message.from_user.id, parts[1].strip(), message)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    if message.from_user.id in _broadcast_pending:
        _broadcast_pending.pop(message.from_user.id, None)
        await message.answer("Отменено")


async def _do_broadcast(admin_id: int, text: str, reply_to: Message):
    global _broadcast_running
    if _broadcast_running:
        await reply_to.answer("Уже идёт рассылка")
        return
    if not text or not str(text).strip():
        await reply_to.answer("Пустой текст")
        return
    _broadcast_running = True
    try:
        users = db.get_users()
        ids = []
        for k in users.keys():
            try:
                ids.append(int(k))
            except Exception:
                pass
        ok = 0
        fail = 0
        await reply_to.answer(f"📢 Рассылка {len(ids)} юзерам...")
        for i, uid in enumerate(ids):
            try:
                await bot.send_message(uid, text)
                ok += 1
            except Exception:
                fail += 1
            # пауза, чтобы не упереться в лимиты API
            if i % 20 == 19:
                await asyncio.sleep(0.35)
            else:
                await asyncio.sleep(0.04)
        await reply_to.answer(f"✅ Рассылка готова\nДоставлено: {ok}\nОшибки: {fail}")
    except Exception as e:
        log.exception("broadcast")
        try:
            await reply_to.answer("Ошибка рассылки: " + str(e)[:120])
        except Exception:
            pass
    finally:
        _broadcast_running = False



@router.message(Command("give"))
async def cmd_give(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            return await message.answer("Формат: /give ID_или_@user сумма\nПример: /give 1780308643 1500")
        tuid = db.parse_user_ref(parts[1])
        if tuid is None:
            # try force int
            try:
                tuid = int(parts[1].lstrip("@"))
            except Exception:
                return await message.answer("Юзер не найден. Используй числовой ID.")
        try:
            amount = int(parts[2].replace(" ", "").replace("★", "").replace("+", ""))
        except ValueError:
            return await message.answer("Сумма числом. Пример: 1500")
        db.ensure_user(tuid)
        bal = change_balance(tuid, amount, "give by " + str(message.from_user.id))
        if amount > 0:
            u = db.get_users()
            u[str(tuid)]["deposited"] = int(u[str(tuid)].get("deposited") or 0) + amount
            db.save_users(u)
        un = (db.get_users().get(str(tuid), {}) or {}).get("username") or tuid
        await message.answer("✅ Зачислено " + str(amount) + "★ → @" + str(un) + " (ID " + str(tuid) + ")\nБаланс: " + str(bal) + "★")
        try:
            await bot.send_message(tuid, "✅ Тебе зачислено +" + str(amount) + "★\nБаланс: " + str(bal) + "★")
        except Exception as e:
            log.warning("notify give: %s", e)
    except Exception as e:
        log.exception("give failed")
        await message.answer("Ошибка /give: " + str(e)[:200])


@router.message(Command("take"))
async def cmd_take(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3:
            return await message.answer("/take ID сумма")
        tuid = db.parse_user_ref(parts[1])
        if tuid is None:
            try:
                tuid = int(parts[1])
            except Exception:
                return await message.answer("Юзер не найден")
        amount = abs(int(parts[2].replace(" ", "")))
        bal = change_balance(tuid, -amount, "take by " + str(message.from_user.id))
        await message.answer("✅ Снято " + str(amount) + "★ с ID " + str(tuid) + "\nБаланс: " + str(bal) + "★")
        try:
            await bot.send_message(tuid, "С баланса снято " + str(amount) + "★\nБаланс: " + str(bal) + "★")
        except Exception:
            pass
    except ValueError:
        await message.answer("Не хватает баланса")
    except Exception as e:
        await message.answer("Ошибка: " + str(e)[:150])



@router.message(Command("gift"))
async def cmd_gift(message: Message):
    if not db.is_admin(message.from_user.id):
        return
    try:
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 4:
            return await message.answer(
                "Формат:\n/gift ID цена ссылка\n"
                "Пример:\n/gift 1780308643 1500 https://t.me/nft/..."
            )
        tuid = db.parse_user_ref(parts[1])
        if tuid is None:
            try:
                tuid = int(str(parts[1]).lstrip("@"))
            except Exception:
                return await message.answer("Юзер не найден. Укажи числовой ID.")
        try:
            price = int(str(parts[2]).replace("★", "").replace(" ", ""))
        except ValueError:
            return await message.answer("Цена числом, пример: 1500")
        link = parts[3].strip()
        if not link:
            return await message.answer("Нужна ссылка на гифт")
        db.ensure_user(tuid)
        inv = db.get_inv()
        if not isinstance(inv, dict):
            inv = {}
        key = str(tuid)
        items = inv.get(key)
        if not isinstance(items, list):
            items = []
        item = {"id": db.new_id(), "link": link, "price": price, "title": "Gift"}
        items.append(item)
        inv[key] = items
        db.save_inv(inv)
        await message.answer(
            "✅ Гифт выдан\n"
            "ID: " + str(tuid) + "\n"
            "Цена: " + str(price) + "★\n"
            "gift_id: " + item["id"] + "\n"
            "Ссылка: " + link
        )
        try:
            await bot.send_message(
                tuid,
                "🎁 Тебе выдан гифт (~" + str(price) + "★)\n" + link,
            )
        except Exception as e:
            log.warning("gift notify: %s", e)
    except Exception as e:
        log.exception("gift")
        await message.answer("Ошибка /gift: " + str(e)[:200])


@router.message(Command("takegift"))
async def cmd_takegift(message: Message):
    """Забрать гифт: /takegift ID gift_id  ИЛИ  /takegift ID all"""
    if not db.is_admin(message.from_user.id):
        return
    try:
        parts = (message.text or "").split()
        if len(parts) < 3:
            return await message.answer(
                "Забрать гифт:\n"
                "/takegift ID gift_id\n"
                "/takegift ID all — все гифты\n"
                "Список: /gifts ID"
            )
        tuid = db.parse_user_ref(parts[1])
        if tuid is None:
            try:
                tuid = int(str(parts[1]).lstrip("@"))
            except Exception:
                return await message.answer("Юзер не найден")
        inv = db.get_inv()
        if not isinstance(inv, dict):
            inv = {}
        key = str(tuid)
        items = inv.get(key)
        if not isinstance(items, list) or not items:
            return await message.answer("У игрока нет гифтов")
        target = parts[2].strip().lower()
        if target == "all":
            n = len(items)
            inv[key] = []
            db.save_inv(inv)
            await message.answer("✅ Снято гифтов: " + str(n) + " у ID " + str(tuid))
            try:
                await bot.send_message(tuid, "Админ забрал все гифты из инвентаря (" + str(n) + ")")
            except Exception:
                pass
            return
        new_items = [x for x in items if str(x.get("id")) != target]
        if len(new_items) == len(items):
            return await message.answer("gift_id не найден. Смотри /gifts " + str(tuid))
        inv[key] = new_items
        db.save_inv(inv)
        await message.answer("✅ Гифт " + target + " забран у ID " + str(tuid))
        try:
            await bot.send_message(tuid, "Админ забрал гифт из инвентаря")
        except Exception:
            pass
    except Exception as e:
        log.exception("takegift")
        await message.answer("Ошибка /takegift: " + str(e)[:200])


@router.message(Command("gifts"))
async def cmd_gifts(message: Message):
    """Список гифтов игрока: /gifts ID"""
    if not db.is_admin(message.from_user.id):
        return
    try:
        parts = (message.text or "").split()
        if len(parts) < 2:
            return await message.answer("/gifts ID")
        tuid = db.parse_user_ref(parts[1])
        if tuid is None:
            try:
                tuid = int(str(parts[1]).lstrip("@"))
            except Exception:
                return await message.answer("Юзер не найден")
        inv = db.get_inv()
        items = inv.get(str(tuid), []) if isinstance(inv, dict) else []
        if not isinstance(items, list) or not items:
            return await message.answer("Пусто у ID " + str(tuid))
        lines = ["Гифты ID " + str(tuid) + ":"]
        for it in items:
            if not isinstance(it, dict):
                continue
            lines.append(
                "• " + str(it.get("id")) + " | " + str(it.get("price", "?")) + "★ | " + str(it.get("link", ""))[:40]
            )
        await message.answer("\n".join(lines))
    except Exception as e:
        await message.answer("Ошибка: " + str(e)[:150])


@router.message(Command("force"))
async def cmd_force(message: Message):
    if not db.is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer("/force ID или 0")
    if parts[1] in ("0", "off", "none"):
        v = None
    else:
        v = db.parse_user_ref(parts[1])
        if v is None:
            try:
                v = int(parts[1])
            except Exception:
                return await message.answer("Юзер не найден")
    a = db.get_arena()
    a["force_uid"] = v
    db.save_arena(a)
    await message.answer("force=" + str(a["force_uid"]))


@router.message(Command("odds777"))
async def cmd_odds(message: Message):
    if not db.is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer("/odds777 0.005")
    s = db.get_settings()
    s["slot_777"] = float(parts[1])
    db.save_settings(s)
    await message.answer("slot_777=" + str(s["slot_777"]))


@router.message(Command("owner2"))
async def cmd_owner2(message: Message):
    if not db.is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer("/owner2 ID")
    st = db.get_settings()
    st["owner2"] = int(parts[1])
    db.save_settings(st)
    await message.answer("ok owner2=" + parts[1])


@router.message(Command("addadmin"))
async def cmd_addadmin(message: Message):
    if not db.is_owner(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer("/addadmin ID")
    st = db.get_settings()
    adm = st.setdefault("admins", [])
    adm.append(int(parts[1]))
    st["admins"] = list(set(int(x) for x in adm))
    db.save_settings(st)
    await message.answer("admin ok")



@router.message(Command("deltop"))
async def cmd_deltop(message: Message):
    """Убрать из топа: /deltop ID — deposited=0"""
    if not db.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        return await message.answer("/deltop ID или @user")
    tuid = db.parse_user_ref(parts[1])
    if tuid is None:
        try:
            tuid = int(parts[1])
        except Exception:
            return await message.answer("Юзер не найден")
    u = db.get_users()
    k = str(tuid)
    if k not in u or not isinstance(u.get(k), dict):
        return await message.answer("Нет в базе")
    old = int(u[k].get("deposited") or 0)
    u[k]["deposited"] = 0
    db.save_users(u)
    await message.answer("Убран из топа ID " + str(tuid) + " (было деп " + str(old) + "★)")


async def _credit_deposit(oid: str, amount: int, admin_id: int, message_or_cb) -> str:
    deps = db.get_deposits()
    row = deps.get(oid)
    if not row or row.get("status") != "pending":
        return "already"
    tuid = int(row["uid"])
    db.ensure_user(tuid, row.get("username") or "")
    bal = change_balance(tuid, amount, "deposit by " + str(admin_id))
    u = db.get_users()
    u[str(tuid)]["deposited"] = int(u[str(tuid)].get("deposited") or 0) + amount
    db.save_users(u)
    row["status"] = "done"
    row["amount"] = amount
    row["by"] = admin_id
    deps[oid] = row
    db.save_deposits(deps)
    un = row.get("username") or tuid
    text = "✅ Зачислено " + str(amount) + "★ → @" + str(un) + " (ID " + str(tuid) + ")\nБаланс: " + str(bal) + "★"
    try:
        await bot.send_message(tuid, "✅ Депозит принят: +" + str(amount) + "★\nБаланс: " + str(bal) + "★")
    except Exception as e:
        log.warning("dep notify user: %s", e)
    return text


@router.callback_query(F.data.startswith("depok:"))
async def cb_depok(callback: CallbackQuery):
    try:
        if not db.is_admin(callback.from_user.id):
            return await callback.answer("нет доступа", show_alert=True)
        parts = (callback.data or "").split(":")
        if len(parts) != 3:
            return await callback.answer("bad")
        amount = int(parts[2])
        oid = parts[1]
        result = await _credit_deposit(oid, amount, callback.from_user.id, callback)
        if result == "already":
            return await callback.answer("Уже обработано", show_alert=True)
        try:
            await callback.message.edit_text(result)
        except Exception:
            await callback.message.answer(result)
        await callback.answer("Готово")
    except Exception as e:
        log.exception("depok")
        await callback.answer("Ошибка: " + str(e)[:80], show_alert=True)


@router.callback_query(F.data.startswith("depask:"))
async def cb_depask(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        return await callback.answer("нет доступа", show_alert=True)
    oid = (callback.data or "").split(":")[-1]
    deps = db.get_deposits()
    row = deps.get(oid)
    if not row or row.get("status") != "pending":
        return await callback.answer("Уже обработано", show_alert=True)
    _dep_pending_amount[callback.from_user.id] = ("stars", oid)
    await callback.answer()
    await callback.message.answer(
        "Своя сумма ★ для ID " + str(row.get("uid")) + " (заказ #" + oid + ")\n"
        "Напиши ТОЛЬКО число, например:\n1500"
    )


@router.callback_query(F.data.startswith("depgift:"))
async def cb_depgift(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        return await callback.answer("нет доступа", show_alert=True)
    oid = (callback.data or "").split(":")[-1]
    deps = db.get_deposits()
    row = deps.get(oid)
    if not row or row.get("status") != "pending":
        return await callback.answer("Уже обработано", show_alert=True)
    _dep_pending_amount[callback.from_user.id] = ("gift", oid)
    await callback.answer()
    await callback.message.answer(
        "Гифт для ID " + str(row.get("uid")) + " (заказ #" + oid + ")\n"
        "Напиши: цена ссылка\n"
        "Пример:\n1500 https://t.me/nft/..."
    )


@router.callback_query(F.data.startswith("depno:"))
async def cb_depno(callback: CallbackQuery):
    try:
        if not db.is_admin(callback.from_user.id):
            return await callback.answer("нет доступа", show_alert=True)
        oid = (callback.data or "").split(":")[-1]
        deps = db.get_deposits()
        row = deps.get(oid)
        if not row or row.get("status") != "pending":
            return await callback.answer("Уже обработано", show_alert=True)
        row["status"] = "rejected"
        row["by"] = callback.from_user.id
        deps[oid] = row
        db.save_deposits(deps)
        try:
            await callback.message.edit_text("❌ Отклонено #" + oid + " ID " + str(row.get("uid")))
        except Exception:
            pass
        try:
            await bot.send_message(int(row["uid"]), "❌ Депозит отклонён. Напиши админу.")
        except Exception:
            pass
        await callback.answer("Отклонено")
    except Exception as e:
        await callback.answer(str(e)[:80], show_alert=True)


@router.message(F.text)
async def cmd_admin_pending_text(message: Message):
    """Своя сумма ★ / гифт после депозита + текст рассылки. Не глотает команды."""
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    aid = message.from_user.id
    # рассылка: ждём текст после /broadcast (мод или админ)
    if _broadcast_pending.get(aid) and db.is_moderator(aid):
        _broadcast_pending.pop(aid, None)
        await _do_broadcast(aid, text, message)
        return
    if not db.is_admin(aid):
        return
    pending = _dep_pending_amount.get(aid)
    if not pending:
        return
    kind, oid = pending
    deps = db.get_deposits()
    row = deps.get(oid)
    if not row or row.get("status") != "pending":
        _dep_pending_amount.pop(aid, None)
        return await message.answer("Заявка уже закрыта")

    if kind == "stars":
        if not text.isdigit():
            return  # not our message
        _dep_pending_amount.pop(aid, None)
        amount = int(text)
        if amount < 1:
            return await message.answer("Сумма > 0")
        try:
            result = await _credit_deposit(oid, amount, aid, message)
            await message.answer(result if result != "already" else "Уже обработано")
        except Exception as e:
            await message.answer("Ошибка: " + str(e)[:150])
        return

    if kind == "gift":
        parts = text.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            return await message.answer("Формат: цена ссылка\n1500 https://...")
        _dep_pending_amount.pop(aid, None)
        price = int(parts[0])
        link = parts[1].strip()
        tuid = int(row["uid"])
        db.ensure_user(tuid, row.get("username") or "")
        inv = db.get_inv()
        item = {"id": db.new_id(), "link": link, "price": price, "title": "Gift"}
        inv.setdefault(str(tuid), []).append(item)
        db.save_inv(inv)
        # гифт-депозит тоже в топ (deposited)
        try:
            users = db.get_users()
            uk = str(tuid)
            if uk not in users or not isinstance(users.get(uk), dict):
                db.ensure_user(tuid)
                users = db.get_users()
            users[uk]["deposited"] = int(users[uk].get("deposited") or 0) + int(price)
            db.save_users(users)
        except Exception as e:
            log.warning("gift dep top: %s", e)
        row["status"] = "done"
        row["gift"] = item
        row["amount"] = price
        row["by"] = aid
        deps[oid] = row
        db.save_deposits(deps)
        await message.answer("✅ Гифт " + str(price) + "★ в инвентарь ID " + str(tuid) + " (в топ +" + str(price) + "★)")
        try:
            await bot.send_message(tuid, "🎁 Депозит-гифт принят (~" + str(price) + "★)\n" + link)
        except Exception:
            pass


@router.callback_query(F.data.startswith("wdone:"))
async def cb_wdone(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        return await callback.answer("no")
    wid = callback.data.split(":")[1]
    w = db.get_withdraws()
    for row in w:
        if row.get("id") == wid:
            row["status"] = "done"
            try:
                await bot.send_message(row["uid"], "✅ Гифт отправлен")
            except Exception:
                pass
    db.save_withdraws(w)
    await callback.answer("ok")
    try:
        await callback.message.edit_reply_markup(None)
    except Exception:
        pass


@router.callback_query(F.data.startswith("wrej:"))
async def cb_wrej(callback: CallbackQuery):
    if not db.is_admin(callback.from_user.id):
        return await callback.answer("no")
    wid = callback.data.split(":")[1]
    w = db.get_withdraws()
    for row in w:
        if row.get("id") == wid and row.get("status") == "pending":
            row["status"] = "rejected"
            inv = db.get_inv()
            inv.setdefault(str(row["uid"]), []).append(row["gift"])
            db.save_inv(inv)
            try:
                if row.get("type") == "stars":
                    change_balance(row["uid"], int(row.get("amount") or 0), "stars_withdraw_reject")
                else:
                    change_balance(row["uid"], WITHDRAW_FEE, "withdraw_reject_fee")
            except Exception:
                pass
            try:
                await bot.send_message(
                    row["uid"],
                    "❌ Вывод отклонён, средства возвращены" if row.get("type") == "stars" else "❌ Вывод отклонён, гифт возвращён",
                )
            except Exception:
                pass
    db.save_withdraws(w)
    await callback.answer("rejected")




async def on_startup():
    url = WEBAPP_URL or os.getenv("RAILWAY_PUBLIC_DOMAIN") or ""
    if url and not url.startswith("http"):
        url = "https://" + url
    if url:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Winline", web_app=WebAppInfo(url=url))
            )
            log.info("menu button set %s", url)
        except Exception as e:
            log.warning("menu: %s", e)



@app.post("/api/admin/reset_top")
async def admin_reset_top(body: AdminGive, x_telegram_id: Optional[str] = Header(None)):
    admin = require_uid(x_telegram_id)
    if not db.is_admin(admin):
        raise HTTPException(403, "admin")
    target = resolve_target(body)
    users = db.get_users()
    k = str(target)
    if k not in users or not isinstance(users.get(k), dict):
        raise HTTPException(404, "user not found")
    users[k]["deposited"] = 0
    db.save_users(users)
    return {"ok": True, "uid": target, "deposited": 0}


@app.post("/api/admin/reset_profile")
async def admin_reset_profile(body: AdminGive, x_telegram_id: Optional[str] = Header(None)):
    admin = require_uid(x_telegram_id)
    if not db.is_admin(admin):
        raise HTTPException(403, "admin")
    target = resolve_target(body)
    users = db.get_users()
    k = str(target)
    if k not in users or not isinstance(users.get(k), dict):
        raise HTTPException(404, "user not found")
    users[k]["balance"] = 0
    users[k]["deposited"] = 0
    users[k]["wager"] = 0
    users[k]["upgrade_win_streak"] = 0
    users[k]["upgrade_lose_streak"] = 0
    db.save_users(users)
    inv = db.get_inv()
    if isinstance(inv, dict):
        inv[k] = []
        db.save_inv(inv)
    try:
        mines = db.get_mines()
        if isinstance(mines, dict) and k in mines:
            del mines[k]
            db.save_mines(mines)
    except Exception:
        pass
    try:
        await bot.send_message(target, "⚠️ Профиль обнулён администратором")
    except Exception:
        pass
    return {"ok": True, "uid": target, "balance": 0, "deposited": 0, "wager": 0}



@app.post("/api/admin/reset_all_top")
async def admin_reset_all_top(x_telegram_id: Optional[str] = Header(None)):
    admin = require_uid(x_telegram_id)
    if not db.is_owner(admin):
        raise HTTPException(403, "owner only")
    users = db.get_users()
    for k, v in list(users.items()):
        if isinstance(v, dict):
            v["deposited"] = 0
    db.save_users(users)
    return {"ok": True}


@app.on_event("startup")
async def startup():
    try:
        log.info(
            "OWNER_ID=%s BOT=%s... CHANNEL=%s",
            OWNER_ID,
            (BOT_TOKEN or "")[:12],
            REQUIRED_CHANNEL or "-",
        )
        if not BOT_TOKEN:
            log.error("BOT_TOKEN пустой — задай в Railway Variables")
        async def _poll():
            try:
                log.info("polling start")
                await dp.start_polling(bot)
            except Exception:
                log.exception("polling crashed")
        asyncio.create_task(_poll())

        async def _rocket_loop():
            log.info("rocket loop start")
            # init round if needed
            try:
                r = db.get_rocket()
                if not r.get("betting_ends_at"):
                    r = _rocket_start_betting(r)
                    db.save_rocket(r)
            except Exception:
                log.exception("rocket init")
            while True:
                try:
                    _rocket_tick()
                except Exception:
                    log.exception("rocket_tick loop")
                await asyncio.sleep(0.15)

        asyncio.create_task(_rocket_loop())
        try:
            await on_startup()
        except Exception:
            log.exception("on_startup failed")
    except Exception:
        log.exception("startup failed")


@app.on_event("shutdown")
async def shutdown():
    try:
        await bot.session.close()
    except Exception:
        pass


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)

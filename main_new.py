import hashlib
import html
import json
import math
import os
import re
import signal
import smtplib
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import pytz
import yfinance as yf
from xai_sdk import Client
from xai_sdk.chat import user, system
from xai_sdk.tools import web_search, x_search

from prompts import PORTFOLIO_REVIEW_SYSTEM_PROMPT, PORTFOLIO_SYSTEM_PROMPT, SYSTEM_PROMPT


CACHE_FILE = "/tmp/last_report_hash.txt"


BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "daily-data")

STATE_FILE = f"{DATA_DIR}/portfolio.json"
PORTFOLIO_BOOK_FILE = f"{DATA_DIR}/xai_portfolio_book.json"
STOCK_HISTORY_FILE = f"{DATA_DIR}/stock_ideas_history.json"
REMOVELIST_FILE = f"{DATA_DIR}/stock_ideas_removelist.json"
LAST_RUN_FILE = f"{DATA_DIR}/last_run_time.txt"
PORTFOLIO_BOOK_URL = "https://stevenssssssss.github.io/daily-report/portfolio_book.html"

REMOVELIST_COOLDOWN_DAYS = 7
RECIPIENT = "stevieeseto@hotmail.com"
MODEL = "grok-4.3"
PORTFOLIO_INITIAL_CAPITAL = 5000.0
PORTFOLIO_POSITION_NOTIONAL = 1000.0
PORTFOLIO_MAX_POSITIONS = 5

# ==================== 新增開關 ====================
USE_XAI = True   # 設為 False 可暫時關閉 xAI 呼叫，快速測試排版
USE_PORTFOLIO_DEMO = False   # 設為 True 使用固定 Buy/Hold/Sell 數據測試 portfolio 排版

# ==================== 原有常數 ====================
TARGETS = {
    "^GSPC": "標普500", "^IXIC": "納斯達克", "^DJI": "道瓊工業",
    "^TNX": "美債10年", "^VIX": "恐慌指數",
}

X_ACCOUNTS = ["elonmusk", "GavinSBaker", "SeekingAlpha", "bloomberg"]

DEMO_PORTFOLIO_ROWS = [
    {"action": "Buy", "ticker": "NVDA", "name": "NVIDIA", "price": "132.40", "pnl": "+4.8%"},
    {"action": "Hold", "ticker": "MU", "name": "Micron", "price": "98.20", "pnl": "+1.6%"},
    {"action": "Sell", "ticker": "AMD", "name": "AMD", "price": "164.80", "pnl": "-2.3%"},
]

def trading_session_instruction(now):
    if now.weekday() >= 5:
        return "週末休市模式：可復盤並為下週準備 watchlist 和潛在買點，允許提出高 conviction 的買入建議。"
    
    if now.hour == 10:
        return "HKT 10:00 美股盤後/盤前準備：只針對美股隔夜動向、NASDAQ 與 DJI 提出 watchlist 或買入建議。"
    
    if now.hour == 16:
        return "HKT 16:30 美股盤前準備：總結美股、NASDAQ 與 DJI，並可積極制定今晚美股 buy/hold/sell 決策。"
    
    if now.hour == 23 or (now.hour < 5):   # 美股交易時段
        return "美股交易活躍時段：可根據即時市場訊號積極提出 buy/hold/sell 決策。"
    
    return "一般交易時段：可正常提出投資決策，視市場訊號強弱決定積極度。"

def build_prompt(today, quotes, status, session_note, time_note, removelist_text, portfolio_text):
    return f"""當前香港時間：{today}
市場狀態：{status}
交易決策時段：{session_note}
最新報價：{quotes}
時間範圍：{time_note}
剔除/冷卻狀態：{removelist_text}
目前模擬 portfolio 狀態：{portfolio_text}"""


def build_portfolio_prompt(today, report, portfolio_text, watchlist_text, session_note, removelist_text):
    signals = market_signal_summary(report)
    return f"""當前香港時間：{today}
交易決策時段：{session_note}
市場訊號：{json.dumps(signals, ensure_ascii=False)}
候選監察名單：{watchlist_text}
剔除/冷卻狀態：{removelist_text}
目前模擬 portfolio 狀態：{portfolio_text}"""


def market_signal_summary(report):
    return {
        "summary": report.get("summary"),
        "executive_brief": report.get("executive_brief"),
        "market_dashboard": report.get("market_dashboard"),
        "x_consensus": report.get("x_consensus"),
    } if isinstance(report, dict) else {}


def portfolio_review_state(book):
    if not isinstance(book, dict):
        return "{}"
    return json.dumps({
        "portfolio": json.loads(portfolio_prompt_state(book)),
        "recent_trade_log": (book.get("trade_log") or [])[-8:],
        "recent_closed_trades": (book.get("closed_trades") or [])[-5:],
        "pending_orders": book.get("pending_orders") or [],
    }, ensure_ascii=False)


def build_portfolio_review_prompt(today, report, book, session_note):
    decisions = report.get("portfolio_decisions", {}) if isinstance(report, dict) else {}
    return f"""當前香港時間：{today}
交易決策時段：{session_note}
壓縮市況：{json.dumps(market_signal_summary(report), ensure_ascii=False)}
今日 portfolio orders：{json.dumps(decisions, ensure_ascii=False)}
目前 portfolio 與最近交易：{portfolio_review_state(book)}

請檢討今日策略質素、目前持倉風險、過去交易是否暴露系統性問題，並提出下次可執行的優化方向。"""


last_token_usage = {"prompt": 0, "completion": 0, "cached": 0}
total_token_usage = {"prompt": 0, "completion": 0, "cached": 0}


def hk_now():
    return datetime.now(pytz.timezone("Asia/Hong_Kong"))


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    state.setdefault("last_checked_time", "")
    state.setdefault("last_successful_email_time", "")
    state.setdefault("latest_summary", "")
    state.setdefault("last_status", "initialized")
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_json_file(path, default):
    try:
        if not os.path.exists(path):
            print(f"📁 檔案不存在，將使用預設值並在下次儲存時建立: {path}")
            return default
        
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if data else default
    except Exception as e:
        print(f"⚠️ 讀取 {path} 失敗: {type(e).__name__} - {e}")
        return default


def sanitize_json_value(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: sanitize_json_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_json_value(v) for v in value]
    return value


def save_json_file(path, data):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sanitize_json_value(data), f, ensure_ascii=False, indent=2, allow_nan=False)
        print(f"✅ 成功儲存檔案: {path}")
    except Exception as e:
        print(f"❌ 儲存 {path} 失敗: {type(e).__name__} - {e}")


def last_run_instruction(state):
    try:
        with open(LAST_RUN_FILE, "r", encoding="utf-8") as f:
            last_run = f.read().strip()
    except Exception:
        last_run = state.get("last_successful_email_time", "").strip()
    return f"上次報告時間為 {last_run}，請重點分析此後發布的新貼文。" if last_run else "請抓取過去 8 小時內的所有重點貼文。"


def quote_format(ticker, close):
    if close is None:
        return "--"
    if ticker in {"BTC-USD", "ETH-USD"}:
        return f"{close:,.0f}"
    if ticker in {"^TNX", "^VIX"}:
        return f"{close:.2f}"
    if "USD" in ticker or ticker in {"JPY=X", "DX-Y.NYB"}:
        return f"{close:.4f}"
    return f"{close:,.2f}"


def fetch_quotes():
    quote_text, rows = {}, []
    for ticker, name in TARGETS.items():
        try:
            hist = yf.Ticker(ticker).history(period="5d")
            if len(hist) < 2:
                quote_text[name] = "N/A"
                continue
            close, prev = hist["Close"].iloc[-1], hist["Close"].iloc[-2]
            pct = (close - prev) / prev * 100
            price = quote_format(ticker, close)
            quote_text[name] = f"{price} ({pct:+.2f}%) [時間:{hist.index[-1].strftime('%m-%d %H:%M')}]"
            rows.append({"name": name, "price": price, "pct": pct})
        except Exception as e:
            print(f"{ticker} 行情讀取失敗：{e}")
            quote_text[name] = "Err"
    return " | ".join(f"{k}: {v}" for k, v in quote_text.items()), rows


def normalize_ticker(ticker):
    symbol = str(ticker or "").strip().upper()
    if symbol.startswith("TPE:"):
        return f"{symbol.split(':', 1)[1]}.TW"
    for prefix in ("NASDAQ:", "NYSE:"):
        symbol = symbol.replace(prefix, "")
    return symbol


def is_allowed_us_equity_ticker(ticker):
    raw = str(ticker or "").strip().upper()
    symbol = normalize_ticker(raw)
    if not symbol or symbol == "N/A":
        return False
    if raw.startswith(("TPE:", "HKEX:", "HKG:", "SHA:", "SHE:", "TSE:")):
        return False
    if symbol.startswith("^") or symbol.endswith(("-USD", "=X", "=F", ".TW", ".HK", ".SS", ".SZ", ".T")):
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol))


def is_valid_price(price):
    return isinstance(price, (int, float)) and math.isfinite(float(price)) and float(price) > 0


def get_latest_price(ticker):
    """改良版：更穩定的價格獲取"""
    symbol = normalize_ticker(ticker)
    if not symbol or symbol == "N/A":
        return None

    try:
        ticker_obj = yf.Ticker(symbol)
        # 優先使用 history
        hist = ticker_obj.history(period="5d", auto_adjust=True)
        
        if len(hist) > 0:
            prices = hist["Close"].dropna()
            if len(prices) > 0:
                price = float(prices.iloc[-1])
                if is_valid_price(price):
                    print(f"✅ {symbol} 最新價格: ${price:.4f} (history)")
                    return price
    except Exception as e:
        print(f"⚠️ {symbol} history 失敗: {e}")

    # 備用方案：使用 info
    try:
        info = ticker_obj.info
        for key in ['currentPrice', 'regularMarketPrice', 'previousClose']:
            if key in info and info[key] is not None:
                price = float(info[key])
                if is_valid_price(price):
                    print(f"✅ {symbol} 最新價格: ${price:.4f} (info.{key})")
                    return price
    except Exception as e:
        print(f"⚠️ {symbol} info 失敗: {e}")

    print(f"❌ {symbol} 無法獲取價格")
    return None


def get_latest_quote(ticker):
    symbol = normalize_ticker(ticker)
    if not symbol or symbol == "N/A":
        return None, None

    try:
        hist = yf.Ticker(symbol).history(period="5d", auto_adjust=True)
        prices = hist["Close"].dropna() if len(hist) > 0 else []
        if len(prices) > 0:
            price = float(prices.iloc[-1])
            pct = None
            if len(prices) >= 2:
                prev = float(prices.iloc[-2])
                if is_valid_price(prev):
                    pct = (price - prev) / prev * 100
            if is_valid_price(price):
                return price, pct
    except Exception as e:
        print(f"⚠️ {symbol} quote 失敗: {e}")

    return get_latest_price(symbol), None


def load_portfolio_book():
    book = load_json_file(PORTFOLIO_BOOK_FILE, {})
    if not isinstance(book, dict):
        book = {}
    book.setdefault("initial_capital", PORTFOLIO_INITIAL_CAPITAL)
    book.setdefault("cash", PORTFOLIO_INITIAL_CAPITAL)
    book.setdefault("positions", {})
    book.setdefault("closed_trades", [])
    book.setdefault("trade_log", [])
    book.setdefault("pending_orders", [])
    return book


def save_portfolio_book(book):
    save_json_file(PORTFOLIO_BOOK_FILE, book)


def normalize_portfolio_position_cost(pos):
    """Use invested/shares as the source of truth for existing position cost."""
    if not isinstance(pos, dict):
        return 0.0

    shares = float(pos.get("shares", 0) or 0)
    invested = float(pos.get("invested", 0) or 0)
    avg_cost = float(pos.get("avg_cost") or pos.get("buy_price_confirmed") or 0)

    if shares > 0 and invested > 0:
        corrected_cost = invested / shares
        if avg_cost <= 0 or abs(avg_cost - corrected_cost) > 0.01:
            pos["avg_cost"] = corrected_cost
            pos["buy_price_confirmed"] = corrected_cost
        return corrected_cost

    if avg_cost > 0:
        pos["avg_cost"] = avg_cost
        pos.setdefault("buy_price_confirmed", avg_cost)
    return avg_cost


def normalize_portfolio_book_costs(book):
    positions = book.get("positions", {}) if isinstance(book, dict) else {}
    if not isinstance(positions, dict):
        return book
    for pos in positions.values():
        normalize_portfolio_position_cost(pos)
    return book


def portfolio_market_value(book):
    total = 0.0
    positions = book.get("positions", {})
    if not isinstance(positions, dict):
        return total
    for ticker, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        normalize_portfolio_position_cost(pos)
        price = get_latest_price(ticker)
        if price is None:
            price = pos.get("last_price", pos.get("avg_cost", 0))
        shares = float(pos.get("shares", 0) or 0)
        total += shares * float(price or 0)
        pos["last_price"] = price
    return total


def portfolio_prompt_state(book):
    positions = []
    for ticker, pos in (book.get("positions") or {}).items():
        price = get_latest_price(ticker)
        if price is None:
            price = pos.get("last_price", pos.get("avg_cost"))
        avg_cost = normalize_portfolio_position_cost(pos)
        shares = float(pos.get("shares", 0) or 0)
        value = shares * float(price or 0)
        pnl_pct = ((float(price) - avg_cost) / avg_cost * 100) if price and avg_cost else 0
        positions.append({
            "ticker": ticker,
            "name": pos.get("name", ""),
            "cost": round(float(pos.get("invested", 0) or 0), 2),
            "value": round(value, 2),
            "pnl_pct": round(pnl_pct, 2),
            "opened_at": pos.get("opened_at", ""),
            "thesis": str(pos.get("reason", ""))[:120],
        })
    return json.dumps({
        "initial_capital": book.get("initial_capital", PORTFOLIO_INITIAL_CAPITAL),
        "cash": round(float(book.get("cash", 0) or 0), 2),
        "max_positions": PORTFOLIO_MAX_POSITIONS,
        "default_buy_usd": PORTFOLIO_POSITION_NOTIONAL,
        "positions": positions,
    }, ensure_ascii=False)


def is_us_market_open(now):
    ny = now.astimezone(pytz.timezone("America/New_York"))
    minutes = ny.hour * 60 + ny.minute
    return ny.weekday() < 5 and 570 <= minutes < 960


def apply_portfolio_decisions(book, report, now):
    """買入時強制記錄正確價格"""
    decisions = report.get("portfolio_decisions", {}) if isinstance(report, dict) else {}
    orders = decisions.get("orders", []) if isinstance(decisions, dict) else []
    if not isinstance(orders, list):
        orders = []

    positions = book.setdefault("positions", {})
    closed_trades = book.setdefault("closed_trades", [])
    trade_log = book.setdefault("trade_log", [])
    pending_orders = book.setdefault("pending_orders", [])
    cash = float(book.get("cash", PORTFOLIO_INITIAL_CAPITAL) or 0)
    now_text = now.strftime("%Y-%m-%d %H:%M")
    can_trade = is_us_market_open(now)
    if can_trade and pending_orders:
        orders = pending_orders + orders
        book["pending_orders"] = []
        pending_orders = book["pending_orders"]
    orders = sorted(
        orders,
        key=lambda order: {"sell": 0, "buy": 1, "hold": 2}.get(str(order.get("action") or "").lower().strip(), 3)
    )

    for order in orders:
        if not isinstance(order, dict):
            continue
        ticker = normalize_ticker(order.get("ticker"))
        action = str(order.get("action") or "").lower().strip()
        if not ticker or ticker == "N/A":
            continue

        price = get_latest_price(ticker)

        if action == "sell" and ticker in positions and (can_trade or order.get("force")):
            # ... (賣出邏輯保持不變)
            pos = positions.pop(ticker)
            shares = float(pos.get("shares", 0) or 0)
            if price is None:
                price = pos.get("last_price", pos.get("avg_cost", 0))
            proceeds = shares * float(price or 0)
            invested = float(pos.get("invested", 0) or 0)
            cash += proceeds
            realized_pnl = proceeds - invested
            closed_trades.append({
                "ticker": ticker,
                "name": pos.get("name", ""),
                "opened_at": pos.get("opened_at", ""),
                "closed_at": now_text,
                "avg_cost": pos.get("avg_cost"),
                "sell_price": price,
                "invested": round(invested, 2),
                "proceeds": round(proceeds, 2),
                "pnl": round(realized_pnl, 2),
                "reason": order.get("reason", ""),
            })
            trade_log.append({
                "time": now_text,
                "action": "sell",
                "ticker": ticker,
                "price": round(float(price or 0), 4),
                "shares": round(shares, 6),
                "amount": round(proceeds, 2),
                "invested": round(invested, 2),
                "pnl": round(realized_pnl, 2),
                "cash_after": round(cash, 2),
                "reason": order.get("reason", ""),
            })

        elif action in {"buy", "sell"} and not can_trade:
            if ticker in positions:
                positions[ticker]["last_decision"] = "hold"
                positions[ticker]["last_reason"] = f"非美股交易時段，原建議 {action} 未執行：{order.get('reason', '')}"
                if action == "sell" and not order.get("force"):
                    pending_orders[:] = [
                        pending for pending in pending_orders
                        if normalize_ticker(pending.get("ticker")) != ticker
                    ]
                    pending_orders.append({
                        "ticker": ticker,
                        "action": "sell",
                        "reason": order.get("reason", ""),
                        "created_at": now_text,
                    })
                if price:
                    positions[ticker]["last_price"] = price
                pos = positions[ticker]
                shares = float(pos.get("shares", 0) or 0)
                avg_cost = normalize_portfolio_position_cost(pos)
                current_price = float(price or pos.get("last_price", avg_cost) or 0)
                value = shares * current_price
                invested = float(pos.get("invested", 0) or 0)
                trade_log.append({
                    "time": now_text,
                    "action": "hold",
                    "ticker": ticker,
                    "price": round(current_price, 4),
                    "shares": round(shares, 6),
                    "value": round(value, 2),
                    "unrealized_pnl": round(value - invested, 2),
                    "cash_after": round(cash, 2),
                    "reason": positions[ticker]["last_reason"],
                })
            else:
                print(f"⏸️ 非美股交易時段，跳過 {ticker} {action}")

        elif action == "hold" and ticker in positions:
            pending_orders[:] = [
                pending for pending in pending_orders
                if normalize_ticker(pending.get("ticker")) != ticker
            ]
            positions[ticker]["last_decision"] = "hold"
            positions[ticker]["last_reason"] = order.get("reason", "")
            if price:
                positions[ticker]["last_price"] = price
            pos = positions[ticker]
            shares = float(pos.get("shares", 0) or 0)
            avg_cost = normalize_portfolio_position_cost(pos)
            current_price = float(price or pos.get("last_price", avg_cost) or 0)
            value = shares * current_price
            invested = float(pos.get("invested", 0) or 0)
            trade_log.append({
                "time": now_text,
                "action": "hold",
                "ticker": ticker,
                "price": round(current_price, 4),
                "shares": round(shares, 6),
                "value": round(value, 2),
                "unrealized_pnl": round(value - invested, 2),
                "cash_after": round(cash, 2),
                "reason": order.get("reason", ""),
            })

        elif action == "buy" and ticker not in positions and len(positions) < PORTFOLIO_MAX_POSITIONS and can_trade:
            allocation = min(float(order.get("allocation_usd") or PORTFOLIO_POSITION_NOTIONAL), 
                           PORTFOLIO_POSITION_NOTIONAL, cash)
            if allocation <= 0 or price is None or price <= 0:
                print(f"❌ {ticker} 買入失敗：價格無效")
                continue

            shares = allocation / price
            cash -= allocation
            
            print(f"🛒 BUY {ticker} | 價格 ${price:.4f} | 股數 {shares:.4f} | 金額 ${allocation:.2f}")

            stop_price = parse_stop_price(order.get("stop"), price)
            target_price = parse_target_price(order.get("target"))
            trailing_stop_pct = 0.05

            positions[ticker] = {
                "ticker": ticker,
                "name": order.get("name", ticker),
                "shares": shares,
                "avg_cost": price,           # ← 關鍵修正
                "invested": allocation,
                "opened_at": now_text,
                "last_price": price,
                "last_decision": "buy",
                "reason": order.get("reason", ""),
                "stop": order.get("stop", ""),
                "target": order.get("target", ""),
                "trailing_stop": order.get("trailing_stop", "獲利超過25%後，最高價回調5%止賺"),
                "stop_price": stop_price,
                "target_price": target_price,
                "trailing_stop_pct": trailing_stop_pct,
                "highest_price": price,
                "buy_price_confirmed": price   # 備份
            }
            trade_log.append({
                "time": now_text,
                "action": "buy",
                "ticker": ticker,
                "price": round(float(price), 4),
                "shares": round(shares, 6),
                "amount": round(allocation, 2),
                "cash_after": round(cash, 2),
                "reason": order.get("reason", ""),
                "stop": order.get("stop", ""),
            })

    book["cash"] = round(cash, 2)
    book["last_updated_at"] = now_text
    normalize_portfolio_book_costs(book)
    return book


def portfolio_snapshot_rows(book):
    """修正後的持倉顯示"""
    rows = []
    for ticker, pos in (book.get("positions") or {}).items():
        # 優先使用 invested / shares 修正後的買入成本
        avg_cost = normalize_portfolio_position_cost(pos)
        
        # 最新市場價格
        current_price = get_latest_price(ticker)
        if current_price is None:
            current_price = pos.get("last_price", avg_cost)

        shares = float(pos.get("shares", 0) or 0)
        value = shares * float(current_price or 0)
        pnl_amount = value - float(pos.get("invested", 0) or 0)
        
        pnl_pct = ((float(current_price) - avg_cost) / avg_cost * 100) if current_price and avg_cost > 0 else 0
        
        action = str(pos.get("last_decision") or "hold").title()

        rows.append({
            "action": action,
            "ticker": ticker,
            "shares_text": f"{shares:.4f}",
            "avg_cost_text": f"${avg_cost:,.2f}",
            "value_text": f"${value:,.2f}",
            "current_price_text": f"${float(current_price or 0):,.2f}",
            "pnl": f"{pnl_pct:+.2f}%",
            "pnl_amount_text": f"{pnl_amount:+,.2f}",
        })
    return rows


def portfolio_snapshot_summary(book):
    initial_capital = float(book.get("initial_capital", PORTFOLIO_INITIAL_CAPITAL) or PORTFOLIO_INITIAL_CAPITAL)
    cash = round(float(book.get("cash", 0) or 0), 2)
    market_value = round(portfolio_market_value(book), 2)
    total_assets = round(cash + market_value, 2)
    total_return_pct = ((total_assets - initial_capital) / initial_capital * 100) if initial_capital else 0
    return {
        "cash": cash,
        "market_value": market_value,
        "total_assets": total_assets,
        "total_return_pct": round(total_return_pct, 2),
    }


def extract_number(text):
    match = re.search(r"\d+(?:\.\d+)?", str(text or "").replace(",", ""))
    return float(match.group(0)) if match else None


def parse_stop_price(value, entry_price=None):
    if isinstance(value, (int, float)) and is_valid_price(value):
        return float(value)

    text = str(value or "")
    number = extract_number(text)
    if number is None:
        return None

    if "%" in text and entry_price and is_valid_price(entry_price):
        return round(float(entry_price) * (1 - number / 100), 4)
    return number


def parse_target_price(value):
    if isinstance(value, (int, float)) and is_valid_price(value):
        return float(value)
    return extract_number(value)


def parse_trailing_stop_pct(value):
    if isinstance(value, (int, float)) and float(value) > 0:
        pct = float(value)
        return pct / 100 if pct > 1 else pct

    text = str(value or "")
    numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))]
    if not numbers:
        return None

    pct = max(numbers) if "%" in text or "回撤" in text else numbers[0]
    return pct / 100 if pct > 1 else pct


def update_position_risk_state(book):
    positions = book.get("positions", {}) if isinstance(book, dict) else {}
    if not isinstance(positions, dict):
        return

    for ticker, pos in positions.items():
        if not isinstance(pos, dict):
            continue

        price = get_latest_price(ticker)
        if price is None:
            price = pos.get("last_price", pos.get("avg_cost"))
        if not is_valid_price(price):
            continue

        pos["last_price"] = float(price)
        prev_high = pos.get("highest_price")
        if is_valid_price(prev_high):
            pos["highest_price"] = max(float(prev_high), float(price))
        else:
            pos["highest_price"] = float(price)


def apply_portfolio_risk_rules(book):
    orders = []
    positions = book.get("positions", {}) if isinstance(book, dict) else {}
    if not isinstance(positions, dict):
        return orders

    for ticker, pos in positions.items():
        if not isinstance(pos, dict):
            continue

        price = pos.get("last_price")
        if not is_valid_price(price):
            continue

        price = float(price)
        avg_cost = normalize_portfolio_position_cost(pos)
        stop_price = pos.get("stop_price")
        trailing_stop_pct = 0.05
        highest_price = pos.get("highest_price", price)

        reason = None
        sell_type = None
        if is_valid_price(stop_price) and price <= float(stop_price):
            sell_type = "stop"
            reason = f"硬性止損觸發：現價 {price:.2f} <= stop_price {float(stop_price):.2f}"
        elif trailing_stop_pct and is_valid_price(highest_price) and avg_cost > 0:
            gain_pct = (price - avg_cost) / avg_cost
            trailing_trigger = float(highest_price) * (1 - float(trailing_stop_pct))
            if gain_pct > 0.25 and price <= trailing_trigger:
                sell_type = "trailing"
                reason = f"Trailing stop 觸發：獲利超過25%，現價 {price:.2f} <= 最高價回調5%的 {trailing_trigger:.2f}"

        if reason:
            orders.append({
                "ticker": ticker,
                "action": "sell",
                "reason": reason,
                "sell_type": sell_type,
                "force": True,
            })

    return orders


def watchlist_buy_candidates(watchlist):
    candidates = set()
    groups = []
    if isinstance(watchlist, dict):
        groups = list(watchlist.get("new", [])) + list(watchlist.get("continued", []))
    elif isinstance(watchlist, list):
        groups = watchlist

    for item in groups:
        if not isinstance(item, dict):
            continue
        ticker = normalize_ticker(item.get("ticker"))
        if not is_allowed_us_equity_ticker(ticker):
            continue
        status = str(item.get("status") or "").lower()
        conviction = item.get("conviction_score")
        catalyst = item.get("catalyst_score")
        technical = item.get("technical_score")
        high_score = (
            isinstance(conviction, (int, float)) and conviction >= 75
            and isinstance(catalyst, (int, float)) and catalyst >= 60
            and isinstance(technical, (int, float)) and technical >= 60
        )
        if status == "strong_buy" or high_score:
            candidates.add(ticker)
    return candidates


def filter_portfolio_buy_orders(report, watchlist):
    decisions = report.get("portfolio_decisions") if isinstance(report, dict) else None
    orders = decisions.get("orders") if isinstance(decisions, dict) else None
    if not isinstance(orders, list):
        return

    buy_candidates = watchlist_buy_candidates(watchlist)
    filtered = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        action = str(order.get("action") or "").lower().strip()
        ticker = normalize_ticker(order.get("ticker"))
        if action == "buy" and ticker not in buy_candidates:
            print(f"⏸️ 跳過 {ticker} buy：不在 strong_buy / 高分 watchlist 候選中")
            continue
        filtered.append(order)
    decisions["orders"] = filtered


def active_removelist(now):
    removelist = load_json_file(REMOVELIST_FILE, [])
    active = []

    for item in removelist:
        try:
            removed_at = datetime.fromisoformat(item.get("removed_at"))
        except Exception:
            active.append(item)
            continue

        if now - removed_at <= timedelta(days=item.get("cooldown_days", REMOVELIST_COOLDOWN_DAYS)):
            active.append(item)

    if len(active) != len(removelist):
        save_json_file(REMOVELIST_FILE, active)
    return active


def removelist_note(now):
    active = active_removelist(now)
    if not active:
        return "目前沒有短期冷卻名單。"

    items = []
    for item in active:
        ticker = normalize_ticker(item.get("ticker"))
        reason = item.get("reason", "短期移出觀察")
        removed_at = item.get("removed_at", "")
        items.append(f"{ticker}（{reason}，removed_at={removed_at}）")
    return "短期冷卻名單：" + "；".join(items)


def market_status(now):
    ny = datetime.now(pytz.timezone("America/New_York"))
    us_open = 570 <= ny.hour * 60 + ny.minute < 960 and ny.weekday() < 5
    try:
        hsi = yf.Ticker("^HSI").history(period="1d")
        asia_open = len(hsi) > 0 and hsi.index[-1].date() == now.date()
    except Exception:
        asia_open = False

    if now.weekday() >= 5 or (not asia_open and not us_open):
        return "今天是週末/假期時段，主要股市多為休市，數據可能是前一交易日收盤。"
    if 9 <= now.hour < 16 and asia_open:
        return "亞洲市場交易中，美股為上一交易日收盤數據。"
    if us_open:
        return "美股交易中，亞洲市場為今日收盤或最近更新數據。"
    return "目前為平日盤前/盤後時段，主要市場多為最近收盤數據。"


def fallback_report():
    return {
        "subject": "市場資料更新中",
        "summary": "市場資料暫時更新中，短線建議降低交易頻率。",
        "executive_brief": [
            "xAI 或資料源暫時無法完成分析，今日報告改以行情表作為主要參考。",
            "在缺乏完整新聞與社群訊號確認前，避免追逐高波動資產。",
            "等待下一次數據更新後，再重新評估美股、亞太與加密市場方向。",
        ],
        "market_dashboard": {
            "us": "美股資料更新中，暫不作方向判斷。",
            "asia": "亞太資料更新中，留意港股與A股成交能否確認方向。",
            "macro": "宏觀資料更新中，重點觀察美元、美債收益率與黃金反應。",
            "crypto": "加密資產維持高波動，短線宜控制槓桿與倉位。",
        },
        "x_consensus": ["X 平台資料暫未完成整理。"],
        "stock_ideas": [
            {
                "ticker": "N/A",
                "name": "資料更新中",
                "sector": "N/A",
                "reason": "暫不提供個股推介。",
                "technical": "N/A",
                "entry": "N/A",
                "stop": "N/A",
                "risk": "資訊不足。",
            }
        ],
    }


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    if not text.startswith("{"):
        text = text[text.find("{") : text.rfind("}") + 1]
    return json.loads(text)


def timeout_handler(signum, frame):
    raise TimeoutError("AI 回應超時")


def ask_xai_with_system(prompt, system_prompt, purpose):
    if not USE_XAI:
        print(f"USE_XAI = False，已跳過 {purpose} xAI 呼叫")
        return fallback_report()

    signal.signal(signal.SIGALRM, timeout_handler)
    if not os.environ.get("API_KEY"):
        raise RuntimeError("缺少 GitHub Secret: API_KEY")

    client = Client(
        api_key=os.environ.get("API_KEY"),
        metadata=(("x-grok-conv-id", "daily_market_morning_note_v2"),)
    )

    global last_token_usage, total_token_usage
    
    for attempt in range(3):
        try:
            chat = client.chat.create(model=MODEL, tools=[web_search(), x_search()], temperature=0.1)
            
            chat.append(system(system_prompt))
            chat.append(user(prompt))
            
            print(f"正在呼叫 xAI grok-4.3 {purpose}（已啟用 Prompt Caching）...")
            signal.alarm(240)
            response = chat.sample()
            signal.alarm(0)
            
            usage = getattr(response, 'usage', None)
            last_token_usage = {"prompt": 0, "completion": 0, "cached": 0}
            
            if usage:
                last_token_usage["prompt"] = getattr(usage, 'prompt_tokens', 0)
                last_token_usage["completion"] = getattr(usage, 'completion_tokens', 0)
                last_token_usage["cached"] = getattr(usage, 'cached_prompt_text_tokens', 0)
            for key in total_token_usage:
                total_token_usage[key] += last_token_usage.get(key, 0)
            
            print(f"✅ Tokens → Prompt: {last_token_usage['prompt']} | Completion: {last_token_usage['completion']} | Cached: {last_token_usage['cached']}")
            print(f"xAI {purpose}成功！")
            return parse_json(response.content)
        except Exception as e:
            signal.alarm(0)
            print(f"第 {attempt + 1} 次失敗：{type(e).__name__} - {e}")
            if attempt < 2:
                time.sleep(8)

    print(f"已使用 fallback：{purpose}")
    last_token_usage = {"prompt": 0, "completion": 0, "cached": 0}
    return fallback_report()


def ask_xai(prompt):
    return ask_xai_with_system(prompt, SYSTEM_PROMPT, "市場分析")


def fallback_portfolio_decisions(book):
    orders = []
    for ticker in (book.get("positions") or {}).keys():
        orders.append({"ticker": ticker, "action": "hold", "reason": "portfolio prompt 失敗，保守維持持倉"})
    return {"portfolio_decisions": {"orders": orders}}


def ask_portfolio_manager(prompt, book):
    if not USE_XAI:
        return fallback_portfolio_decisions(book)
    result = ask_xai_with_system(prompt, PORTFOLIO_SYSTEM_PROMPT, "portfolio 決策")
    decisions = result.get("portfolio_decisions") if isinstance(result, dict) else None
    orders = decisions.get("orders") if isinstance(decisions, dict) else None
    if not isinstance(orders, list):
        return fallback_portfolio_decisions(book)
    return result


def fallback_portfolio_review():
    return {
        "portfolio_review": {
            "strategy_health": "warning",
            "summary": "portfolio review prompt 失敗，今日只保留交易決策紀錄，暫不調整策略。",
            "what_worked": [],
            "mistakes_or_risks": ["review 資料不足或 AI 回應失敗，避免用未驗證結論影響策略。"],
            "next_improvements": ["下次重新檢查市況、持倉 thesis、最近交易紀錄。"],
            "risk_notes": [],
        }
    }


def ask_portfolio_review(prompt):
    if not USE_XAI:
        return fallback_portfolio_review()
    result = ask_xai_with_system(prompt, PORTFOLIO_REVIEW_SYSTEM_PROMPT, "portfolio review")
    review = result.get("portfolio_review") if isinstance(result, dict) else None
    if not isinstance(review, dict):
        return fallback_portfolio_review()
    return result


def esc(value):
    return html.escape(str(value or "").strip())


def li(items):
    return "".join(f"<li>{esc(item)}</li>" for item in (items if isinstance(items, list) else [items]) if str(item).strip())


def portfolio_review_html(review):
    if not isinstance(review, dict):
        return ""
    health = str(review.get("strategy_health") or "").strip()
    summary = str(review.get("summary") or "").strip()
    parts = [
        "<h2>Portfolio Strategy Review</h2>",
        f"<div class=\"box\"><b>策略狀態：</b>{esc(health)}<br><b>總結：</b>{esc(summary)}</div>",
    ]
    for title, items in (
        ("有效地方", review.get("what_worked")),
        ("問題 / 風險", review.get("mistakes_or_risks")),
        ("下次優化", review.get("next_improvements")),
        ("風險備註", review.get("risk_notes")),
    ):
        rendered = li(items or [])
        if rendered:
            parts.append(f"<h3 style=\"font-size:15px;margin:14px 0 6px;\">{esc(title)}</h3><ul>{rendered}</ul>")
    return "".join(parts)


def quote_table(rows):
    return "".join(
        f"<tr><td>{esc(r['name'])}</td><td align='right'>{esc(r['price'])}</td><td align='right' class='{'up' if r['pct'] >= 0 else 'down'}'>{r['pct']:+.2f}%</td></tr>"
        for r in rows
    )


def enrich_stock_ideas(items, history):
    if isinstance(items, dict):
        new_list = enrich_stock_ideas(items.get("new", []), history)
        continued_list = enrich_stock_ideas(items.get("continued", []), history)
        return {"new": new_list, "continued": continued_list}

    if not isinstance(items, list):
        return items

    enriched = []
    for item in items:
        if not isinstance(item, dict):
            enriched.append(item)
            continue

        ticker_raw = str(item.get("ticker") or "").strip()
        ticker_norm = normalize_ticker(ticker_raw)

        old = history.get(ticker_norm, {})
        current_price, current_pct = get_latest_quote(ticker_raw)

        item = dict(item)

        item["first_recommended_at"] = item.get("first_recommended_at") or old.get("first_recommended_at", "本期新增")
        item["last_recommended_at"] = item.get("last_recommended_at") or old.get("last_recommended_at", "本期新增")

        item["current_price"] = current_price
        item["current_pct"] = current_pct
        item["first_price"] = old.get("first_price", item.get("first_price"))
        item["performance_pct"] = None

        first_price = item.get("first_price")
        if first_price is not None and current_price is not None:
            item["performance_pct"] = round((current_price - first_price) / first_price * 100, 2)

        enriched.append(item)

    return enriched


def update_stock_history(items, now):
    if not isinstance(items, list):
        return

    history = load_json_file(STOCK_HISTORY_FILE, {})
    removelist = active_removelist(now)
    removelist_tickers = {normalize_ticker(item.get("ticker")) for item in removelist}
    now_text = now.strftime("%Y-%m-%d %H:%M")

    for item in items:
        if not isinstance(item, dict):
            continue

        ticker = normalize_ticker(item.get("ticker"))
        if not is_allowed_us_equity_ticker(item.get("ticker")):
            continue

        status = str(item.get("status") or "").lower().strip()
        if status == "remove":
            removed = history.pop(ticker, None)
            if ticker not in removelist_tickers:
                removelist.append({
                    "ticker": ticker,
                    "name": item.get("name", (removed or {}).get("name", "")),
                    "reason": item.get("reason", "watchlist status=remove"),
                    "removed_at": now.isoformat(),
                    "cooldown_days": REMOVELIST_COOLDOWN_DAYS,
                    "first_price": (removed or {}).get("first_price"),
                    "sell_price": (removed or {}).get("last_price"),
                    "performance_pct": None,
                })
                removelist_tickers.add(ticker)
            continue

        current_price = get_latest_price(ticker)
        record = history.get(ticker, {})
        if not record:
            record = {
                "ticker": ticker,
                "name": item.get("name", ""),
                "first_recommended_at": now_text,
                "first_price": current_price,
                "recommend_count": 0,
            }

        record.update({
            "name": item.get("name", record.get("name", "")),
            "sector": item.get("sector", record.get("sector", "")),
            "status": item.get("status", record.get("status", "watch")),
            "conviction_score": item.get("conviction_score", record.get("conviction_score")),
            "catalyst_score": item.get("catalyst_score", record.get("catalyst_score")),
            "technical_score": item.get("technical_score", record.get("technical_score")),
            "sentiment_score": item.get("sentiment_score", record.get("sentiment_score")),
            "risk_score": item.get("risk_score", record.get("risk_score")),
            "last_review_reason": item.get("reason", record.get("last_review_reason", "")),
            "last_recommended_at": now_text,
            "last_price": current_price,
            "stop": item.get("stop", record.get("stop", "")),
            "recommend_count": int(record.get("recommend_count", 0)) + 1,
        })
        history[ticker] = record

        stop_price = extract_number(item.get("stop"))
        if current_price is not None and stop_price is not None and current_price <= stop_price and ticker not in removelist_tickers:
            performance_pct = None
            first_price = record.get("first_price")
            if isinstance(first_price, (int, float)) and isinstance(current_price, (int, float)):
                performance_pct = round((current_price - first_price) / first_price * 100, 2)
            removelist.append({
                "ticker": ticker,
                "name": record.get("name", item.get("name", "")),
                "reason": "跌穿止蝕位",
                "removed_at": now.isoformat(),
                "cooldown_days": REMOVELIST_COOLDOWN_DAYS,
                "first_price": first_price,
                "sell_price": current_price,
                "performance_pct": performance_pct,
            })
            removelist_tickers.add(ticker)

    save_json_file(STOCK_HISTORY_FILE, history)
    save_json_file(REMOVELIST_FILE, removelist)


def display_date(today):
    try:
        dt = datetime.strptime(str(today), "%Y-%m-%d %H:%M")
        return f"{dt.month}/{dt.day}/{dt.year} {dt.strftime('%H:%M')}"
    except Exception:
        return esc(today)


def portfolio_rows_from_stock_ideas(items, sell_items=None):
    rows = []
    if not isinstance(items, dict):
        return rows

    if isinstance(items.get("portfolio_rows"), list):
        return items.get("portfolio_rows")

    max_active_positions = max(1, PORTFOLIO_INITIAL_CAPITAL // PORTFOLIO_POSITION_NOTIONAL)

    for action, group_name in (("Buy", "new"), ("Hold", "continued")):
        for item in items.get(group_name, []):
            if len(rows) >= max_active_positions:
                break
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or "").replace("NASDAQ:", "").strip()
            if not ticker or ticker == "N/A":
                continue
            performance = item.get("performance_pct")
            pnl = f"{performance:+.2f}%" if isinstance(performance, (int, float)) else "新推"
            trade_price = item.get("first_price") if item.get("first_price") is not None else item.get("current_price")
            rows.append({
                "action": item.get("action", action),
                "ticker": ticker,
                "name": item.get("name", ""),
                "price": quote_format(ticker, trade_price) if isinstance(trade_price, (int, float)) else trade_price or "--",
                "pnl": pnl,
            })

    for item in sell_items or []:
        if not isinstance(item, dict):
            continue
        ticker = normalize_ticker(item.get("ticker"))
        if not ticker or ticker == "N/A":
            continue
        sell_price = item.get("sell_price") if item.get("sell_price") is not None else item.get("last_price")
        first_price = item.get("first_price")
        pnl_value = item.get("performance_pct")
        if pnl_value is None and isinstance(first_price, (int, float)) and isinstance(sell_price, (int, float)):
            pnl_value = round((sell_price - first_price) / first_price * 100, 2)
        rows.append({
            "action": "Sell",
            "ticker": ticker,
            "name": item.get("name", "移出觀察"),
            "price": quote_format(ticker, sell_price) if isinstance(sell_price, (int, float)) else sell_price or "--",
            "pnl": f"{pnl_value:+.2f}%" if isinstance(pnl_value, (int, float)) else "--",
        })

    return rows


def portfolio_table(items, today, sell_items=None):
    rows = DEMO_PORTFOLIO_ROWS if USE_PORTFOLIO_DEMO else portfolio_rows_from_stock_ideas(items, sell_items)
    if not rows:
        return ""

    summary = items.get("portfolio_summary", {}) if isinstance(items, dict) else {}
    total_assets = summary.get("total_assets")
    total_return_pct = summary.get("total_return_pct")

    total_assets_text = f"Total Assets ${total_assets:,.2f}" if isinstance(total_assets, (int, float)) else "Total Assets --"
    total_return_text = f"{total_return_pct:+.2f}%" if isinstance(total_return_pct, (int, float)) else ""
    total_return_class = "gain" if total_return_text.startswith("+") else "loss" if total_return_text.startswith("-") else "flat"

    html_parts = [f'''
    <div class="portfolio-panel">
      <div class="portfolio-head">
        <div class="portfolio-head-left">
          <div>xAI 模擬 Portfolio</div>
          <div class="portfolio-capital-line">
            <span class="portfolio-capital-label {total_return_class}">{esc(total_assets_text)}</span>
            <span class="portfolio-capital-change {total_return_class}">{esc(total_return_text)}</span>
          </div>
        </div>
        <div class="portfolio-date">{esc(display_date(today))}</div>
      </div>
      <table class="portfolio-table">
        <thead>
          <tr>
            <th style="width:18%;">Action</th>
            <th style="width:42%;">Position</th>
            <th style="width:20%;text-align:right;">Value</th>
            <th style="width:20%;text-align:right;">P/L</th>
          </tr>
        </thead>
        <tbody>
    ''']

    for row in rows:
        action = str(row.get("action") or "Hold").strip().title()
        action_class = action.lower() if action in {"Buy", "Hold", "Sell"} else "hold"
        pnl = str(row.get("pnl") or "").strip()
        pnl_class = "gain" if pnl.startswith("+") else "loss" if pnl.startswith("-") else "flat"
        shares_text = str(row.get("shares_text") or "--").strip()
        avg_cost_text = str(row.get("avg_cost_text") or "--").strip()
        value_text = str(row.get("value_text") or row.get("price") or "--").strip()
        current_price_text = str(row.get("current_price_text") or "").strip()
        pnl_amount_text = str(row.get("pnl_amount_text") or "").strip()

        html_parts.append(f'''
          <tr>
            <td class="portfolio-action"><span class="portfolio-badge {action_class}">{esc(action)}</span></td>
            <td>
              <div class="portfolio-ticker">{esc(row.get("ticker", ""))}</div>
              <div class="portfolio-subline">{esc(shares_text)} @ {esc(avg_cost_text)}</div>
            </td>
            <td class="portfolio-price">
              <div>{esc(value_text)}</div>
              <div class="portfolio-subline">{esc(current_price_text)}</div>
            </td>
            <td class="portfolio-pnl {pnl_class}">
              <div>{esc(pnl)}</div>
              <div class="portfolio-subline {pnl_class}">{esc(pnl_amount_text)}</div>
            </td>
          </tr>
        ''')

    html_parts.append('''
        </tbody>
      </table>
      <div style="margin:10px 0 0;text-align:right;font-size:14px;line-height:1.4;">
        <a href="''' + esc(PORTFOLIO_BOOK_URL) + '''" style="color:#2563eb;font-size:14px;font-weight:600;text-decoration:none;">View full portfolio book</a>
      </div>
    </div>
    ''')
    return "".join(html_parts)


def stock_cards(items, today=None, sell_items=None):
    if not isinstance(items, dict):
        return f"<div class='stock-card'>{esc(items)}</div>"

    html_parts = []

    html_parts.append(portfolio_table(items, today or "", sell_items))

    new_items = items.get("new", [])
    if new_items:
        html_parts.append('<h2 style="color:#1d4ed8; margin:22px 0 10px 0;">活躍板塊股票推介 - 【本期重點推介】</h2>')
        for item in new_items:
            html_parts.append(render_stock_card(item))

    continued_items = items.get("continued", [])
    if continued_items:
        html_parts.append('<h2 style="color:#334155; margin:28px 0 10px 0; padding-top:20px;">活躍板塊股票推介 - 【持續追蹤名單】</h2>')
        for item in continued_items:
            html_parts.append(render_stock_card(item))

    return "".join(html_parts)


def render_stock_card(item):
    if not isinstance(item, dict):
        return f"<div class='stock-card'>{esc(item)}</div>"

    ticker = str(item.get("ticker") or "").replace("NASDAQ:", "").strip()
    performance = item.get("performance_pct")
    performance_text = f"{performance:+.2f}%" if isinstance(performance, (int, float)) else "本期新增"
    latest_quote_text = latest_quote_display(item)
    levels = display_trade_levels(item)

    return f"""
    <div class="stock-card">
      <div class="stock-title">{esc(ticker)} | {esc(item.get("name", ""))}</div>
      <div><b>首次推介：</b>{esc(item.get("first_recommended_at", "未知"))}</div>
      <div><b>上次推介：</b>{esc(item.get("last_recommended_at", "未知"))}</div>
      <div><b>首次推介後表現：</b>{esc(performance_text)}</div>
      <div><b>最新報價：</b>{esc(latest_quote_text)}</div>
      <div><b>板塊：</b>{esc(item.get("sector", ""))}</div>
      <div><b>推介理由：</b>{esc(item.get("reason", ""))}</div>
      <div><b>技術面：</b>{esc(item.get("technical", ""))}</div>
      <div><b>入場條件：</b>{esc(levels["entry"])}</div>
      <div><b>止蝕位：</b>{esc(levels["stop"])}</div>
      <div><b>目標價：</b>{esc(levels["target"])}</div>
      <div><b>移動止賺：</b>{esc(levels["trailing_stop"])}</div>
      <div><b>主要風險：</b>{esc(item.get("risk", ""))}</div>
    </div>
    """


def latest_quote_display(item):
    price = item.get("current_price")
    if not is_valid_price(price):
        price = item.get("last_price")
    pct = item.get("current_pct")
    if is_valid_price(price) and isinstance(pct, (int, float)) and math.isfinite(float(pct)):
        return f"${float(price):,.2f}（{float(pct):+.2f}%）"
    if is_valid_price(price):
        return f"${float(price):,.2f}"
    return "--"


def display_trade_levels(item):
    current_price = item.get("current_price")
    if not is_valid_price(current_price):
        current_price = item.get("last_price")
    if not is_valid_price(current_price):
        first_price = item.get("first_price")
        current_price = first_price if is_valid_price(first_price) else None

    raw_stop = extract_number(item.get("stop"))
    raw_target = extract_number(item.get("target"))

    if is_valid_price(current_price):
        price = float(current_price)
        stop = raw_stop if is_valid_price(raw_stop) and price * 0.75 <= float(raw_stop) < price else round(price * 0.9, 2)
        target = raw_target if is_valid_price(raw_target) and float(raw_target) > price else round(price * 1.3, 2)
        return {
            "entry": item.get("entry") if item.get("entry") and item.get("entry") != "N/A" else f"現價附近或回調至 ${price:,.2f}",
            "stop": f"${float(stop):,.2f}",
            "target": f"${float(target):,.2f}",
            "trailing_stop": "獲利超過25%後，最高價回調5%止賺",
        }

    return {
        "entry": item.get("entry", ""),
        "stop": item.get("stop", ""),
        "target": item.get("target", ""),
        "trailing_stop": item.get("trailing_stop", "獲利超過25%後，最高價回調5%止賺"),
    }


def normalize_watchlist_trade_levels(watchlist):
    if not isinstance(watchlist, dict):
        return watchlist
    for group in ("new", "continued"):
        for item in watchlist.get(group, []):
            if not isinstance(item, dict):
                continue
            levels = display_trade_levels(item)
            item["entry"] = levels["entry"]
            item["stop"] = levels["stop"]
            item["target"] = levels["target"]
            item["trailing_stop"] = levels["trailing_stop"]
    return watchlist


def email_html(report, quote_rows, today, token_info=None, sell_items=None):
    if token_info is None:
        token_info = {"prompt": 0, "completion": 0, "cached": 0}
    
    total_tokens = token_info["prompt"] + token_info["completion"]
    cost = (token_info["prompt"] * 1.25 + token_info["completion"] * 2.50) / 1_000_000
    
    d = report.get("market_dashboard") or {}
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
body{{margin:0;background:#ffffff;color:#111827;font-family:Arial,sans-serif}}
.c{{width:100%;max-width:100%;margin:0;padding:2px;background:#ffffff;box-sizing:border-box}}
h1{{font-size:24px;margin:0 0 4px}} 
h2{{font-size:17px;margin:22px 0 10px;padding-bottom:6px;border-bottom:1px solid #ddd}}
p,li,.box{{font-size:15px;line-height:1.65}} 
li{{margin-bottom:10px}} ul{{padding-left:22px}}
td{{padding:9px 0;border-bottom:1px solid #eee;font-size:14px}}
.meta{{color:#777;font-size:12px}} 
.summary{{font-size:18px;font-weight:700;line-height:1.5;margin:22px 0}}
.box,.stock-card{{background:#f9fafb;border-left:4px solid #1d4ed8;padding:10px 10px;margin:10px 0}} 
.stock-card{{font-size:15px;line-height:1.65}} 
.stock-title{{font-weight:700;margin-bottom:6px}} 
.portfolio-panel{{width:calc(100% - 10px);box-sizing:border-box;background:transparent;border:0;padding:0;margin:12px 5px 18px}}
.portfolio-head{{display:flex;justify-content:space-between;align-items:flex-end;gap:8px;color:#111827;font-size:19px;font-weight:700;border-bottom:2px solid #111827;padding:0 2px 7px;margin-bottom:0}}
.portfolio-head-left{{display:flex;flex-direction:column;align-items:flex-start}}
.portfolio-capital-line{{margin-top:6px;font-size:11px;font-weight:600;white-space:nowrap}}
.portfolio-capital-label{{color:#64748b}}
.portfolio-capital-label.gain{{color:#059669}}
.portfolio-capital-label.loss{{color:#e11d48}}
.portfolio-capital-label.flat{{color:#64748b}}
.portfolio-capital-change{{margin-left:6px;font-weight:700}}
.portfolio-capital-change.gain{{color:#059669}}
.portfolio-capital-change.loss{{color:#e11d48}}
.portfolio-capital-change.flat{{color:#64748b}}
.portfolio-date{{font-size:11px;font-weight:500;color:#64748b;white-space:nowrap}}
.portfolio-table{{width:100%;border-collapse:collapse;table-layout:fixed;border:0;background:#ffffff}}
.portfolio-table th{{color:#64748b;font-size:10px;font-weight:700;text-transform:uppercase;text-align:left;padding:7px 5px;border-bottom:1px solid #cbd5e1;background:#f8fafc}}
.portfolio-table td{{padding:9px 5px;border-bottom:1px solid #e5e7eb;font-size:13px;vertical-align:middle;word-break:break-word}}
.portfolio-table tr:last-child td{{border-bottom:1px solid #cbd5e1}}
.portfolio-action{{font-weight:700;white-space:nowrap}}
.portfolio-badge{{display:inline-block;border-radius:4px;padding:2px 4px;font-size:11px;line-height:1.2;text-transform:uppercase}}
.portfolio-badge.buy{{color:#047857;background:#d1fae5}} .portfolio-badge.hold{{color:#92400e;background:#fef3c7}} .portfolio-badge.sell{{color:#be123c;background:#ffe4e6}}
.portfolio-ticker{{font-weight:700;color:#111827;font-size:14px;line-height:1.15}}
.portfolio-subline{{color:#64748b;font-size:10px;line-height:1.2;margin-top:3px;white-space:nowrap}}
.portfolio-subline.gain{{color:#059669}} .portfolio-subline.loss{{color:#e11d48}} .portfolio-subline.flat{{color:#64748b}}
.portfolio-price{{color:#111827;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
.portfolio-pnl{{font-weight:400;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}} .portfolio-pnl.gain{{color:#059669}} .portfolio-pnl.loss{{color:#e11d48}} .portfolio-pnl.flat{{color:#64748b}}
.up{{color:#0a8f3c;font-weight:700}} .down{{color:#d93025;font-weight:700}}
.footer{{color:#888;font-size:11px;margin-top:28px;text-align:center}}
</style></head><body><div class="c">
<h1>Market Watch | 投行市場快報</h1>
<div class="meta">{esc(today)} HKT</div>

<div class="summary">{esc(report.get("summary"))}</div>

<h2>核心摘要</h2>
<ul>{li(report.get("executive_brief", []))}</ul>

<h2>快速市場行情</h2>
<table style="width:100%;border-collapse:collapse;">
{quote_table(quote_rows)}
</table>

<h2>X 市場共識</h2>
<ul>{li(report.get("x_consensus", []))}</ul>


{stock_cards(report.get("stock_ideas", []), today, sell_items)}

{portfolio_review_html(report.get("portfolio_review"))}

<h2>詳細市場動態</h2>
<div class="box"><b>美股 / AI：</b>{esc(d.get("us"))}</div>
<div class="box"><b>亞太：</b>{esc(d.get("asia"))}</div>
<div class="box"><b>宏觀：</b>{esc(d.get("macro"))}</div>
<div class="box"><b>加密：</b>{esc(d.get("crypto"))}</div>

<div class="footer">
  Real-time X Intelligence · Powered by xAI<br>
  本次報告消耗 <b>{total_tokens:,}</b> tokens (Cached: <b>{token_info["cached"]:,}</b>)｜預估費用 <b>${cost:.4f}</b> USD
</div>
</div></body></html>"""


def should_send(content):
    if os.environ.get("FORCE_SEND") == "1":
        print("手動執行，強制發送。")
        return True

    new_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            old_hash = f.read().strip()
    except Exception:
        old_hash = None
    if old_hash == new_hash:
        print("內容與上次完全相同，跳過發送。")
        return False
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        f.write(new_hash)
    return True


def enrich_sell_items(items, history):
    enriched = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        ticker = normalize_ticker(row.get("ticker"))
        record = history.get(ticker, {}) if isinstance(history, dict) else {}
        row.setdefault("name", record.get("name", "移出觀察"))
        row.setdefault("first_price", record.get("first_price"))
        if row.get("sell_price") is None:
            row["sell_price"] = row.get("last_price", record.get("last_price"))
        if row.get("sell_price") is None:
            row["sell_price"] = get_latest_price(ticker)
        first_price = row.get("first_price")
        sell_price = row.get("sell_price")
        if row.get("performance_pct") is None and isinstance(first_price, (int, float)) and isinstance(sell_price, (int, float)):
            row["performance_pct"] = round((sell_price - first_price) / first_price * 100, 2)
        enriched.append(row)
    return enriched


def send_email(subject, content):
    if not os.environ.get("GMAIL_USER"):
        raise RuntimeError("缺少 GitHub Secret: GMAIL_USER")
    if not os.environ.get("GMAIL_PASSWORD"):
        raise RuntimeError("缺少 GitHub Secret: GMAIL_PASSWORD")

    clean_subject = str(subject or "").strip()
    clean_subject = re.sub(r"^市場觀察[：:]\s*", "", clean_subject)
    clean_subject = re.sub(r"\s*[:：]\s*", "：", clean_subject)
    clean_subject = re.sub(r"<[^>]+>", "", clean_subject)
    #final_subject = "Market Watch | 投行市場快報：" + clean_subject.strip()
    final_subject = clean_subject.strip()
    
    print(f"郵件標題 → {final_subject}")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = final_subject
    msg["From"] = formataddr(("AI環球金融行情分析", os.environ["GMAIL_USER"]))
    msg["To"] = RECIPIENT
    msg.attach(MIMEText(content, "html", "utf-8"))

    print(f"正在登入 Gmail SMTP，準備發送到 {RECIPIENT}...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.environ["GMAIL_USER"], os.environ["GMAIL_PASSWORD"])
        server.send_message(msg)
    print("Gmail SMTP 發送完成。")


def get_full_active_stock_ideas(current_items, history, removelist, now):
    new_recommendations = []
    continued = []
    seen_tickers = set()
    removelist_tickers = {normalize_ticker(item.get("ticker")) for item in removelist}

    for item in current_items:
        if not isinstance(item, dict):
            continue
        ticker_norm = normalize_ticker(item.get("ticker"))
        if (
            not is_allowed_us_equity_ticker(item.get("ticker"))
            or ticker_norm in removelist_tickers
            or str(item.get("status") or "").lower().strip() == "remove"
        ):
            continue

        new_item = dict(item)
        new_item["reason"] = "【本期新推】 " + str(new_item.get("reason", "")).strip()
        new_item["is_new"] = True
        new_recommendations.append(new_item)
        seen_tickers.add(ticker_norm)

    history_items = list(history.items())
    for ticker_norm, record in history_items[:12]:
        record_ticker = record.get("ticker", ticker_norm)
        if (
            not is_allowed_us_equity_ticker(record_ticker)
            or ticker_norm in seen_tickers
            or ticker_norm in removelist_tickers
            or str(record.get("status") or "").lower().strip() == "remove"
        ):
            continue

        current_price, current_pct = get_latest_quote(ticker_norm)
        hist_item = {
            "ticker": record_ticker,
            "name": record.get("name", ""),
            "sector": record.get("sector", ""),
            "status": record.get("status", "watch"),
            "conviction_score": record.get("conviction_score"),
            "catalyst_score": record.get("catalyst_score"),
            "technical_score": record.get("technical_score"),
            "sentiment_score": record.get("sentiment_score"),
            "risk_score": record.get("risk_score"),
            "reason": record.get("last_review_reason", record.get("reason", "長期追蹤 | 等待新催化劑")),
            "technical": record.get("technical", "技術面維持觀察"),
            "entry": record.get("entry", "參考技術支撐位"),
            "stop": record.get("stop", "N/A"),
            "risk": record.get("risk", "板塊輪動與宏觀風險"),
            "first_recommended_at": record.get("first_recommended_at", "未知"),
            "last_recommended_at": record.get("last_recommended_at", "未知"),
            "current_price": current_price,
            "current_pct": current_pct,
            "performance_pct": None,
            "is_new": False
        }

        first_price = record.get("first_price")
        curr_price = hist_item["current_price"]
        if first_price is not None and curr_price is not None:
            hist_item["performance_pct"] = round((curr_price - first_price) / first_price * 100, 2)

        continued.append(hist_item)
        seen_tickers.add(ticker_norm)

    return {"new": new_recommendations, "continued": continued}


def main():
    global total_token_usage
    total_token_usage = {"prompt": 0, "completion": 0, "cached": 0}

    print("main_new.py 已啟動。")
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"📁 狀態資料夾已確認: {DATA_DIR}/")
    print(f"FORCE_SEND={os.environ.get('FORCE_SEND', '')}")
    print(f"USE_XAI={USE_XAI}")
    print(f"API_KEY 已設定：{bool(os.environ.get('API_KEY'))}")
    print(f"GMAIL_USER 已設定：{bool(os.environ.get('GMAIL_USER'))}")
    print(f"GMAIL_PASSWORD 已設定：{bool(os.environ.get('GMAIL_PASSWORD'))}")

    state = load_state()
    save_state(state)

    now = hk_now()
    today = now.strftime("%Y-%m-%d %H:%M")
    print(f"香港時間：{today}")
    print("正在讀取市場報價...")
    quotes, quote_rows = fetch_quotes()
    print(f"市場報價讀取完成：{len(quote_rows)} 個項目。")

    stock_history = load_json_file(STOCK_HISTORY_FILE, {})
    portfolio_book = load_portfolio_book()
    prompt = build_prompt(
        today,
        quotes,
        market_status(now),
        trading_session_instruction(now),
        last_run_instruction(state),
        removelist_note(now),
        portfolio_prompt_state(portfolio_book),
    )
    
    report = ask_xai(prompt)
    current_ideas = report.get("stock_ideas", []) if isinstance(report, dict) else []
    update_stock_history(current_ideas, now)
    stock_history = load_json_file(STOCK_HISTORY_FILE, {})
    removelist = active_removelist(now)
    full_ideas = get_full_active_stock_ideas(current_ideas, stock_history, removelist, now)
    full_ideas = normalize_watchlist_trade_levels(full_ideas)
    watchlist_text = json.dumps(full_ideas, ensure_ascii=False)
    portfolio_prompt = build_portfolio_prompt(
        today,
        report,
        portfolio_prompt_state(portfolio_book),
        watchlist_text,
        trading_session_instruction(now),
        removelist_note(now),
    )
    portfolio_report = ask_portfolio_manager(portfolio_prompt, portfolio_book)
    if isinstance(portfolio_report, dict):
        report["portfolio_decisions"] = portfolio_report.get("portfolio_decisions", {})
    filter_portfolio_buy_orders(report, full_ideas)

    update_position_risk_state(portfolio_book)
    risk_orders = apply_portfolio_risk_rules(portfolio_book)
    if risk_orders:
        decisions = report.setdefault("portfolio_decisions", {})
        if not isinstance(decisions, dict):
            decisions = {}
            report["portfolio_decisions"] = decisions
        ai_orders = decisions.get("orders", [])
        if not isinstance(ai_orders, list):
            ai_orders = []
        risk_tickers = {order.get("ticker") for order in risk_orders}
        decisions["orders"] = risk_orders + [
            order for order in ai_orders
            if normalize_ticker(order.get("ticker")) not in risk_tickers
        ]
    portfolio_book = apply_portfolio_decisions(portfolio_book, report, now)

    review_prompt = build_portfolio_review_prompt(
        today,
        report,
        portfolio_book,
        trading_session_instruction(now),
    )
    review_report = ask_portfolio_review(review_prompt)
    if isinstance(review_report, dict):
        report["portfolio_review"] = review_report.get("portfolio_review", {})
        if isinstance(report["portfolio_review"], dict):
            review_entry = {
                "time": today,
                "review": report["portfolio_review"],
            }
            portfolio_book["latest_review"] = review_entry
            review_history = portfolio_book.setdefault("review_history", [])
            if isinstance(review_history, list):
                review_history.append(review_entry)
                portfolio_book["review_history"] = review_history[-20:]

    save_portfolio_book(portfolio_book)
    
    stock_ideas = enrich_stock_ideas(full_ideas, stock_history)
    if not isinstance(stock_ideas, dict):
        stock_ideas = {"new": [], "continued": []}
    stock_ideas["portfolio_rows"] = portfolio_snapshot_rows(portfolio_book)
    stock_ideas["portfolio_summary"] = portfolio_snapshot_summary(portfolio_book)
    report["stock_ideas"] = stock_ideas
    
    display_sell_items = enrich_sell_items(removelist, stock_history)
    content = email_html(report, quote_rows, today, total_token_usage, display_sell_items)
    
    active_count = len(report.get("stock_ideas", {}).get("portfolio_rows", []))
    print(f"Email HTML 已建立。Portfolio 目前 {active_count} 個持倉。")

    if should_send(content):
        subject = report.get("subject") or report.get("summary") or "最新市場情報"
        send_email(subject, content)
        
        with open(LAST_RUN_FILE, "w", encoding="utf-8") as f:
            f.write(today)
        state.update({
            "last_successful_email_time": today,
            "latest_summary": re.sub(r"<[^>]+>", "", str(subject)),
            "last_status": "sent",
            "last_checked_time": now.isoformat(),
        })
        print(f"成功發送最新市場情報，並已更新時間錨點為：{today}")
    else:
        state.update({
            "last_status": "skipped_duplicate",
            "last_checked_time": now.isoformat(),
            "latest_summary": re.sub(r"<[^>]+>", "", str(report.get("summary", ""))),
        })
        print("無新情報，節省郵件配額。")

    save_state(state)


if __name__ == "__main__":
    main()

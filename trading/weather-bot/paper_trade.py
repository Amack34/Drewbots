#!/usr/bin/env python3
"""
Paper trading mode for weather bot.
Tracks hypothetical trades without executing. Logs what it WOULD have traded and tracks P&L.
"""

import json
import sqlite3
import logging
from datetime import datetime, timezone
from pathlib import Path

from weather_collector import CONFIG
from signal_generator import Signal

DB_PATH = CONFIG["db_path"]
LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "paper_trade.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("paper_trade")

PAPER_BANKROLL_START = 10000  # cents ($100)


def init_paper_db():
    """Create paper trading tables."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            market_type TEXT NOT NULL,
            event_ticker TEXT NOT NULL,
            market_ticker TEXT NOT NULL,
            action TEXT NOT NULL,
            side TEXT NOT NULL,
            price_cents INTEGER NOT NULL,
            contracts INTEGER NOT NULL,
            confidence REAL,
            edge_pct REAL,
            reason TEXT,
            current_temp_f REAL,
            forecast_temp_f REAL,
            surrounding_avg_f REAL,
            settled INTEGER DEFAULT 0,
            settlement_result TEXT,
            pnl_cents INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            settled_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS paper_balance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            balance_cents INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # Initialize balance if empty
    c.execute("SELECT COUNT(*) FROM paper_balance")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO paper_balance (balance_cents, updated_at) VALUES (?, ?)",
                  (PAPER_BANKROLL_START, datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()


def get_paper_balance() -> int:
    """Get current paper balance in cents."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT balance_cents FROM paper_balance ORDER BY id DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    return row[0] if row else PAPER_BANKROLL_START


def get_todays_trade_count() -> int:
    """Count paper trades placed today (ET timezone, since Kalshi operates on ET)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Use ET date (UTC-5) for daily counter
    from datetime import timedelta
    now_et = datetime.now(timezone.utc) - timedelta(hours=5)
    today_et = now_et.strftime("%Y-%m-%d")
    # Get trades where the ET date matches today
    c.execute("""SELECT COUNT(*) FROM paper_trades 
                 WHERE date(created_at, '-5 hours') = ?""", (today_et,))
    count = c.fetchone()[0]
    conn.close()
    return count


def is_duplicate_trade(market_ticker: str, side: str) -> bool:
    """Check if we already have an open (unsettled) trade on this market+side today."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    from datetime import timedelta
    now_et = datetime.now(timezone.utc) - timedelta(hours=5)
    today_et = now_et.strftime("%Y-%m-%d")
    c.execute("""SELECT COUNT(*) FROM paper_trades 
                 WHERE market_ticker = ? AND side = ? AND settled = 0
                 AND date(created_at, '-5 hours') = ?""",
              (market_ticker, side, today_et))
    count = c.fetchone()[0]
    conn.close()
    return count > 0


def paper_trade(signal: Signal, contracts: int = 1) -> dict | None:
    """Record a paper trade from a signal."""
    init_paper_db()

    # Dedup check — don't buy same bracket+side twice in a day
    if is_duplicate_trade(signal.market_ticker, signal.side):
        log.info("Paper trade skipped (DEDUP): already have open %s %s trade on %s today",
                 signal.action, signal.side, signal.market_ticker)
        return None

    balance = get_paper_balance()
    cost = signal.suggested_price * contracts  # cents

    # Risk checks
    max_position = int(balance * CONFIG["risk"]["max_position_pct"] / 100)
    if cost > max_position:
        log.warning("Paper trade rejected: cost %d¢ > max position %d¢", cost, max_position)
        return None

    if get_todays_trade_count() >= CONFIG["risk"]["max_trades_per_day"]:
        log.warning("Paper trade rejected: max daily trades reached")
        return None

    if cost > balance:
        log.warning("Paper trade rejected: insufficient paper balance (%d¢ < %d¢)", balance, cost)
        return None

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Add signal_source column if it doesn't exist
    try:
        c.execute("ALTER TABLE paper_trades ADD COLUMN signal_source TEXT DEFAULT 'model'")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    now = datetime.now(timezone.utc).isoformat()
    signal_source = getattr(signal, 'signal_source', 'model')

    c.execute("""
        INSERT INTO paper_trades
        (city, market_type, event_ticker, market_ticker, action, side,
         price_cents, contracts, confidence, edge_pct, reason,
         current_temp_f, forecast_temp_f, surrounding_avg_f, signal_source, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (signal.city, signal.market_type, signal.event_ticker,
          signal.market_ticker, signal.action, signal.side,
          signal.suggested_price, contracts, signal.confidence,
          signal.edge_pct, signal.reason, signal.current_temp_f,
          signal.forecast_temp_f, signal.surrounding_avg_f, signal_source, now))

    # Deduct cost from balance
    new_balance = balance - cost
    c.execute("INSERT INTO paper_balance (balance_cents, updated_at) VALUES (?, ?)",
              (new_balance, now))

    conn.commit()
    conn.close()

    trade = {
        "city": signal.city,
        "ticker": signal.market_ticker,
        "action": signal.action,
        "side": signal.side,
        "price": signal.suggested_price,
        "contracts": contracts,
        "cost": cost,
        "balance_after": new_balance,
    }
    log.info("PAPER TRADE: %s %s %s x%d @ %d¢ | Balance: $%.2f → $%.2f (%s)",
             signal.action, signal.side, signal.market_ticker,
             contracts, signal.suggested_price,
             balance / 100, new_balance / 100, signal_source)
    return trade


def settle_paper_trade(trade_id: int, won: bool):
    """Settle a paper trade and update P&L."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    c.execute("SELECT price_cents, contracts, side FROM paper_trades WHERE id = ?", (trade_id,))
    row = c.fetchone()
    if not row:
        log.warning("Paper trade %d not found", trade_id)
        conn.close()
        return

    price, contracts, side = row

    if won:
        # Won: receive 100¢ per contract, paid price per contract
        pnl = (100 - price) * contracts
        result = "WON"
    else:
        # Lost: lose the price paid
        pnl = -(price * contracts)
        result = "LOST"

    c.execute("""
        UPDATE paper_trades
        SET settled = 1, settlement_result = ?, pnl_cents = ?, settled_at = ?
        WHERE id = ?
    """, (result, pnl, now, trade_id))

    # Update balance (add back cost + pnl)
    balance = get_paper_balance()
    # Cost was already deducted. If won, add 100*contracts. If lost, nothing to add.
    if won:
        new_balance = balance + 100 * contracts
    # If lost, cost was already deducted, so balance stays
    else:
        new_balance = balance

    c.execute("INSERT INTO paper_balance (balance_cents, updated_at) VALUES (?, ?)",
              (new_balance, now))

    conn.commit()
    conn.close()
    log.info("SETTLED trade %d: %s | P&L: %+d¢ | Balance: $%.2f",
             trade_id, result, pnl, new_balance / 100)


def get_paper_summary() -> dict:
    """Get paper trading performance summary."""
    init_paper_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    balance = get_paper_balance()
    c.execute("SELECT COUNT(*) FROM paper_trades")
    total_trades = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM paper_trades WHERE settled = 1 AND settlement_result = 'WON'")
    wins = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM paper_trades WHERE settled = 1 AND settlement_result = 'LOST'")
    losses = c.fetchone()[0]
    c.execute("SELECT COALESCE(SUM(pnl_cents), 0) FROM paper_trades WHERE settled = 1")
    total_pnl = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM paper_trades WHERE settled = 0")
    open_trades = c.fetchone()[0]

    conn.close()

    return {
        "balance_cents": balance,
        "balance_usd": f"${balance / 100:.2f}",
        "starting_balance_usd": f"${PAPER_BANKROLL_START / 100:.2f}",
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": f"{wins / (wins + losses) * 100:.1f}%" if (wins + losses) > 0 else "N/A",
        "total_pnl_cents": total_pnl,
        "total_pnl_usd": f"${total_pnl / 100:.2f}",
        "open_trades": open_trades,
        "roi_pct": f"{(balance - PAPER_BANKROLL_START) / PAPER_BANKROLL_START * 100:.1f}%",
    }


def get_paper_positions() -> list[dict]:
    """Get open paper positions aggregated by ticker, mimicking Kalshi's format.
    YES trades = positive position, NO trades = negative position.
    Returns: [{"ticker": str, "position": int, "market_exposure": int}, ...]
    """
    init_paper_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Aggregate unsettled trades by ticker
    c.execute("""
        SELECT market_ticker, side, SUM(contracts), SUM(price_cents * contracts)
        FROM paper_trades
        WHERE settled = 0
        GROUP BY market_ticker, side
    """)
    rows = c.fetchall()
    conn.close()

    # Merge YES and NO for same ticker
    positions = {}  # ticker -> {"position": int, "market_exposure": int}
    for ticker, side, total_qty, total_cost in rows:
        if ticker not in positions:
            positions[ticker] = {"ticker": ticker, "position": 0, "market_exposure": 0}
        if side == "yes":
            positions[ticker]["position"] += total_qty
        else:  # no
            positions[ticker]["position"] -= total_qty
        positions[ticker]["market_exposure"] += total_cost

    return list(positions.values())


def get_paper_portfolio_value(client) -> tuple:
    """Calculate paper portfolio value using live market prices.
    Returns: (cash_cents, total_exposure_cents, positions_with_prices)
    positions_with_prices: list of dicts with ticker, position, exposure, current_value, yes_bid
    """
    import time as _time
    cash = get_paper_balance()
    positions = get_paper_positions()
    total_exposure = 0
    enriched = []

    for pos in positions:
        ticker = pos["ticker"]
        qty = pos["position"]
        exposure = pos["market_exposure"]
        if qty == 0:
            continue

        total_exposure += exposure
        try:
            _time.sleep(0.15)
            mkt = client.get_market(ticker).get("market", {})
            yes_bid = mkt.get("yes_bid", 0) or 0
            no_bid = mkt.get("no_bid", 0) or 0

            if qty < 0:  # NO position
                current_value = abs(qty) * (100 - yes_bid)
            else:  # YES position
                current_value = qty * yes_bid

            enriched.append({
                "ticker": ticker,
                "position": qty,
                "market_exposure": exposure,
                "current_value": current_value,
                "yes_bid": yes_bid,
                "no_bid": no_bid,
            })
        except Exception as e:
            log.warning("Failed to price paper position %s: %s", ticker, e)
            enriched.append({
                "ticker": ticker,
                "position": qty,
                "market_exposure": exposure,
                "current_value": exposure,  # fallback: assume no change
                "yes_bid": 0,
                "no_bid": 0,
            })

    return cash, total_exposure, enriched


def close_paper_position(ticker: str, side: str, qty: int, price: int):
    """Close a paper position by recording a settlement-like trade.
    For NO close: credit = qty * (100 - price)  [selling NO, receive NO value]
    For YES close: credit = qty * price  [selling YES, receive YES bid]
    price = the close price (YES bid for YES, NO bid for NO)
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now(timezone.utc).isoformat()

    if side == "no":
        credit = qty * (100 - price)  # price here is the yes_bid; NO value = 100 - yes_bid
    else:
        credit = qty * price  # YES close at yes_bid

    # Mark matching unsettled trades as settled
    # Find trades for this ticker+side, settle them FIFO
    remaining = qty
    c.execute("""
        SELECT id, contracts, price_cents FROM paper_trades
        WHERE market_ticker = ? AND side = ? AND settled = 0
        ORDER BY id ASC
    """, (ticker, side))
    rows = c.fetchall()

    total_cost = 0
    for trade_id, contracts, entry_price in rows:
        if remaining <= 0:
            break
        settle_qty = min(contracts, remaining)
        cost = settle_qty * entry_price
        total_cost += cost

        if settle_qty == contracts:
            pnl = (credit * settle_qty // qty) - cost  # proportional credit
            c.execute("""UPDATE paper_trades 
                SET settled = 1, settlement_result = 'CLOSED', pnl_cents = ?, settled_at = ?
                WHERE id = ?""", (pnl, now, trade_id))
        else:
            # Partial close — split the trade (settle part, leave rest)
            pnl = (credit * settle_qty // qty) - cost
            c.execute("""UPDATE paper_trades 
                SET contracts = contracts - ?, settled = 0
                WHERE id = ?""", (settle_qty, trade_id))
            # Insert settled portion
            c.execute("""INSERT INTO paper_trades 
                (city, market_type, event_ticker, market_ticker, action, side,
                 price_cents, contracts, confidence, edge_pct, reason,
                 current_temp_f, forecast_temp_f, surrounding_avg_f,
                 settled, settlement_result, pnl_cents, created_at, settled_at)
                SELECT city, market_type, event_ticker, market_ticker, action, side,
                 price_cents, ?, confidence, edge_pct, reason,
                 current_temp_f, forecast_temp_f, surrounding_avg_f,
                 1, 'CLOSED', ?, created_at, ?
                FROM paper_trades WHERE id = ?""", (settle_qty, pnl, now, trade_id))
        remaining -= settle_qty

    # Credit the balance
    balance = get_paper_balance()
    new_balance = balance + credit
    c.execute("INSERT INTO paper_balance (balance_cents, updated_at) VALUES (?, ?)",
              (new_balance, now))

    conn.commit()
    conn.close()
    log.info("PAPER CLOSE: %s %s x%d @ %d¢ | credit=%d¢ | Balance: $%.2f → $%.2f",
             side, ticker, qty, price, credit, balance / 100, new_balance / 100)


def get_paper_total_account_value(client) -> int:
    """Get total paper account value: cash + market value of all positions."""
    cash, _, enriched = get_paper_portfolio_value(client)
    market_value = sum(p["current_value"] for p in enriched)
    return cash + market_value


if __name__ == "__main__":
    init_paper_db()
    summary = get_paper_summary()
    print("\n=== Paper Trading Summary ===")
    for k, v in summary.items():
        print(f"  {k}: {v}")

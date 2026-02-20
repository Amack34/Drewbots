#!/usr/bin/env python3
"""
Kalshi API client for weather trading bot.
Handles authentication (RSA API key signing), market data, and order management.
API docs: https://docs.kalshi.com
"""

import json
import logging
import uuid
import base64
import datetime
import urllib.request
import urllib.error
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

LOG_DIR = Path(CONFIG["log_dir"])
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "trader.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("kalshi_trader")


class KalshiClient:
    """Kalshi API client with RSA key authentication."""

    def __init__(self, api_key_id: str = None, private_key_path: str = None, use_demo: bool = False):
        kalshi_cfg = CONFIG["kalshi"]
        self.api_key_id = api_key_id or kalshi_cfg["api_key_id"]
        self.private_key_path = private_key_path or kalshi_cfg["private_key_path"]

        if use_demo or CONFIG.get("use_demo", False):
            self.base_url = kalshi_cfg.get("demo_url", "https://demo-api.kalshi.co")
        else:
            self.base_url = kalshi_cfg.get("base_url", "https://api.elections.kalshi.com")

        self.private_key = None
        self._load_key()

    def _load_key(self):
        """Load RSA private key from file."""
        if not HAS_CRYPTO:
            log.warning("cryptography package not installed — authenticated endpoints won't work")
            return
        try:
            with open(self.private_key_path, "rb") as f:
                self.private_key = serialization.load_pem_private_key(
                    f.read(), password=None, backend=default_backend()
                )
            log.info("Private key loaded from %s", self.private_key_path)
        except FileNotFoundError:
            log.warning("Private key file not found: %s — auth endpoints will fail", self.private_key_path)
        except Exception as e:
            log.warning("Failed to load private key: %s", e)

    def _sign(self, timestamp_ms: str, method: str, path: str) -> str:
        """Create RSA-PSS signature for request authentication."""
        path_no_query = path.split("?")[0]
        message = f"{timestamp_ms}{method}{path_no_query}".encode("utf-8")
        signature = self.private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(signature).decode("utf-8")

    def _auth_headers(self, method: str, path: str) -> dict:
        """Generate authentication headers."""
        if not self.private_key:
            raise RuntimeError("No private key loaded — cannot authenticate")
        ts = str(int(datetime.datetime.now().timestamp() * 1000))
        sig = self._sign(ts, method, path)
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": sig,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, data: dict = None, auth: bool = False) -> dict:
        """Make an API request."""
        url = self.base_url + path
        body = json.dumps(data).encode() if data else None

        if auth:
            headers = self._auth_headers(method, path)
        else:
            headers = {"Content-Type": "application/json"}

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        # Rate limiting: 100ms between requests
        import time
        if not hasattr(self, '_last_request_time'):
            self._last_request_time = 0
        elapsed = time.time() - self._last_request_time
        if elapsed < 0.35:
            time.sleep(0.35 - elapsed)
        self._last_request_time = time.time()

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp_body = resp.read()
                if resp_body:
                    return json.loads(resp_body)
                return {}
        except urllib.error.HTTPError as e:
            error_body = e.read().decode() if e.fp else ""
            log.error("HTTP %d %s %s: %s", e.code, method, path, error_body[:500])
            raise
        except urllib.error.URLError as e:
            log.error("URL Error %s %s: %s", method, path, e)
            raise

    # ---- Public endpoints (no auth) ----

    def get_markets(self, event_ticker: str = None, series_ticker: str = None,
                    status: str = "open", limit: int = 100, cursor: str = None) -> dict:
        """Get markets, optionally filtered."""
        params = [f"limit={limit}"]
        if event_ticker:
            params.append(f"event_ticker={event_ticker}")
        if series_ticker:
            params.append(f"series_ticker={series_ticker}")
        if status:
            params.append(f"status={status}")
        if cursor:
            params.append(f"cursor={cursor}")
        path = "/trade-api/v2/markets?" + "&".join(params)
        return self._request("GET", path)

    def get_market(self, ticker: str) -> dict:
        """Get a single market by ticker."""
        return self._request("GET", f"/trade-api/v2/markets/{ticker}")

    def get_orderbook(self, ticker: str) -> dict:
        """Get order book for a market."""
        return self._request("GET", f"/trade-api/v2/markets/{ticker}/orderbook")

    def get_event(self, event_ticker: str) -> dict:
        """Get event details."""
        return self._request("GET", f"/trade-api/v2/events/{event_ticker}")

    def get_exchange_status(self) -> dict:
        """Check if exchange is open."""
        return self._request("GET", "/trade-api/v2/exchange/status")

    # ---- Authenticated endpoints ----

    def get_balance(self) -> dict:
        """Get portfolio balance."""
        return self._request("GET", "/trade-api/v2/portfolio/balance", auth=True)

    def get_positions(self, event_ticker: str = None) -> dict:
        """Get current positions."""
        path = "/trade-api/v2/portfolio/positions"
        if event_ticker:
            path += f"?event_ticker={event_ticker}"
        return self._request("GET", path, auth=True)

    def get_orders(self, status: str = None, ticker: str = None) -> dict:
        """Get orders."""
        params = []
        if status:
            params.append(f"status={status}")
        if ticker:
            params.append(f"ticker={ticker}")
        path = "/trade-api/v2/portfolio/orders"
        if params:
            path += "?" + "&".join(params)
        return self._request("GET", path, auth=True)

    def create_order(self, ticker: str, action: str, side: str, count: int,
                     order_type: str = "limit", yes_price: int = None,
                     no_price: int = None, client_order_id: str = None) -> dict:
        """
        Place an order.
        
        Args:
            ticker: Market ticker (e.g., "KXHIGHNY-26FEB15-35")
            action: "buy" or "sell"
            side: "yes" or "no"
            count: Number of contracts
            order_type: "limit" or "market"
            yes_price: Price in cents (1-99) for yes side
            no_price: Price in cents (1-99) for no side
            client_order_id: UUID for deduplication
        """
        order = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": order_type,
            "client_order_id": client_order_id or str(uuid.uuid4()),
        }
        if yes_price is not None:
            order["yes_price"] = yes_price
        if no_price is not None:
            order["no_price"] = no_price

        log.info("Placing order: %s %s %s x%d @ %s¢ on %s",
                 action, side, order_type, count,
                 yes_price or no_price, ticker)

        return self._request("POST", "/trade-api/v2/portfolio/orders", data=order, auth=True)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an order by ID."""
        log.info("Cancelling order %s", order_id)
        return self._request("DELETE", f"/trade-api/v2/portfolio/orders/{order_id}", auth=True)

    # ---- Weather-specific helpers ----

    def get_weather_markets(self, event_ticker: str) -> list[dict]:
        """Get all markets for a weather event ticker (e.g., KXHIGHNY-26FEB15)."""
        result = self.get_markets(event_ticker=event_ticker)
        return result.get("markets", [])

    def get_weather_event_today(self, series_ticker: str) -> list[dict]:
        """Get today's weather markets for a series (e.g., KXHIGHNY)."""
        today = datetime.date.today().strftime("%y%b%d").upper()
        event_ticker = f"{series_ticker}-{today}"
        log.info("Looking for event: %s", event_ticker)
        try:
            markets = self.get_weather_markets(event_ticker)
            return markets
        except urllib.error.HTTPError as e:
            if e.code == 404:
                log.info("No markets found for %s", event_ticker)
                return []
            raise

    def find_best_bracket(self, markets: list[dict], target_temp: float) -> dict | None:
        """Find the market bracket that contains the target temperature."""
        for m in markets:
            # Market titles typically have bracket info, or use floor/ceiling strike values
            title = m.get("title", "")
            ticker = m.get("ticker", "")

            # Try to extract bracket from subtitle or title
            # Kalshi weather tickers end with the lower bound, e.g., KXHIGHNY-26FEB15-B35
            # The bracket is typically 5°F wide
            try:
                # Extract number from end of ticker
                parts = ticker.split("-")
                if parts:
                    last = parts[-1]
                    # Remove leading 'B' if present
                    if last.startswith("B"):
                        last = last[1:]
                    bracket_low = int(last)
                    bracket_high = bracket_low + 4  # 5°F brackets
                    if bracket_low <= target_temp <= bracket_high:
                        return m
            except (ValueError, IndexError):
                continue
        return None


def test_public_api():
    """Test that public API endpoints work."""
    client = KalshiClient()
    print("\n=== Testing Kalshi Public API ===\n")

    # Exchange status
    try:
        status = client.get_exchange_status()
        print(f"Exchange status: {json.dumps(status, indent=2)}")
    except Exception as e:
        print(f"Exchange status error: {e}")

    # Try to find weather markets
    for series in ["KXHIGHNY", "KXHIGHPHIL", "KXHIGHMIA"]:
        try:
            markets = client.get_weather_event_today(series)
            if markets:
                print(f"\n{series}: Found {len(markets)} markets")
                for m in markets[:3]:
                    yes_price = m.get("yes_bid", "?")
                    title = m.get("title", m.get("ticker", "?"))
                    print(f"  {title}: yes_bid={yes_price}¢")
            else:
                print(f"\n{series}: No markets found today")
        except Exception as e:
            print(f"\n{series}: Error - {e}")


if __name__ == "__main__":
    test_public_api()

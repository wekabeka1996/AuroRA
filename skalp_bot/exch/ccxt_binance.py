from __future__ import annotations
import os
import ccxt
from typing import Any, Literal, Optional, Dict, List, Tuple
from pathlib import Path

# Aurora Core WebSocket integration
try:
    from core.market.websocket_client import BinanceWebSocketClient
    _WEBSOCKET_AVAILABLE = True
except ImportError as e:
    print(f"Warning: WebSocket client not available: {e}")
    _WEBSOCKET_AVAILABLE = False
    BinanceWebSocketClient = None


class CCXTBinanceAdapter:
    """
    CCXT Binance adapter with safe defaults and env-based credentials.

    Supports:
    - USDM futures (binanceusdm) and spot (binance)
    - Testnet toggle (set_sandbox_mode)
    - recvWindow/timeout/adjustForTimeDifference
    - Best-effort leverage configuration (if provided)
    """

    def __init__(self, cfg):
        self.cfg = cfg

        # Backward-compatible: read either flat cfg or nested exchange section
        exch = cfg.get("exchange", {}) if isinstance(cfg, dict) else {}
        # Environment overrides
        env_id = os.getenv("EXCHANGE_ID")
        env_testnet = os.getenv("EXCHANGE_TESTNET")
        env_use_futs = os.getenv("EXCHANGE_USE_FUTURES")

        use_futures = bool(exch.get("use_futures", cfg.get("use_futures", True)))
        testnet = bool(exch.get("testnet", cfg.get("testnet", True)))
        if env_use_futs is not None:
            use_futures = str(env_use_futs).lower() in {"1", "true", "yes"}
        if env_testnet is not None:
            testnet = str(env_testnet).lower() in {"1", "true", "yes"}
        exchange_id = exch.get("id", ("binanceusdm" if use_futures else "binance"))
        if env_id:
            exchange_id = env_id

        # Per-request recvWindow and client timeout
        try:
            recv_window_ms = int(exch.get("recv_window_ms", os.getenv("BINANCE_RECV_WINDOW", 5000)))
        except Exception:
            recv_window_ms = 5000
        try:
            timeout_ms = int(exch.get("timeout_ms", 20000))
        except Exception:
            timeout_ms = 20000
        try:
            adjust_time = bool(exch.get("adjust_for_time_diff", True))
        except Exception:
            adjust_time = True

        # Store as instance attributes for testing
        self.recv_window_ms = recv_window_ms
        self.timeout_ms = timeout_ms
        self.adjust_for_time_diff = adjust_time

        # Build CCXT constructor params
        options = {
            "defaultType": ("future" if use_futures else "spot"),
            "adjustForTimeDifference": adjust_time,
            "recvWindow": recv_window_ms,
        }
        params = {
            "enableRateLimit": True,
            "timeout": timeout_ms,
            "options": options,
        }

        # Instantiate exchange by id with safe fallback
        try:
            ex_class = getattr(ccxt, exchange_id)
        except AttributeError:
            # Fallback: some ccxt builds may not expose binanceusdm; use binance with futures defaultType
            if exchange_id == "binanceusdm" and hasattr(ccxt, "binance"):
                ex_class = getattr(ccxt, "binance")
                try:
                    # ensure defaultType is future in params.options
                    opts = params.setdefault("options", {})
                    opts["defaultType"] = "future"
                except Exception:
                    pass
            else:
                raise
        self.ex = ex_class(params)
        # Keep a flag for futures to enable reduceOnly on close orders
        self.use_futures = use_futures

        # Load markets early for precision/limits access
        try:
            self.ex.load_markets()
        except Exception:
            # Will attempt lazily later
            pass

        # Testnet (sandbox) mode
        try:
            if testnet:
                self.ex.set_sandbox_mode(True)
        except Exception:
            # Some exchanges may not support sandbox; ignore silently
            pass

        # Optionally load .env from repo root or CWD for convenience
        try:
            root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            for env_candidate in (os.path.join(root_dir, ".env"), os.path.join(os.getcwd(), ".env")):
                if os.path.isfile(env_candidate):
                    for line in open(env_candidate, "r", encoding="utf-8"):
                        s = line.strip()
                        if not s or s.startswith("#"):
                            continue
                        if "=" in s:
                            k, v = s.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k and (k not in os.environ):
                                os.environ[k] = v
                    break
        except Exception:
            pass

        # Credentials from environment variables (configurable names)
        key_env = exch.get("api_key_env", "BINANCE_API_KEY")
        sec_env = exch.get("api_secret_env", "BINANCE_API_SECRET")
        key, sec = os.getenv(key_env), os.getenv(sec_env)
        if key and sec:
            self.ex.apiKey = key
            self.ex.secret = sec

        # Symbol and dry-run
        self.symbol = exch.get("symbol", cfg.get("symbol", "BTC/USDT"))
        # Dry-run defaults to True for testnet, False for live
        default_dry = testnet if testnet is not None else True
        self.dry = bool(cfg.get("dry_run", default_dry))
        if os.getenv("DRY_RUN") is not None:
            self.dry = str(os.getenv("DRY_RUN")).lower() in {"1", "true", "yes"}
        # Early validation: LIVE mode requires keys
        if self.dry is False and (not getattr(self.ex, 'apiKey', None) or not getattr(self.ex, 'secret', None)):
            raise RuntimeError("Missing BINANCE_API_KEY/SECRET for LIVE run (DRY_RUN=false)")

        # Optional: set leverage if provided (best-effort; ignore failures)
        lev = exch.get("leverage", cfg.get("leverage"))
        if use_futures and lev:
            try:
                # Unified in CCXT (if supported). Some versions require symbol.
                if hasattr(self.ex, "set_leverage"):
                    self.ex.set_leverage(int(lev), self.symbol)
            except Exception:
                pass
        
        # === AURORA WEBSOCKET INTEGRATION ===
        # Initialize WebSocket client for real-time market data
        self._websocket_client = None
        self._websocket_enabled = bool(exch.get("enable_websocket", cfg.get("enable_websocket", True)))
        
        if self._websocket_enabled and _WEBSOCKET_AVAILABLE and use_futures:
            try:
                # Extract symbols from config - support multiple formats
                symbols = []
                
                # Try universe.symbols format first
                universe_symbols = cfg.get('universe', {}).get('symbols', [])
                if universe_symbols:
                    symbols = universe_symbols
                
                # Try overlay.market.symbols format (from YAML overlays)
                market_symbols = cfg.get('overlay', {}).get('market', {}).get('symbols', [])
                if market_symbols and not symbols:
                    # Extract symbol names from market format
                    for sym_config in market_symbols:
                        if isinstance(sym_config, dict) and 'name' in sym_config:
                            symbols.append(sym_config['name'])
                        elif isinstance(sym_config, str):
                            symbols.append(sym_config)
                
                # Fallback to current symbol
                if not symbols:
                    symbol_clean = self.symbol.replace('/', '').upper()
                    symbols = [symbol_clean]
                
                # Clean symbols (remove slashes, ensure uppercase)
                symbols_clean = []
                for s in symbols:
                    if isinstance(s, str):
                        s_clean = s.replace('/', '').upper()
                        symbols_clean.append(s_clean)
                
                if symbols_clean:
                    self._websocket_client = BinanceWebSocketClient(symbols_clean)
                    self._websocket_client.start()
                    print(f"✓ Aurora WebSocket started for symbols: {symbols_clean}")
                
            except Exception as e:
                print(f"Warning: Failed to initialize Aurora WebSocket client: {e}")
                self._websocket_client = None
        elif not use_futures:
            print("Info: Aurora WebSocket currently supports Futures only")
        elif not _WEBSOCKET_AVAILABLE:
            print("Warning: Aurora WebSocket client not available (missing dependencies)")
        elif not self._websocket_enabled:
            print("Info: Aurora WebSocket disabled in config")

        # WebSocket client alias for testing
        self.ws_client = self._websocket_client

    def fetch_top_of_book(self):
        def to_float(x: Any, default: float = 0.0) -> float:
            try:
                return float(x)
            except Exception:
                return default

        try:
            ob = self.ex.fetch_order_book(self.symbol, limit=5)
        except Exception:
            # Return empty data on any exception
            return 0.0, 0.0, [], [], []
            
        bids = [(to_float(p), to_float(q)) for p, q in ob.get("bids", [])[:5]]
        asks = [(to_float(p), to_float(q)) for p, q in ob.get("asks", [])[:5]]
        raw_trades = self.ex.fetch_trades(self.symbol, limit=50) or []
        trades = [
            {
                "side": (t.get("side") or "buy"),
                "qty": to_float(t.get("amount"), 0.0),
                "price": to_float(t.get("price"), 0.0),
                "ts": t.get("timestamp") or t.get("time") or 0,
            }
            for t in raw_trades
        ]
        if not bids or not asks:
            # Fallback mid/spread when book is empty
            return 0.0, 0.0, bids, asks, trades
        mid = (to_float(bids[0][0]) + to_float(asks[0][0])) / 2.0
        spread = to_float(asks[0][0]) - to_float(bids[0][0])
        return mid, spread, bids, asks, trades

    def _ensure_markets(self):
        try:
            if not getattr(self.ex, "markets", None):
                self.ex.load_markets()
        except Exception:
            pass

    def _quantize_amount(self, amount: float) -> float:
        try:
            return float(self.ex.amount_to_precision(self.symbol, amount))
        except Exception:
            # fallback: round to 1e-6
            return float(f"{amount:.6f}")

    def _quantize_price(self, price: float) -> float:
        try:
            return float(self.ex.price_to_precision(self.symbol, price))
        except Exception:
            # fallback: round to 1e-2
            return float(f"{price:.2f}")

    def _get_limits(self) -> dict:
        self._ensure_markets()
        try:
            m = self.ex.markets.get(self.symbol) or self.ex.market(self.symbol)
            return (m.get("limits") or {}) if m else {}
        except Exception:
            return {}

    def _estimate_price(self) -> float:
        # Try ticker last/close; fallback to mid from order book
        try:
            ticker = self.ex.fetch_ticker(self.symbol) or {}
            p = ticker.get("last") or ticker.get("close")
            if p:
                return float(p)
        except Exception:
            pass
        try:
            ob = self.ex.fetch_order_book(self.symbol, limit=5) or {}
            bids = ob.get("bids") or []
            asks = ob.get("asks") or []
            if bids and asks:
                return (float(bids[0][0]) + float(asks[0][0])) / 2.0
        except Exception:
            pass
        return 0.0

    def place_order(
        self,
        side: Literal["buy", "sell"],
        qty: float,
        price: float | None = None,
        *,
        reduce_only: bool = False,
    ):
        """Place order with exchange precision and limit checks.

        - Quantizes amount/price via ccxt helpers
        - Validates minQty and minCost when available
        """
        if self.dry:
            return {"info": "dry_run", "side": side, "qty": qty, "price": price, "reduceOnly": bool(reduce_only)}

        order_type = "limit" if price is not None else "market"
        params: dict[str, Any] = {"timeInForce": "GTC"} if order_type == "limit" else {}
        # For futures, allow reduceOnly on close orders
        if self.use_futures and reduce_only:
            try:
                params["reduceOnly"] = True
            except Exception:
                pass

        # Quantize amount/price to exchange precision
        qty_q = self._quantize_amount(float(qty))
        price_q = None
        if price is not None:
            price_q = self._quantize_price(float(price))

        # Enforce limits where possible
        limits = self._get_limits()
        min_amt = None
        min_cost = None
        try:
            min_amt = (limits.get("amount") or {}).get("min")
        except Exception:
            pass
        try:
            min_cost = (limits.get("cost") or {}).get("min")
        except Exception:
            pass

        if min_amt is not None and qty_q < float(min_amt):
            raise ValueError(f"Order amount {qty_q} below minQty {min_amt} for {self.symbol}")

        # Estimate cost for market orders (or when price not provided)
        est_price = price_q if price_q is not None else self._estimate_price()
        if min_cost is not None and est_price and (qty_q * est_price) < float(min_cost):
            raise ValueError(
                f"Order cost {qty_q * est_price:.8f} below minCost {min_cost} for {self.symbol}"
            )

        return self.ex.create_order(self.symbol, order_type, side, qty_q, price_q, params)

    def close_position(self, side_current: Literal["LONG", "SHORT"], qty: float):
        """Place a market order to close an existing position amount.

        For futures, uses reduceOnly=True to avoid unintentionally increasing exposure.
        """
        ex_side: Literal["buy", "sell"] = "sell" if side_current == "LONG" else "buy"
        return self.place_order(ex_side, qty, price=None, reduce_only=True)

    def cancel_all(self):
        if self.dry:
            return {"info": "dry_run"}
        try:
            return self.ex.cancel_all_orders(self.symbol)
        except Exception:
            return False

    # --- Optional helpers for account state (stubs if not implemented) ---
    def get_positions(self):
        """Return a list of position dicts; stubbed for now."""
        try:
            # Real implementation could query futures positions via ccxt
            return []
        except Exception:
            return []

    def get_gross_exposure_usdt(self) -> float:
        """Return estimated gross exposure in USDT; stubbed for now."""
        try:
            return 0.0
        except Exception:
            return 0.0

    # --- OHLCV helper for indicators ---
    def fetch_ohlcv_1m(self, limit: int = 200):
        """Fetch 1m OHLCV bars for current symbol. Returns list of [ts, o,h,l,c,v]."""
        try:
            return self.ex.fetch_ohlcv(self.symbol, timeframe="1m", limit=int(limit)) or []
        except Exception:
            return []
    
    # --- Aurora WebSocket lifecycle management ---
    def stop_websocket(self):
        """Stop Aurora WebSocket client if running."""
        if self._websocket_client and hasattr(self._websocket_client, 'stop'):
            try:
                self._websocket_client.stop()
                print("✓ Aurora WebSocket client stopped")
            except Exception as e:
                print(f"Warning: Error stopping WebSocket client: {e}")
    
    def is_websocket_running(self):
        """Check if Aurora WebSocket client is running."""
        if self._websocket_client and hasattr(self._websocket_client, 'is_running'):
            try:
                return self._websocket_client.is_running()
            except Exception:
                pass
        return False
    
    def __del__(self):
        """Cleanup WebSocket on destruction."""
        try:
            self.stop_websocket()
        except Exception:
            pass

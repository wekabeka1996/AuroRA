# -*- coding: utf-8 -*-
"""
Aurora Core WebSocket Client for Binance Futures
==============================================

Real-time market data feed that generates Aurora events (WS.CONNECT, MARKET.BOOK, MARKET.TICKER) 
in aurora_events.jsonl format.

This replaces the external workaround scripts by integrating WebSocket directly into Aurora Core.
"""

import asyncio
import json
import os
import ssl
import time
import threading
from pathlib import Path
from typing import List, Optional, Any, Dict
import websockets

from core.logging.anti_flood import AntiFloodJSONLWriter, create_default_anti_flood_logger
from core.env_config import load_binance_futures_cfg


class BinanceWebSocketClient:
    """
    Binance Futures WebSocket client integrated into Aurora Core.
    
    Features:
    - Uses core.env_config for configuration
    - Writes to aurora_events.jsonl using AntiFloodJSONLWriter
    - Handles ticker and bookTicker streams
    - Proper event format using 'e' field (not 'stream')
    - Background thread execution
    """
    
    def __init__(self, symbols: List[str], session_dir: Optional[Path] = None):
        """
        Initialize WebSocket client.
        
        Args:
            symbols: List of trading symbols (e.g., ['SOLUSDT', 'SOONUSDT'])
            session_dir: Directory for aurora_events.jsonl (default: AURORA_SESSION_DIR or 'logs')
        """
        self.symbols = [s.lower() for s in symbols]
        
        # Load Binance Futures configuration
        try:
            self.binance_cfg = load_binance_futures_cfg()
            # Extract WebSocket base URL
            # ws_url format: "wss://fstream.binance.com/stream"
            ws_url = self.binance_cfg.ws_url
            if ws_url.endswith('/stream'):
                self.base_url = ws_url.replace('/stream', '/ws/')
            else:
                self.base_url = "wss://fstream.binance.com/ws/"
        except Exception as e:
            print(f"Warning: Failed to load Binance config, using defaults: {e}")
            self.base_url = "wss://fstream.binance.com/ws/"
        
        # Session directory for aurora_events.jsonl
        if session_dir is None:
            session_dir = Path(os.getenv("AURORA_SESSION_DIR", "logs"))
        session_dir.mkdir(parents=True, exist_ok=True)
        
        # Anti-flood events writer
        events_file = session_dir / "aurora_events.jsonl"
        anti_flood = create_default_anti_flood_logger()
        self._events_writer = AntiFloodJSONLWriter(events_file, anti_flood)
        
        # Runtime state
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        
        print(f"✓ Aurora WebSocket Client initialized for {symbols}")
        print(f"  Base URL: {self.base_url}")
        print(f"  Events file: {events_file}")
    
    def _log_event(self, event_code: str, details: Dict[str, Any], symbol: Optional[str] = None) -> None:
        """Write event to aurora_events.jsonl using anti-flood protection."""
        event = {
            "ts_ns": int(time.time() * 1_000_000_000),
            "run_id": "aurora-core-websocket",
            "event_code": event_code,
            "symbol": symbol,
            "cid": None,
            "oid": None,
            "side": None,
            "order_type": None,
            "price": None,
            "qty": None,
            "position_id": None,
            "details": details,
            "src": "aurora_core_ws"
        }
        
        try:
            self._events_writer.write_event(event_code, event)
        except Exception as e:
            print(f"Warning: Failed to write WebSocket event: {e}")
    
    async def _connect_ticker_stream(self, symbol: str) -> None:
        """Connect to ticker stream for one symbol."""
        url = f"{self.base_url}{symbol}@ticker"
        ssl_context = ssl.create_default_context()
        
        try:
            async with websockets.connect(url, ssl=ssl_context) as websocket:
                self._log_event("WS.CONNECT", {"url": url, "symbol": symbol}, symbol.upper())
                
                while self._running:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=30)
                        data = json.loads(message)
                        
                        # Binance sends event type in 'e' field, not 'stream'
                        event_type = data.get('e')
                        if event_type == '24hrTicker':
                            self._log_event("MARKET.TICKER", {
                                "price": data.get('c', '0'),  # close price
                                "change_24h": data.get('P', '0'),  # price change percent
                                "volume": data.get('v', '0'),  # volume
                                "high_24h": data.get('h', '0'),  # high price
                                "low_24h": data.get('l', '0')  # low price
                            }, symbol.upper())
                        
                    except asyncio.TimeoutError:
                        if self._running:
                            print(f"[{symbol.upper()}] Ticker WebSocket timeout, sending ping...")
                            await websocket.ping()
                    except Exception as e:
                        if self._running:
                            print(f"[{symbol.upper()}] Ticker stream error: {e}")
                        break
                        
        except Exception as e:
            if self._running:
                print(f"[{symbol.upper()}] Ticker WebSocket connection error: {e}")
    
    async def _connect_book_stream(self, symbol: str) -> None:
        """Connect to book ticker stream for one symbol."""
        url = f"{self.base_url}{symbol}@bookTicker"
        ssl_context = ssl.create_default_context()
        
        try:
            async with websockets.connect(url, ssl=ssl_context) as websocket:
                self._log_event("WS.CONNECT", {"url": url, "symbol": symbol}, symbol.upper())
                
                while self._running:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=30)
                        data = json.loads(message)
                        
                        # Binance sends event type in 'e' field
                        event_type = data.get('e')
                        if event_type == 'bookTicker':
                            bid_price = float(data.get('b', 0))
                            ask_price = float(data.get('a', 0))
                            spread = ask_price - bid_price if ask_price > bid_price else 0.0
                            
                            self._log_event("MARKET.BOOK", {
                                "bid": data.get('b', '0'),
                                "ask": data.get('a', '0'),
                                "spread": str(spread),
                                "bid_qty": data.get('B', '0'),
                                "ask_qty": data.get('A', '0')
                            }, symbol.upper())
                        
                    except asyncio.TimeoutError:
                        if self._running:
                            print(f"[{symbol.upper()}] Book WebSocket timeout, sending ping...")
                            await websocket.ping()
                    except Exception as e:
                        if self._running:
                            print(f"[{symbol.upper()}] Book stream error: {e}")
                        break
                        
        except Exception as e:
            if self._running:
                print(f"[{symbol.upper()}] Book WebSocket connection error: {e}")
    
    async def _run_streams(self) -> None:
        """Run all WebSocket streams concurrently."""
        print(f"Starting Aurora WebSocket streams for {[s.upper() for s in self.symbols]}...")
        
        tasks = []
        # Create tasks for each symbol and stream type
        for symbol in self.symbols:
            tasks.append(asyncio.create_task(self._connect_ticker_stream(symbol)))
            tasks.append(asyncio.create_task(self._connect_book_stream(symbol)))
        
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            print("WebSocket streams cancelled")
        except Exception as e:
            print(f"WebSocket streams error: {e}")
    
    def _thread_target(self) -> None:
        """Background thread target that runs the asyncio event loop."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_streams())
        except Exception as e:
            print(f"WebSocket thread error: {e}")
        finally:
            if self._loop:
                self._loop.close()
    
    def start(self) -> None:
        """Start WebSocket client in background thread."""
        if self._running:
            print("WebSocket client already running")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._thread_target, daemon=True)
        self._thread.start()
        print("✓ Aurora WebSocket client started in background")
    
    def stop(self) -> None:
        """Stop WebSocket client."""
        if not self._running:
            return
        
        print("Stopping Aurora WebSocket client...")
        self._running = False
        
        # Cancel all tasks in the event loop
        if self._loop and not self._loop.is_closed():
            try:
                # Schedule the cancellation in the event loop
                def cancel_all():
                    tasks = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
                    for task in tasks:
                        task.cancel()
                
                self._loop.call_soon_threadsafe(cancel_all)
            except Exception:
                pass
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        
        print("✓ Aurora WebSocket client stopped")
    
    def is_running(self) -> bool:
        """Check if WebSocket client is running."""
        return self._running and self._thread and self._thread.is_alive()
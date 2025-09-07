# -*- coding: utf-8 -*-
"""
Shadow broker implementation with Binance exchange filters validation.
Simulates Binance Spot trading without real order submission.
"""
import time
import json
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
import requests

from core.env_config import load_binance_cfg
from core.order_logger import OrderLoggers


@dataclass
class BinanceFilters:
    """Binance exchange filters for a trading pair."""
    lot_size_min_qty: Decimal
    lot_size_max_qty: Decimal
    lot_size_step_size: Decimal
    price_filter_min_price: Decimal
    price_filter_max_price: Decimal
    price_filter_tick_size: Decimal
    min_notional: Decimal
    percent_price_multiplier_up: Decimal = Decimal("1.1")
    percent_price_multiplier_down: Decimal = Decimal("0.9")


@dataclass
class OrderReject:
    """Order rejection with reason."""
    reason: str
    details: str


class ShadowBroker:
    """
    Shadow broker that validates orders against live Binance filters
    and simulates fills without real execution.
    """
    
    def __init__(self, symbols: List[str], slippage_bps: float = 2.0):
        """
        Initialize shadow broker.
        
        Args:
            symbols: List of trading symbols to validate
            slippage_bps: Slippage in basis points for market orders
        """
        self.symbols = symbols
        self.slippage_bps = slippage_bps
        self.filters: Dict[str, BinanceFilters] = {}
        self.order_counter = 0
        self.binance_cfg = load_binance_cfg()
        
        # Initialize filters from live exchange
        self._fetch_exchange_info()
        
    def _fetch_exchange_info(self) -> None:
        """Fetch exchange info from live Binance API."""
        try:
            url = f"{self.binance_cfg.base_url}/api/v3/exchangeInfo"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            exchange_info = response.json()
            
            for symbol_info in exchange_info.get("symbols", []):
                symbol = symbol_info.get("symbol")
                if symbol not in self.symbols:
                    continue
                    
                if symbol_info.get("status") != "TRADING":
                    continue
                    
                # Parse filters
                filters = {}
                for filter_info in symbol_info.get("filters", []):
                    filter_type = filter_info.get("filterType")
                    filters[filter_type] = filter_info
                
                # Extract required filters
                lot_size = filters.get("LOT_SIZE", {})
                price_filter = filters.get("PRICE_FILTER", {})
                min_notional = filters.get("MIN_NOTIONAL", {}) or filters.get("NOTIONAL", {})
                percent_price = filters.get("PERCENT_PRICE", {})
                
                if not all([lot_size, price_filter, min_notional]):
                    continue
                
                self.filters[symbol] = BinanceFilters(
                    lot_size_min_qty=Decimal(lot_size.get("minQty", "0")),
                    lot_size_max_qty=Decimal(lot_size.get("maxQty", "999999999")),
                    lot_size_step_size=Decimal(lot_size.get("stepSize", "1")),
                    price_filter_min_price=Decimal(price_filter.get("minPrice", "0")),
                    price_filter_max_price=Decimal(price_filter.get("maxPrice", "999999999")),
                    price_filter_tick_size=Decimal(price_filter.get("tickSize", "0.01")),
                    min_notional=Decimal(min_notional.get("minNotional", "0")),
                    percent_price_multiplier_up=Decimal(percent_price.get("multiplierUp", "1.1")),
                    percent_price_multiplier_down=Decimal(percent_price.get("multiplierDown", "0.9"))
                )
                
        except Exception as e:
            # Log warning but don't fail - use default filters
            print(f"Warning: Failed to fetch exchange info: {e}")
            self._set_default_filters()
    
    def _set_default_filters(self) -> None:
        """Set default filters when API is unavailable."""
        for symbol in self.symbols:
            self.filters[symbol] = BinanceFilters(
                lot_size_min_qty=Decimal("0.001"),
                lot_size_max_qty=Decimal("999999999"),
                lot_size_step_size=Decimal("0.001"),
                price_filter_min_price=Decimal("0.01"),
                price_filter_max_price=Decimal("999999999"),
                price_filter_tick_size=Decimal("0.01"),
                min_notional=Decimal("10.0")
            )
    
    def _round_quantity(self, symbol: str, quantity: Decimal) -> Decimal:
        """Round quantity according to LOT_SIZE filter."""
        if symbol not in self.filters:
            return quantity
            
        filters = self.filters[symbol]
        step_size = filters.lot_size_step_size
        
        # Round down to step size precision
        rounded = (quantity // step_size) * step_size
        return rounded.quantize(step_size, rounding=ROUND_DOWN)
    
    def _round_price(self, symbol: str, price: Decimal) -> Decimal:
        """Round price according to PRICE_FILTER."""
        if symbol not in self.filters:
            return price
            
        filters = self.filters[symbol]
        tick_size = filters.price_filter_tick_size
        
        # Round to tick size precision
        rounded = (price // tick_size) * tick_size
        return rounded.quantize(tick_size, rounding=ROUND_DOWN)
    
    def _validate_order(self, symbol: str, side: str, order_type: str, 
                       quantity: Decimal, price: Optional[Decimal] = None) -> Optional[OrderReject]:
        """Validate order against Binance filters."""
        if symbol not in self.filters:
            return OrderReject("UNKNOWN_SYMBOL", f"No filters available for {symbol}")
        
        filters = self.filters[symbol]
        
        # Validate quantity
        if quantity < filters.lot_size_min_qty:
            return OrderReject("LOT_SIZE", f"Quantity {quantity} < min {filters.lot_size_min_qty}")
        
        if quantity > filters.lot_size_max_qty:
            return OrderReject("LOT_SIZE", f"Quantity {quantity} > max {filters.lot_size_max_qty}")
        
        # Check step size
        remainder = quantity % filters.lot_size_step_size
        if remainder != 0:
            return OrderReject("LOT_SIZE", f"Quantity {quantity} not multiple of step size {filters.lot_size_step_size}")
        
        # Validate price for limit orders
        if price is not None:
            if price < filters.price_filter_min_price:
                return OrderReject("PRICE_FILTER", f"Price {price} < min {filters.price_filter_min_price}")
            
            if price > filters.price_filter_max_price:
                return OrderReject("PRICE_FILTER", f"Price {price} > max {filters.price_filter_max_price}")
            
            # Check tick size
            remainder = price % filters.price_filter_tick_size
            if remainder != 0:
                return OrderReject("PRICE_FILTER", f"Price {price} not multiple of tick size {filters.price_filter_tick_size}")
        
        # Validate notional
        notional_price = price if price is not None else Decimal("50000")  # Estimate for market orders
        notional = quantity * notional_price
        
        if notional < filters.min_notional:
            return OrderReject("MIN_NOTIONAL", f"Notional {notional} < min {filters.min_notional}")
        
        return None
    
    def _generate_order_id(self) -> str:
        """Generate unique order ID."""
        self.order_counter += 1
        return f"SHADOW_{int(time.time() * 1000)}_{self.order_counter}"
    
    def _simulate_fill(self, symbol: str, side: str, order_type: str, 
                      quantity: Decimal, price: Optional[Decimal] = None) -> Dict[str, Any]:
        """Simulate order fill with realistic parameters."""
        timestamp = int(time.time() * 1000)
        
        # For market orders, simulate slippage
        if order_type == "MARKET":
            # Simulate getting filled at slightly worse price
            slippage_factor = Decimal(self.slippage_bps) / Decimal(10000)
            if side == "BUY":
                fill_price = Decimal("50000") * (1 + slippage_factor)  # Mock BTC price
            else:
                fill_price = Decimal("50000") * (1 - slippage_factor)
        else:
            # Limit orders fill at exact price
            fill_price = price or Decimal("50000")
        
        # Round fill price
        fill_price = self._round_price(symbol, fill_price)
        
        return {
            "symbol": symbol,
            "orderId": self._generate_order_id(),
            "orderListId": -1,
            "clientOrderId": f"shadow_{timestamp}",
            "transactTime": timestamp,
            "price": str(fill_price),
            "origQty": str(quantity),
            "executedQty": str(quantity),
            "cummulativeQuoteQty": str(quantity * fill_price),
            "status": "FILLED",
            "timeInForce": "GTC",
            "type": order_type,
            "side": side,
            "fills": [{
                "price": str(fill_price),
                "qty": str(quantity),
                "commission": "0.001",
                "commissionAsset": "BNB",
                "tradeId": timestamp
            }]
        }
    
    def submit_order(self, symbol: str, side: str, order_type: str, 
                    quantity: float, price: Optional[float] = None,
                    time_in_force: str = "GTC") -> Dict[str, Any]:
        """
        Submit shadow order with full Binance validation.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "BUY" or "SELL"
            order_type: "MARKET", "LIMIT", "STOP_LOSS_LIMIT", "TAKE_PROFIT_LIMIT"
            quantity: Order quantity
            price: Limit price (required for limit orders)
            time_in_force: "GTC", "IOC", "FOK"
            
        Returns:
            Dict with order response or error
        """
        # Convert to Decimal for precision
        qty_decimal = Decimal(str(quantity))
        price_decimal = Decimal(str(price)) if price is not None else None
        
        # Round to exchange precision
        qty_rounded = self._round_quantity(symbol, qty_decimal)
        if price_decimal is not None:
            price_rounded = self._round_price(symbol, price_decimal)
        else:
            price_rounded = None
        
        # Validate order
        rejection = self._validate_order(symbol, side, order_type, qty_rounded, price_rounded)
        if rejection:
            # Log rejection event
            self._log_order_event("REJECTED", symbol, side, order_type, 
                                qty_rounded, price_rounded, rejection.reason)
            
            return {
                "code": -1013,
                "msg": f"Filter failure: {rejection.reason} - {rejection.details}"
            }
        
        # Handle time in force for IOC/FOK
        if time_in_force == "IOC" and order_type == "LIMIT":
            # IOC: immediate or cancel - simulate partial fill possibility
            if qty_rounded > Decimal("1.0"):  # Mock: large orders get partial fill
                qty_rounded = qty_rounded * Decimal("0.7")  # 70% fill
                qty_rounded = self._round_quantity(symbol, qty_rounded)
        
        elif time_in_force == "FOK" and order_type == "LIMIT":
            # FOK: fill or kill - simulate rejection for large orders
            if qty_rounded > Decimal("10.0"):  # Mock: large FOK orders rejected
                self._log_order_event("REJECTED", symbol, side, order_type,
                                    qty_rounded, price_rounded, "FOK_INSUFFICIENT_LIQUIDITY")
                return {
                    "code": -2010,
                    "msg": "Account has insufficient balance for requested action"
                }
        
        # Simulate successful fill
        fill_result = self._simulate_fill(symbol, side, order_type, qty_rounded, price_rounded)
        
        # Log successful order
        self._log_order_event("FILLED", symbol, side, order_type,
                            qty_rounded, price_rounded, "SUCCESS")
        
        return fill_result
    
    def _log_order_event(self, status: str, symbol: str, side: str, order_type: str,
                        quantity: Decimal, price: Optional[Decimal], reason: str) -> None:
        """Log order event for TCA and metrics."""
        event = {
            "timestamp": int(time.time() * 1000),
            "event_type": "ORDER.SHADOW",
            "symbol": symbol,
            "side": side,
            "type": order_type,
            "quantity": str(quantity),
            "price": str(price) if price else None,
            "status": status,
            "reason": reason,
            "latency_ms": 1 + (hash(symbol) % 5),  # Mock 1-5ms latency
            "slippage_bps": self.slippage_bps if order_type == "MARKET" else 0
        }
        
        # Log to file for orchestrator to pick up
        try:
            with open("logs/shadow_orders.jsonl", "a") as f:
                f.write(json.dumps(event) + "\n")
        except Exception:
            pass  # Non-fatal if logging fails
    
    def get_filters(self, symbol: str) -> Optional[BinanceFilters]:
        """Get current filters for symbol."""
        return self.filters.get(symbol)
    
    def validate_and_round_order(self, symbol: str, side: str, order_type: str,
                                quantity: float, price: Optional[float] = None) -> Tuple[bool, str, float, Optional[float]]:
        """
        Validate and round order parameters.
        
        Returns:
            (is_valid, message, rounded_quantity, rounded_price)
        """
        qty_decimal = Decimal(str(quantity))
        price_decimal = Decimal(str(price)) if price is not None else None
        
        # Round to exchange precision
        qty_rounded = self._round_quantity(symbol, qty_decimal)
        price_rounded = self._round_price(symbol, price_decimal) if price_decimal else None
        
        # Validate
        rejection = self._validate_order(symbol, side, order_type, qty_rounded, price_rounded)
        if rejection:
            return False, f"{rejection.reason}: {rejection.details}", float(qty_rounded), float(price_rounded) if price_rounded else None
        
        return True, "OK", float(qty_rounded), float(price_rounded) if price_rounded else None
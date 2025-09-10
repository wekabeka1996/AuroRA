from __future__ import annotations

"""
Symbol Codec utilities

Provide a simple interface and concrete codecs for Binance and Gate formats.
"""

from dataclasses import dataclass
from typing import Protocol


class SymbolCodec(Protocol):
    def encode(self, base: str, quote: str) -> str: ...

    def decode(self, symbol: str) -> tuple[str, str]: ...


@dataclass(frozen=True)
class BinanceCodec:
    sufs: tuple[str, ...] = ("USDT", "BUSD", "USDC", "BTC", "ETH")

    def encode(self, base: str, quote: str) -> str:
        return f"{base}{quote}".upper()

    def decode(self, symbol: str) -> tuple[str, str]:
        s = symbol.replace("-", "").replace("/", "").replace("_", "").upper()
        # try known suffixes
        for suf in self.sufs:
            if s.endswith(suf) and len(s) > len(suf):
                return s[: -len(suf)], suf
        # fallback: split 3/4 last chars
        if len(s) > 4:
            return s[:-4], s[-4:]
        if len(s) > 3:
            return s[:-3], s[-3:]
        raise ValueError(f"Cannot decode symbol: {symbol}")


@dataclass(frozen=True)
class GateCodec:
    def encode(self, base: str, quote: str) -> str:
        return f"{base}_{quote}".upper()

    def decode(self, symbol: str) -> tuple[str, str]:
        s = symbol.replace("-", "/").replace("_", "/").upper()
        if "/" in s:
            base, quote = s.split("/", 1)
            return base, quote
        # fallback to Binance-like
        bnb = BinanceCodec()
        return bnb.decode(s)


__all__ = [
    "SymbolCodec",
    "BinanceCodec",
    "GateCodec",
]

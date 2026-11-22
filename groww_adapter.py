"""Read-only Groww Trading API adapter for StockAlgo.

Only authentication, market-data, profile, portfolio and order-history reads are
exposed. There are deliberately no broker order-write methods. All order
submission, modification and cancellation remain hard-disabled.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from typing import Any


class GrowwNotConfigured(RuntimeError):
    """Groww credentials or SDK are not configured."""


class GrowwAdapter:
    _token_lock = threading.Lock()
    _cached_token: str | None = None
    _cached_credential_fingerprint: str | None = None
    _token_created_at: float = 0.0
    # Conservative in-process cache. Groww's API-key flow requires daily approval.
    _token_ttl_seconds = 20 * 60 * 60
    _SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9&._-]{0,39}$")

    def __init__(self) -> None:
        self.api_key = os.getenv("GROWW_API_KEY", "").strip()
        self.api_secret = os.getenv("GROWW_API_SECRET", "").strip()
        if not self.api_key or not self.api_secret:
            raise GrowwNotConfigured(
                "Set GROWW_API_KEY and GROWW_API_SECRET in the service environment."
            )
        try:
            from growwapi import GrowwAPI
        except ImportError as exc:
            raise GrowwNotConfigured(
                "Groww SDK is not installed. Deploy the updated requirements-render.txt."
            ) from exc
        self._GrowwAPI = GrowwAPI
        self.client = GrowwAPI(self._get_access_token(GrowwAPI))

    @classmethod
    def _get_access_token(cls, sdk: Any | None = None) -> str:
        api_key = os.getenv("GROWW_API_KEY", "").strip()
        api_secret = os.getenv("GROWW_API_SECRET", "").strip()
        if not api_key or not api_secret:
            raise GrowwNotConfigured(
                "Set GROWW_API_KEY and GROWW_API_SECRET in the service environment."
            )
        fingerprint = hashlib.sha256(f"{api_key}:{api_secret}".encode()).hexdigest()
        now = time.time()
        with cls._token_lock:
            if (
                cls._cached_token
                and cls._cached_credential_fingerprint == fingerprint
                and now - cls._token_created_at < cls._token_ttl_seconds
            ):
                return cls._cached_token
            if sdk is None:
                try:
                    from growwapi import GrowwAPI as sdk
                except ImportError as exc:
                    raise GrowwNotConfigured(
                        "Groww SDK is not installed. Deploy the updated requirements-render.txt."
                    ) from exc
            # Official Groww API Key + Secret flow. Daily approval may be required
            # in Groww Cloud before token generation succeeds.
            token = sdk.get_access_token(api_key=api_key, secret=api_secret)
            if not token:
                raise RuntimeError("Groww did not return an access token.")
            cls._cached_token = str(token)
            cls._cached_credential_fingerprint = fingerprint
            cls._token_created_at = now
            return cls._cached_token

    @classmethod
    def clear_token_cache(cls) -> None:
        with cls._token_lock:
            cls._cached_token = None
            cls._cached_credential_fingerprint = None
            cls._token_created_at = 0.0

    @staticmethod
    def _plain(value: Any) -> Any:
        """Convert SDK response objects into JSON-compatible values."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): GrowwAdapter._plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [GrowwAdapter._plain(v) for v in value]
        if hasattr(value, "model_dump"):
            return GrowwAdapter._plain(value.model_dump())
        if hasattr(value, "to_dict"):
            return GrowwAdapter._plain(value.to_dict())
        if hasattr(value, "__dict__"):
            return GrowwAdapter._plain(
                {k: v for k, v in vars(value).items() if not k.startswith("_")}
            )
        return str(value)

    @staticmethod
    def _exchange(client: Any, exchange: str) -> str:
        value = exchange.strip().upper()
        if value not in {"NSE", "BSE"}:
            raise ValueError("exchange must be NSE or BSE")
        return client.EXCHANGE_NSE if value == "NSE" else client.EXCHANGE_BSE

    @staticmethod
    def _segment(client: Any, segment: str) -> str:
        value = segment.strip().upper()
        if value not in {"CASH", "FNO"}:
            raise ValueError("segment must be CASH or FNO")
        return client.SEGMENT_CASH if value == "CASH" else client.SEGMENT_FNO

    @classmethod
    def _symbol(cls, symbol: str) -> str:
        value = symbol.strip().upper()
        if not cls._SYMBOL_RE.fullmatch(value):
            raise ValueError("Invalid trading symbol")
        return value

    def profile(self) -> Any:
        return self._plain(self.client.get_user_profile())

    def quote(self, symbol: str, exchange: str = "NSE", segment: str = "CASH") -> Any:
        return self._plain(self.client.get_quote(
            exchange=self._exchange(self.client, exchange),
            segment=self._segment(self.client, segment),
            trading_symbol=self._symbol(symbol),
        ))

    def ltp(self, symbols: list[str], exchange: str = "NSE", segment: str = "CASH") -> Any:
        if not symbols or len(symbols) > 50:
            raise ValueError("Provide between 1 and 50 symbols per LTP request.")
        prefix = exchange.strip().upper()
        if prefix not in {"NSE", "BSE"}:
            raise ValueError("exchange must be NSE or BSE")
        exchange_symbols = tuple(f"{prefix}_{self._symbol(s)}" for s in symbols)
        return self._plain(self.client.get_ltp(
            segment=self._segment(self.client, segment),
            exchange_trading_symbols=exchange_symbols,
        ))

    def ohlc(self, symbols: list[str], exchange: str = "NSE", segment: str = "CASH") -> Any:
        if not symbols or len(symbols) > 50:
            raise ValueError("Provide between 1 and 50 symbols per OHLC request.")
        prefix = exchange.strip().upper()
        if prefix not in {"NSE", "BSE"}:
            raise ValueError("exchange must be NSE or BSE")
        exchange_symbols = tuple(f"{prefix}_{self._symbol(s)}" for s in symbols)
        return self._plain(self.client.get_ohlc(
            segment=self._segment(self.client, segment),
            exchange_trading_symbols=exchange_symbols,
        ))

    def holdings(self) -> Any:
        return self._plain(self.client.get_holdings_for_user(timeout=10))

    def positions(self, segment: str | None = None) -> Any:
        if segment:
            return self._plain(self.client.get_positions_for_user(
                segment=self._segment(self.client, segment)
            ))
        return self._plain(self.client.get_positions_for_user())

    def orders(self, segment: str | None = None, page: int = 0, page_size: int = 100) -> Any:
        if page < 0:
            raise ValueError("page must be zero or greater")
        kwargs: dict[str, Any] = {"page": page, "page_size": min(max(page_size, 1), 100)}
        if segment:
            kwargs["segment"] = self._segment(self.client, segment)
        return self._plain(self.client.get_order_list(**kwargs))

    def candles(
        self, symbol: str, exchange: str, start_time: str, end_time: str,
        interval_minutes: int = 5, segment: str = "CASH",
    ) -> Any:
        interval_names = {
            1: "CANDLE_INTERVAL_MIN_1", 5: "CANDLE_INTERVAL_MIN_5",
            10: "CANDLE_INTERVAL_MIN_10", 15: "CANDLE_INTERVAL_MIN_15",
            30: "CANDLE_INTERVAL_MIN_30", 60: "CANDLE_INTERVAL_HOUR_1",
            240: "CANDLE_INTERVAL_HOUR_4", 1440: "CANDLE_INTERVAL_DAY_1",
            10080: "CANDLE_INTERVAL_WEEK_1",
        }
        constant = interval_names.get(int(interval_minutes))
        if not constant or not hasattr(self.client, constant):
            raise ValueError("Unsupported candle interval: use 1, 5, 10, 15, 30, 60, 240, 1440 or 10080 minutes.")
        return self._plain(self.client.get_historical_candles(
            exchange=self._exchange(self.client, exchange),
            segment=self._segment(self.client, segment),
            groww_symbol=f"{exchange.strip().upper()}-{self._symbol(symbol)}",
            start_time=start_time,
            end_time=end_time,
            candle_interval=getattr(self.client, constant),
        ))

    # Explicit fail-closed methods prevent accidental live order activity.
    def place_order(self, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("Live Groww order placement is disabled in StockAlgo.")

    def modify_order(self, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("Live Groww order modification is disabled in StockAlgo.")

    def cancel_order(self, *args: Any, **kwargs: Any) -> None:
        raise PermissionError("Live Groww order cancellation is disabled in StockAlgo.")

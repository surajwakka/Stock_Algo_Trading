"""Read-only Groww market-data service functions."""
from groww_auth import get_groww_client


def get_quote(symbol: str, exchange: str = "NSE", segment: str = "CASH"):
    return get_groww_client().quote(symbol=symbol, exchange=exchange, segment=segment)


def get_ltp(symbols: list[str], exchange: str = "NSE", segment: str = "CASH"):
    return get_groww_client().ltp(symbols=symbols, exchange=exchange, segment=segment)


def get_ohlc(symbols: list[str], exchange: str = "NSE", segment: str = "CASH"):
    return get_groww_client().ohlc(symbols=symbols, exchange=exchange, segment=segment)


def get_historical_candles(
    symbol: str, exchange: str, start_time: str, end_time: str,
    interval_minutes: int = 5, segment: str = "CASH",
):
    return get_groww_client().candles(
        symbol, exchange, start_time, end_time, interval_minutes, segment
    )

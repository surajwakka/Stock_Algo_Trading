"""Read-only Groww account and portfolio service functions."""
from groww_auth import get_groww_client


def get_profile():
    return get_groww_client().profile()


def get_holdings():
    return get_groww_client().holdings()


def get_positions(segment: str | None = None):
    return get_groww_client().positions(segment=segment)

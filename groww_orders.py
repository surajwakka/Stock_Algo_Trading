"""Read-only Groww order history. No submit/modify/cancel operations are exposed."""
from groww_auth import get_groww_client


def get_order_history(segment: str | None = None, page: int = 0, page_size: int = 100):
    return get_groww_client().orders(segment=segment, page=page, page_size=page_size)

"""Groww authentication facade. Credentials are read only from environment."""
from groww_adapter import GrowwAdapter, GrowwNotConfigured


def get_groww_client() -> GrowwAdapter:
    return GrowwAdapter()


__all__ = ["get_groww_client", "GrowwAdapter", "GrowwNotConfigured"]

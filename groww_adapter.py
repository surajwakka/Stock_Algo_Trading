"""Groww adapter placeholder. Live authentication and order placement are disabled."""
class GrowwAdapter:
    def __init__(self, *args, **kwargs):
        raise PermissionError("Groww integration is disabled in this paper-only release.")
    def place_limit(self, *args, **kwargs):
        raise PermissionError("Live broker orders are disabled.")

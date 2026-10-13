"""Errors raised by inventory services. Messages are user-facing (Korean)."""


class InventoryError(Exception):
    """A request that cannot be applied. str(error) is shown to the user."""


class NotFound(InventoryError):
    """The referenced record does not exist."""

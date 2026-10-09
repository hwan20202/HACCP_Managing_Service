"""Quantity scaling for *_e6 columns (rule S3): stored integer = base-unit quantity x 1,000,000."""

from decimal import Decimal, InvalidOperation

SCALE = 1_000_000


def to_e6(value):
    """Convert a quantity in the base unit to the stored integer.

    Accepts int, Decimal or str. float is rejected because it cannot represent
    values such as 0.1 exactly. More than 6 decimal places is an error, not rounding.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("Use int, Decimal or str for quantities, not float.")
    try:
        number = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"Not a number: {value!r}") from error
    if not number.is_finite():
        raise ValueError(f"Not a finite number: {value!r}")
    scaled = number * SCALE
    if scaled != scaled.to_integral_value():
        raise ValueError(f"More than 6 decimal places: {value!r}")
    return int(scaled)


def from_e6(value):
    """Convert a stored integer back to a Decimal in the base unit, without trailing zeros."""
    number = Decimal(value) / SCALE
    return (
        number.quantize(Decimal(1)) if number == number.to_integral_value() else number.normalize()
    )

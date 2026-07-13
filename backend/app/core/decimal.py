from decimal import Decimal

CNY_CENT = Decimal("0.01")
DB_QUANTUM = Decimal("0.000000000001")
NUMERIC_28_12_MAX_INTEGER_DIGITS = 16
NUMERIC_28_12_MAX_FRACTIONAL_DIGITS = 12


def quantize_cny(value: Decimal) -> Decimal:
    return value.quantize(CNY_CENT)


def fits_numeric_28_12(value: Decimal) -> bool:
    if not value.is_finite():
        return False
    if value.is_zero():
        return True

    _, raw_digits, raw_exponent = value.as_tuple()
    digits = list(raw_digits)
    exponent = raw_exponent
    while exponent < 0 and digits[-1] == 0:
        digits.pop()
        exponent += 1

    integer_digits = max(len(digits) + exponent, 0)
    fractional_digits = max(-exponent, 0)
    return (
        integer_digits <= NUMERIC_28_12_MAX_INTEGER_DIGITS
        and fractional_digits <= NUMERIC_28_12_MAX_FRACTIONAL_DIGITS
    )

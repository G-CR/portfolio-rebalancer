from decimal import Decimal

CNY_CENT = Decimal("0.01")
DB_QUANTUM = Decimal("0.000000000001")


def quantize_cny(value: Decimal) -> Decimal:
    return value.quantize(CNY_CENT)

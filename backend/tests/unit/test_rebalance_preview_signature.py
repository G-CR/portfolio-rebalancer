from app.services.rebalance_version import rebalance_preview_input_signature


def _signature(
    *,
    price: str = "100",
    holding_version: int = 1,
    target: str = "0.5",
) -> str:
    return rebalance_preview_input_signature(
        effective_inputs={"price:ETF": (price, "valid", "source-1", "CNY")},
        holding_versions={"holding-1": holding_version},
        asset_class_targets={"class-1": target},
    )


def test_preview_signature_is_stable_for_equal_inputs() -> None:
    assert _signature() == _signature()


def test_preview_signature_changes_when_price_holding_or_target_changes() -> None:
    baseline = _signature()
    assert _signature(price="101") != baseline
    assert _signature(holding_version=2) != baseline
    assert _signature(target="0.6") != baseline

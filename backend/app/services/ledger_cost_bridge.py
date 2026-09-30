"""Compatibility bridge for existing holding drawers and legacy audit APIs."""
from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select, func

from app.db.ledger_models import LedgerEntry, LedgerPeriod
from app.domain.cost_basis import CostBasis, resolve_fee
from app.schemas.ledger import EntryRequest
from app.schemas.cost_adjustment import CostAdjustmentPreviewResponse, CostBasisStateResponse, FeePreviewResponse
from app.services.errors import ServiceError
from app.services.reference_fx import reference_for, shanghai_today


async def request_for(session, holding, operation, payload, idempotency_key=None):
    from app.services.cost_adjustments import _get_holding_defaults, _resolve_fee_defaults
    from app.services.ledger import digest
    currency = holding.trade_currency
    if operation == 'purchase':
        from app.services.cost_adjustments import _validate_fee_default_save
        _validate_fee_default_save(payload)
        defaults = await _get_holding_defaults(session, holding.id)
        resolved = _resolve_fee_defaults(holding, defaults, payload)
        fee = resolve_fee(trade_value=payload.quantity * payload.price, quantity=payload.quantity,
            rule=resolved.rule, actual_fee=payload.actual_fee)
        fee_currency = resolved.fee_currency
    else:
        if payload.price is None:
            raise ServiceError(422, 'LEDGER_SALE_PRICE_REQUIRED', '启用账本后卖出需要成交价格，不能将未知收入记为零。')
        fee, fee_currency = payload.fee, payload.fee_currency or currency
    return EntryRequest(holding_id=holding.id, kind='purchase' if operation == 'purchase' else 'sale',
        occurred_on=payload.occurred_on or shanghai_today(), quantity=payload.quantity, price=payload.price,
        fee=fee, fee_currency=fee_currency, note=payload.note,
        idempotency_key=idempotency_key or digest({'holding': str(holding.id), 'version': holding.version, 'operation': operation, 'payload': payload.model_dump(mode='json')}))


async def ledger_preview(session, holding, operation, payload, idempotency_key=None):
    from app.services.ledger import preview_entry
    from app.services.cost_adjustments import _basis_response, _holding_cost_basis
    request = await request_for(session, holding, operation, payload, idempotency_key)
    preview = await preview_entry(session, request)
    after_quantity = Decimal(preview['after']['quantity'])
    after_price = Decimal(preview['after']['average_cost_price'])
    fx_estimate = holding.cost_fx_to_cny if after_quantity else Decimal(0)
    fee_rate = preview['reference_details']['fee'].get('rate')
    fee_cny = request.fee * Decimal(fee_rate) if fee_rate is not None else Decimal(0) if request.fee == 0 else None
    return CostAdjustmentPreviewResponse(holding_id=holding.id, holding_version=holding.version, operation=operation,
        before=_basis_response(_holding_cost_basis(holding), holding.quantity_precision),
        after=CostBasisStateResponse(quantity=str(after_quantity), average_cost_price=str(after_price),
            cost_fx_to_cny=str(fx_estimate), total_cost_cny=str(after_quantity * after_price * fx_estimate)), note=payload.note,
        preview_token=preview['preview_token'], reference_details=preview['reference_details'],
        fee=FeePreviewResponse(mode='actual' if operation == 'sell' or payload.actual_fee is not None else 'estimated',
            currency=request.fee_currency, amount=str(request.fee), amount_cny=str(fee_cny) if fee_cny is not None else None),
        original_cost=preview['after']['original_cost'], reference_label='人民币成本为旧口径历史估算；期间参考损益见投资记录')


async def automatic_purchase_preview(session, holding, defaults, payload):
    """Pre-opening legacy holding update using automatic spot reference, preserving estimate."""
    from app.services.cost_adjustments import PreviewResult, FeePreview, _holding_cost_basis, _resolve_fee_defaults, _storage_basis
    from app.services.cost_adjustments import _validate_fee_default_save
    _validate_fee_default_save(payload)
    resolved = _resolve_fee_defaults(holding, defaults, payload)
    fee = resolve_fee(trade_value=payload.quantity * payload.price, quantity=payload.quantity, rule=resolved.rule, actual_fee=payload.actual_fee)
    day = payload.occurred_on or shanghai_today()
    fx, _ = await reference_for(session, holding.trade_currency, day)
    fee_fx, _ = await reference_for(session, resolved.fee_currency, day)
    if resolved.fee_currency == holding.trade_currency:
        fee_original = fee
    elif fee == 0:
        fee_original = Decimal(0)
    elif fx is None or fee_fx is None:
        raise ServiceError(409, 'LEDGER_OPENING_REQUIRED', '跨币种费用参考汇率缺失，请先建立长期账本以保存待补全操作。')
    else:
        fee_original = fee * fee_fx / fx
    before = _holding_cost_basis(holding)
    quantity = holding.quantity + payload.quantity
    cost = holding.quantity * holding.average_cost_price + payload.quantity * payload.price + fee_original
    # Existing estimate stays explicitly an estimate, not a fabricated operation FX.
    after = _storage_basis(CostBasis(quantity=quantity, average_price=cost / quantity, cost_fx=holding.cost_fx_to_cny))
    return PreviewResult(operation='purchase', operation_type='PURCHASE', before=before, after=after,
        fee=FeePreview(mode='actual' if payload.actual_fee is not None else 'estimated', currency=resolved.fee_currency, amount=fee, amount_cny=fee * fee_fx if fee_fx is not None else Decimal(0)),
        note=payload.note, input_summary={**payload.model_dump(mode='json'), 'reference_fx': str(fx) if fx is not None else None, 'reference_pending': fx is None, 'reference_only': True})


async def record_external_change(session, holding, reason, note=None):
    """Record a genuine data correction/legacy replacement without inventing cashflow."""
    period = await session.scalar(select(LedgerPeriod).where(LedgerPeriod.singleton == 1).with_for_update())
    if not period:
        return
    sequence = (await session.scalar(select(func.max(LedgerEntry.sequence)))) or 0
    session.add(LedgerEntry(id=uuid4(), period_id=period.id, holding_id=holding.id,
        kind='manual_correction', occurred_on=shanghai_today(), sequence=sequence + 1,
        currency=holding.trade_currency, fee_currency=holding.trade_currency,
        quantity=holding.quantity, price=Decimal(0), amount=holding.quantity * holding.average_cost_price,
        fee=Decimal(0), fee_original=Decimal(0), ratio=Decimal(1), reference_details={},
        idempotency_key=f'external:{uuid4()}', request_hash='external_correction',
        incomplete_reason=reason, note=note))
    await session.flush()

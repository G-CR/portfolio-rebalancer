from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CostAdjustment, Holding, HoldingDefault, utcnow
from app.domain.cost_basis import CostBasis, FeeRule, Purchase, add_purchase, resolve_fee, sell_quantity
from app.schemas.cost_adjustment import (
    CostAdjustmentCollectionResponse,
    CostAdjustmentConfirmRequest,
    CostAdjustmentHistoryItemResponse,
    CostAdjustmentPreviewResponse,
    CostBasisStateResponse,
    FeePreviewResponse,
    HoldingDefaultsResponse,
    ManualCorrectionPreviewRequest,
    PurchasePreviewRequest,
    RestoreConfirmPayload,
    RestorePreviewRequest,
    SellPreviewRequest,
)
from app.services.errors import ServiceError

_CNY = "CNY"
_ZERO = Decimal("0")
_CENT = Decimal("0.01")
_STORAGE_SCALE = Decimal("0.000000000001")
_FEE_RULE_FIELDS = (
    "commission_rate",
    "minimum_commission",
    "per_share_fee",
    "fixed_fee",
)
_OperationPayload = TypeVar("_OperationPayload", bound=BaseModel)


@dataclass(frozen=True)
class ResolvedFeeDefaults:
    fee_currency: str
    rule: FeeRule


@dataclass(frozen=True)
class FeePreview:
    mode: str
    currency: str
    amount: Decimal
    amount_cny: Decimal


@dataclass(frozen=True)
class PreviewResult:
    operation: str
    operation_type: str
    before: CostBasis
    after: CostBasis
    fee: FeePreview | None
    note: str | None
    input_summary: dict[str, object]


async def get_adjustment_context(
    session: AsyncSession, holding_id: UUID
) -> CostAdjustmentCollectionResponse:
    holding = await _get_active_holding(session, holding_id)
    defaults = await _get_holding_defaults(session, holding.id)
    adjustments = list(
        await session.scalars(
            select(CostAdjustment)
            .where(CostAdjustment.holding_id == holding.id)
            .order_by(CostAdjustment.created_at.asc(), CostAdjustment.id.asc())
        )
    )

    return CostAdjustmentCollectionResponse(
        holding_id=holding.id,
        holding_version=holding.version,
        defaults=_defaults_response(defaults),
        items=[
            CostAdjustmentHistoryItemResponse(
                id=item.id,
                operation_type=item.operation_type,
                before=_history_basis_response(
                    _normalized_cost_basis(
                        quantity=item.before_quantity,
                        average_price=item.before_average_cost_price,
                        cost_fx=item.before_cost_fx_to_cny,
                    )
                ),
                after=_history_basis_response(
                    _normalized_cost_basis(
                        quantity=item.after_quantity,
                        average_price=item.after_average_cost_price,
                        cost_fx=item.after_cost_fx_to_cny,
                    )
                ),
                input_summary=item.input_summary,
                note=item.note,
                created_at=item.created_at,
            )
            for item in adjustments
        ],
    )


async def preview_purchase(
    session: AsyncSession,
    holding_id: UUID,
    payload: PurchasePreviewRequest,
) -> CostAdjustmentPreviewResponse:
    try:
        holding = await _get_active_holding(session, holding_id)
        defaults = await _get_holding_defaults(session, holding.id)
        preview = _preview_purchase_from_holding(holding, defaults, payload)
        return _preview_response(holding, preview)
    except InvalidOperation as exc:
        raise _numeric_range_error() from exc


async def preview_sell(
    session: AsyncSession,
    holding_id: UUID,
    payload: SellPreviewRequest,
) -> CostAdjustmentPreviewResponse:
    try:
        holding = await _get_active_holding(session, holding_id)
        preview = _preview_sell_from_holding(holding, payload)
        return _preview_response(holding, preview)
    except InvalidOperation as exc:
        raise _numeric_range_error() from exc


async def preview_correction(
    session: AsyncSession,
    holding_id: UUID,
    payload: ManualCorrectionPreviewRequest,
) -> CostAdjustmentPreviewResponse:
    try:
        holding = await _get_active_holding(session, holding_id)
        preview = _preview_correction_from_holding(holding, payload)
        return _preview_response(holding, preview)
    except InvalidOperation as exc:
        raise _numeric_range_error() from exc


async def preview_restore(
    session: AsyncSession,
    holding_id: UUID,
    adjustment_id: UUID,
    payload: RestorePreviewRequest,
) -> CostAdjustmentPreviewResponse:
    try:
        holding = await _get_active_holding(session, holding_id)
        adjustment = await _get_cost_adjustment(session, holding.id, adjustment_id)
        preview = _preview_restore_from_holding(holding, adjustment, payload)
        return _preview_response(holding, preview)
    except InvalidOperation as exc:
        raise _numeric_range_error() from exc


async def confirm_adjustment(
    session: AsyncSession,
    holding_id: UUID,
    request: CostAdjustmentConfirmRequest,
) -> CostAdjustmentPreviewResponse:
    holding = await _get_active_holding(session, holding_id, lock=True)
    if holding.version != request.expected_version:
        raise ServiceError(
            409,
            "STALE_COST_PREVIEW",
            "Holding was modified after the preview was generated.",
            {"current_version": holding.version},
        )

    try:
        preview = await _preview_for_confirmation(session, holding, request)
    except InvalidOperation as exc:
        raise _numeric_range_error() from exc
    before = preview.before
    after = preview.after

    holding.quantity = after.quantity
    holding.average_cost_price = after.average_price
    holding.cost_fx_to_cny = after.cost_fx
    holding.updated_at = utcnow()

    if request.operation == "purchase":
        purchase_payload = PurchasePreviewRequest.model_validate(request.payload)
        if purchase_payload.save_fee_defaults:
            await _persist_fee_defaults(session, holding.id, purchase_payload)

    adjustment = CostAdjustment(
        holding_id=holding.id,
        operation_type=preview.operation_type,
        before_quantity=before.quantity,
        before_average_cost_price=before.average_price,
        before_cost_fx_to_cny=before.cost_fx,
        after_quantity=after.quantity,
        after_average_cost_price=after.average_price,
        after_cost_fx_to_cny=after.cost_fx,
        input_summary=preview.input_summary,
        note=preview.note,
        created_at=utcnow(),
    )
    session.add(adjustment)
    await session.flush()

    try:
        response = _preview_response(holding, preview)
    except InvalidOperation as exc:
        raise _numeric_range_error() from exc
    return response.model_copy(
        update={"holding_version": holding.version, "adjustment_id": adjustment.id}
    )


async def _preview_for_confirmation(
    session: AsyncSession,
    holding: Holding,
    request: CostAdjustmentConfirmRequest,
) -> PreviewResult:
    if request.operation == "purchase":
        defaults = await _get_holding_defaults(session, holding.id)
        payload = _validate_operation_payload(PurchasePreviewRequest, request.payload)
        return _preview_purchase_from_holding(holding, defaults, payload)
    if request.operation == "sell":
        payload = _validate_operation_payload(SellPreviewRequest, request.payload)
        return _preview_sell_from_holding(holding, payload)
    if request.operation == "manual_correction":
        payload = _validate_operation_payload(
            ManualCorrectionPreviewRequest,
            request.payload,
        )
        return _preview_correction_from_holding(holding, payload)
    if request.operation == "restore":
        confirm_payload = _validate_operation_payload(
            RestoreConfirmPayload,
            request.payload,
        )
        payload = RestorePreviewRequest(note=confirm_payload.note)
        adjustment = await _get_cost_adjustment(
            session,
            holding.id,
            confirm_payload.adjustment_id,
        )
        return _preview_restore_from_holding(holding, adjustment, payload)
    raise ServiceError(422, "UNSUPPORTED_COST_OPERATION", "Unsupported cost operation.")


def _preview_purchase_from_holding(
    holding: Holding,
    defaults: HoldingDefault | None,
    payload: PurchasePreviewRequest,
) -> PreviewResult:
    _validate_fee_default_save(payload)
    before = _holding_cost_basis(holding)
    resolved_defaults = _resolve_fee_defaults(holding, defaults, payload)
    trade_value = payload.quantity * payload.price
    fee_amount = resolve_fee(
        trade_value=trade_value,
        quantity=payload.quantity,
        rule=resolved_defaults.rule,
        actual_fee=payload.actual_fee,
    )
    fee_currency = resolved_defaults.fee_currency
    fee_trade_currency = fee_amount if fee_currency == holding.trade_currency else _ZERO
    fee_cny = fee_amount if fee_currency == _CNY else _ZERO
    after = _storage_basis(
        add_purchase(
            before,
            Purchase(
                quantity=payload.quantity,
                price=payload.price,
                fx=payload.fx,
                fee_trade_currency=fee_trade_currency,
                fee_cny=fee_cny,
            ),
        )
    )

    fee_amount_cny = fee_amount if fee_currency == _CNY else fee_amount * payload.fx

    return PreviewResult(
        operation="purchase",
        operation_type="PURCHASE",
        before=before,
        after=after,
        fee=FeePreview(
            mode="actual" if payload.actual_fee is not None else "estimated",
            currency=fee_currency,
            amount=fee_amount,
            amount_cny=fee_amount_cny,
        ),
        note=_normalized_optional_note(payload.note),
        input_summary={
            "quantity": _decimal_string(payload.quantity),
            "price": _decimal_string(payload.price),
            "fx": _decimal_string(payload.fx),
            "fee_currency": fee_currency,
            "commission_rate": _decimal_string(resolved_defaults.rule.commission_rate),
            "minimum_commission": _decimal_string(resolved_defaults.rule.minimum_commission),
            "per_share_fee": _decimal_string(resolved_defaults.rule.per_share_fee),
            "fixed_fee": _decimal_string(resolved_defaults.rule.fixed_fee),
            "actual_fee": (
                _decimal_string(payload.actual_fee) if payload.actual_fee is not None else None
            ),
            "resolved_fee": _decimal_string(fee_amount),
            "resolved_fee_cny": _decimal_string(fee_amount_cny),
            "save_fee_defaults": payload.save_fee_defaults,
        },
    )


def _preview_sell_from_holding(
    holding: Holding,
    payload: SellPreviewRequest,
) -> PreviewResult:
    before = _holding_cost_basis(holding)
    try:
        after = _storage_basis(sell_quantity(before, payload.quantity))
    except ValueError as exc:
        raise ServiceError(
            422,
            "SELL_QUANTITY_EXCEEDS_HOLDING",
            "Sell quantity cannot exceed the current holding quantity.",
            {
                "current_quantity": _decimal_string(before.quantity),
                "requested_quantity": _decimal_string(payload.quantity),
            },
        ) from exc

    return PreviewResult(
        operation="sell",
        operation_type="SELL",
        before=before,
        after=after,
        fee=None,
        note=_normalized_optional_note(payload.note),
        input_summary={
            "quantity": _decimal_string(payload.quantity),
            "note": _normalized_optional_note(payload.note),
        },
    )


def _preview_correction_from_holding(
    holding: Holding,
    payload: ManualCorrectionPreviewRequest,
) -> PreviewResult:
    note = _require_nonempty_note(
        payload.note,
        code="MANUAL_CORRECTION_NOTE_REQUIRED",
        message="Manual correction requires a note.",
    )
    before = _holding_cost_basis(holding)
    try:
        after = _normalized_cost_basis(
            quantity=payload.quantity,
            average_price=payload.average_cost_price,
            cost_fx=payload.cost_fx_to_cny,
        )
    except ValueError as exc:
        raise ServiceError(422, "INVALID_COST_BASIS", str(exc)) from exc

    return PreviewResult(
        operation="manual_correction",
        operation_type="MANUAL_CORRECTION",
        before=before,
        after=after,
        fee=None,
        note=note,
        input_summary={
            "quantity": _decimal_string(payload.quantity),
            "average_cost_price": _decimal_string(payload.average_cost_price),
            "cost_fx_to_cny": _decimal_string(payload.cost_fx_to_cny),
            "note": note,
        },
    )


def _preview_restore_from_holding(
    holding: Holding,
    adjustment: CostAdjustment,
    payload: RestorePreviewRequest,
) -> PreviewResult:
    note = _require_nonempty_note(
        payload.note,
        code="RESTORE_NOTE_REQUIRED",
        message="Restore requires a note.",
    )
    before = _holding_cost_basis(holding)
    after = _normalized_cost_basis(
        quantity=adjustment.after_quantity,
        average_price=adjustment.after_average_cost_price,
        cost_fx=adjustment.after_cost_fx_to_cny,
    )
    return PreviewResult(
        operation="restore",
        operation_type="MANUAL_CORRECTION",
        before=before,
        after=after,
        fee=None,
        note=note,
        input_summary={
            "source_adjustment_id": str(adjustment.id),
            "note": note,
        },
    )


async def _persist_fee_defaults(
    session: AsyncSession,
    holding_id: UUID,
    payload: PurchasePreviewRequest,
) -> None:
    holding = await _get_active_holding(session, holding_id)
    existing = await _get_holding_defaults(session, holding_id)
    resolved = _resolve_fee_defaults(holding, existing, payload)
    if existing is None:
        existing = HoldingDefault(
            holding_id=holding_id,
            fee_currency=resolved.fee_currency,
            commission_rate=resolved.rule.commission_rate,
            minimum_commission=resolved.rule.minimum_commission,
            per_share_fee=resolved.rule.per_share_fee,
            fixed_fee=resolved.rule.fixed_fee,
        )
        session.add(existing)
        return

    existing.fee_currency = resolved.fee_currency
    existing.commission_rate = resolved.rule.commission_rate
    existing.minimum_commission = resolved.rule.minimum_commission
    existing.per_share_fee = resolved.rule.per_share_fee
    existing.fixed_fee = resolved.rule.fixed_fee


def _resolve_fee_defaults(
    holding: Holding,
    defaults: HoldingDefault | None,
    payload: PurchasePreviewRequest,
) -> ResolvedFeeDefaults:
    fee_currency = (payload.fee_currency or (defaults.fee_currency if defaults else None) or holding.trade_currency).upper()
    allowed_currencies = {holding.trade_currency, _CNY}
    if fee_currency not in allowed_currencies:
        raise ServiceError(
            422,
            "INVALID_FEE_CURRENCY",
            "Fee currency must be the holding trade currency or CNY.",
            {"fee_currency": fee_currency, "trade_currency": holding.trade_currency},
        )

    return ResolvedFeeDefaults(
        fee_currency=fee_currency,
        rule=FeeRule(
            commission_rate=_or_default(
                payload.commission_rate,
                defaults.commission_rate if defaults else None,
            ),
            minimum_commission=_or_default(
                payload.minimum_commission,
                defaults.minimum_commission if defaults else None,
            ),
            per_share_fee=_or_default(
                payload.per_share_fee,
                defaults.per_share_fee if defaults else None,
            ),
            fixed_fee=_or_default(
                payload.fixed_fee,
                defaults.fixed_fee if defaults else None,
            ),
        ),
    )


def _preview_response(
    holding: Holding,
    preview: PreviewResult,
) -> CostAdjustmentPreviewResponse:
    return CostAdjustmentPreviewResponse(
        holding_id=holding.id,
        holding_version=holding.version,
        operation=preview.operation,  # type: ignore[arg-type]
        before=_basis_response(preview.before, holding.quantity_precision),
        after=_basis_response(preview.after, holding.quantity_precision),
        fee=(
            FeePreviewResponse(
                mode=preview.fee.mode,  # type: ignore[arg-type]
                currency=preview.fee.currency,
                amount=_price_decimal(preview.fee.amount),
                amount_cny=_money_decimal(preview.fee.amount_cny),
            )
            if preview.fee is not None
            else None
        ),
        note=preview.note,
    )


def _basis_response(value: CostBasis, quantity_precision: int) -> CostBasisStateResponse:
    return CostBasisStateResponse(
        quantity=_scale_decimal(value.quantity, quantity_precision),
        average_cost_price=_price_decimal(value.average_price),
        cost_fx_to_cny=_trim_decimal(value.cost_fx),
        total_cost_cny=_money_decimal(value.total_cost_cny),
    )


def _history_basis_response(value: CostBasis) -> CostBasisStateResponse:
    return CostBasisStateResponse(
        quantity=_trim_decimal(value.quantity),
        average_cost_price=_price_decimal(value.average_price),
        cost_fx_to_cny=_trim_decimal(value.cost_fx),
        total_cost_cny=_money_decimal(value.total_cost_cny),
    )


def _validate_operation_payload(
    model: type[_OperationPayload],
    payload: dict[str, object],
) -> _OperationPayload:
    try:
        return model.model_validate(payload, extra="forbid")
    except ValidationError as exc:
        errors = [
            {
                "field": ".".join(("payload", *(str(part) for part in error["loc"]))),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        if any(
            error["type"] == "cost_adjustment_numeric_out_of_range"
            for error in exc.errors()
        ):
            raise ServiceError(
                422,
                "COST_ADJUSTMENT_NUMERIC_OUT_OF_RANGE",
                "Cost adjustment numeric fields must fit NUMERIC(28,12).",
                {"errors": errors},
            ) from exc
        raise ServiceError(
            422,
            "INVALID_COST_ADJUSTMENT_PAYLOAD",
            "Cost adjustment payload is invalid for the operation.",
            {"errors": errors},
        ) from exc


def _validate_fee_default_save(payload: PurchasePreviewRequest) -> None:
    if not payload.save_fee_defaults:
        return
    missing_fields = [
        field_name
        for field_name in _FEE_RULE_FIELDS
        if getattr(payload, field_name) is None
    ]
    if missing_fields:
        raise ServiceError(
            422,
            "INCOMPLETE_FEE_DEFAULT_RULE",
            "Saving fee defaults requires all four fee rule fields.",
            {"missing_fields": missing_fields},
        )


def _numeric_range_error() -> ServiceError:
    return ServiceError(
        422,
        "COST_ADJUSTMENT_NUMERIC_OUT_OF_RANGE",
        "Cost adjustment numeric fields must fit NUMERIC(28,12).",
    )


def _defaults_response(defaults: HoldingDefault | None) -> HoldingDefaultsResponse | None:
    if defaults is None:
        return None
    return HoldingDefaultsResponse(
        fee_currency=defaults.fee_currency,
        commission_rate=_trim_decimal(defaults.commission_rate),
        minimum_commission=_trim_decimal(defaults.minimum_commission),
        per_share_fee=_trim_decimal(defaults.per_share_fee),
        fixed_fee=_trim_decimal(defaults.fixed_fee),
    )


async def _get_active_holding(
    session: AsyncSession,
    holding_id: UUID,
    *,
    lock: bool = False,
) -> Holding:
    statement = select(Holding).where(
        Holding.id == holding_id,
        Holding.is_active.is_(True),
    )
    if lock:
        statement = statement.with_for_update()
    holding = await session.scalar(statement)
    if holding is None:
        raise ServiceError(404, "HOLDING_NOT_FOUND", "Active holding was not found.")
    return holding


async def _get_holding_defaults(
    session: AsyncSession, holding_id: UUID
) -> HoldingDefault | None:
    return await session.scalar(
        select(HoldingDefault).where(HoldingDefault.holding_id == holding_id)
    )


async def _get_cost_adjustment(
    session: AsyncSession,
    holding_id: UUID,
    adjustment_id: UUID,
) -> CostAdjustment:
    adjustment = await session.scalar(
        select(CostAdjustment).where(
            CostAdjustment.id == adjustment_id,
            CostAdjustment.holding_id == holding_id,
        )
    )
    if adjustment is None:
        raise ServiceError(
            404,
            "COST_ADJUSTMENT_NOT_FOUND",
            "Cost adjustment record was not found for the holding.",
        )
    return adjustment


def _holding_cost_basis(holding: Holding) -> CostBasis:
    return _normalized_cost_basis(
        quantity=holding.quantity,
        average_price=holding.average_cost_price,
        cost_fx=holding.cost_fx_to_cny,
    )


def _or_default(value: Decimal | None, fallback: Decimal | None) -> Decimal:
    if value is not None:
        return value
    if fallback is not None:
        return fallback
    return _ZERO


def _storage_basis(value: CostBasis) -> CostBasis:
    if value.quantity == 0:
        return CostBasis(
            quantity=_ZERO,
            average_price=_ZERO,
            cost_fx=_ZERO,
            _total_cost_cny=_ZERO,
        )

    quantity = value.quantity.quantize(_STORAGE_SCALE)
    average_price = value.average_price.quantize(_STORAGE_SCALE)
    cost_fx = value.cost_fx.quantize(_STORAGE_SCALE)
    return CostBasis(
        quantity=quantity,
        average_price=average_price,
        cost_fx=cost_fx,
        _total_cost_cny=quantity * average_price * cost_fx,
    )


def _normalized_cost_basis(
    *, quantity: Decimal, average_price: Decimal, cost_fx: Decimal
) -> CostBasis:
    if quantity == 0:
        return CostBasis(
            quantity=_ZERO,
            average_price=_ZERO,
            cost_fx=_ZERO,
            _total_cost_cny=_ZERO,
        )
    return _storage_basis(
        CostBasis(
            quantity=quantity,
            average_price=average_price,
            cost_fx=cost_fx,
        )
    )


def _require_nonempty_note(note: str | None, *, code: str, message: str) -> str:
    normalized = _normalized_optional_note(note)
    if normalized:
        return normalized
    raise ServiceError(422, code, message)


def _normalized_optional_note(note: str | None) -> str | None:
    if note is None:
        return None
    normalized = note.strip()
    if not normalized:
        return None
    return normalized


def _trim_decimal(value: Decimal) -> str:
    normalized = format(value.normalize(), "f")
    if normalized == "-0":
        return "0"
    return normalized


def _scale_decimal(value: Decimal, scale: int) -> str:
    if scale <= 0:
        return format(value.quantize(Decimal("1")), "f")
    quantum = Decimal("1").scaleb(-scale)
    return format(value.quantize(quantum), "f")


def _price_decimal(value: Decimal) -> str:
    trimmed = _trim_decimal(value)
    if "." not in trimmed:
        return f"{trimmed}.00"

    integer, fraction = trimmed.split(".", 1)
    if len(fraction) == 1:
        return f"{integer}.{fraction}0"
    return trimmed


def _money_decimal(value: Decimal) -> str:
    return format(value.quantize(_CENT), "f")


def _decimal_string(value: Decimal) -> str:
    return format(value, "f")

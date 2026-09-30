from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Holding, MarketData, CostAdjustment
from app.db.ledger_models import LedgerEntry, LedgerOpening, LedgerPeriod, ReferenceFxRevision
from app.domain.ledger import Entry, replay
from app.schemas.ledger import EntryRequest, OpeningRequest
from app.core.decimal import fits_numeric_28_12
from app.services.errors import ServiceError
from app.services.reference_fx import reference_for, shanghai_today

ZERO = Decimal(0)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def request_hash(request) -> str:
    return digest(request.model_dump(mode='json', exclude={'preview_token'}))


def number(value):
    return str(value) if value is not None else None


async def get_period(session, *, lock=False):
    statement = select(LedgerPeriod).where(LedgerPeriod.singleton == 1)
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def _price(session, holding):
    return await _current_value(session, 'price', holding.symbol)


async def _current_value(session, data_type, symbol):
    from app.services.analytics import _load_market_rows, _load_override_rows, _resolve_effective_values
    keys = {(data_type, symbol)}
    automated = await _load_market_rows(session, keys)
    manual = await _load_override_rows(session, keys)
    value = _resolve_effective_values(keys, automated_rows=automated, override_rows=manual)[f'{data_type}:{symbol}']
    return value.value


async def preview_opening(session: AsyncSession, request: OpeningRequest):
    if await get_period(session):
        raise ServiceError(409, 'LEDGER_ALREADY_OPEN', '长期账本已启用，请勿重复建立期初。')
    holdings = list(await session.scalars(select(Holding).where(Holding.is_active.is_(True)).order_by(Holding.id)))
    items = []
    today = shanghai_today()
    for holding in holdings:
        price = await _price(session, holding)
        fx, details = await reference_for(session, holding.trade_currency, today)
        items.append(dict(holding_id=str(holding.id), symbol=holding.symbol, name=holding.name,
            account_name=holding.account_name, currency=holding.trade_currency,
            version=holding.version, quantity=number(holding.quantity),
            average_cost_price=number(holding.average_cost_price), original_cost=number(holding.quantity * holding.average_cost_price),
            legacy_cost_fx=number(holding.cost_fx_to_cny), baseline_fx=number(holding.baseline_fx_to_cny),
            market_price=number(price), reference_fx=number(fx),
            reference_value_cny=number(holding.quantity * price * fx) if price is not None and fx is not None else None,
            reference_details=details))
    payload = {'opened_on': today.isoformat(), 'items': items}
    return {**payload, 'preview_token': digest(payload), 'mode': 'current_day', 'legacy_cost_label': '旧成本汇率为历史估算，不代表实际换汇成本'}


async def confirm_opening(session: AsyncSession, request: OpeningRequest):
    existing = await get_period(session, lock=True)
    if existing:
        if existing.idempotency_key == request.idempotency_key and existing.request_hash == request_hash(request):
            return {'period_id': str(existing.id), 'opened_on': existing.opened_on.isoformat()}
        raise ServiceError(409, 'LEDGER_ALREADY_OPEN', '长期账本已启用。')
    # Lock all holdings so preview state cannot change during the opening write.
    await session.execute(select(Holding).where(Holding.is_active.is_(True)).with_for_update())
    preview = await preview_opening(session, request)
    if not request.preview_token or request.preview_token != preview['preview_token']:
        raise ServiceError(409, 'STALE_LEDGER_PREVIEW', '期初持仓或行情已变化，请重新预览。')
    period = LedgerPeriod(id=uuid4(), opened_on=shanghai_today(), idempotency_key=request.idempotency_key, request_hash=request_hash(request))
    session.add(period)
    await session.flush()
    for item in preview['items']:
        session.add(LedgerOpening(period_id=period.id, holding_id=UUID(item['holding_id']),
            trade_currency=item['currency'], symbol=item['symbol'], account_name=item['account_name'],
            **{key: Decimal(item[key]) if item[key] is not None else None for key in ['quantity', 'average_cost_price', 'original_cost', 'legacy_cost_fx', 'baseline_fx', 'market_price', 'reference_fx', 'reference_value_cny']},
            reference_details=item['reference_details']))
    await session.flush()
    return {'period_id': str(period.id), 'opened_on': period.opened_on.isoformat()}


async def _entries(session, holding_id):
    return list(await session.scalars(select(LedgerEntry).where(LedgerEntry.holding_id == holding_id).order_by(LedgerEntry.occurred_on, LedgerEntry.sequence)))


def effective_entries(entries):
    reversed_ids = {entry.reverses_id for entry in entries if entry.kind == 'reversal'}
    return [entry for entry in entries if entry.kind != 'reversal' and entry.id not in reversed_ids]


def replay_entries(opening, entries, trade_currency):
    domain = []
    for item in effective_entries(entries):
        # Dividends in another currency are grouped separately, never added to holding currency.
        if item.kind == 'dividend' and item.currency != trade_currency:
            continue
        domain.append(Entry(kind=item.kind, occurred_on=item.occurred_on, sequence=item.sequence,
            quantity=item.quantity, price=item.price, fee=item.fee_original or ZERO,
            amount=item.amount, ratio=item.ratio, incomplete_reason=item.incomplete_reason))
    with localcontext() as context:
        context.prec = 60
        return replay(opening.quantity if opening else ZERO, opening.original_cost if opening else ZERO, domain)


async def _converted(session, entry, holding):
    rate, details = await reference_for(session, entry.currency, entry.occurred_on)
    fee_rate, fee_details = await reference_for(session, entry.fee_currency, entry.occurred_on)
    trade_rate, _ = await reference_for(session, holding.trade_currency, entry.occurred_on)
    original_fee = entry.fee if entry.fee_currency == holding.trade_currency else entry.fee * fee_rate / trade_rate if fee_rate is not None and trade_rate is not None else ZERO if entry.fee == 0 else None
    if entry.kind in {'purchase', 'sale'}:
        gross = entry.quantity * entry.price
        cash = (-gross if entry.kind == 'purchase' else gross) * rate - entry.fee * (fee_rate or ZERO) if rate is not None and (fee_rate is not None or entry.fee == 0) else None
    elif entry.kind == 'dividend':
        cash = entry.amount * rate if rate is not None else None
    elif entry.kind == 'split':
        cash = ZERO
    else:
        cash = None
    entry.reference_fx = rate
    entry.fee_original = original_fee
    entry.reference_cash_flow_cny = cash
    entry.reference_details = {**(entry.reference_details or {}), 'trade': details, 'fee': fee_details}
    return entry


async def _prepare_entry(session, request, *, lock=False):
    period = await get_period(session, lock=lock)
    if not period:
        raise ServiceError(409, 'LEDGER_NOT_OPEN', '请先预览并建立期初。')
    if request.occurred_on < period.opened_on or request.occurred_on > shanghai_today():
        raise ServiceError(422, 'LEDGER_DATE_OUTSIDE_PERIOD', '发生日期必须在启用日至今天之间。')
    statement = select(Holding).where(Holding.id == request.holding_id)
    if lock:
        statement = statement.with_for_update()
    holding = await session.scalar(statement)
    if holding is None:
        raise ServiceError(404, 'HOLDING_NOT_FOUND', '持仓不存在。')
    currency = (request.currency or holding.trade_currency).upper()
    if request.kind in {'purchase', 'sale'} and currency != holding.trade_currency:
        raise ServiceError(422, 'LEDGER_TRADE_CURRENCY', '买卖币种必须与标的一致。')
    if not holding.is_active and request.kind in {'purchase', 'sale', 'split'}:
        raise ServiceError(409, 'LEDGER_HOLDING_ARCHIVED', '归档标的仅可补记分红和更正。')
    entries = await _entries(session, holding.id)
    opening = await session.scalar(select(LedgerOpening).where(LedgerOpening.holding_id == holding.id))
    current = replay_entries(opening, entries, holding.trade_currency)
    if request.kind != 'manual_correction' and (current.quantity != holding.quantity or abs(current.average_price - holding.average_cost_price) > Decimal('0.000000001')):
        raise ServiceError(409, 'LEDGER_POSITION_DIVERGED', '持仓变化无法被账本解释；请记录人工修正并核对成本链。')
    sequence = (await session.scalar(select(func.max(LedgerEntry.sequence)))) or 0
    entry = LedgerEntry(id=uuid4(), period_id=period.id, holding_id=holding.id,
        kind=request.kind, occurred_on=request.occurred_on, sequence=sequence + 1,
        currency=currency, quantity=request.quantity, price=request.price,
        amount=request.quantity * request.price if request.kind in {'purchase', 'sale'} else request.amount,
        fee=request.fee, fee_currency=(request.fee_currency or currency).upper(), ratio=request.ratio,
        idempotency_key=request.idempotency_key, request_hash=request_hash(request), note=request.note,
        replaces_id=request.replaces_id, linked_entry_id=request.linked_entry_id,
        reference_details={'dividend_gross_amount': number(request.gross_amount), 'dividend_tax': number(request.tax)})
    if request.linked_entry_id:
        linked = next((item for item in effective_entries(entries) if item.id == request.linked_entry_id), None)
        if linked is None or linked.kind != 'dividend' or request.kind != 'purchase':
            raise ServiceError(422, 'LEDGER_INVALID_REINVESTMENT', '再投资买入须关联同一标的的有效分红记录。')
    await _converted(session, entry, holding)
    if request.kind == 'manual_correction':
        entry.incomplete_reason = '人工修正改变持仓，收益记录不完整。'
    effective = effective_entries(entries)
    replaced = None
    if request.replaces_id:
        replaced = next((item for item in effective if item.id == request.replaces_id), None)
        if replaced is None:
            raise ServiceError(409, 'LEDGER_CORRECTION_CONFLICT', '原流水不存在或已被冲销。')
        effective = [item for item in effective if item.id != replaced.id]
        entry.sequence = replaced.sequence
    try:
        result = replay_entries(opening, [*effective, entry], holding.trade_currency)
    except ValueError as exc:
        raise ServiceError(422, 'LEDGER_REPLAY_CONFLICT', str(exc)) from exc
    with localcontext() as context:
        context.prec = 100
        numeric_valid = all(fits_numeric_28_12(value.quantize(Decimal('0.000000000001'))) for value in [entry.amount, result.quantity, result.average_price, result.cost])
    if not numeric_valid:
        raise ServiceError(422, 'LEDGER_NUMERIC_OUT_OF_RANGE', '交易结果超出 NUMERIC(28,12) 可保存范围。')
    before = {'quantity': number(holding.quantity), 'average_cost_price': number(holding.average_cost_price)}
    after = {'quantity': number(result.quantity), 'average_cost_price': number(result.average_price), 'original_cost': number(result.cost)}
    token = digest({'request': request_hash(request), 'version': holding.version,
        'entries': [(str(item.id), item.request_hash) for item in entries], 'before': before,
        'after': after, 'reference': entry.reference_details})
    return holding, entry, result, replaced, {'before': before, 'after': after, 'preview_token': token,
        'reference_details': entry.reference_details, 'reference_cash_flow_cny': number(entry.reference_cash_flow_cny),
        'original_fee_pending': entry.fee_original is None, 'incomplete_reasons': result.reasons}


async def preview_entry(session, request):
    return (await _prepare_entry(session, request))[-1]


async def confirm_entry(session, request):
    existing = await session.scalar(select(LedgerEntry).where(LedgerEntry.idempotency_key == request.idempotency_key))
    if existing:
        if existing.request_hash != request_hash(request):
            raise ServiceError(409, 'LEDGER_IDEMPOTENCY_CONFLICT', '防重复键已用于其他流水。')
        return serialize_entry(existing)
    holding, entry, result, replaced, preview = await _prepare_entry(session, request, lock=True)
    if not request.preview_token or preview['preview_token'] != request.preview_token:
        raise ServiceError(409, 'STALE_LEDGER_PREVIEW', '持仓、流水或参考汇率已变化，请重新预览。')
    if replaced:
        session.add(LedgerEntry(id=uuid4(), period_id=entry.period_id, holding_id=holding.id,
            kind='reversal', occurred_on=entry.occurred_on, sequence=entry.sequence,
            currency=entry.currency, quantity=ZERO, price=ZERO, amount=ZERO, fee=ZERO,
            fee_currency=entry.fee_currency, fee_original=ZERO, ratio=Decimal(1),
            reverses_id=replaced.id, idempotency_key=f'reversal:{entry.id}', request_hash=entry.request_hash,
            note=request.note, reference_details={}, reference_cash_flow_cny=ZERO))
    before_quantity, before_price = holding.quantity, holding.average_cost_price
    holding.quantity = result.quantity
    holding.average_cost_price = result.average_price
    # Preserve historical CNY cost estimate rather than fabricate a blended exchange cost.
    session.add(entry)
    operation_type = {'purchase': 'PURCHASE', 'sale': 'SELL'}.get(entry.kind, 'MANUAL_CORRECTION')
    session.add(CostAdjustment(holding_id=holding.id, operation_type=operation_type,
        before_quantity=before_quantity, before_average_cost_price=before_price,
        before_cost_fx_to_cny=holding.cost_fx_to_cny, after_quantity=result.quantity,
        after_average_cost_price=result.average_price, after_cost_fx_to_cny=holding.cost_fx_to_cny,
        input_summary={'ledger_entry_id': str(entry.id), 'ledger_kind': entry.kind, 'reference_cost_only': True}, note=entry.note,
        created_at=datetime.now(timezone.utc)))
    await session.flush()
    return serialize_entry(entry)


def serialize_entry(item):
    return {key: number(getattr(item, key)) for key in ['quantity', 'price', 'amount', 'fee', 'fee_original', 'ratio', 'reference_fx', 'reference_cash_flow_cny']} | {
        'id': str(item.id), 'holding_id': str(item.holding_id), 'kind': item.kind,
        'occurred_on': item.occurred_on.isoformat(), 'created_at': item.created_at.isoformat() if item.created_at else None,
        'currency': item.currency, 'fee_currency': item.fee_currency, 'note': item.note,
        'reference_details': item.reference_details, 'incomplete_reason': item.incomplete_reason,
        'reverses_id': str(item.reverses_id) if item.reverses_id else None,
        'replaces_id': str(item.replaces_id) if item.replaces_id else None,
        'linked_entry_id': str(item.linked_entry_id) if item.linked_entry_id else None,
    }


async def list_entries(session, holding_id=None, account=None, kind=None, date_from=None, date_to=None):
    statement = select(LedgerEntry, Holding).join(Holding, Holding.id == LedgerEntry.holding_id)
    for field, value in [(LedgerEntry.holding_id, holding_id), (Holding.account_name, account), (LedgerEntry.kind, kind)]:
        if value is not None:
            statement = statement.where(field == value)
    if date_from:
        statement = statement.where(LedgerEntry.occurred_on >= date_from)
    if date_to:
        statement = statement.where(LedgerEntry.occurred_on <= date_to)
    rows = (await session.execute(statement.order_by(LedgerEntry.occurred_on.desc(), LedgerEntry.sequence.desc(), LedgerEntry.created_at.desc()))).all()
    return [serialize_entry(item) | {'symbol': holding.symbol, 'name': holding.name, 'account_name': holding.account_name, 'is_archived': not holding.is_active} for item, holding in rows]


async def repair_reference_conversions(session):
    """Audit reference-only repairs; no replacement of frozen final values."""
    rows = (await session.execute(select(LedgerEntry, Holding).join(Holding, Holding.id == LedgerEntry.holding_id).where(LedgerEntry.kind != 'reversal'))).all()
    old_states = {}
    for _, holding in rows:
        if holding.id not in old_states:
            opening = await session.scalar(select(LedgerOpening).where(LedgerOpening.holding_id == holding.id))
            old_states[holding.id] = replay_entries(opening, await _entries(session, holding.id), holding.trade_currency)
    affected = {}
    for entry, holding in rows:
        details = entry.reference_details or {}
        if all(details.get(part, {}).get('status') in {'final', 'fallback'} for part in ['trade', 'fee']):
            continue
        before = {'reference_fx': number(entry.reference_fx), 'cash_flow': number(entry.reference_cash_flow_cny), 'details': details}
        old_fee = entry.fee_original
        await _converted(session, entry, holding)
        if old_fee != entry.fee_original:
            affected[holding.id] = holding
        after = {'reference_fx': number(entry.reference_fx), 'cash_flow': number(entry.reference_cash_flow_cny), 'details': entry.reference_details}
        if before != after:
            session.add(ReferenceFxRevision(entry_id=entry.id, before=before, after=after, reason='日终参考定稿或补齐'))
    # Cross-currency fee conversion changes average original-currency cost; replay
    # all later trades atomically, provided no unrelated unrecorded edit occurred.
    for holding_id, holding in affected.items():
        old = old_states[holding_id]
        if old.quantity == holding.quantity and abs(old.average_price - holding.average_cost_price) <= Decimal('0.000000001'):
            opening = await session.scalar(select(LedgerOpening).where(LedgerOpening.holding_id == holding_id))
            updated = replay_entries(opening, await _entries(session, holding_id), holding.trade_currency)
            holding.average_cost_price = updated.average_price
    openings = list(await session.scalars(select(LedgerOpening)))
    for opening in openings:
        if opening.reference_details.get('status') in {'final', 'fallback'}:
            continue
        period = await session.get(LedgerPeriod, opening.period_id)
        rate, details = await reference_for(session, opening.trade_currency, period.opened_on)
        if rate is None:
            continue
        before = {'rate': number(opening.reference_fx), 'value': number(opening.reference_value_cny), 'details': opening.reference_details}
        opening.reference_fx, opening.reference_details = rate, details
        opening.reference_value_cny = opening.quantity * opening.market_price * rate if opening.market_price is not None else None
        after = {'rate': number(rate), 'value': number(opening.reference_value_cny), 'details': details}
        if before != after:
            session.add(ReferenceFxRevision(opening_id=opening.id, before=before, after=after, reason='期初参考定稿或补齐'))


async def statistics(session):
    period = await get_period(session)
    if not period:
        return {'period': None, 'currencies': [], 'reference_pnl_cny': None, 'incomplete_reasons': ['尚未建立期初'], 'holdings': []}
    holdings = list(await session.scalars(select(Holding)))
    openings = {item.holding_id: item for item in await session.scalars(select(LedgerOpening))}
    grouped = defaultdict(lambda: dict(unrealized=ZERO, realized=ZERO, dividends=ZERO, opening_unrealized=ZERO, reasons=[]))
    reference_total = ZERO
    reasons = []
    holding_summaries = []
    for holding in holdings:
        opening = openings.get(holding.id)
        entries = await _entries(session, holding.id)
        if not opening and not entries and holding.quantity == 0:
            continue
        result = replay_entries(opening, entries, holding.trade_currency)
        group = grouped[holding.trade_currency]
        local_reasons = list(result.reasons)
        if result.quantity != holding.quantity or abs(result.average_price - holding.average_cost_price) > Decimal('0.000000001'):
            local_reasons.append(f'{holding.symbol} 持仓变化无法被账本解释')
        if any(item.kind in {'purchase', 'sale'} and item.fee_original is None for item in effective_entries(entries)):
            local_reasons.append(f'{holding.symbol} 跨币种费用折算待补全')
        price = await _price(session, holding) if holding.quantity else ZERO
        fx = Decimal(1) if holding.trade_currency == 'CNY' else await _current_value(session, 'fx', f'{holding.trade_currency}/CNY')
        if price is None:
            local_reasons.append(f'{holding.symbol} 当前价格缺失')
        if opening and opening.market_price is None:
            local_reasons.append(f'{holding.symbol} 期初价格缺失')
        unrealized = holding.quantity * price - result.cost if price is not None else None
        opening_unrealized = opening.quantity * opening.market_price - opening.original_cost if opening and opening.market_price is not None else ZERO
        group['unrealized'] += unrealized or ZERO
        group['realized'] += result.realized
        group['opening_unrealized'] += opening_unrealized
        for item in effective_entries(entries):
            if item.kind == 'dividend':
                grouped[item.currency]['dividends'] += item.amount
        group['reasons'].extend(local_reasons)
        reasons.extend(local_reasons)
        cash_entries = [item for item in effective_entries(entries) if item.kind in {'purchase', 'sale', 'dividend'}]
        if fx is None or (opening and opening.reference_value_cny is None) or any(item.reference_cash_flow_cny is None for item in cash_entries):
            reasons.append(f'{holding.symbol} 人民币参考折算待补全')
        elif price is not None:
            reference_total += holding.quantity * price * fx - (opening.reference_value_cny if opening else ZERO) + sum((item.reference_cash_flow_cny for item in cash_entries), ZERO)
        holding_summaries.append({'holding_id': str(holding.id), 'symbol': holding.symbol, 'currency': holding.trade_currency,
            'quantity': number(holding.quantity), 'original_cost': number(result.cost), 'unrealized': number(unrealized),
            'realized': number(result.realized), 'dividends': number(result.dividends), 'incomplete_reasons': local_reasons})
    currencies = []
    for currency, group in sorted(grouped.items()):
        complete = not group['reasons']
        currencies.append({'currency': currency, **{key: number(group[key]) for key in ['unrealized', 'realized', 'dividends', 'opening_unrealized']},
            'period_pnl': number(group['unrealized'] + group['realized'] + group['dividends'] - group['opening_unrealized']) if complete else None,
            'complete': complete, 'incomplete_reasons': list(dict.fromkeys(group['reasons']))})
    return {'period': {'id': str(period.id), 'opened_on': period.opened_on.isoformat()}, 'currencies': currencies,
        'reference_pnl_cny': number(reference_total) if not reasons else None,
        'incomplete_reasons': list(dict.fromkeys(reasons)), 'holdings': holding_summaries,
        'reference_label': '人民币参考期间损益，不表示实际换汇盈亏或收益率',
        'scope_label': '证券投资池，不包含池外外币现金持有收益；平均成本口径不用于税务申报'}

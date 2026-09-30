from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select

from app.db.models import MarketData, MarketDataOverride, Holding
from app.db.ledger_models import ReferenceFxDay, LedgerEntry
from app.services.reference_fx import freeze_reference_fx, shanghai_today


async def create_holding(api_client, currency='USD'):
    asset_id = (await api_client.get('/api/asset-classes')).json()[2]['id']
    response = await api_client.post('/api/holdings', json={'asset_class_id': asset_id,
        'symbol': 'SPY', 'name': 'SPY', 'market': 'US', 'account_name': 'ledger-test',
        'trade_currency': currency, 'quantity': '10', 'average_cost_price': '5',
        'cost_fx_to_cny': '7.2', 'baseline_fx_to_cny': '7.2', 'lot_size': '1',
        'quantity_precision': 4, 'is_rebalance_preferred': True})
    assert response.status_code == 201
    return response.json()


async def open_ledger(api_client):
    payload = {'idempotency_key': str(uuid4())}
    preview = await api_client.post('/api/ledger/opening/preview', json=payload)
    assert preview.status_code == 200, preview.text
    payload['preview_token'] = preview.json()['preview_token']
    result = await api_client.post('/api/ledger/opening/confirm', json=payload)
    assert result.status_code == 200, result.text
    return payload


async def record(api_client, holding, kind, **kwargs):
    payload = {'holding_id': holding['id'], 'kind': kind, 'occurred_on': shanghai_today().isoformat(),
        'idempotency_key': str(uuid4()), **kwargs}
    preview = await api_client.post('/api/ledger/entries/preview', json=payload)
    assert preview.status_code == 200, preview.text
    payload['preview_token'] = preview.json()['preview_token']
    result = await api_client.post('/api/ledger/entries/confirm', json=payload)
    assert result.status_code == 200, result.text
    return result.json(), payload


async def test_missing_fx_saves_original_trade_idempotently(api_client, db_session):
    holding = await create_holding(api_client)
    await open_ledger(api_client)
    item, payload = await record(api_client, holding, 'purchase', quantity='2', price='10', fee='1')
    assert item['reference_fx'] is None
    assert item['reference_cash_flow_cny'] is None
    duplicate = await api_client.post('/api/ledger/entries/confirm', json=payload)
    assert duplicate.status_code == 200
    assert duplicate.json()['id'] == item['id']
    current = await db_session.get(Holding, UUID(holding['id']))
    assert current.quantity == 12
    assert abs(current.quantity * current.average_cost_price - Decimal('71')) < Decimal('0.000000001')


async def test_sale_split_and_correction_replay_once(api_client):
    holding = await create_holding(api_client, 'CNY')
    await open_ledger(api_client)
    purchase, _ = await record(api_client, holding, 'purchase', quantity='2', price='10', fee='1')
    sale, _ = await record(api_client, holding, 'sale', quantity='3', price='12', fee='2')
    assert sale['reference_cash_flow_cny'] == '34'
    await record(api_client, holding, 'split', ratio='2')
    replacement, _ = await record(api_client, holding, 'purchase', quantity='2', price='11', fee='1', replaces_id=purchase['id'], note='价格录入修正')
    entries = (await api_client.get('/api/ledger/entries')).json()
    assert any(item['reverses_id'] == purchase['id'] for item in entries)
    assert replacement['replaces_id'] == purchase['id']
    summary = (await api_client.get('/api/ledger/statistics')).json()
    assert summary['holdings'][0]['quantity'] == '18.000000000000'


async def test_daily_valid_quote_freezes_without_drift(api_client, db_session):
    await create_holding(api_client)
    now = datetime.now(timezone.utc)
    db_session.add(MarketData(data_type='fx', symbol='USD/CNY', source='test', value=Decimal('7'), market_time=now, fetched_at=now, status='valid'))
    await db_session.commit()
    assert await freeze_reference_fx(db_session, shanghai_today()) == 1
    await db_session.commit()
    db_session.add(MarketData(data_type='fx', symbol='USD/CNY', source='test-2', value=Decimal('8'), market_time=now, fetched_at=now, status='valid'))
    await db_session.commit()
    assert await freeze_reference_fx(db_session, shanghai_today()) == 0
    row = await db_session.scalar(select(ReferenceFxDay))
    assert row.rate == 7


async def test_dividend_tax_validation_and_oversell_rollback(api_client, db_session):
    holding = await create_holding(api_client)
    await open_ledger(api_client)
    invalid = await api_client.post('/api/ledger/entries/preview', json={'holding_id': holding['id'], 'kind': 'dividend', 'amount': '8', 'gross_amount': '10', 'tax': '1', 'occurred_on': shanghai_today().isoformat(), 'idempotency_key': str(uuid4())})
    assert invalid.status_code == 422
    payload = {'holding_id': holding['id'], 'kind': 'sale', 'quantity': '11', 'price': '8', 'occurred_on': shanghai_today().isoformat(), 'idempotency_key': str(uuid4())}
    rejected = await api_client.post('/api/ledger/entries/preview', json=payload)
    assert rejected.status_code == 422
    assert (await db_session.get(Holding, UUID(holding['id']))).quantity == 10
    assert list(await db_session.scalars(select(LedgerEntry))) == []


async def test_same_day_fx_preview_confirm_and_cross_currency_fee_backfill(api_client, db_session):
    holding = await create_holding(api_client)
    await open_ledger(api_client)
    first, _ = await record(api_client, holding, 'purchase', quantity='2', price='10', fee='7', fee_currency='CNY')
    assert first['fee_original'] is None
    await record(api_client, holding, 'sale', quantity='2', price='12')
    now = datetime.now(timezone.utc)
    db_session.add(MarketData(data_type='fx', symbol='USD/CNY', source='test', value=Decimal('7'), market_time=now, fetched_at=now, status='valid'))
    await db_session.commit()
    await freeze_reference_fx(db_session, shanghai_today())
    await db_session.commit()
    # Updated fee cost is replayed through the sale; future original trades remain usable.
    current = await db_session.get(Holding, UUID(holding['id']), populate_existing=True)
    assert abs(current.average_cost_price - Decimal(71) / Decimal(12)) < Decimal('0.000000001')
    await record(api_client, holding, 'purchase', quantity='1', price='11')


async def test_provisional_quote_opening_and_trade_can_confirm(api_client, db_session):
    holding = await create_holding(api_client)
    now = datetime.now(timezone.utc)
    db_session.add(MarketData(data_type='fx', symbol='USD/CNY', source='test', value=Decimal('7'), market_time=now, fetched_at=now, status='valid'))
    await db_session.commit()
    await open_ledger(api_client)
    item, _ = await record(api_client, holding, 'purchase', quantity='1', price='10')
    assert item['reference_details']['trade']['status'] == 'provisional'
    assert Decimal(item['amount']) == 10


async def test_existing_cost_drawer_records_once_without_manual_fx(api_client):
    holding = await create_holding(api_client)
    await open_ledger(api_client)
    payload = {'quantity': '2', 'price': '10', 'actual_fee': '1', 'occurred_on': shanghai_today().isoformat()}
    response = await api_client.post(f"/api/cost-adjustments/{holding['id']}/preview-purchase", json=payload)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview['fee']['amount'] == '1'
    confirmed = await api_client.post(f"/api/cost-adjustments/{holding['id']}/confirm", json={'expected_version': preview['holding_version'], 'operation': 'purchase', 'payload': payload, 'preview_token': preview['preview_token']})
    assert confirmed.status_code == 200, confirmed.text
    entries = (await api_client.get('/api/ledger/entries')).json()
    assert len(entries) == 1
    assert Decimal(confirmed.json()['after']['quantity']) == 12


async def test_opening_manual_price_unrealized_is_not_period_profit(api_client, db_session):
    holding = await create_holding(api_client, 'CNY')
    now = datetime.now(timezone.utc)
    override = MarketDataOverride(data_type='price', symbol='SPY', value=Decimal('8'), note='期初核对', effective_at=now)
    db_session.add(override)
    await db_session.commit()
    await open_ledger(api_client)
    summary = (await api_client.get('/api/ledger/statistics')).json()
    cny = next(item for item in summary['currencies'] if item['currency'] == 'CNY')
    assert Decimal(cny['opening_unrealized']) == 30
    assert Decimal(cny['period_pnl']) == 0
    assert Decimal(summary['reference_pnl_cny']) == 0
    await record(api_client, holding, 'dividend', amount='8', gross_amount='10', tax='2')
    summary = (await api_client.get('/api/ledger/statistics')).json()
    assert Decimal(summary['reference_pnl_cny']) == 8
    dividend = (await api_client.get('/api/ledger/entries', params={'kind': 'dividend'})).json()[0]
    assert dividend['reference_details']['dividend_gross_amount'] == '10'
    assert dividend['reference_details']['dividend_tax'] == '2'


async def test_current_reference_valuation_uses_latest_fx_without_changing_frozen_opening(api_client, db_session):
    await create_holding(api_client)
    now = datetime.now(timezone.utc)
    db_session.add(MarketDataOverride(data_type='price', symbol='SPY', value=Decimal('8'), note='价格核对', effective_at=now))
    db_session.add(MarketData(data_type='fx', symbol='USD/CNY', source='opening', value=Decimal('7'), market_time=now, fetched_at=now, status='valid'))
    await db_session.commit()
    await freeze_reference_fx(db_session, shanghai_today())
    await db_session.commit()
    await open_ledger(api_client)
    db_session.add(MarketDataOverride(data_type='fx', symbol='USD/CNY', value=Decimal('8'), note='当前估值参考', effective_at=now))
    await db_session.commit()
    summary = (await api_client.get('/api/ledger/statistics')).json()
    assert Decimal(summary['currencies'][0]['period_pnl']) == 0
    assert Decimal(summary['reference_pnl_cny']) == 80
    assert (await db_session.scalar(select(ReferenceFxDay))).rate == 7

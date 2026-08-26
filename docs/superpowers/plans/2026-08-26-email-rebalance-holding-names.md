# Email Rebalance Holding Names Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show each rebalance trade in the daily email as `名称（代码）`, avoid duplicate labels, and remove the low-value reason column.

**Architecture:** Keep the change inside the email renderer. Build a symbol-to-name lookup from the `PortfolioAnalyticsResponse` already passed to `build_digest_html()`, format each trade label with a safe symbol-only fallback, and leave the rebalance API, database, browser UI, and backup contracts unchanged.

**Tech Stack:** Python 3.13, FastAPI service code, Pydantic response models, pytest

## Global Constraints

- Only the HTML table under “再平衡建议” changes.
- Display `名称（代码）` when name and symbol differ; display the symbol once when they match.
- Missing or ambiguous name mappings fall back to the symbol and must not prevent email delivery.
- Keep “标的”, “方向”, “数量”, and “金额 (CNY)”; remove “原因”.
- Do not change the browser UI, rebalance API, database schema, or backup format.
- Preserve HTML escaping for both holding names and symbols.

---

### Task 1: Render named rebalance trades in the daily email

**Files:**
- Modify: `backend/tests/unit/test_email_digest_render.py:141-166`
- Modify: `backend/app/services/email_digest.py:139-164`

**Interfaces:**
- Consumes: `build_digest_html(*, analytics: PortfolioAnalyticsResponse, rebalance: RebalancePreviewResponse | None, local_date: date) -> str`
- Produces: no new public interface; the existing renderer emits the revised four-column trade table.

- [ ] **Step 1: Write failing tests for the primary label and removed reason column**

Update `test_digest_html_contains_summary_holdings_and_trades()` with these assertions:

```python
    assert "标普 500（SPY）" in html
    assert ">原因</th>" not in html
    assert "当前低配，可直接使用同币种现金补足目标仓位。" not in html
```

- [ ] **Step 2: Add edge-case tests for duplicate suppression, fallback, and escaping**

Add a focused rendering helper and three tests to `backend/tests/unit/test_email_digest_render.py`:

```python
def _render_trade_label(
    *, holding_symbol: str, holding_name: str, trade_symbol: str
) -> str:
    holding = _holding().model_copy(
        update={"symbol": holding_symbol, "name": holding_name}
    )
    analytics = _analytics().model_copy(update={"holdings": [holding]})
    trade = _result().trades[0].model_copy(update={"symbol": trade_symbol})
    result = _result().model_copy(update={"trades": (trade,)})
    rebalance = _rebalance().model_copy(
        update={
            "result": result,
            "fx_comparison": RebalanceComparisonResponse(
                valuation_basis="fx_neutral",
                result=result,
            ),
        }
    )
    return build_digest_html(
        analytics=analytics,
        rebalance=rebalance,
        local_date=date(2026, 8, 26),
    )


def test_digest_html_shows_symbol_once_when_holding_name_matches() -> None:
    html = _render_trade_label(
        holding_symbol="QQQ",
        holding_name="QQQ",
        trade_symbol="QQQ",
    )

    assert "QQQ" in html
    assert "QQQ（QQQ）" not in html


def test_digest_html_falls_back_to_symbol_when_trade_has_no_holding() -> None:
    html = _render_trade_label(
        holding_symbol="SPY",
        holding_name="标普 500",
        trade_symbol="159209",
    )

    assert "159209" in html
    assert "标普 500（159209）" not in html


def test_digest_html_falls_back_when_one_symbol_has_different_names() -> None:
    first = _holding().model_copy(update={"symbol": "159209", "name": "名称 A"})
    second = _holding().model_copy(
        update={
            "holding_id": "00000000-0000-0000-0000-000000000002",
            "symbol": "159209",
            "name": "名称 B",
        }
    )
    analytics = _analytics().model_copy(update={"holdings": [first, second]})
    trade = _result().trades[0].model_copy(update={"symbol": "159209"})
    result = _result().model_copy(update={"trades": (trade,)})
    rebalance = _rebalance().model_copy(update={"result": result})

    html = build_digest_html(
        analytics=analytics,
        rebalance=rebalance,
        local_date=date(2026, 8, 26),
    )

    assert "159209" in html
    assert "名称 A（159209）" not in html
    assert "名称 B（159209）" not in html


def test_digest_html_escapes_the_complete_trade_label() -> None:
    html = _render_trade_label(
        holding_symbol="159209",
        holding_name="成长<&",
        trade_symbol="159209",
    )

    assert "成长&lt;&amp;（159209）" in html
    assert "成长<&（159209）" not in html
```

- [ ] **Step 3: Run the focused test file and verify RED**

Run from the repository root through the guarded backend test entry point:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_email_digest_render.py -q'
```

Expected: the primary name-format, ambiguous-name, escaping, and reason-removal assertions fail because the renderer still emits only `trade.symbol` and the five-column table. Existing symbol-only fallback assertions may already pass and serve as regression coverage.

- [ ] **Step 4: Implement the minimal renderer change**

In `build_digest_html()`, build the lookup once and use it while constructing trade rows:

```python
    names_by_symbol: dict[str, set[str]] = {}
    for holding in analytics.holdings:
        names_by_symbol.setdefault(holding.symbol, set()).add(holding.name)
    holding_names = {
        symbol: next(iter(names))
        for symbol, names in names_by_symbol.items()
        if len(names) == 1
    }

    if rebalance is not None and rebalance.result.trades:
        trade_rows = []
        for trade in rebalance.result.trades:
            holding_name = holding_names.get(trade.symbol)
            trade_label = (
                f"{holding_name}（{trade.symbol}）"
                if holding_name and holding_name != trade.symbol
                else trade.symbol
            )
            trade_rows.append(
                [
                    _esc(trade_label),
                    "买入" if trade.action == "buy" else "卖出",
                    _one_decimal(trade.quantity),
                    _money(trade.amount_cny),
                ]
            )
        rebalance_html = _table(
            ["标的", "方向", "数量", "金额 (CNY)"],
            trade_rows,
        )
```

Do not change the `TradeSuggestionResponse` schema or any caller.

- [ ] **Step 5: Run the focused tests and verify GREEN**

Run:

```bash
make test-backend PYTEST_ARGS='tests/unit/test_email_digest_render.py -q'
```

Expected: all tests in `test_email_digest_render.py` pass.

- [ ] **Step 6: Run the email integration regression tests**

Run:

```bash
make test-backend PYTEST_ARGS='tests/integration/test_email_digest.py tests/unit/test_email_digest_render.py -q'
```

Expected: all daily and manual digest tests pass, with no production Compose project or data volume accessed.

- [ ] **Step 7: Run final backend verification and inspect the diff**

Run:

```bash
make test-backend
git diff --check
git diff -- backend/app/services/email_digest.py backend/tests/unit/test_email_digest_render.py
```

Expected: the complete backend suite passes, `git diff --check` prints nothing, and the diff contains only the renderer and its tests.

- [ ] **Step 8: Commit the implementation**

```bash
git add backend/app/services/email_digest.py backend/tests/unit/test_email_digest_render.py
git commit -m "feat: label email rebalance trades"
```

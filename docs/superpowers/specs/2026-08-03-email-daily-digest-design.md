# Email Daily Digest Design

## Goal

Send a daily portfolio digest email on trading days with per-holding profit/loss analysis and rebalancing suggestions. The configured daily refresh time is the analysis start point: the worker refreshes market data, creates the daily snapshot, and then sends the email as soon as the data is ready. There is no hard send-time guarantee.

## Architecture And Data Flow

Extend the worker's existing daily pipeline in `backend/app/worker.py`:

1. Refresh all required market data (existing `refresh_all_required_data`).
2. Create the daily snapshot (existing `create_daily_snapshot_if_complete`).
3. Send the daily digest (new step, wrapped in its own transaction and try/except):
   - Not enabled or not configured -> return silently.
   - Not a trading day (Saturday or Sunday in `Asia/Shanghai`) -> return.
   - Portfolio data incomplete (`PORTFOLIO_DATA_INCOMPLETE`) -> do not run analysis; send a "data anomaly" email listing the missing items.
   - Data complete -> compute portfolio analytics and rebalance suggestions with default settings constraints, render HTML, send via SMTP.

Failure isolation: a send failure only logs an error (exception class and message category, never credentials) and never affects market refresh or snapshot creation. No automatic retry within the run; the next daily run retries naturally. No email history table; operational inspection relies on `docker compose logs worker`.

New backend service module: `backend/app/services/email_digest.py`, with a pure render function (analytics + rebalance suggestion inputs -> HTML) and an async send function that runs stdlib `smtplib` in `asyncio.to_thread`.

Rebalancing suggestions reuse the existing engine with the settings defaults: `rebalance_available_cny`, `rebalance_available_usd`, `rebalance_valuation_basis`, `default_tolerance`, `minimum_trade_amount_cny`, `allow_sell`, and `allow_fx`. Stale data is acceptable: the email is sent with a warning banner.

## Storage Model

Extend the singleton `settings` row with:

- `email_enabled`, default `false`
- `email_recipient`, nullable
- `email_smtp_host`, nullable
- `email_smtp_port`, default `465`
- `email_smtp_security`, `ssl` or `starttls`, default `ssl`
- `email_smtp_username`, nullable
- `email_from`, nullable; empty means the username is used as the sender

The SMTP authorization code is stored in the existing `encrypted_secrets` table with `provider = 'smtp'`, encrypted with the same Fernet secret store used for provider API keys. Responses expose only a masked value (`****xxxx`).

## API

- `GET /api/settings/email` -> email settings (password masked).
- `PUT /api/settings/email` -> save settings; an empty password field leaves the stored password unchanged, a non-empty value encrypts and replaces it.
- `POST /api/settings/email/test` -> send a test email with the current configuration; returns `ok` or an error category (`smtp_connect_failed`, `smtp_auth_failed`, `smtp_recipient_rejected`).
- `POST /api/email/digest` -> manually run the full pipeline now: refresh market data, create the daily snapshot, then send the digest. Ignores the trading-day restriction. Returns a status:
  - `sent` - the full digest was sent
  - `anomaly_sent` - data was incomplete, so a data-anomaly email was sent instead
  - `skipped_empty` - the portfolio has no positions, nothing was sent
  - `not_configured` - email is disabled or incompletely configured, nothing was sent
  - plus `sent_at` when an email was sent.

Validation: recipient format via `email.utils.parseaddr`, port in range, `security` one of the enum values. Missing host/port/username/recipient with `email_enabled = true` is rejected with 422.

## Frontend

Add an "邮件通知" section to the existing `ProviderSettings` component on the data-source page (`/data-sources`), next to the existing "自动刷新与再平衡默认值" section. Fields: enable switch, recipient, SMTP host, port, security mode (SSL/STARTTLS), username, authorization code (password input, masked value placeholder), optional sender, save button, and a "发送测试邮件" button with inline success/failure result. Reuse `FormField` and existing market-data styles.

Add a "立即发送日报" button next to the test-email button. It triggers `POST /api/email/digest`, shows a pending state ("正在刷新并发送..."), and maps the returned status to inline feedback:

- `sent` -> "日报已发送"
- `anomaly_sent` -> "数据不完整，已发送数据异常通知"
- `skipped_empty` -> "暂无持仓，未发送"
- `not_configured` -> "请先完成邮件配置"

The scheduled worker path keeps the trading-day restriction; only the manual trigger ignores it.

## Email Content

Subject: `投资组合日报 <YYYY-MM-DD>` (local date). HTML with inline styles, no external resources, UTF-8, MIME multipart with a plain-text fallback; Chinese subject RFC 2047 encoded.

Normal digest:

1. Summary: data date/time, total market value (CNY), total unrealized PnL and return, decision status (保持现状 / 建议补仓 / 建议再平衡).
2. Asset-class table: name, target weight, actual weight, drift, class PnL.
3. Per-holding PnL table grouped by asset class: name/symbol, account, quantity, cost price, current price, cost FX, current FX, market value (CNY), unrealized PnL (CNY), PnL rate, price effect, FX effect. Reuses `analytics.py` per-position results.
4. Rebalance suggestions from the default-constraint preview: decision summary, max drift before/after, trade list (symbol, action, quantity, amount CNY, reason text) when trades exist; "当前配置在容差内，无需调整" when none; infeasible notice when infeasible.
5. Footer: data cutoff time; stale data adds a yellow banner "部分行情数据可能过期" at the top while content is still sent.

Number formatting: CNY money values keep two decimals; prices, FX rates, quantities, and percentages (PnL rate, weights, drift) keep one decimal.

Data-anomaly email:

- Subject: `投资组合日报 <YYYY-MM-DD>（数据异常）`
- Body states that analysis was not generated and lists the anomalous data items (symbol, missing type price/fx, status, source), directing the user to the data-source page. No analysis content is included.

## Sending Details And Edge Cases

- `ssl` uses `SMTP_SSL` (default port 465); `starttls` uses `SMTP` plus explicit `starttls()` (587).
- Login with username + authorization code; sender is `email_from` or the username.
- 30-second timeout for connect and operations.
- Incomplete configuration counts as disabled; the worker skips without noise.
- Weekend check uses the worker timezone (`Asia/Shanghai`).

## Testing

Backend unit tests:

- Render functions: key numbers and Chinese labels present; HTML special characters in names escaped; empty-portfolio and no-trade copy.
- Data-anomaly email rendering: missing items listed, no analysis content.
- SMTP send: mock `smtplib`, verify SSL and STARTTLS branches, login/recipient/sender/timeout; assert logs never include the authorization code.
- Trading-day check: Mon-Fri true, Sat/Sun false.
- Settings validation: port range, security enum, recipient format return 422.

Backend integration tests:

- Settings API: saved password is ciphertext in DB, masked in responses; empty password preserves the stored value.
- Test-email API: mock SMTP returns `ok` or the matching error category.
- Worker pipeline with a mocked send function: disabled skip, non-trading-day skip, incomplete data sends the anomaly email, complete data sends the full digest; a send failure does not affect snapshot creation.
- Manual digest API: `not_configured`, `skipped_empty`, `anomaly_sent`, and `sent` statuses; a manual trigger on a weekend still sends, while the scheduled path skips weekends.

Frontend tests (existing RTL patterns):

- `EmailSettingsForm` rendering, save calls, test-button success/failure feedback, manual-digest button status feedback, empty authorization-code behavior.

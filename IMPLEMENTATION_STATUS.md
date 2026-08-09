# Implementation Status — ScalpLab 0.2.0

## Release scope

This release implements the safe research path through Milestone 2: historical backtesting, live Binance market-data recording, integrity-aware microstructure storage/replay, rolling walk-forward validation, and live shadow/paper trading. **Authenticated/live-money Binance order execution is intentionally absent.**

## Implemented

### Research / backtest
- Exact start/end Binance USD-M historical backtests with UTC-day cache and missing-range download.
- Single or multiple symbols and arbitrary TC/LC/LSR/RB/VB/TR combinations.
- One shared deterministic decision engine for backtest, replay and shadow.
- Explicit `OHLCV_PROXY`, `TRADE_FLOW` and `MICROSTRUCTURE` modes.
- Full LC/LSR/TR refuse to run when required microstructure fields are missing.
- Next-bar signal execution, maker/taker fees, slippage, passive/aggressive/market simulation, missed passive fills, stop-first ambiguous-bar policy, partial TP, breakeven and time stop.
- Portfolio/open-risk caps and simple same-direction rolling correlation reduction.
- Data-gap-aware trade invalidation and conservative accounting.
- Headline return reconciles with ending equity; valid-trade research P&L is reported separately.
- Attribution by strategy, symbol, regime and direction plus R distribution and NO-TRADE codes.
- Rolling chronological walk-forward folds with optional threshold tuning only on past train/validation folds.
- Grid-search research optimizer that does not optimize risk policy by default.
- Calibration scaffolding; no fake win probability without adequate historical samples.

### Live recorder / integrity
- Public Binance Futures + Spot WebSocket ingestion.
- Futures diff-depth local order-book reconstruction with snapshot bridging and sequence validation.
- Connect-and-buffer-before-snapshot bootstrap to avoid snapshot/stream race gaps.
- Recorder sessions, heartbeats, Linux boot-ID restart classification and explicit gap reasons.
- Same-boot unclean session -> process crash; clean shutdown across boot -> manual reboot; unclean different boot -> hard reboot/power-loss-style interruption.
- Network disconnect and depth-sequence gaps stored permanently.
- Stale/sequence-broken books become untrusted and are resnapshotted before L2 features resume.
- Crash-safe gzip JSONL chunks: RAM buffer -> `.tmp` -> fsync -> atomic rename.
- Incomplete temp files retained as `.incomplete`, never accepted as valid history.
- Finalized chunks orphaned between atomic rename and SQLite metadata commit are rediscovered/re-registered after restart.
- SQLite/WAL integrity metadata and source provenance.
- Restart backfill of recoverable 1m candles, funding and recent aggregate trades; L2 gap remains missing.
- Futures aggregate-trade recovery respects Binance's recent-history and sub-hour request constraints and marks partial 24h-limited recovery explicitly.

### Microstructure
- CVD and Spot CVD.
- Taker imbalance, trade velocity and aggressive volume.
- OFI-style combined flow/book pressure feature.
- Spread, mid, microprice and microprice change.
- Top-depth imbalance.
- Replenishment and cancellation interval features.
- Approximate bid/ask absorption.
- OI / OI delta availability and funding availability.
- Liquidation buy/sell notional intervals.
- Spot/perpetual basis when Spot book is available.
- Explicit Spot/OI/funding availability so missing context is not treated as neutral confirmation.
- 1-second derived feature snapshots.

### Replay / external sample data
- Local recorded-feature loader and resampling into replay bars.
- Per-bar microstructure coverage; sub-bar missing snapshots can invalidate a replay bar.
- Configurable minimum overall microstructure coverage gate.
- Tardis first-day-of-month sample downloader and incremental L2 replay builder.
- Tardis replay skips buffered deltas before the first initial snapshot.

### Live shadow / paper
- Live shadow engine using the same decision engine as research backtests.
- Uses fresh microstructure features when healthy; visibly degrades to lower data mode otherwise.
- Simulated pending/passive/aggressive/market fills, fees, stops, targets and time exits.
- Persistent SQLite shadow ledger.
- No API key, account endpoint or exchange order submission path.

### Operations / storage
- `/data/scalp` preferred bulk data path with local fallback.
- 128 GB NVMe + 500 GB HDD oriented layout.
- Storage usage, 7-day GB/day estimate and days-to-full estimate.
- Warning / pressure / emergency thresholds.
- Raw L2 retention/pruning policy; disk pressure first reduces raw-depth persistence while keeping in-memory feature processing alive.
- `scalp doctor`, `scalp selftest`, `scalp storage-status`, `scalp storage-prune`.
- Whole-market lightweight `scalp radar` current-activity ranker.
- systemd recorder and web-service examples with restart-on-failure.

### Web UI
- Premium dark research dashboard.
- No upload workflow: normal history comes directly from Binance.
- Exact start/end/timeframe/symbol/strategy backtest controls.
- Backtest, local L2 replay and walk-forward launch controls.
- Optional walk-forward past-fold threshold tuning checkbox.
- Results by strategy, regime, direction, walk-forward fold, trades and NO-TRADE reasons.
- Recorder controls and stream/book state.
- Latest microstructure feature cards.
- Shadow controls and recent paper ledger.
- Data-integrity timeline and gap reasons.
- Storage pressure/retention view and run history.
- UI/API explicitly state live-money execution is disabled.

### Optional research ML
- Small logistic-regression numerical baseline behind an optional dependency.
- Research only; not in trade decision path.

## Automated validation

- `22` unit/integration/scenario tests currently pass.
- Python compile check passes.
- Editable CLI install smoke-tested in the build environment.
- Web API/UI local smoke test passes (`/api/health`, root page).
- Source scan finds no Binance order endpoints or API-key/secret handling.

## Partial / deferred by design

1. **Dynamic automatic Tier-1 -> full-L2 promotion** — `scalp radar` exists and static L2 tiers are configurable, but changing live WebSocket subscriptions automatically based on radar ranking is not yet enabled. This avoids unvalidated reconnect/subscription churn in the first unattended recorder release.
2. **Cross-exchange live confirmation** — Bybit/OKX/Hyperliquid are not connected in 0.2. Binance Futures + Spot are the trusted primary source first.
3. **Deep matching-engine queue-position simulator** — passive fills are conservative approximations, not a full historical exchange queue reconstruction.
4. **Continuous free historical full L2** — impossible from normal Binance history when it was not recorded. Tardis free sample-day support is included; continuous third-party history may require paid data.
5. **Complete historical OI** — live OI is recorded; historical availability depends on the source/range.
6. **Large Hugging Face time-series foundation models** — intentionally deferred until recorded data proves a simple numerical baseline has incremental value.
7. **Real-money trading** — deliberately absent and should remain a separate later milestone after manual burn-in/review.

## Required real-host burn-in before trusting M2 data

The sandbox used to build this release cannot provide a realistic multi-day Binance WebSocket + HDD + reboot/power-loss burn-in. On the Ubuntu mini-server run:

```bash
scalp selftest
scalp doctor
scalp record --symbols BTCUSDT,ETHUSDT,SOLUSDT --full-l2 BTCUSDT,ETHUSDT,SOLUSDT
```

Then verify at least several days of:
- zero unexplained sequence corruption,
- automatic reconnect/resnapshot,
- actual GB/day storage use,
- clean/manual reboot recovery,
- forced-process-crash recovery,
- a deliberate short network outage,
- replay coverage and shadow-vs-backtest behavior.

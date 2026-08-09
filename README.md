# ScalpLab 0.2 — Research + Live Microstructure Platform

ScalpLab is a deterministic crypto-scalping research platform for **Binance USDⓈ-M Futures**. It combines historical backtesting, live Futures/Spot recording, local L2 reconstruction, microstructure replay, rolling walk-forward validation, and **shadow/paper trading only**.

> Live-money execution is intentionally not implemented in this release.

## Operating modes

1. **Backtest** — choose symbol(s), exact start/end, timeframe, and strategy set. Historical candles are pulled directly from Binance and cached by UTC day.
2. **Live Record** — record Futures trades/L2, Spot trades, OI/funding, liquidations, and derived 1-second microstructure features.
3. **Replay** — replay locally recorded microstructure through the same TC/LC/LSR/RB/VB/TR decision engine.
4. **Shadow** — consume live market data and simulate strategy decisions without sending exchange orders.
5. **Walk-forward** — rolling chronological out-of-sample validation.

## Strategies

- `TC` Trend Continuation
- `LC` Liquidity Cascade
- `LSR` Liquidity Sweep Reversal
- `RB` Range Mean Reversion
- `VB` Volatility Breakout
- `TR` Trend Reversal

LC/LSR/TR refuse to claim full microstructure validation when required L2/flow fields are unavailable. Historical candle/trade operation is explicitly a proxy mode.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
scalp selftest
scalp serve --host 0.0.0.0 --port 8080
```

Open `http://SERVER_IP:8080`.

### Historical exact-range backtest

```bash
scalp backtest \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --interval 5m \
  --from 2026-07-01T00:00:00Z \
  --to   2026-07-15T00:00:00Z
```

### Start live recorder

```bash
scalp record \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT \
  --full-l2 BTCUSDT,ETHUSDT,SOLUSDT
```

### Health check

```bash
scalp doctor
scalp storage-status
```

### Replay recorded microstructure

```bash
scalp replay --symbols BTCUSDT --interval 1m \
  --from 2026-08-10T00:00:00Z --to 2026-08-11T00:00:00Z
```

### Live shadow testing

```bash
scalp shadow --symbols BTCUSDT,ETHUSDT,SOLUSDT
```

### Tardis free sample

The project contains an adapter for publicly accessible first-day-of-month sample datasets:

```bash
scalp tardis-sample --symbol BTCUSDT --day 2025-01-01 --type incremental_book_L2
scalp tardis-replay --symbol BTCUSDT --day 2025-01-01 --interval 1m
```

## Storage layout

Designed for the current target machine:

- 128 GB NVMe: Ubuntu, app, virtualenv, SQLite/WAL state, current working cache.
- 500 GB HDD: `/data/scalp` bulk raw L2, trades, features, historical cache/archive.

If `/data/scalp` is unavailable, ScalpLab falls back to `data/bulk` and reports that path in the UI/doctor output.

```text
/data/scalp/
├── live/
├── features/
├── historical/
├── events/
├── backtests/
└── archive/
```

Raw data is buffered in RAM, written as compressed time chunks to `.tmp`, fsynced, then atomically renamed. Incomplete temporary chunks are retained as `.incomplete` after restart rather than treated as valid data.

## Data integrity / restart behavior

A missing interval is never interpolated as valid L2 history.

- Each recorder process gets a `session_id`.
- Heartbeats persist the last valid stream/book state.
- Linux boot ID is tracked to distinguish a same-boot process crash from a hard reboot/power-loss style interruption.
- Any depth-sequence discontinuity makes the local book untrusted.
- The recorder downloads a new book snapshot and resynchronizes before L2 features become healthy again.
- Backtests detect time discontinuities. A position spanning an unresolved gap is conservatively resolved and excluded from normal strategy statistics.

## systemd

Example service units are in `systemd/`.

The units assume:

- project at `/opt/scalplab`
- virtualenv at `/opt/scalplab/.venv`
- service user `scalp`

Install after adapting paths/user if needed:

```bash
sudo ./scripts/install-systemd.sh
```

## Research-only ML baseline

Optional simple numerical ML research is available:

```bash
pip install -e '.[ml]'
scalp ml-research --symbol BTCUSDT --interval 5m --days 90
```

This does **not** enter the trading decision path. It exists only to establish a simple baseline before testing larger time-series foundation models.

## Important limitations

- Historical Binance OHLCV/trade data cannot reconstruct event-level L2 that was never recorded.
- The local recorder needs uninterrupted network/power for complete native L2 coverage; gaps are explicitly logged.
- L2 cancellation versus true execution cannot always be inferred perfectly from snapshots/deltas alone; features are deterministic approximations and should be validated in replay.
- Tardis free samples cover sample days, not continuous free history.
- No authenticated Binance trading/account/order endpoints exist in this release.

## Recovery note: aggregate trades

Binance USD-M aggregate-trade REST history is useful for **recent** restart recovery, but it is not a permanent historical archive. ScalpLab chunks time requests below one hour and marks recovery as partial if the outage extends beyond the endpoint's recent-history window. Candles/funding may still be backfilled while native missing L2 remains a gap.

## Walk-forward tuning

The Web UI can run walk-forward with tuning disabled (fixed settings) or enable **past-fold threshold tuning**. In tuned mode only signal thresholds such as minimum strategy score/separation are selected on train/validation folds; the chosen settings are then frozen on the subsequent unseen test fold. Risk-policy limits are not optimized for profit.

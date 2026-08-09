# Milestone 1 Status

## Complete

- Standalone Python package built from scratch.
- Premium responsive FastAPI web UI; no file-upload workflow.
- Binance USD-M public kline downloader with pagination, cache, symbol-universe discovery and funding-history adapter.
- Data modes: OHLCV_PROXY, TRADE_FLOW, MICROSTRUCTURE model definitions.
- Six strategies, long and short: TC, LC, LSR, RB, VB, TR.
- Proxy flags for LC/LSR/TR when historical L2 evidence is absent.
- Shared feature engine and closed-bar 15m/1h context alignment.
- Regime probabilities for trend/range/compression/expansion/transition/pump/dump/exhaustion.
- Evidence-family agreement and directional conflict gating.
- NO-TRADE reason accounting.
- Risk sizing, max symbol/open risk, notional cap, pending-order reservation and correlation reduction.
- Passive/aggressive/market execution simulation, maker/taker fees, slippage and missed passive fills.
- Next-bar entries and shifted rolling levels to reduce look-ahead bias.
- Conservative stop-first resolution when OHLCV cannot order stop and target touches.
- TP1 partial exit, optional breakeven, final target, time stop and strategy transition tracking.
- SQLite run history, config hash and detailed trade ledger.
- Score-bucket calibration output that remains uncalibrated under the minimum sample count.
- Chronological train/validation/test walk-forward tool.
- Small grid-search optimizer for signal thresholds (not risk escalation).
- 11 automated tests passing.

## Intentionally deferred to Milestone 2

- Historical/live L2 book reconstruction.
- True OFI/microprice/wall persistence/cancel/replenishment/absorption replay.
- Full LC/LSR/TR microstructure validation.
- Live Binance websocket recorder.
- Spot-vs-futures and Bybit/OKX/Hyperliquid confirmation feeds.
- Paper/live order routing.

## Sandbox verification limitation

The development sandbox has outbound DNS disabled, so the actual `fapi.binance.com` HTTP request cannot be executed here. The application uses the documented public Binance USD-M Futures endpoints and is intended to fetch them directly when run on a normal Internet-connected Ubuntu host.

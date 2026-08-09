# Scalp Project — TODO After Milestone 2 Plan

Last consolidated: 2026-08-09  
Scope: Changes, additions, and new requirements discussed after the Milestone 2 plan.

---

## Priority Legend

- **P0** — Required before recorded data can be trusted
- **P1** — Required for Milestone 2 / research usability
- **P2** — Important enhancement after core M2 is stable
- **P3** — Future research / optional

---

# 1. Backtesting UX and Data Acquisition

## P1 — Direct Binance historical backtesting

- [ ] Remove any dependency on user-uploaded market data for normal usage.
- [ ] Backtest UI must fetch historical data directly from Binance.
- [ ] Add symbol selector for a single Binance USD-M Futures pair.
- [ ] Add multi-symbol selection.
- [ ] Add exact start date/time selector.
- [ ] Add exact end date/time selector.
- [ ] Add timeframe selector:
  - [ ] 1m
  - [ ] 3m
  - [ ] 5m
  - [ ] 15m
  - [ ] Additional supported Binance intervals as needed
- [ ] Add strategy selector:
  - [ ] TC
  - [ ] LC
  - [ ] LSR
  - [ ] RB
  - [ ] VB
  - [ ] TR
  - [ ] All strategies
- [ ] Allow testing strategy combinations.
- [ ] Add universe choices:
  - [ ] Single symbol
  - [ ] Selected symbols
  - [ ] Top liquid USDT perpetuals
  - [ ] All eligible USDT perpetuals
- [x] Cache downloaded Binance historical data locally.
- [x] Only download missing historical ranges when cache already exists.
- [x] Track historical-cache last-access time and keep reused data hot for at least 2 hours after its most recent backtest/replay use before it becomes eligible for eviction.
- [x] Reuse cache coverage across runtime-root migration so already downloaded ranges are not fetched again.
- [x] Add cache size, last-used time, hit/miss status, and explicit cleanup controls to the Storage UI.
- [x] Show historical-data source and coverage in the UI.

## P1 — Backtest result views

- [ ] Equity curve.
- [ ] Drawdown curve.
- [ ] Net return.
- [ ] Gross return.
- [ ] Trade count.
- [ ] Win rate.
- [ ] Profit factor.
- [ ] Expectancy.
- [ ] Average R.
- [ ] Fees.
- [ ] Slippage.
- [ ] Maker/taker ratio.
- [ ] Performance by strategy.
- [ ] Performance by symbol.
- [ ] Performance by regime.
- [ ] Long vs short performance.
- [ ] R-distribution.
- [ ] Individual trade explorer.
- [ ] NO-TRADE reason statistics.

---

# 2. Shared Strategy Engine Across All Modes

## P0/P1

Use **one strategy engine** for all operating modes.

- [ ] Backtest uses the same TC/LC/LSR/RB/VB/TR implementation.
- [ ] Historical replay uses the same implementation.
- [ ] Live shadow/paper mode uses the same implementation.
- [ ] Do not create separate simplified strategy code paths except explicitly declared proxy logic.
- [ ] Strategy behavior must depend on feature availability/data mode, not duplicated implementations.

Target architecture:

```text
                 STRATEGY ENGINE
               TC LC LSR RB VB TR
                       |
         +-------------+-------------+
         |             |             |
         v             v             v
      BACKTEST       REPLAY      LIVE SHADOW
```

---

# 3. Data Quality Modes

## P0

Formalize data modes and expose them everywhere.

- [ ] `OHLCV_PROXY`
- [ ] `TRADE_FLOW`
- [ ] `MICROSTRUCTURE`

For each strategy:

- [ ] Declare required features.
- [ ] Declare minimum data mode.
- [ ] Declare whether proxy operation is available.
- [ ] Clearly label proxy/full results.

Expected behavior with limited historical data:

- [ ] TC = basic/full with candle data where appropriate.
- [ ] RB = basic/full with candle data where appropriate.
- [ ] VB = basic/full with candle data where appropriate.
- [ ] LC = proxy unless true microstructure is available.
- [ ] LSR = proxy unless true microstructure is available.
- [ ] TR = structural proxy unless richer evidence is available.

Never silently imply that OHLCV tested:

- [ ] Absorption.
- [ ] Replenishment.
- [ ] True OFI.
- [ ] Microprice.
- [ ] Wall persistence.
- [ ] Cancellation behavior.
- [ ] True liquidity consumption.

---

# 4. Live Binance Data Recorder

## P0/P1

### Binance Futures

- [ ] Public WebSocket connection manager.
- [ ] Trades / aggTrades ingestion.
- [ ] Diff-depth ingestion.
- [ ] Local order-book reconstruction.
- [ ] Best bid/ask.
- [ ] Spread.
- [ ] Mark/index/basis where applicable.
- [ ] OI polling/stream integration where available.
- [ ] Funding integration.
- [ ] Liquidation stream/data integration where available.

### Binance Spot confirmation

- [ ] Spot trades.
- [ ] Spot depth where useful.
- [ ] Spot CVD.
- [ ] Spot/futures divergence.
- [ ] Spot confirmation features.

### Derived live features

- [ ] CVD.
- [ ] CVD slope/change.
- [ ] OFI.
- [ ] Taker imbalance.
- [ ] Trade velocity.
- [ ] Trade acceleration.
- [ ] Microprice.
- [ ] Depth imbalance.
- [ ] Book slope.
- [ ] Book thinning.
- [ ] Wall detection.
- [ ] Wall persistence.
- [ ] Cancellation rate.
- [ ] Replenishment.
- [ ] Liquidity consumption.
- [ ] Absorption.
- [ ] Price progress per aggressive volume.
- [ ] Liquidity map.

---

# 5. Unexpected Restart / Power Loss / Data Gaps

## P0 — Critical

Missing live data must be explicitly recorded as missing. Never hide or interpolate it.

### Detect and classify gaps

- [ ] Persist recorder heartbeat.
- [ ] Persist last valid Futures trade timestamp.
- [ ] Persist last valid Spot trade timestamp.
- [ ] Persist last valid depth update timestamp.
- [ ] Persist last valid order-book sequence ID.
- [ ] Persist last successful storage flush.
- [ ] Detect unclean shutdown on startup.
- [ ] Record exact gap start/end where possible.

Gap reason enum:

- [ ] `POWER_LOSS`
- [ ] `MANUAL_REBOOT`
- [ ] `PROCESS_CRASH`
- [ ] `NETWORK_OUTAGE`
- [ ] `BINANCE_DISCONNECT`
- [ ] `STREAM_SEQUENCE_GAP`
- [ ] `DISK_FULL`
- [ ] `RECORDER_OVERLOAD`
- [ ] `CLOCK_SYNC_ERROR`
- [ ] `UNKNOWN`

### Recorder session tracking

Every process lifetime gets a unique session ID.

- [ ] `session_id`.
- [ ] Start timestamp.
- [ ] End timestamp.
- [ ] Clean/unclean status.
- [ ] Restart reason when known.
- [ ] Events reference their recorder session.

### Restart recovery

On startup:

- [ ] Wait for network availability.
- [ ] Verify system clock/NTP synchronization.
- [ ] Load last recorder checkpoint.
- [ ] Detect whether previous session closed cleanly.
- [ ] Create a permanent DATA_GAP record if required.
- [ ] Backfill recoverable historical data.
- [ ] Never reuse stale pre-disconnect L2 state.
- [ ] Fetch a fresh order-book snapshot.
- [ ] Synchronize subsequent deltas.
- [ ] Verify sequence continuity.
- [ ] Only mark order book healthy after successful synchronization.
- [ ] Start a new recording segment.

### Backfillable vs non-backfillable data

Potentially recover:

- [ ] OHLCV.
- [ ] Historical trades/aggTrades when available.
- [ ] Funding.
- [ ] OI where Binance historical coverage permits.

Do **not** fabricate/reconstruct missing live-only microstructure:

- [ ] Missing L2 deltas remain missing.
- [ ] Missing OFI remains missing.
- [ ] Missing microprice remains missing.
- [ ] Missing wall history remains missing.
- [ ] Missing cancellation events remain missing.
- [ ] Missing replenishment remains missing.
- [ ] Missing absorption remains missing.

### Backtester gap behavior

- [ ] Calculate coverage per feature/data mode.
- [ ] Exclude invalid microstructure periods by default.
- [ ] Add configurable minimum coverage threshold.
- [ ] Option to abort backtest below required coverage.
- [ ] Do not silently downgrade `LC_FULL` to `LC_PROXY` mid-trade.
- [ ] Mark trades spanning unresolved gaps as `INVALID_DATA_GAP`.
- [ ] Exclude invalid-gap trades from normal performance metrics.
- [ ] If lower-resolution data proves a stop was hit, allow conservative resolution as a loss.
- [ ] Never choose a favorable outcome because data is missing.

---

# 6. Order-Book Integrity

## P0

- [ ] Implement Binance snapshot + delta reconstruction correctly.
- [ ] Validate update/sequence IDs.
- [ ] Detect any missing diff-depth sequence.
- [ ] Immediately mark book `UNTRUSTED` after sequence loss.
- [ ] Stop producing L2-dependent strategy signals while book is untrusted.
- [ ] Rebuild from fresh snapshot before re-enabling.
- [ ] Store order-book quality status with feature snapshots.

Possible book states:

- [ ] `SYNCING`
- [ ] `HEALTHY`
- [ ] `STALE`
- [ ] `SEQUENCE_GAP`
- [ ] `UNTRUSTED`
- [ ] `RESYNCING`

---

# 7. Historical / Third-Party L2 Support

## P2

### Binance historical sources

- [ ] Support Binance official historical OHLCV.
- [ ] Support Binance historical trades/aggTrades.
- [ ] Support available funding/OI history.
- [ ] Treat coarse/sampled historical book depth separately from true incremental L2.
- [ ] Validate any historical depth dataset before use.

### Tardis.dev free sample support

- [ ] Add Tardis historical data adapter.
- [ ] Support free sample days where available.
- [ ] Import incremental L2.
- [ ] Import book snapshots.
- [ ] Import trades.
- [ ] Import quotes.
- [ ] Import derivative ticker.
- [ ] Import liquidation data where present.
- [ ] Normalize Tardis data into the same internal event schemas.
- [ ] Use Tardis samples to test `LC_FULL`, `LSR_FULL`, and richer `TR` replay before enough local data accumulates.

### External gap repair

If verified external data covers a local outage:

- [ ] Keep the original local gap record.
- [ ] Create a separate repaired/augmented dataset.
- [ ] Track source provenance per segment.
- [ ] Never pretend local recorder had uninterrupted coverage.

---

# 8. Live Shadow / Paper Testing

## P1/P2

No real Binance orders yet.

- [ ] Consume real live Binance market data.
- [ ] Run real strategy engine continuously.
- [ ] Generate simulated entries.
- [ ] Generate simulated exits.
- [ ] Simulate maker/taker fees.
- [ ] Simulate spread/slippage.
- [ ] Simulate passive/aggressive/market execution.
- [ ] Track missed fills.
- [ ] Track actual strategy transitions.
- [ ] Store every shadow decision.
- [ ] Compare shadow outcomes to backtest expectations.

Dashboard should show:

- [ ] Current symbol.
- [ ] Current regime scores.
- [ ] Current six-strategy matrix.
- [ ] Selected action.
- [ ] Simulated entry.
- [ ] Stop.
- [ ] Targets.
- [ ] Current R/P&L.
- [ ] Execution quality.
- [ ] Reasons for/against.
- [ ] Data-quality state.

**Do not implement live-money order execution until explicit later approval/review.**

---

# 9. Walk-Forward Testing

## P1

Walk-forward is a validation framework, not inherently machine learning.

- [ ] Add Standard Backtest mode.
- [ ] Add Optimization mode.
- [ ] Add Walk-Forward mode.

Walk-forward configuration:

- [ ] Total date range.
- [ ] Train window.
- [ ] Validation window if used.
- [ ] Test window.
- [ ] Rolling vs expanding training.
- [ ] Retraining/re-optimization cadence.

Requirements:

- [ ] Tune only on past training/validation data.
- [ ] Freeze parameters for each future test fold.
- [ ] Never optimize on the future test fold.
- [ ] Report every fold separately.
- [ ] Aggregate out-of-sample results.
- [ ] Flag unstable parameter selections.
- [ ] Track positive/negative fold percentage.

UI example modes:

```text
○ Standard Backtest
○ Optimization
● Walk Forward
```

---

# 10. Strategy Combination Research

## P2

- [ ] Backtest each strategy independently.
- [ ] Backtest all six together.
- [ ] Backtest arbitrary selected combinations.
- [ ] Compare results with one strategy removed.
- [ ] Determine whether each strategy adds net portfolio value.
- [ ] Measure strategy P&L correlation.
- [ ] Detect strategies that are duplicates of the same underlying risk source.

Examples:

- [ ] TC only.
- [ ] LC only.
- [ ] TC + VB.
- [ ] TC + LC.
- [ ] LC + LSR.
- [ ] TC + LC + LSR.
- [ ] All six.
- [ ] All except RB, etc.

---

# 11. Premium Web UI Enhancements

## P1

### Main navigation

- [ ] Overview.
- [ ] Backtest.
- [ ] Walk Forward.
- [ ] Optimization.
- [ ] Live Recorder.
- [ ] Shadow Trading.
- [ ] Data Integrity.
- [ ] Storage.
- [ ] Strategy Explorer.
- [ ] Settings.

### Data Integrity screen

Show:

- [ ] Recorder uptime.
- [ ] Valid microstructure coverage.
- [ ] Number of gaps.
- [ ] Longest gap.
- [ ] Recent gap timeline.
- [ ] Gap reason.
- [ ] Backfill status.
- [ ] Book synchronization state.
- [ ] Stream lag.
- [ ] Dropped events.
- [ ] Reconnect count.
- [ ] Clock/NTP health.

### Data coverage display

For selected backtest period show:

- [ ] OHLCV coverage.
- [ ] Trade-flow coverage.
- [ ] L2 coverage.
- [ ] OI coverage.
- [ ] Funding coverage.
- [ ] Spot coverage.
- [ ] Final usable data mode.
- [ ] Which strategies are full vs proxy.

---

# 12. Self-Test / Health Commands

## P0/P1

Add:

```bash
scalp doctor
```

Checks:

- [ ] Binance reachable.
- [ ] Futures WebSocket works.
- [ ] Spot WebSocket works.
- [ ] System clock sane.
- [ ] Depth sequence valid.
- [ ] Local order book synchronized.
- [ ] Trades arriving.
- [ ] CVD changing.
- [ ] OFI changing.
- [ ] Microprice changing.
- [ ] OI updating.
- [ ] Funding updating.
- [ ] Recorder writing successfully.
- [ ] Database healthy.
- [ ] Replay can read recorded chunks.
- [ ] Disk space healthy.
- [ ] HDD/NVMe paths writable.

Add:

```bash
scalp selftest
```

- [ ] Run automated unit/integration/scenario suite.
- [ ] Return non-zero status on critical failure.
- [ ] Produce human-readable summary.

---

# 13. Automatic Startup / Service Management

## P0

Use systemd on Ubuntu.

Boot sequence:

```text
BOOT
  ↓
Network available
  ↓
NTP/time synchronized
  ↓
Recorder service
  ↓
Futures/Spot connections
  ↓
Fresh book synchronization
  ↓
Health verification
  ↓
Recording enabled
```

Tasks:

- [ ] Create `scalp-recorder.service`.
- [ ] Automatic start after boot.
- [ ] Automatic restart after crash.
- [ ] Backoff after repeated failures.
- [ ] Clean shutdown handler.
- [ ] Persist last healthy checkpoint.
- [ ] Never treat automatic restart as proof no data gap occurred.

---

# 14. Storage Architecture — Current Hardware

Current planned hardware:

```text
128 GB NVMe M.2
500 GB HDD
```

## P0/P1 — NVMe usage

Use NVMe for:

- [ ] Ubuntu.
- [ ] Application/project code.
- [ ] Python environment.
- [ ] SQLite metadata.
- [ ] Active state/checkpoints.
- [ ] Temporary working files.
- [ ] Small recent cache.
- [ ] Web UI/backend.
- [ ] Current backtest working data where beneficial.

Avoid allowing bulk historical/raw L2 data to fill NVMe.

## P1 — HDD usage

Use HDD for bulk storage:

```text
/data/scalp/
├── historical/
├── live/
│   ├── futures/
│   ├── spot/
│   ├── trades/
│   └── depth/
├── features/
├── events/
├── archive/
└── backtests/
```

Store:

- [ ] Raw L2 chunks.
- [ ] Trades.
- [ ] Long-term Parquet features.
- [ ] Historical Binance cache.
- [ ] Preserved event/trade windows.
- [ ] Archived replay data.

## P0 — HDD-friendly write design

Do not perform thousands of tiny synchronous HDD writes.

Use:

```text
WebSocket
   ↓
RAM buffer
   ↓
batch
   ↓
compressed segment
   ↓
HDD
```

- [ ] Buffered writes.
- [ ] Bounded RAM buffer.
- [ ] Periodic flush.
- [ ] Backpressure handling.
- [ ] Detect recorder overload.

---

# 15. Power-Loss-Safe File Writing

## P0

- [ ] Do not keep one giant daily raw file open.
- [ ] Store data in small time-based segments.
- [ ] Use temporary filename while writing.
- [ ] Flush and fsync appropriately.
- [ ] Atomically rename completed segment.
- [ ] Detect `.tmp`/incomplete files after restart.
- [ ] Mark incomplete segment as corrupted/incomplete.
- [ ] Preserve metadata about missing interval.

Example:

```text
21-15.parquet.tmp
      ↓ successful close
21-15.parquet
```

Recommended segmentation:

- [ ] 1–5 minute chunks for very high-volume raw L2, configurable.
- [ ] Larger chunks for 1-second feature data if safe.

---

# 16. Storage Retention Policy

## P1

Initial policy for 500 GB HDD:

- [ ] Raw high-resolution L2: target approximately 30 days initially.
- [ ] 1-second derived features: retain long term.
- [ ] OHLCV: retain long term.
- [ ] OI/funding: retain long term.
- [ ] Trade/setup windows: retain permanently where practical.
- [ ] Historical downloaded cache: prune only according to explicit policy.

Preserve high-resolution windows around important setups:

- [ ] ~10 minutes before a signal.
- [ ] Entire trade.
- [ ] ~10–20 minutes after exit.
- [ ] Preserve abnormal pump/dump/liquidation events.

---

# 17. Tiered Recording to Control Disk Usage

## P1

Do NOT full-record L2 for every Binance USDT perpetual continuously.

Use tiering:

```text
ALL USDT PERPS
      ↓
cheap scanner
      ↓
30–50 interesting symbols
      ↓
richer trade-flow tracking
      ↓
5–10 priority symbols
      ↓
full 100ms L2
      ↓
1–5 strongest setups
      ↓
preserve highest-resolution event windows
```

Tasks:

- [ ] Define promotion/demotion rules.
- [ ] Record 1-second lightweight features for broad universe.
- [ ] Record trade flow for active candidates.
- [ ] Record full L2 only for priority candidates.
- [ ] Ensure BTC/ETH can be permanently prioritized if desired.
- [ ] Dynamically reduce recording load under CPU/disk pressure.

---

# 18. Storage Monitoring / Disk Pressure

## P0/P1

Dashboard should report:

- [ ] NVMe total/used/free.
- [ ] HDD total/used/free.
- [ ] Today's data volume.
- [ ] 7-day average GB/day.
- [ ] Estimated days until full.
- [ ] Storage by category.
- [ ] Retention settings.
- [ ] SMART health for HDD if available.

Initial disk-pressure behavior:

### >80% HDD used

- [ ] Warning.

### >90%

- [ ] Stop/promote fewer low-priority raw L2 streams.
- [ ] Continue critical feature snapshots.
- [ ] Continue active-trade/event recording.
- [ ] Begin policy-based pruning if enabled.

### >95%

- [ ] Emergency retention cleanup.
- [ ] Protect metadata/database/system disk.
- [ ] Never let root/NVMe filesystem fill due to market data.

No deletion outside configured retention policy.

---

# 19. Data Provenance

## P1

Every segment/chunk should record source.

Examples:

- [ ] `BINANCE_LIVE`
- [ ] `BINANCE_HISTORICAL`
- [ ] `TARDIS`
- [ ] `LOCAL_DERIVED`
- [ ] `BACKFILLED`

Metadata:

- [ ] Exchange.
- [ ] Symbol.
- [ ] Data type.
- [ ] Start/end.
- [ ] Recorder session.
- [ ] Source.
- [ ] Quality state.
- [ ] Gap status.
- [ ] Hash/checksum where practical.
- [ ] Schema version.

---

# 20. Optional Machine-Learning Research Layer

## P3 — Do not block M2

Walk-forward itself is not ML.

After reliable data collection exists, optionally test whether ML adds incremental value.

Potential models to research:

- [ ] Simple logistic regression baseline.
- [ ] Gradient-boosted tree baseline.
- [ ] Random forest baseline.
- [ ] Small time-series model.
- [ ] IBM Granite Tiny Time Mixers / similar lightweight time-series foundation model.
- [ ] Chronos-family forecasting model if hardware permits.
- [ ] TimesFM-family experiment if hardware permits.

Architecture:

```text
Market features
      |
+-----+------+
|            |
v            v
Rules       ML forecast
TC..TR       model
|            |
+-----+------+
      |
Meta research comparison
```

Initial ML authority:

- [ ] Research only.
- [ ] Do not let ML initiate real trades.
- [ ] Compare rules-only vs rules+ML.
- [ ] Only promote ML to confirmation/veto if walk-forward OOS results improve.
- [ ] Keep historical calibrated probability statistical; do not use arbitrary model confidence as win probability.

Potential UI options later:

- [ ] ML disabled.
- [ ] Research only.
- [ ] Confirmation.
- [ ] Veto.
- [ ] Position-size modifier.

---

# 21. Operating Modes — Final Target

The application should expose three primary operational modes:

## BACKTEST

- [ ] Historical Binance data.
- [ ] Selected symbol(s).
- [ ] Exact time range.
- [ ] Selected timeframe.
- [ ] Selected strategies.
- [ ] Walk-forward/optimization.
- [ ] Historical replay where richer data exists.

## LIVE RECORD

- [ ] Binance Futures.
- [ ] Binance Spot.
- [ ] L2 reconstruction.
- [ ] Trade flow.
- [ ] OI/funding.
- [ ] Microstructure feature generation.
- [ ] Data-integrity engine.
- [ ] Long-term storage.

## LIVE SHADOW

- [ ] Real current data.
- [ ] Same strategy engine.
- [ ] Simulated executions.
- [ ] No real-money orders.
- [ ] Compare with backtest.

Do not proceed to real-money execution merely because these modes exist.

---

# 22. Recommended Implementation Order From Here

## Milestone 2A — Data Reliability Foundation

- [ ] Storage paths and schemas.
- [ ] Recorder session tracking.
- [ ] Heartbeats/checkpoints.
- [ ] Binance Futures connection.
- [ ] Binance Spot connection.
- [ ] Local order-book reconstruction.
- [ ] Sequence validation.
- [ ] Gap detection.
- [ ] Restart recovery.
- [ ] Power-loss-safe storage chunks.
- [ ] systemd auto-start/restart.
- [ ] `scalp doctor`.

## Milestone 2B — Microstructure Features

- [ ] CVD.
- [ ] OFI.
- [ ] Microprice.
- [ ] Depth imbalance.
- [ ] Wall persistence.
- [ ] Cancellation.
- [ ] Replenishment.
- [ ] Consumption.
- [ ] Absorption.
- [ ] Spot/perp divergence.
- [ ] OI/funding/liquidation integration.
- [ ] Liquidity map.

## Milestone 2C — Replay + Full Strategy Upgrade

- [ ] Replay locally recorded events.
- [ ] Add Tardis sample replay.
- [ ] `LC_FULL`.
- [ ] `LSR_FULL`.
- [ ] Richer `TR_FULL`.
- [ ] Data-gap-aware replay.
- [ ] Coverage-based result reporting.
- [ ] Strategy transition replay.

## Milestone 2D — Premium Research UI

- [ ] Recorder dashboard.
- [ ] Data Integrity dashboard.
- [ ] Storage dashboard.
- [ ] Backtest exact range selector.
- [ ] Full/proxy availability display.
- [ ] Walk-forward UI.
- [ ] Strategy-combination testing.
- [ ] Event/trade explorer.

## Milestone 2E — Shadow Trading

- [ ] Live strategy scoring.
- [ ] Simulated orders.
- [ ] Execution simulation.
- [ ] Shadow trade ledger.
- [ ] Backtest-vs-shadow comparison.

## Later

- [ ] ML research.
- [ ] Cross-exchange confirmation expansion.
- [ ] More storage if actual usage requires it.
- [ ] Real-money Binance execution only after separate manual review and approval.

---

# 23. Non-Negotiable Rules Added After M2

- [ ] **Missing data must remain visibly missing.**
- [ ] **Never interpolate missing L2/microstructure data.**
- [ ] **Never reuse stale order-book state after reconnect.**
- [ ] **Never hide a power-loss/network gap by backfilling only candles.**
- [ ] **Backtests must know which feature families were actually available.**
- [ ] **A trade crossing an unresolved data gap cannot be counted as a normal winner.**
- [ ] **Use the same strategy implementation for backtest, replay, and live shadow.**
- [ ] **No normal user data uploads required; pull market history from exchange/data adapters.**
- [ ] **Protect storage from filling the root/system drive.**
- [ ] **Full raw L2 recording must be tiered, not every pair forever.**
- [ ] **Live-money execution remains outside the current milestone.**

---

# 24. Current Hardware Assumption

Primary local research server:

```text
CPU:     Intel i3-8100
RAM:     8 GB
NVMe:    128 GB
HDD:     500 GB
OS:      Ubuntu
```

Current conclusion:

- [x] Hardware is sufficient to start M2.
- [x] Use NVMe for OS/app/active metadata.
- [x] Use 500 GB HDD for bulk market data.
- [x] Design tiered recording and retention before buying more storage.
- [ ] Measure actual GB/day after recorder runs for at least several days.
- [ ] Re-evaluate 1 TB / 2 TB SSD or HDD expansion based on measured usage.

---

# Definition of Success Before Moving Toward Live Money

- [ ] Reliable restart recovery.
- [ ] Verified gap detection.
- [ ] Verified order-book resynchronization.
- [ ] Stable multi-day recording.
- [ ] No silent data corruption.
- [ ] Data-coverage reporting works.
- [ ] Full strategy replay works where true data exists.
- [ ] Historical backtest works by symbol + exact time range.
- [ ] Walk-forward works.
- [ ] Shadow trading works.
- [ ] Backtest vs shadow discrepancy is understood.
- [ ] Risk/execution models remain conservative.
- [ ] Manual review completed before any real Binance order capability is enabled.

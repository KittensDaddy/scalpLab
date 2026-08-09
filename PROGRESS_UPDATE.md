# ScalpLab 0.2.1 — Progress Display Update

## 2026-08-10 top-20 recorder smoke test

A 25-second isolated public-Binance capture verified the rebuilt tiering path:

- Futures top-20 lightweight connection connected.
- Spot lightweight connection connected after filtering unavailable Spot pairs.
- Dedicated Futures full-L2 connection connected; the BTC book reached `HEALTHY`.
- 16,986 events, 4,033 trades, and 222 depth updates processed.
- Zero dropped events and zero reconnects.
- 119 finalized compressed chunks totaling 369,878 bytes after clean shutdown.
- Runtime output stayed beneath the isolated selected root.

## What changed

- Finite CLI jobs display a real percentage, progress bar, elapsed time and current stage.
- Web backtest/replay/walk-forward jobs display real continuously updated progress and elapsed time.
- Binance historical loading reports cache/download progress by symbol and UTC day.
- Backtest replay reports processed bars, completed trades and currently open positions.
- Optimization reports parameter-set progress.
- Walk-forward reports fold and tuning progress.
- Recorder uses a live heartbeat instead of a fake percentage because recording is continuous.
- Shadow mode uses a live heartbeat with bars/equity/open/pending counters.

## Update an existing checkout

From `~/scalpLab`, extract the patch over the project root:

```bash
unzip -o scalplab-0.2.1-progress-patch.zip -d .
```

Because ScalpLab was installed with `pip install -e`, the source change is immediately active. Restart the running Web UI:

```bash
scalp serve --host 0.0.0.0 --port 1120
```

Optional verification:

```bash
scalp selftest
```

Expected result: `24 passed`.

## Examples

Finite CLI job:

```text
[██████████████░░░░░░░░░░░░░░]  51%  00:18  Replay 3,842/7,510 bars · trades 12 · open 1
```

Continuous recorder:

```text
[LIVE 00:18:42] events 1,823,912 · trades 84,510 · depth 1,739,402 · features 3,390 · Futures CONNECTED · Spot CONNECTED · disk OK
```

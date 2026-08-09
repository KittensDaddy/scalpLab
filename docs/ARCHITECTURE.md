# Architecture

```text
Binance historical REST ───────────────┐
Binance Futures/Spot WebSockets ──┐    │
Tardis sample adapter ─────────────┼────┤
                                  v    v
                        Normalization / storage
                                  │
                   ┌──────────────┴──────────────┐
                   v                             v
            Feature engine             Integrity engine
                   │                 sessions/gaps/coverage
                   v
             Regime engine
                   │
                   v
       Shared StrategyDecisionEngine
          TC LC LSR RB VB TR
                   │
       ┌───────────┼────────────┐
       v           v            v
    Backtest      Replay       Shadow
```

Backtest, replay and shadow import the same `StrategyDecisionEngine`; only the source/data mode changes.

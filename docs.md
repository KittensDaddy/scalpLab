# Architecture Notes

## Decision pipeline

Binance public data → normalized frame → feature engine → regime scores → six strategies (long & short) → evidence/conflict gate → portfolio risk → execution simulator → trade ledger/report.

## Strategy identifiers

- TC: Trend Continuation
- LC: Liquidity Cascade (`LC_PROXY` semantics in OHLCV mode)
- LSR: Liquidity Sweep Reversal (`LSR_PROXY` in OHLCV mode)
- RB: Range Mean Reversion
- VB: Volatility Breakout
- TR: Trend Reversal (`TR structural proxy` in OHLCV mode)

## No-look-ahead rule

A signal computed from a closed bar may only fill on a subsequent bar. Rolling breakout/range levels are shifted so the active bar cannot define its own historical threshold.

## Same-bar ambiguity

If a held position's stop and target are both touched inside one OHLCV bar, the default is stop-first. Lower-timeframe/event replay is a Milestone 2 improvement.

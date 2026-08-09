from __future__ import annotations
from dataclasses import dataclass
from scalp.config import AppConfig
from scalp.models import DataMode, Direction, ExecutionMode, StrategyResult
from scalp.regimes import regime_scores
from scalp.strategies import all_strategies
from scalp.strategy_rules import DeclarativeStrategy

@dataclass
class Decision:
    winner: StrategyResult | None
    reason: str | None
    results: list[StrategyResult]
    regimes: dict[str, float]

class StrategyDecisionEngine:
    """Single deterministic strategy/selection implementation shared by backtest/replay/shadow."""
    def __init__(self, cfg: AppConfig, data_mode: DataMode):
        self.cfg = cfg
        self.data_mode = data_mode
        enabled = set(cfg.strategies.enabled)
        builtins={s.id:s for s in all_strategies()}
        self.strategies=[]
        for sid in cfg.strategies.enabled:
            definition=cfg.strategies.version_definitions.get(sid)
            self.strategies.append(DeclarativeStrategy(sid,definition) if definition else builtins[sid])

    def evaluate(self, row) -> Decision:
        reg = regime_scores(row)
        results: list[StrategyResult] = []
        for strategy in self.strategies:
            for direction in (Direction.LONG, Direction.SHORT):
                try:
                    results.append(strategy.evaluate(row, reg, direction, self.data_mode))
                except Exception as exc:
                    # A missing optional feature may make a strategy ineligible, but never breaks other strategies.
                    results.append(StrategyResult(
                        strategy_id=strategy.id, direction=direction, eligible=False, score=0,
                        evidence_agreement=0, regime_compatibility=0, execution_quality=0,
                        data_mode=self.data_mode, proxy=True,
                        reasons_against=[f"Evaluation unavailable: {type(exc).__name__}"],
                    ))
        winner, reason = self.select(results)
        return Decision(winner, reason, results, reg)

    def select(self, results: list[StrategyResult]):
        longs = sorted([r for r in results if r.direction == Direction.LONG and r.eligible], key=lambda x: x.score, reverse=True)
        shorts = sorted([r for r in results if r.direction == Direction.SHORT and r.eligible], key=lambda x: x.score, reverse=True)
        best_l = longs[0] if longs else None
        best_s = shorts[0] if shorts else None
        if not best_l and not best_s:
            return None, "NO_TRADE_INSUFFICIENT_DATA"
        winner = max([x for x in (best_l, best_s) if x], key=lambda x: x.score)
        opp = best_s if winner.direction == Direction.LONG else best_l
        if winner.score < self.cfg.strategies.min_score:
            return None, "NO_TRADE_LOW_SCORE"
        if winner.evidence_agreement < self.cfg.strategies.min_evidence_agreement:
            return None, "NO_TRADE_LOW_EVIDENCE"
        if winner.expected_r < self.cfg.strategies.min_expected_r:
            return None, "NO_TRADE_LOW_RR"
        if opp and winner.score - opp.score < self.cfg.strategies.min_separation:
            return None, "NO_TRADE_CONFLICT"
        return winner, None

    @staticmethod
    def execution_mode(result: StrategyResult) -> ExecutionMode:
        if result.strategy_id == "RB":
            return ExecutionMode.PASSIVE
        if result.strategy_id in {"LC", "VB"} and result.urgency >= 90:
            return ExecutionMode.MARKET
        if result.urgency >= 60:
            return ExecutionMode.AGGRESSIVE
        return ExecutionMode.PASSIVE

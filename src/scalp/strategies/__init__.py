from .tc import TrendContinuation
from .lc import LiquidityCascade
from .lsr import LiquiditySweepReversal
from .rb import RangeMeanReversion
from .vb import VolatilityBreakout
from .tr import TrendReversal

def all_strategies():
    return [TrendContinuation(),LiquidityCascade(),LiquiditySweepReversal(),RangeMeanReversion(),VolatilityBreakout(),TrendReversal()]

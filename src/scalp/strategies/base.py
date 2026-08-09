from __future__ import annotations
from abc import ABC, abstractmethod
import math
from scalp.models import DataMode, Direction, StrategyResult

def clamp(v,a=0,b=100): return max(a,min(b,float(v)))
def val(row,key,default=0.0):
    try:
        x=row.get(key,default) if hasattr(row,"get") else getattr(row,key,default)
        if x is None or (isinstance(x,float) and math.isnan(x)): return default
        return x
    except Exception: return default

def missing(row,keys):
    out=[]
    for k in keys:
        x=val(row,k,None)
        if x is None: out.append(k)
    return out

def agreement(evidence:dict[str,float])->float:
    # Evidence keys are independent families, not individual indicators.
    vals=[abs(v) for v in evidence.values() if abs(v)>=0.20]
    if not vals: return 0.0
    return clamp(sum(vals)/len(vals)*100)

class Strategy(ABC):
    id="BASE"
    minimum_data_mode=DataMode.OHLCV_PROXY
    full_features: tuple[str,...]=()
    @abstractmethod
    def evaluate(self,row,regimes,direction:Direction,data_mode:DataMode)->StrategyResult: ...
    def required_features(self,mode:DataMode): return list(self.full_features if mode==DataMode.MICROSTRUCTURE else ())
    def result(self,direction,score,evidence,regime,mode,reasons_for,reasons_against,stop,target,expected_r,urgency=50,eligible=True,proxy=True,required=None,missing_features=None):
        return StrategyResult(self.id,direction,eligible,clamp(score),agreement(evidence),clamp(regime),100.0,mode,proxy,reasons_for,reasons_against,evidence,stop,target,expected_r,urgency,required or [],missing_features or [])

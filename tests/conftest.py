import numpy as np, pandas as pd, pytest

def make_market(kind="trend", n=360, seed=7, start=100.0):
    rng=np.random.default_rng(seed); ts=pd.date_range("2026-01-01",periods=n,freq="5min",tz="UTC")
    if kind=="trend":
        base=start+np.linspace(0,18,n)+np.sin(np.linspace(0,14,n))*1.4+rng.normal(0,.18,n)
    elif kind=="range":
        base=start+np.sin(np.linspace(0,35,n))*3+rng.normal(0,.20,n)
    elif kind=="breakout":
        base=np.r_[start+rng.normal(0,.18,n//2).cumsum()*.08, np.linspace(start,start+14,n-n//2)+rng.normal(0,.25,n-n//2)]
    elif kind=="reversal":
        base=np.r_[np.linspace(start,start+12,n//2),np.linspace(start+12,start-6,n-n//2)]+rng.normal(0,.22,n)
    else:
        base=start+rng.normal(0,.2,n).cumsum()
    o=np.r_[base[0],base[:-1]]; c=base; spread=np.abs(rng.normal(.35,.12,n))+0.08
    h=np.maximum(o,c)+spread; l=np.minimum(o,c)-spread
    vol=rng.lognormal(7.2,.35,n)
    if kind=="breakout": vol[n//2:n//2+20]*=2.5
    buy_share=np.clip(.5+np.sign(np.r_[0,np.diff(c)])*.08+rng.normal(0,.05,n),.05,.95)
    return pd.DataFrame({"timestamp":ts,"open":o,"high":h,"low":l,"close":c,"volume":vol,"quote_volume":vol*c,"trades":np.maximum(1,(vol/20).astype(int)),"taker_buy_base":vol*buy_share,"taker_buy_quote":vol*buy_share*c})

@pytest.fixture
def trend_df(): return make_market("trend")
@pytest.fixture
def range_df(): return make_market("range")
@pytest.fixture
def breakout_df(): return make_market("breakout")

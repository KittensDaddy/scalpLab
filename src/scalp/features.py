from __future__ import annotations
import numpy as np
import pandas as pd

def _rsi(s: pd.Series, n=14):
    d=s.diff(); up=d.clip(lower=0); dn=-d.clip(upper=0)
    au=up.ewm(alpha=1/n,adjust=False,min_periods=n).mean(); ad=dn.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=au/(ad.replace(0,np.nan)); return (100-(100/(1+rs))).fillna(50)

def _atr(df: pd.DataFrame,n=14):
    prev=df.close.shift(1)
    tr=pd.concat([(df.high-df.low).abs(),(df.high-prev).abs(),(df.low-prev).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()

def _adx(df: pd.DataFrame,n=14):
    up=df.high.diff(); down=-df.low.diff()
    plus_dm=up.where((up>down)&(up>0),0.0); minus_dm=down.where((down>up)&(down>0),0.0)
    atr=_atr(df,n).replace(0,np.nan)
    plus=100*plus_dm.ewm(alpha=1/n,adjust=False,min_periods=n).mean()/atr
    minus=100*minus_dm.ewm(alpha=1/n,adjust=False,min_periods=n).mean()/atr
    dx=100*(plus-minus).abs()/(plus+minus).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False,min_periods=n).mean().fillna(0)

def _rolling_vwap(df,n=48):
    typical=(df.high+df.low+df.close)/3
    pv=typical*df.volume
    return pv.rolling(n,min_periods=max(5,n//4)).sum()/df.volume.rolling(n,min_periods=max(5,n//4)).sum().replace(0,np.nan)

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    x=df.copy().sort_values("timestamp").reset_index(drop=True)
    x["ret1"]=x.close.pct_change()
    x["ema20"]=x.close.ewm(span=20,adjust=False).mean(); x["ema50"]=x.close.ewm(span=50,adjust=False).mean()
    x["ema20_slope"]=(x.ema20/x.ema20.shift(3)-1)*100
    x["atr"]= _atr(x,14); x["atr_ma"]=x.atr.rolling(30,min_periods=10).mean()
    x["rsi"]= _rsi(x.close,14); x["adx"]=_adx(x,14)
    x["vol_ma"]=x.volume.rolling(20,min_periods=5).mean(); x["vol_ratio"]=x.volume/x.vol_ma.replace(0,np.nan)
    x["vwap"]= _rolling_vwap(x,48)
    x["prev_high20"]=x.high.shift(1).rolling(20,min_periods=10).max(); x["prev_low20"]=x.low.shift(1).rolling(20,min_periods=10).min()
    x["range_high"]=x.high.shift(1).rolling(30,min_periods=15).max(); x["range_low"]=x.low.shift(1).rolling(30,min_periods=15).min()
    width=(x.range_high-x.range_low).replace(0,np.nan); x["range_pos"]=(x.close-x.range_low)/width
    mid=x.close.rolling(20,min_periods=10).mean(); std=x.close.rolling(20,min_periods=10).std()
    x["bb_width"]=(4*std/mid.replace(0,np.nan)); x["bb_width_pct"]=x.bb_width.rolling(100,min_periods=20).rank(pct=True)
    x["rv20"]=x.ret1.rolling(20,min_periods=10).std()*np.sqrt(20)
    net=(x.close-x.close.shift(10)).abs(); path=x.close.diff().abs().rolling(10,min_periods=5).sum(); x["efficiency"]=net/path.replace(0,np.nan)
    rng=(x.high-x.low).replace(0,np.nan); x["close_loc"]=(x.close-x.low)/rng
    x["body_frac"]=(x.close-x.open).abs()/rng
    x["taker_buy_share"]=x.taker_buy_base/x.volume.replace(0,np.nan) if "taker_buy_base" in x else np.nan
    x["cvd_proxy"]=(2*x.taker_buy_base-x.volume).cumsum() if "taker_buy_base" in x else np.nan
    x["cvd_slope"] = x.cvd_proxy.diff(3) if "cvd_proxy" in x else np.nan
    x["atr_pct"]=x.atr/x.close.replace(0,np.nan)
    x["macro_trend"] = np.where(x.ema20>x.ema50,1,-1)
    return x.replace([np.inf,-np.inf],np.nan)


def add_multitimeframe_context(df: pd.DataFrame, base_interval: str) -> pd.DataFrame:
    """Attach only CLOSED 15m/1h context bars using backward as-of joins."""
    x=df.copy().sort_values("timestamp").reset_index(drop=True)
    for rule,label in [("15min","ctx15"),("1h","ctx1h")]:
        z=x.set_index("timestamp")[["open","high","low","close","volume"]].resample(rule,closed="right",label="right").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
        z[f"{label}_ema20"]=z.close.ewm(span=20,adjust=False).mean()
        z[f"{label}_ema50"]=z.close.ewm(span=50,adjust=False).mean()
        z[f"{label}_trend"]=np.where(z[f"{label}_ema20"]>z[f"{label}_ema50"],1,-1)
        z=z[[f"{label}_trend"]].reset_index()
        x=pd.merge_asof(x.sort_values("timestamp"),z.sort_values("timestamp"),on="timestamp",direction="backward")
    return x

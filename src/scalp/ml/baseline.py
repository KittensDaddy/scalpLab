from __future__ import annotations
import numpy as np, pandas as pd
from scalp.features import build_features

FEATURES=["ret1","ema20_slope","atr_pct","rsi","adx","vol_ratio","bb_width_pct","rv20","efficiency","close_loc","taker_buy_share","cvd_slope"]

def logistic_walkforward(df,train_frac=.70):
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import accuracy_score,roc_auc_score
    except ImportError as e:
        raise RuntimeError("Install optional ML dependencies: pip install -e '.[ml]'") from e
    x=build_features(df).copy(); x["target"]=(x.close.shift(-1)>x.close).astype(int); x=x.dropna(subset=FEATURES+["target"])
    n=len(x); cut=max(100,int(n*train_frac))
    if n-cut<50: return {"error":"INSUFFICIENT_SAMPLE","samples":n}
    train=x.iloc[:cut]; test=x.iloc[cut:]; model=LogisticRegression(max_iter=1000,class_weight="balanced"); model.fit(train[FEATURES],train.target)
    prob=model.predict_proba(test[FEATURES])[:,1]; pred=(prob>=.5).astype(int)
    return {"mode":"RESEARCH_ONLY","model":"LogisticRegression","train_samples":len(train),"test_samples":len(test),"accuracy":round(float(accuracy_score(test.target,pred)),4),"auc":round(float(roc_auc_score(test.target,prob)),4) if len(set(test.target))>1 else None,"feature_coefficients":dict(sorted(zip(FEATURES,model.coef_[0]),key=lambda x:abs(x[1]),reverse=True))}

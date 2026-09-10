# -*- coding: utf-8 -*-
"""40年滚动换池测试: 每5年用过去5年波动重筛高波动龙头池(=自适应+龙头集中=随时切换).
   复刻 core20.bt, 但运行在自定义长面板上, 且池子随时段轮换(非冻结)."""
import pandas as pd, numpy as np
np.seterr(all="ignore")

C_BP = 1.0

def load_long(f):
    d = pd.read_csv(f, index_col=0, parse_dates=True).apply(pd.to_numeric, errors="coerce")
    d.columns = [c.lstrip("\ufeff") for c in d.columns]
    d = d[~d.index.duplicated(keep="last")]
    return d.resample("ME").last()

PX = pd.concat([load_long("data/us_universe_weekly_adjclose.csv"),
                load_long("data/yahoo_global_weekly_adjclose.csv")], axis=1)
PX = PX.loc[:, ~PX.columns.duplicated()]
keep = [c for c in PX.columns if (PX[c].dropna().index[-1]-PX[c].dropna().index[0]).days/365.25 >= 40]
PX = PX[keep].sort_index()
print(f"≥40年历史龙头: {PX.shape[1]} 只 | {PX.index[0]:%Y-%m}->{PX.index[-1]:%Y-%m} 跨 {(PX.index[-1]-PX.index[0]).days/365.25:.0f}年")

def bt(px, w0, w1, scheme="EW", mode="ADAPT", strength=0.40, c_bp=C_BP, lookback=24, slow=60):
    px = px.loc[w0:w1].dropna(how="any")
    if len(px) < 72: return None
    r = px.pct_change().dropna(how="any")
    if len(r) < 60: return None
    R = np.clip(r.values, -0.95, None); T, N = R.shape; yrs = T/12.0
    c = c_bp/10000.0
    w_eq = np.ones(N)/N
    w_iv = np.zeros((T,N))
    sd24 = pd.DataFrame(R).rolling(24,min_periods=12).std().values
    sd24 = np.where(np.isfinite(sd24)&(sd24>1e-8), sd24, np.nan)
    for t in range(T):
        v = sd24[t]
        if np.all(np.isfinite(v)):
            iv=1.0/v; w_iv[t]=iv/iv.sum()
        else: w_iv[t]=w_eq
    lp=np.log(px.values); rel=lp-lp.mean(axis=1,keepdims=True); disp=rel.std(axis=1)
    z_T=np.zeros((T,N)); mom_T=np.zeros((T,N))
    for t in range(lookback,T):
        win=rel[t-lookback:t]; z_T[t]=-np.clip((rel[t-1]-win.mean(0))/(win.std(0)+1e-9),-2,2)
    for t in range(13,T):
        cum=np.prod(1+R[t-12:t-1],axis=0); mom_T[t]=(cum-cum.mean())/(cum.std()+1e-9)
    val,w=1.0,w_eq.copy(); nav=np.zeros(T+1); nav[0]=1.0; turn=0.0; nreb=0
    for t in range(T):
        wd=w*(1+R[t]); wd=wd/(wd.sum()+1e-12)
        tgt=w_eq if scheme=="EW" else w_iv[t]
        if mode=="ADAPT":
            sig=(z_T[t] if (t>=slow and disp[t-lookback:t].mean()>np.median(disp[t-slow:t])) else (mom_T[t] if t>=13 else np.zeros(N)))
        else: sig=np.zeros(N)
        if np.any(sig!=0):
            tw=np.clip(tgt+strength*tgt*sig,0,None); tgt=tw/(tw.sum()+1e-12)
        do=True
        if np.max(np.abs(wd-tgt))<0.10: do=False
        gr=float(np.dot(w,R[t])); val*=(1+gr)
        if do:
            turn+=float(np.abs(tgt-wd).sum()); nreb+=1; val*=(1-turn*c); w=tgt
        else: w=wd
        nav[t+1]=val
    if not np.isfinite(val) or val<=0: return None
    return dict(mult=val, net=(val**(1/yrs)-1)*100, n_reb=nreb)

# 滚动换池: 每10年用过去10年波动重筛 vol>=45 龙头池, 交易下一个10年
start_year = PX.index[0].year
years = list(range(start_year+10, PX.index[-1].year+1, 10))  # 首个交易窗需先有10年warmup
win_mult = 1.0
seg_rows = []
pools_seen = set()
N_MAX = 20
for yi in years:
    d0 = f"{yi}-01-31"; d1 = f"{min(yi+10, PX.index[-1].year+1)}-01-31"
    tr0 = f"{max(start_year, yi-10)}-01-31"   # 训练窗口=过去10年(避免前视), 不足则从头
    tr_px = PX.loc[tr0:d0]
    vol = {}
    for c in PX.columns:
        s = tr_px[c].dropna()
        r = s.pct_change().dropna()
        if len(r) < 60: continue
        if (r.abs()>0.9).any(): continue
        vol[c] = r.std()*np.sqrt(12)*100
    cand = [c for c,v in vol.items() if v>=45]
    if len(cand) < 3:
        cand = [c for c,v in vol.items() if v>=35]   # 兜底
    trp = PX.loc[tr0:d0, cand].dropna(how="any")
    corr = trp.pct_change().dropna().corr().fillna(0).values
    ix = {c:j for j,c in enumerate(cand)}
    sel = []; pool = sorted(cand, key=lambda c:-vol[c])
    while len(sel) < min(N_MAX,len(cand)) and pool:
        top = pool[:max(3,len(pool))]
        if not sel: pick=top[0]
        else:
            best=None;bc=None
            for c in top:
                ac=np.mean([corr[ix[c]][ix[o]] for o in sel])
                if best is None or ac<best: best,bc=ac,c
            pick=bc
        sel.append(pick); pool.remove(pick)
    m = bt(PX[sel], d0, d1)
    if m is None: continue
    seg_rows.append((d0[:4], len(sel), round(m['net'],1), round(m['mult'],2), sorted(set(sel)-pools_seen)))
    pools_seen.update(sel)
    win_mult *= m['mult']
total_yrs = (PX.index[-1]-PX.index[0]).days/365.25
full_cagr = (win_mult**(1/total_yrs)-1)*100
print("\n=== 40年滚动换池(每10年重筛高波动龙头, 随时切换) ===")
print(f"全期净CAGR: {full_cagr:.2f}% | 终值倍数: {win_mult:.1f}x | 跨度 {total_yrs:.0f}年")
print("\n时段    池N  段CAGR  段倍数  新进龙头")
for y,n,cg,mu,new in seg_rows:
    print(f"  {y}    {n:>2}    {cg:>6}%  {mu:>6}x  {','.join(new) if new else '(沿用)'}")

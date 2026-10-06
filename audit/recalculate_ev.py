#!/usr/bin/env python3
"""Old de-vig selection vs raw-odds EV, cell and pooled block bootstrap."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
sys.path[:0]=[str(Path(__file__).parent),str(Path(__file__).parents[1]/'SoccerMath')]
from backtest_experiment_all import load_league,run_walkforward,LEAGUES
from economic_ev import select_positive_ev
MODELS={'Poisson':('poisson_1','poisson_X','poisson_2'),'Elo':('elo_1','elo_X','elo_2'),'SoccerMath':('sm_1','sm_X','sm_2'),'Elo xG fix':('elo_fix_1','elo_fix_X','elo_fix_2'),'SoccerMath xG fix':('smfix_1','smfix_X','smfix_2')}
O=('1','X','2');F=('fair_b365_1','fair_b365_X','fair_b365_2');Q=('B365H','B365D','B365A')
def select(r,cols,method):
 p=np.array([r[c] for c in cols],float);q=np.array([r[c] for c in Q],float);f=np.array([r[c] for c in F],float)
 if not np.all(np.isfinite(np.r_[p,q,f])):return None
 if method=='ev':
  z=select_positive_ev(p,q);return None if z is None else z[0]
 j=int(np.argmax(p-f));return j if p[j]>f[j] else None
def main(reps=2000):
 rows=[]
 for prefix,league in LEAGUES:
  d=run_walkforward(load_league(prefix),camp_key=league)
  for season in ('2024/25','2025/26'):
   for idx,r in d[d.season==season].iterrows():
    for model,cols in MODELS.items():
     rec={'league':league,'season':season,'date':str(r.date)[:10],'row':f'{league}|{season}|{idx}','model':model}
     for method in ('old','ev'):
      j=select(r,cols,method);rec[method+'_selected']=j is not None;rec[method+'_side']=j
      rec[method+'_return']=np.nan if j is None else (r[Q[j]]-1 if r.real_1x2==O[j] else -1.)
     rows.append(rec)
 d=pd.DataFrame(rows);cells=[];pooled=[];rng=np.random.default_rng(240533)
 for keys,g in d.groupby(['league','season','model']):
  a=g[g.old_selected];b=g[g.ev_selected];cells.append(dict(zip(['league','season','model'],keys))|{'old_n':len(a),'old_roi':100*a.old_return.mean(),'new_n':len(b),'new_roi':100*b.ev_return.mean(),'new_rows_not_old':len(set(b.row)-set(a.row)),'removed_rows':len(set(a.row)-set(b.row))})
 for model,g in d.groupby('model'):
  vals={}; blocks=g[['league','season','date']].astype(str).agg('|'.join,axis=1);u=blocks.unique()
  for method in ('old','ev'):
   z=g[g[method+'_selected']];vals[method+'_n']=len(z);vals[method+'_roi']=100*z[method+'_return'].mean()
  boots=[]
  for _ in range(reps):
   chosen=rng.choice(u,len(u),replace=True);ix=np.concatenate([np.flatnonzero(blocks.to_numpy()==x) for x in chosen]);s=g.iloc[ix]
   boots.append(100*(s.loc[s.ev_selected,'ev_return'].mean()-s.loc[s.old_selected,'old_return'].mean()))
  vals.update(model=model,delta_roi=vals['ev_roi']-vals['old_roi'],ci95_low=float(np.quantile(boots,.025)),ci95_high=float(np.quantile(boots,.975)))
  pooled.append(vals)
 Path('audit/output').mkdir(exist_ok=True);Path('audit/output/ev_recalculation.json').write_text(json.dumps(cells,indent=2));pd.DataFrame(pooled).to_csv('audit/output/ev_pooled.csv',index=False)
 print(pd.DataFrame(pooled).to_string(index=False));print('new_rows_not_old',sum(x['new_rows_not_old'] for x in cells),'removed_rows',sum(x['removed_rows'] for x in cells))
if __name__=='__main__':main()

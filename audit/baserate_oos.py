#!/usr/bin/env python3
"""Benchmark train, expanding PIT (con/senza shrinkage), oracolo; seed fisso."""
import argparse,sys
from pathlib import Path
import numpy as np,pandas as pd
sys.path[:0]=[str(Path(__file__).parent),str(Path(__file__).parents[1]/'SoccerMath')]
from backtest_experiment_all import LEAGUES,load_league,run_walkforward
def scores(y,p):
 p=np.clip(np.asarray(p,float),1e-12,1-1e-12);y=np.asarray(y,float);return np.mean((y-p)**2),np.mean(-(y*np.log(p)+(1-y)*np.log(1-p)))
def decomp(y,p,bins=10):
 y=np.asarray(y,float);p=np.asarray(p,float);ids=np.minimum((p*bins).astype(int),bins-1);m=y.mean();rel=res=0.
 for b in range(bins):
  z=ids==b
  if z.any():rel+=z.mean()*(p[z].mean()-y[z].mean())**2;res+=z.mean()*(y[z].mean()-m)**2
 return rel,res,m*(1-m)
def boot(y,pm,pb,blocks,reps,seed):
 rng=np.random.default_rng(seed);u=np.unique(blocks);db=[];dl=[]
 for _ in range(reps):
  take=rng.choice(u,len(u),replace=True);ix=np.concatenate([np.flatnonzero(blocks==x) for x in take]);a,b=scores(y[ix],pm[ix]);c,d=scores(y[ix],pb[ix]);db.append(a-c);dl.append(b-d)
 return *np.quantile(db,[.025,.975]),*np.quantile(dl,[.025,.975])
def raw(prefix,upto):
 d=pd.concat([pd.read_csv(Path('SoccerMath/database')/f'{prefix}_{y}.csv') for y in range(2022,upto)],ignore_index=True);g=d.FTHG+d.FTAG
 return {'OU2.5':(g>2.5).astype(int).to_numpy(),'GG/NG':((d.FTHG>0)&(d.FTAG>0)).astype(int).to_numpy()}
def main():
 a=argparse.ArgumentParser();a.add_argument('--reps',type=int,default=2000);a.add_argument('--shrinkage',type=float,default=20);z=a.parse_args();obs=[]
 for prefix,league in LEAGUES:
  bt=run_walkforward(load_league(prefix),camp_key=league)
  for season,year in [('2024/25',2024),('2025/26',2025)]:
   d=bt[bt.season==season].sort_values('date');tr=raw(prefix,year)
   for market,pcol,target,rc in [('OU2.5','poisson_o25','OVER','real_uo'),('GG/NG','poisson_gg','GG','real_gg')]:
    y=(d[rc]==target).astype(int).to_numpy();prior=tr[market].mean();n=np.arange(len(y));cum=np.r_[0,np.cumsum(y)[:-1]]
    exp=(z.shrinkage*prior+cum)/(z.shrinkage+n);exp0=np.divide(cum,n,out=np.full(len(y),prior),where=n>0)
    for i,(_,r) in enumerate(d.iterrows()):obs.append(dict(league=league,season=season,date=str(r.date)[:10],market=market,y=y[i],model=r[pcol],train=prior,expanding=exp[i],expanding_no_shrink=exp0[i],ORACOLO=y.mean(),train_n=len(tr[market])))
 o=pd.DataFrame(obs);detail=[];pooled=[]
 for keys,g in o.groupby(['league','season','market']):
  for bn in ['train','expanding','expanding_no_shrink','ORACOLO']:detail.append(metric(g,keys,bn,z.reps,False))
 for market,g in o.groupby('market'):
  for bn in ['train','expanding','expanding_no_shrink','ORACOLO']:pooled.append(metric(g,(market,),bn,z.reps,True))
 Path('audit/output').mkdir(exist_ok=True);pd.DataFrame(detail).to_csv('audit/output/baserate_benchmarks.csv',index=False);pd.DataFrame(pooled).to_csv('audit/output/baserate_pooled.csv',index=False);print(pd.DataFrame(pooled).to_string(index=False))
def metric(g,keys,bn,reps,pooled):
 y=g.y.to_numpy(float);pm=g.model.to_numpy(float);pb=g[bn].to_numpy(float);mb,mll=scores(y,pm);bb,bll=scores(y,pb);mr,mres,mu=decomp(y,pm);br,bres,bu=decomp(y,pb);blocks=g[['league','season','date']].agg('|'.join,axis=1).to_numpy();lo,hi,llo,lhi=boot(y,pm,pb,blocks,reps,240533)
 base={'market':keys[0] if pooled else keys[2],'benchmark':bn,'n':len(g),'model_brier':mb,'benchmark_brier':bb,'delta_brier':mb-bb,'brier_ci_low':lo,'brier_ci_high':hi,'model_logloss':mll,'benchmark_logloss':bll,'delta_logloss':mll-bll,'logloss_ci_low':llo,'logloss_ci_high':lhi,'brier_skill':1-mb/bb,'model_reliability':mr,'model_resolution':mres,'model_uncertainty':mu,'benchmark_reliability':br,'benchmark_resolution':bres,'benchmark_uncertainty':bu}
 if not pooled:base={'league':keys[0],'season':keys[1]}|base
 return base
if __name__=='__main__':main()

"""Apply saved REV2 probability configuration to an already validated fixed-rule board."""
import argparse,json
from pathlib import Path
import numpy as np
from scipy.special import expit,logit
from core import kelly,payout
def probability(config,market,week,market_novig=None,historical_only=False):
 z=config['historical_models' if historical_only else 'updated_models'][market];phase='W1-7' if week<=7 else 'W8+'
 if z['method']=='Pooled Jeffreys':return z['a']/(z['a']+z['b'])
 if z['method']=='Season partial pooling':
  g=z['groups'][phase]
  if not z['k']:return g['a']/(g['a']+g['b'])
  mu=float(np.dot(z['mu_nodes'],z['mu_weights']));return (g['wins']+z['k']*mu)/(g['n']+z['k'])
 if market_novig is None or not 0<market_novig<1:raise ValueError('Contemporaneous two-sided no-vig ML probability required')
 offset=z['alpha']+z.get('phase_contrast',0)*(1 if week<=7 else -1)
 return float(expit(logit(market_novig)+offset))
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'results/recalibration_config.json');ap.add_argument('--market',choices=['Spread','Total','Moneyline'],required=True);ap.add_argument('--week',type=int,required=True);ap.add_argument('--odds',type=float,required=True);ap.add_argument('--no-vig',type=float);a=ap.parse_args();c=json.loads(a.config.read_text());p=probability(c,a.market,a.week,a.no_vig)
 print(json.dumps(dict(model_p=p,full_kelly=kelly(p,a.odds),ev=p*payout(a.odds)-(1-p),adjusted_kelly=None,recommended_kelly=None,note='Use only after REV1 qualification and valid pregame input checks. Late OU remains B+/Watch.'),indent=2))

"""Fixed full-population search menu. No outcome-driven rule construction."""
import numpy as np

def menu(market):
    rules=[]
    def add(name,base,context='all',magnitude=0):rules.append(dict(name=name,base=base,context=context,magnitude=magnitude))
    if market in ['Spread','Moneyline']:
        for base in ['relative_positive','relative_negative','own_positive','own_negative','own_and_relative_positive']:
            add(base,base)
        for ctx in ['favorite','underdog','srs_agrees','srs_disagrees']:
            add('relative_positive__'+ctx,'relative_positive',ctx)
            add('own_positive__'+ctx,'own_positive',ctx)
        for q in [.5,.75]:
            add('relative_positive__magnitude_q'+str(q),'relative_positive','all',q)
            for ctx in ['favorite','underdog']:
                add('relative_positive__'+ctx+'__magnitude_q'+str(q),'relative_positive',ctx,q)
        if market=='Moneyline':
            for band in ['favorite_heavy','favorite_short','dog_small','dog_medium','dog_large']:
                for base in ['relative_positive','own_positive']:
                    add(base+'__'+band,base,band)
        else:
            for band in ['handicap_small','handicap_medium','handicap_large']:
                add('relative_positive__'+band,'relative_positive',band)
    else:
        for direction in ['Over','Under']:
            for base in ['offense_positive','defense_positive','both_positive','combined_positive','offense_conflict','defense_conflict']:
                add(direction+'__'+base,base,direction)
            for ctx in ['total_low','total_middle','total_high','gap_agrees','gap_disagrees']:
                add(direction+'__combined_positive__'+ctx,'combined_positive',direction+'|'+ctx)
            for q in [.5,.75]:add(direction+'__combined_positive__magnitude_q'+str(q),'combined_positive',direction,q)
    return rules

def cuts(d,market):
    return dict(magnitude50=float(d.rel.abs().quantile(.5)),magnitude75=float(d.rel.abs().quantile(.75)),total33=float(d.total.quantile(1/3)),total67=float(d.total.quantile(2/3)))

def choose(d,mask,score):
    # One side per game; ties use anchor then canonical side, never outcomes.
    x=d.loc[mask,['idx','sign','anchor']].copy();x['score']=score[mask]
    x=x.sort_values(['idx','score','anchor','sign'],ascending=[True,False,False,False]).drop_duplicates('idx')
    sign=np.zeros(int(d.idx.max())+1);sign[x.idx.to_numpy(int)]=x.sign
    return sign

def context_mask(d,ctx,thresholds):
    mask=np.ones(len(d),bool)
    for part in ctx.split('|'):
        if part=='all':continue
        if part in ['Over','Under']:mask&=d.selection.eq(part).to_numpy()
        elif part=='favorite':mask&=np.where(d.market.eq('Spread'),d.line.to_numpy()<0,d.anchor.to_numpy()>.5)
        elif part=='underdog':mask&=np.where(d.market.eq('Spread'),d.line.to_numpy()>0,d.anchor.to_numpy()<.5)
        elif part in ['srs_agrees','gap_agrees']:mask&=d.gap.to_numpy()>0
        elif part in ['srs_disagrees','gap_disagrees']:mask&=d.gap.to_numpy()<0
        elif part=='favorite_heavy':mask&=d.odds.to_numpy()<-200
        elif part=='favorite_short':mask&=(d.odds.to_numpy()>=-200)&(d.odds.to_numpy()<0)
        elif part=='dog_small':mask&=(d.odds.to_numpy()>0)&(d.odds.to_numpy()<200)
        elif part=='dog_medium':mask&=(d.odds.to_numpy()>=200)&(d.odds.to_numpy()<400)
        elif part=='dog_large':mask&=d.odds.to_numpy()>=400
        elif part=='handicap_small':mask&=d.line.abs().to_numpy()<3
        elif part=='handicap_medium':mask&=(d.line.abs().to_numpy()>=3)&(d.line.abs().to_numpy()<7)
        elif part=='handicap_large':mask&=d.line.abs().to_numpy()>=7
        elif part=='total_low':mask&=d.total.to_numpy()<thresholds['total33']
        elif part=='total_middle':mask&=(d.total.to_numpy()>=thresholds['total33'])&(d.total.to_numpy()<thresholds['total67'])
        elif part=='total_high':mask&=d.total.to_numpy()>=thresholds['total67']
        else:raise ValueError(part)
    return mask

def indicators(d,rule,thresholds):
    ctx=context_mask(d,rule['context'],thresholds)
    b=rule['base'];rel=d.rel.to_numpy();own=d.own.to_numpy();off=d.off.to_numpy();defense=d.defense.to_numpy()
    conditions=dict(relative_positive=rel>0,relative_negative=rel<0,own_positive=own>0,own_negative=own<0,own_and_relative_positive=(own>0)&(rel>0),offense_positive=off>0,defense_positive=defense>0,both_positive=(off>0)&(defense>0),combined_positive=rel>0,offense_conflict=(off>0)&(defense<0),defense_conflict=(defense>0)&(off<0))
    mask=ctx&conditions[b]
    if rule['magnitude']:mask&=abs(rel)>=thresholds['magnitude50' if rule['magnitude']==.5 else 'magnitude75']
    structural=choose(d,ctx,d.anchor.to_numpy())
    selected=choose(d,mask,rel)
    return structural,selected

//! Deterministic policy compiler. All inputs are observable at this information set.
use postflop_solver::Action;
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Trait {
    pub kind: String,
    pub strength: f64,
    pub streets: Vec<usize>, // public board length: 3, 4, 5
}

// Percent of the current pot added to one action kind at the opponent's decisions on these streets.
#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Incentives {
    #[serde(default)] pub check: f32,
    #[serde(default)] pub bet: f32,
    #[serde(default)] pub fold: f32,
    #[serde(default)] pub call: f32,
    #[serde(default,skip_serializing_if="Option::is_none")] pub streets: Option<Vec<usize>>, // public board length: 3, 4, 5; absent means every street
}

#[derive(Clone, Debug, Default, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Profile {
    #[serde(default)]
    pub traits: Vec<Trait>,
    // Explicit synthetic full-tree policy for independently checkable acceptance games.
    pub fixture_river_bet: Option<f64>,
    #[serde(default)]
    pub overrides:Vec<Override>,
    #[serde(default)]
    pub incentives:Option<Incentives>,
}

#[derive(Clone,Debug,Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
pub struct Override {
    pub path:Vec<usize>,pub combo:String,pub probabilities:Vec<f32>,
    #[serde(default)] pub scene:Option<serde_json::Value>,
    #[serde(default)] pub actions:Option<Vec<String>>,
    #[serde(default)] pub board:Option<Vec<String>>,
    #[serde(default)] pub seat:Option<usize>,
}

pub fn validate(profile: &Profile) -> Result<(), String> {
    if let Some(i)=&profile.incentives {
        if [i.check,i.bet,i.fold,i.call].iter().any(|v|!v.is_finite()||v.abs()>50.0) {return Err("incentives must be finite percentages within 50".into());}
        if i.streets.as_ref().is_some_and(|s|s.is_empty()||s.iter().any(|v|!(3..=5).contains(v))) {return Err("incentive streets must be a nonempty subset of [3,4,5]".into());}
    }
    for o in &profile.overrides {
        if !o.combo.is_ascii() || o.combo.len()!=4 || o.probabilities.is_empty() || o.probabilities.iter().any(|p|!p.is_finite() || *p<0.0 || *p>1.0) || (o.probabilities.iter().sum::<f32>()-1.0).abs()>1e-6 {
            return Err("manual override must specify a complete probability distribution summing to 1".into());
        }
    }
    if let Some(q) = profile.fixture_river_bet {
        if !(0.0..=1.0).contains(&q) { return Err("fixture probability outside [0,1]".into()); }
        if !profile.traits.is_empty() { return Err("fixture and traits cannot be mixed".into()); }
    }
    for t in &profile.traits {
        if !["station", "overbluff", "underbluff", "weak_check", "double_barrel_give_up", "delayed_aggression"].contains(&t.kind.as_str()) {
            return Err(format!("unknown trait {}", t.kind));
        }
        if !t.strength.is_finite() || !(0.0..=6.0).contains(&t.strength) || t.streets.is_empty() || t.streets.iter().any(|s| !(3..=5).contains(s)) {
            return Err("trait strength must be 0..6 and streets a nonempty subset of [3,4,5]".into());
        }
    }
    Ok(())
}

// Exact made-hand category (not a strength/equity abstraction). Kicker irrelevant here.
pub fn category(cards: &[u8]) -> u8 {
    // Many betting histories share the same cards. Cache only exact card sets,
    // never equity, ranges or a history-dependent policy decision.
    thread_local! {static CACHE:std::cell::RefCell<std::collections::HashMap<u64,u8>>=std::cell::RefCell::new(std::collections::HashMap::new());}
    let mask=cards.iter().fold(0u64,|m,&c|m|(1u64<<c));
    // Preserve the old evaluator's behavior even for unreachable duplicate-card inputs.
    let distinct=mask.count_ones() as usize==cards.len();
    if distinct {if let Some(v)=CACHE.with(|c|c.borrow().get(&mask).copied()){return v;}}
    let mut best = 0;
    for a in 0..cards.len() { for b in a+1..cards.len() { for c in b+1..cards.len() {
        for d in c+1..cards.len() { for e in d+1..cards.len() {
            let five = [cards[a], cards[b], cards[c], cards[d], cards[e]];
            let mut counts = [0u8; 13];
            for card in five { counts[card as usize / 4] += 1; }
            let flush = five.iter().all(|x| x % 4 == five[0] % 4);
            let straight = (0..9).any(|s| (s..s+5).all(|r| counts[r] > 0)) || [12,0,1,2,3].iter().all(|&r| counts[r]>0);
            let pairs = counts.iter().filter(|&&n| n == 2).count();
            let rank = if flush && straight {8} else if counts.contains(&4) {7}
                else if counts.contains(&3) && pairs > 0 {6} else if flush {5}
                else if straight {4} else if counts.contains(&3) {3}
                else if pairs == 2 {2} else if pairs == 1 {1} else {0};
            best = best.max(rank);
        } }
    } } }
    if distinct {CACHE.with(|c|{let mut c=c.borrow_mut();if c.len()<1_000_000 {c.insert(mask,best);}});}
    best
}

pub fn compile<'a>(base: &[f32], actions: &[Action], hole: (u8,u8), board: &[u8], history: &[(usize, usize, Action)], profile: &'a Profile, player: usize) -> (Vec<f32>, Vec<&'a str>) {
    let facing = actions.contains(&Action::Fold);
    if let Some(q) = profile.fixture_river_bet {
        let mut p = vec![0.0; actions.len()];
        if facing {
            for (i,a) in actions.iter().enumerate() { p[i] = match a { Action::Fold | Action::Call => 0.5, _ => 0.0 }; }
        } else {
            let bet = if board.len()==5 { q as f32 } else { 1.0 };
            let n = actions.iter().filter(|a| matches!(a, Action::Bet(_) | Action::AllIn(_))).count();
            for (i,a) in actions.iter().enumerate() { p[i] = match a { Action::Check => if n==0 {1.0} else {1.0-bet}, Action::Bet(_) | Action::AllIn(_) => bet/n as f32, _=>0.0 }; }
        }
        return (p, vec!["synthetic-barrel-reference-v1".into()]);
    }
    if profile.traits.iter().all(|t|t.strength==0.0 || !t.streets.contains(&board.len())) {return (base.to_vec(),vec![]);}
    if board.contains(&hole.0)||board.contains(&hole.1) {return (base.to_vec(),vec![]);}
    let mut cards=[0;7];cards[..board.len()].copy_from_slice(board);cards[board.len()]=hole.0;cards[board.len()+1]=hole.1;
    let rank = category(&cards[..board.len()+2]);
    // On paired boards a board-only pair still counts as weak.
    let board_rank = if board.len() >= 5 { category(board) } else {
        let mut c=[0;13]; for x in board { c[*x as usize/4]+=1; }
        if c.contains(&3) {3} else if c.iter().filter(|&&n| n==2).count()==2 {2} else if c.contains(&2) {1} else {0}
    };
    let hole_pair = hole.0/4==hole.1/4 || board.iter().any(|c| c/4==hole.0/4 || c/4==hole.1/4);
    let weak = rank <= board_rank && !hole_pair;
    let strong = rank >= 2 && rank > board_rank;
    let mut flop_checks = history.iter().filter(|(s,_,_)| *s==3).map(|(_,_,a)| *a);
    let delayed = flop_checks.next()==Some(Action::Check) && flop_checks.next()==Some(Action::Check) && flop_checks.next().is_none();
    let barrelled = [3,4].iter().all(|street| history.iter().any(|(s,p,a)| s==street && *p==player && matches!(a,Action::Bet(_) | Action::Raise(_) | Action::AllIn(_))));
    let mut biases = vec![0.0f64; actions.len()];
    let mut trace = Vec::new();
    let mut traits = profile.traits.iter().collect::<Vec<_>>();
    traits.sort_by(|a,b| a.kind.cmp(&b.kind).then(a.strength.total_cmp(&b.strength)));
    for t in traits {
        if t.strength==0.0 || !t.streets.contains(&board.len()) { continue; }
        let mut applied=false;
        for (i,a) in actions.iter().enumerate() {
            let aggressive = matches!(a,Action::Bet(_) | Action::Raise(_) | Action::AllIn(_));
            let delta = match t.kind.as_str() {
                "station" if facing && *a==Action::Call => t.strength,
                "overbluff" if !facing && aggressive && weak => t.strength,
                "underbluff" if !facing && aggressive && weak => -t.strength,
                "weak_check" if !facing && aggressive && strong => t.strength,
                "double_barrel_give_up" if !facing && aggressive && weak => {
                    if board.len()<5 {t.strength} else if barrelled {-t.strength} else {0.0}
                },
                "delayed_aggression" if !facing && aggressive && board.len()==4 && delayed => t.strength,
                _ => 0.0,
            };
            biases[i]+=delta; applied |= delta != 0.0;
        }
        if applied {trace.push(t.kind.as_str());}
    }
    if trace.is_empty() { return (base.to_vec(), trace); } // Neutral is bit-for-bit baseline.
    if biases.iter().all(|b|*b==0.0){return (base.to_vec(),trace);}
    // Hierarchical normalization: bias total aggression once, then retain the
    // baseline conditional sizing mix. Zero-frequency groups use uniform sizes.
    let group=|a:&Action|match a {Action::Call=>1,Action::Bet(_)|Action::Raise(_)|Action::AllIn(_)=>2,_=>0};
    let mut mass=[0.0f64;3];let mut count=[0;3];let mut bias=[0.0;3];
    for (i,a) in actions.iter().enumerate(){let g=group(a);mass[g]+=base[i] as f64;count[g]+=1;bias[g]=biases[i];}
    let mut w=[0.0;3];for g in 0..3 {if count[g]>0 {w[g]=mass[g].max(1e-6)*bias[g].exp();}}
    let total:f64=w.iter().sum();
    let mut sizing_mass=[0.0;3];
    for (i,a) in actions.iter().enumerate(){let g=group(a);sizing_mass[g]+=(base[i] as f64).max(1e-6/count[g] as f64);}
    (actions.iter().enumerate().map(|(i,a)|{let g=group(a);(w[g]/total*(base[i] as f64).max(1e-6/count[g] as f64)/sizing_mass[g]) as f32}).collect(),trace)
}

#[cfg(test)]
mod tests {
    use super::*;
    fn t(kind:&str)->Trait { Trait {kind:kind.into(),strength:2.0,streets:vec![3,4,5]} }
    #[test] fn composition_and_neutral() {
        let board=[0,5,22,27,32]; let hole=(40,37);
        let p=Profile{traits:vec![t("station"),t("overbluff")],..Profile::default()};
        let (a,_)=compile(&[0.7,0.3],&[Action::Fold,Action::Call],hole,&board,&[],&p,1);
        let (b,_)=compile(&[1.0,0.0],&[Action::Check,Action::Bet(10)],hole,&board,&[],&p,1);
        assert!(a[1]>0.3 && b[1]>0.0);
        let mut reversed=p.clone(); reversed.traits.reverse();
        assert_eq!(compile(&[0.7,0.3],&[Action::Fold,Action::Call],hole,&board,&[],&p,1),compile(&[0.7,0.3],&[Action::Fold,Action::Call],hole,&board,&[],&reversed,1));
        assert_eq!(compile(&[1.0,0.0],&[Action::Check,Action::Bet(10)],hole,&board,&[],&Profile::default(),1).0,vec![1.0,0.0]);
    }
    #[test] fn draw_reclassified_and_history() {
        assert_eq!(category(&[50,46,42,38,0]),0);
        assert_eq!(category(&[50,46,42,38,0,34]),8);
        let p=Profile{traits:vec![t("delayed_aggression")],..Profile::default()};
        let a=[Action::Check,Action::Bet(10)];
        let h=[(3,0,Action::Check),(3,1,Action::Check)];
        assert!(compile(&[0.5,0.5],&a,(40,37),&[0,5,22,27],&h,&p,1).0[1]>0.5);
        assert_eq!(compile(&[0.5,0.5],&a,(40,37),&[0,5,22,27],&[],&p,1).0,vec![0.5,0.5]);
    }
    #[test] fn multiple_sizes_share_one_aggression_bias() {
        let p=Profile{traits:vec![t("overbluff")],..Profile::default()};
        let a=compile(&[0.7,0.3],&[Action::Check,Action::Bet(10)],(40,37),&[0,5,22,27,32],&[],&p,1).0;
        let b=compile(&[0.7,0.1,0.2],&[Action::Check,Action::Bet(10),Action::Bet(20)],(40,37),&[0,5,22,27,32],&[],&p,1).0;
        assert!((a[1]-b[1]-b[2]).abs()<1e-6);
        assert!((b[2]/b[1]-2.0).abs()<1e-6);
        let c=compile(&[0.7,0.3,0.0],&[Action::Check,Action::Bet(10),Action::Bet(20)],(40,37),&[0,5,22,27,32],&[],&p,1).0;
        assert!(c[2]>0.0 && (c.iter().sum::<f32>()-1.0).abs()<1e-6);
    }
}

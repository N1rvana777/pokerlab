//! Information-set best response over the engine's canonical tree.
//! Own actions are selected only AFTER hidden-opponent reach is integrated.
use postflop_solver::*;
use rayon::prelude::*;
use std::mem::MaybeUninit;

pub fn probabilities<G: Game>(game: &G, node: &G::Node) -> Vec<f32> {
    let n = node.num_actions();
    let h = game.num_private_hands(node.player());
    let mut p = vec![0.0; n*h];
    if n == 1 { p.fill(1.0); return p; }
    if game.is_compression_enabled() {
        normalize_probabilities(&mut p, &dense_strategy_compressed(game,node), n, h);
    } else {
        normalize_probabilities(&mut p, &dense_strategy(game,node), n, h);
    }
    let lock=game.locking_strategy(node);
    if !lock.is_empty() {
        for (v,&fixed) in p.iter_mut().zip(lock) {if fixed>=0.0 {*v=fixed;}}
    }
    p
}

// Every u16 is represented exactly in both f32 and f64, so reading its f64 value
// directly preserves the former u16 -> f32 -> f64 arithmetic and summation order.
// Avoid a second full f32 copy while retaining the same zero-reach default.
fn normalize_probabilities<T:Copy+Into<f64>>(p:&mut [f32],values:&[T],n:usize,h:usize) {
    for hand in 0..h {
        let sum:f64=(0..n).map(|a|values[a*h+hand].into()).sum();
        for a in 0..n {p[a*h+hand]=if sum>0.0 {(values[a*h+hand].into()/sum) as f32}else{1.0/n as f32};}
    }
}

pub fn set_probabilities<G:Game>(game:&G,node:&mut G::Node, values:&[f32], compressed:bool) {
    if compressed {
        let scale=values.iter().copied().fold(0.0f32,f32::max);
        let encoder=65535.0/scale.max(f32::MIN_POSITIVE);
        for (d,&v) in dense_strategy_compressed_mut(game,node).iter_mut().zip(values) {*d=(v*encoder).round().clamp(0.0,65535.0) as u16;}
        node.set_strategy_scale(scale);
    } else {dense_strategy_mut(game,node).copy_from_slice(values);}
}

pub fn export_best_response<G: Game>(game: &G, hero: usize) -> f32 {
    export_with_parallelism::<G, true>(game, hero)
}

fn export_with_parallelism<G: Game, const PARALLEL: bool>(game: &G, hero: usize) -> f32 {
    let values=visit::<G, PARALLEL>(game,&mut game.root(),hero,game.initial_weights(hero^1));
    values.iter().zip(game.initial_weights(hero)).map(|(&v,&w)|v as f64*w as f64).sum::<f64>() as f32
}

// An indexed collect preserves the original action order. Only disjoint child
// subtrees run concurrently; all sums, isomorphic swaps and tie-breaking below
// retain their serial order and precision. The false specialization is kept as
// a regression reference, without changing the production API.
fn children<N: GameNode, F, const PARALLEL: bool>(node: &N, evaluate: F) -> Vec<Vec<f32>>
where F: Fn(usize) -> Vec<f32> + Send + Sync {
    if PARALLEL && node.enable_parallelization() {
        (0..node.num_actions()).into_par_iter().map(evaluate).collect()
    } else {
        (0..node.num_actions()).map(evaluate).collect()
    }
}

fn visit<G:Game, const PARALLEL: bool>(game:&G,node:&mut G::Node,hero:usize,reach:&[f32])->Vec<f32> {
    let h=game.num_private_hands(hero);
    if node.is_terminal() {
        let mut result=vec![MaybeUninit::new(0.0);h];
        game.evaluate(&mut result,node,hero,reach);
        // evaluate initializes all entries, per Game's evaluator contract.
        return result.into_iter().map(|v|unsafe{v.assume_init()}).collect();
    }
    let n=node.num_actions();
    if node.is_chance() {
        let next:Vec<f32>=reach.iter().map(|r|r/game.chance_factor(node) as f32).collect();
        let children=children::<_, _, PARALLEL>(node,|a|visit::<G, PARALLEL>(game,&mut node.play(a),hero,&next));
        let mut sum=vec![0.0f64;h];
        for child in &children {for (v,&c) in sum.iter_mut().zip(child) {*v+=c as f64;}}
        for (i,&index) in game.isomorphic_chances(node).iter().enumerate() {
            let mut v=children[index as usize].clone();
            for &(a,b) in &game.isomorphic_swap(node,i)[hero] {v.swap(a as usize,b as usize);}
            for (out,c) in sum.iter_mut().zip(v) {*out+=c as f64;}
        }
        return sum.into_iter().map(|x|x as f32).collect();
    }
    if node.player()==hero {
        assert!(game.locking_strategy(node).is_empty(),"Hero must not be locked during BR extraction");
        let children=children::<_, _, PARALLEL>(node,|a|visit::<G, PARALLEL>(game,&mut node.play(a),hero,reach));
        let mut result=vec![0.0;h];
        let mut strategy=vec![0.0;n*h];
        for hand in 0..h {
            let mut best=0;
            for a in 1..n {if children[a][hand]>children[best][hand] {best=a;}}
            result[hand]=children[best][hand];
            strategy[best*h+hand]=1.0;
        }
        if n>1 {set_probabilities(game,node,&strategy,game.is_compression_enabled());}
        result
    } else {
        let p=probabilities(game,node);
        let mut sum=vec![0.0;h];
        let evaluate=|a:usize| {
            let next:Vec<f32>=reach.iter().enumerate().map(|(j,&r)|r*p[a*reach.len()+j]).collect();
            visit::<G, PARALLEL>(game,&mut node.play(a),hero,&next)
        };
        if PARALLEL && node.enable_parallelization() {
            let children=children::<_, _, PARALLEL>(node,evaluate);
            for child in children {for (v,c) in sum.iter_mut().zip(child) {*v+=c;}}
        } else {
            // Keep the original streaming reduction on serial/River nodes.
            for a in 0..n {for (v,c) in sum.iter_mut().zip(evaluate(a)) {*v+=c;}}
        }
        sum
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probability_reads_preserve_previous_copy_based_normalization() {
        fn old(values:&[f32],n:usize,h:usize)->Vec<u32> {
            let mut p=vec![0.0f32;n*h];
            for hand in 0..h {
                let sum:f64=(0..n).map(|a|values[a*h+hand] as f64).sum();
                for a in 0..n {p[a*h+hand]=if sum>0.0 {(values[a*h+hand] as f64/sum) as f32}else{1.0/n as f32};}
            }
            p.into_iter().map(f32::to_bits).collect()
        }
        let h=65536;
        let mut words=Vec::with_capacity(3*h);
        words.extend((0..h).map(|i|i as u16));
        words.extend((0..h).map(|i|(65535-i) as u16));
        words.extend((0..h).map(|i|(i%7) as u16));
        words[h]=0; // first hand has zero mass in every action
        let floats:Vec<f32>=words.iter().map(|&v|v as f32).collect();
        let mut result=vec![0.0;3*h];
        normalize_probabilities(&mut result,&words,3,h);
        assert_eq!(result.into_iter().map(f32::to_bits).collect::<Vec<_>>(),old(&floats,3,h));
        let floats=[0.0,f32::from_bits(1),1.0e20,0.0,f32::MIN_POSITIVE,1.0e-20];
        let mut result=[0.0;6];
        normalize_probabilities(&mut result,&floats,2,3);
        assert_eq!(result.map(f32::to_bits).to_vec(),old(&floats,2,3));
    }

    fn game(street: BoardState, compressed: bool, sparse: bool) -> PostFlopGame {
        let cards = CardConfig {
            range: ["AA:0.7,AKs:0.3".parse().unwrap(), "KK:0.4,KQs:0.8".parse().unwrap()],
            flop: flop_from_str("9h8h2h").unwrap(),
            turn: if street == BoardState::Turn { card_from_str("4s").unwrap() } else { NOT_DEALT },
            river: NOT_DEALT,
        };
        let bets: BetSizeOptions = ("50%", "").try_into().unwrap();
        let river: BetSizeOptions = ("50%", "2x").try_into().unwrap();
        let tree = ActionTree::new(TreeConfig {
            initial_state: street,
            starting_pot: 20,
            effective_stack: 20,
            flop_bet_sizes: [bets.clone(), bets.clone()],
            turn_bet_sizes: [bets.clone(), bets],
            river_bet_sizes: [river.clone(), river],
            ..Default::default()
        }).unwrap();
        let mut game = PostFlopGame::prepare_config(cards, tree, false).unwrap();
        game.set_sparse_storage(sparse).unwrap();
        game.build_prepared().unwrap();
        let bytes = if compressed { game.memory_usage().1 } else { game.memory_usage().0 };
        assert!(bytes < 20 * 1024 * 1024, "BR fixture exceeds 20 MiB: {bytes}");
        game.allocate_memory(compressed);
        game
    }

    fn freeze_opponent(game: &PostFlopGame, node: &mut PostFlopNode, hero: usize) {
        if node.is_terminal() { return; }
        if !node.is_chance() && node.player() != hero && node.num_actions() > 1 {
            let n = node.num_actions();
            let h = game.num_private_hands(node.player());
            let mut p = vec![0.0; n * h];
            // Suit-symmetric, deliberately non-equilibrium policy. With >2
            // actions, the middle action has zero reach but its subtree remains.
            p[..h].fill(0.37);
            p[(n - 1) * h..].fill(0.63);
            set_probabilities(game, node, &p, game.is_compression_enabled());
        }
        for a in 0..node.num_actions() { freeze_opponent(game, &mut node.play(a), hero); }
    }

    fn policy_words(game: &PostFlopGame, player: Option<usize>) -> Vec<u32> {
        fn append(game: &PostFlopGame, node: &PostFlopNode, player: Option<usize>, out: &mut Vec<u32>) {
            if node.is_terminal() { return; }
            if !node.is_chance() && node.num_actions() > 1 && player.map_or(true, |p| p == node.player()) {
                out.push(node.player() as u32);
                out.push(node.num_actions() as u32);
                if game.is_compression_enabled() {
                    out.push(node.strategy_scale().to_bits());
                    out.extend(dense_strategy_compressed(game,node).iter().map(|&v| v as u32));
                } else {
                    out.extend(dense_strategy(game,node).iter().map(|v| v.to_bits()));
                }
            }
            for a in 0..node.num_actions() { append(game, &node.play(a), player, out); }
        }
        let mut out = Vec::new();
        append(game, &game.root(), player, &mut out);
        out
    }

    fn count_chances(game: &PostFlopGame, node: &PostFlopNode) -> (usize, usize, usize) {
        if node.is_terminal() { return (0, 0, 0); }
        let mut counts = (0, 0, 0);
        if node.is_chance() {
            counts.0 += node.num_actions();
            counts.1 += game.isomorphic_chances(node).len();
        }
        if node.enable_parallelization() && node.num_actions() > 1 { counts.2 += 1; }
        for a in 0..node.num_actions() {
            let child = count_chances(game, &node.play(a));
            counts.0 += child.0;
            counts.1 += child.1;
            counts.2 += child.2;
        }
        counts
    }

    #[test]
    fn parallel_br_preserves_every_policy_word_ev_and_frozen_opponent() {
        let pool = rayon::ThreadPoolBuilder::new().num_threads(4).build().unwrap();
        pool.install(|| {
            for street in [BoardState::Turn, BoardState::Flop] {
                for compressed in [false, true] {
                    for hero in 0..2 {
                        let serial = game(street, compressed, false);
                        let parallel = game(street, compressed, true);
                        let counts = count_chances(&serial, &serial.root());
                        assert!(counts.0 > 0 && counts.1 > 0 && counts.2 > 0,
                            "must exercise real, isomorphic and parallel chance branches: {counts:?}");
                        // Identical solved baselines, then freeze the same opponent.
                        // Never run CFR after compiling that fixed policy.
                        for iteration in 0..3 {
                            solve_step(&serial, iteration);
                            solve_step(&parallel, iteration);
                        }
                        assert_eq!(policy_words(&serial, None), policy_words(&parallel, None),
                            "dense and sparse baselines differ before freezing");
                        freeze_opponent(&serial, &mut serial.root(), hero);
                        freeze_opponent(&parallel, &mut parallel.root(), hero);
                        let opponent = policy_words(&serial, Some(hero ^ 1));
                        assert_eq!(opponent, policy_words(&parallel, Some(hero ^ 1)));
                        let serial_ev = export_with_parallelism::<_, false>(&serial, hero);
                        let parallel_ev = export_best_response(&parallel, hero);
                        assert_eq!(serial_ev.to_bits(), parallel_ev.to_bits());
                        assert_eq!(policy_words(&serial, None), policy_words(&parallel, None));
                        assert_eq!(opponent, policy_words(&serial, Some(hero ^ 1)));
                        assert_eq!(opponent, policy_words(&parallel, Some(hero ^ 1)));
                        // Independent sum-product evaluation, no action maxima.
                        let serial_evaluation = compute_current_ev(&serial);
                        let parallel_evaluation = compute_current_ev(&parallel);
                        assert_eq!(serial_evaluation.map(f32::to_bits), parallel_evaluation.map(f32::to_bits));
                        assert!((parallel_ev - parallel_evaluation[hero]).abs() <= 0.0002,
                            "BR={parallel_ev}, reevaluated={}", parallel_evaluation[hero]);
                    }
                }
            }
        });
    }
}

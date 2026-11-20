mod policy;
mod response;
mod snapshot;
mod checkpoint;
mod memory;
use postflop_solver::*;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{io::{self, BufRead, Read, Write}, time::Instant};
use policy::Profile;

const REV: &str = "9d1509fe5077d019825f833eed04b16d342dfda1";
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Request {
    schema_version: u32,
    board: Vec<String>,
    players: Vec<String>, // OOP, IP range text; future schemas can add players.
    pot: i32,
    stack: i32,
    bets: Vec<String>, // flop, turn, river, same for both seats in this prototype.
    #[serde(default)] raises: Vec<String>,
    #[serde(default)] expand_suits: bool,
    #[serde(default)] compression: bool,
    #[serde(default)] auto_suits: bool,
    #[serde(default="default_threads")] threads: usize,
    #[serde(default)] time_limit_seconds: Option<u64>,
    #[serde(default)] bets_ip: Vec<String>,
    #[serde(default)] raises_ip: Vec<String>,
    #[serde(default)] donks: Vec<String>, // Turn/River; empty vector inherits default sizes.
    #[serde(default)] raise_limit: Option<usize>, // Raises allowed per street, all-ins included; None keeps every raise.
    #[serde(default)] lines: Vec<Vec<String>>, // Extra action lines for node-specific sizes, e.g. ["Check","Bet(690)"]; chance cards omitted.
    #[serde(default)] rake_rate: f64,
    #[serde(default)] rake_cap: f64,
    #[serde(default)] add_allin_threshold: f64,
    #[serde(default)] force_allin_threshold: f64,
    #[serde(default)] merging_threshold: f64,
    hero: usize,
    mode: String,
    target: f32,
    target_unit: String,
    max_iterations: u32,
    memory_budget_mb: u64,
    #[serde(default)] profile: Profile,
    #[serde(default)] runtime: Runtime,
}

// Node held fixed during CFR: the chosen action's probability per combo, the other action takes the rest.
#[derive(Clone,Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
struct SolveLock {path:Vec<usize>,action:usize,frequency:std::collections::HashMap<String,f32>}

#[derive(Clone,Default,Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
struct Runtime {
    // Explicit diagnostic only: cold fixed-iteration comparison, never a solved policy.
    #[serde(default)] benchmark_iterations:Option<u32>,
    #[serde(default)] benchmark_check_every:Option<u32>,
    #[serde(default)] estimate_only:bool,
    #[serde(default)] storage_estimate_only:bool,
    // Diagnostic dense reference; normal compressed, unlocked games use sparse storage.
    #[serde(default)] dense_storage:bool,
    #[serde(default)] solve_locks:Vec<SolveLock>,
    baseline_file:Option<String>,
    #[serde(default)] baseline_key:String,
    output_prefix:Option<String>,
    inspect_file:Option<String>,
    #[serde(default)] checkpoint_file:Option<String>,
    #[serde(default)] checkpoint_key:String,
    #[serde(default)] inspect_key:String,
    #[serde(default)] query_path:Vec<usize>,
}

fn default_threads()->usize {1}

fn progress(phase:&str,detail:Value){eprintln!("{}",json!({"phase":phase,"detail":detail}));}

#[derive(Default, Serialize)]
struct Coverage { #[serde(skip)] compiled:Vec<u64>, nodes: usize, combos: usize, trait_combos: usize, zero_reach_under_compiled_prefix: usize, streets: [usize;3], digest: u64, symmetry_reuses:usize, samples:Vec<Value> }

fn hash_values(hash: &mut u64, values:&[f32]) {
    for p in values { for b in p.to_bits().to_le_bytes() { *hash ^= b as u64; *hash=hash.wrapping_mul(1099511628211); } }
}

// Full legal tree traversal, including baseline-zero branches. Traits are suit-invariant;
// Manual asymmetric locks use an explicitly expanded public-card tree.
fn lock_tree(game:&mut PostFlopGame, req:&Request, events:&mut Vec<(usize,usize,Action)>, coverage:&mut Coverage, verify:bool) {
    if game.is_terminal_node() { return; }
    let path=game.history().to_vec();
    if game.is_chance_node() {
        let parent=game.checkpoint_interpreter();
        let mask=game.possible_cards();
        for c in 0..52 { if mask & (1u64<<c)!=0 {
            game.play(c); lock_tree(game,req,events,coverage,verify); game.restore_interpreter(&parent);
        } }
        return;
    }
    let player=game.current_player();
    let board=game.current_board();
    let actions=game.available_actions();
    let compact=req.compression && req.profile.overrides.is_empty();
    if player!=req.hero {
        coverage.nodes+=1; coverage.streets[board.len()-3]+=1;
        if verify {
            let locked=if compact {game.strategy()}else{game.current_locking_strategy().expect("missing full-tree opponent lock")};
            hash_values(&mut coverage.digest,&locked);
        } else if compact && coverage.compiled[game.current_node_id()/64] & (1u64<<(game.current_node_id()%64))!=0 {
            coverage.symmetry_reuses+=1;hash_values(&mut coverage.digest,&game.strategy());
        } else if let Some(locked)=game.current_locking_strategy() {
            // The engine can map several actual runouts to one canonical node.
            // Never apply soft traits twice to an already compiled canonical policy.
            coverage.symmetry_reuses+=1;
            hash_values(&mut coverage.digest,&locked);
        } else {
            let hands=game.private_cards(player).to_vec();
            let base=game.strategy();
            let weights=game.weights(player).to_vec();
            let mut out=base.clone();
            for (h,&hole) in hands.iter().enumerate() {
                let b:Vec<f32>=(0..actions.len()).map(|a|base[a*hands.len()+h]).collect();
                let (mut p,mut trace)=policy::compile(&b,&actions,hole,&board,events,&req.profile,player);
                for o in &req.profile.overrides {
                    if o.path==path {
                        let a=card_from_str(&o.combo[..2]).unwrap();let c=card_from_str(&o.combo[2..]).unwrap();
                        if (hole.0==a && hole.1==c)||(hole.0==c && hole.1==a) {p=o.probabilities.clone();trace=vec!["manual_override".into()];}
                    }
                }
                coverage.combos+=1;
                coverage.trait_combos+=usize::from(!trace.is_empty());
                coverage.zero_reach_under_compiled_prefix+=usize::from(weights[h]==0.0);
                if coverage.samples.len()<24 {
                    coverage.samples.push(json!({"board":board.iter().map(|&c|card_to_string(c).unwrap()).collect::<Vec<_>>(),
                        "history":events.iter().map(|(s,p,a)|json!({"street":s,"player":p,"action":format!("{a:?}")})).collect::<Vec<_>>(),
                        "combo":holes_to_strings(&[hole]).unwrap()[0],"before":b,"after":p,"rules":trace,
                        "source":if trace.is_empty(){"baseline-dcfr-unverified-at-zero-reach"}else{"research-assumption-traits-v1"},
                        "actions":actions.iter().map(|a|format!("{a:?}")).collect::<Vec<_>>()}));
                }
                for (a,&v) in p.iter().enumerate() { out[a*hands.len()+h]=v; }
            }
            if compact {
                if out!=base {game.replace_current_strategy(&out);}
                coverage.compiled[game.current_node_id()/64] |= 1u64<<(game.current_node_id()%64);
                hash_values(&mut coverage.digest,&game.strategy());
            } else {
                game.lock_current_strategy(&out);
                hash_values(&mut coverage.digest,&game.current_locking_strategy().unwrap());
            }
        }
    }
    let parent=game.checkpoint_interpreter();
    for (a,&action) in actions.iter().enumerate() {
        events.push((board.len(),player,action)); game.play(a);
        lock_tree(game,req,events,coverage,verify);
        events.pop(); game.restore_interpreter(&parent);
    }
}

// The engine has no raise cap, so lines past the limit leave the small public tree before expansion.
fn cap_raises(tree:&mut ActionTree,limit:usize,raises:usize)->Result<(),String> {
    if tree.is_terminal_node() {return Ok(());}
    let raises=if tree.is_chance_node() {0} else {raises};
    let actions=tree.available_actions().to_vec();
    let facing=actions.contains(&Action::Fold);
    for action in actions {
        let raise=facing && matches!(action,Action::Raise(_)|Action::AllIn(_));
        if raise && raises>=limit {
            let mut line=tree.history().to_vec();line.push(action);
            tree.remove_line(&line)?;
            continue;
        }
        tree.play(action)?;
        cap_raises(tree,limit,raises+usize::from(raise))?;
        tree.undo()?;
    }
    Ok(())
}

fn parse_action(text:&str)->Result<Action,String> {
    let amount=|prefix:&str|text.strip_prefix(prefix).and_then(|t|t.strip_suffix(')')).and_then(|t|t.parse::<i32>().ok());
    match text {
        "Fold"=>Ok(Action::Fold),"Check"=>Ok(Action::Check),"Call"=>Ok(Action::Call),
        _=>amount("Bet(").map(Action::Bet).or(amount("Raise(").map(Action::Raise)).or(amount("AllIn(").map(Action::AllIn)).ok_or(format!("invalid action {text}")),
    }
}

// Upstream compute_exploitability, also returning the best-response values.
// A biased seat gives up chips on purpose, so with incentives only the other seat's gap can reach zero.
fn baseline_gap(game:&PostFlopGame,req:&Request)->(f32,[f32;2]) {
    if req.profile.incentives.is_none() {return exploitability(game);}
    let best=compute_player_mes_ev(game,req.hero);
    let mut mes=[0.0;2];mes[req.hero]=best;
    ((best-compute_current_ev(game)[req.hero]).max(0.0),mes)
}

fn exploitability(game:&PostFlopGame)->(f32,[f32;2]) {
    let mes=compute_mes_ev(game);
    if !game.is_raked() {return ((mes[0]+mes[1])*0.5,mes);}
    let current=compute_current_ev(game);
    (((mes[0]-current[0])+(mes[1]-current[1]))*0.5,mes)
}

fn validate(r:&Request)->Result<(),String> {
    if let Some(n)=r.runtime.benchmark_iterations {
        if n==0 || n>100_000 || r.runtime.estimate_only || r.runtime.storage_estimate_only || r.runtime.baseline_file.is_some() || r.runtime.checkpoint_file.is_some() || r.runtime.output_prefix.is_some() || r.runtime.inspect_file.is_some() || !r.runtime.query_path.is_empty() {
            return Err("fixed-iteration diagnostic requires 1..100000 cold iterations and no cache, query or output paths".into());
        }
    }
    if r.schema_version!=1 || r.players.len()!=2 || r.hero>1 { return Err("schema v1 engine supports exactly two players".into()); }
    if !(3..=5).contains(&r.board.len()) || r.bets.len()!=3 || (!r.raises.is_empty() && r.raises.len()!=3) {return Err("board needs 3..5 cards; bets/raises need three streets".into());}
    if (!r.bets_ip.is_empty()&&r.bets_ip.len()!=3)||(!r.raises_ip.is_empty()&&r.raises_ip.len()!=3)||(!r.donks.is_empty()&&r.donks.len()!=2){return Err("IP sizes require three streets; donks require Turn/River".into());}
    if r.pot<=0 || r.stack<=0 || r.pot>1_000_000 || r.stack>1_000_000 {return Err("pot/stack must be integers in 1..1000000".into());}
    if !(0.0..=1.0).contains(&r.rake_rate) || !r.rake_cap.is_finite() || r.rake_cap<0.0 {return Err("rake needs a rate in 0..1 and a non-negative cap".into());}
    if !r.target.is_finite() || r.target<=0.0 || r.max_iterations==0 || r.max_iterations>100_000 {return Err("invalid target/iteration limit".into());}
    if !["chips","pot_pct"].contains(&r.target_unit.as_str()) || !["equilibrium","fixed","preview","locked"].contains(&r.mode.as_str()) {return Err("unsupported mode or target unit".into());}
    if r.memory_budget_mb==0 || r.memory_budget_mb>24576 {return Err("memory budget must be 1..24576 MiB".into());}
    // Legacy metadata only: wall-clock deadlines are not applied to normal solves.
    if r.mode=="equilibrium" && (!r.profile.traits.is_empty() || r.profile.fixture_river_bet.is_some() || !r.profile.overrides.is_empty()) {return Err("equilibrium mode cannot apply opponent traits".into());}
    if r.board.len()!=5 && !r.profile.overrides.is_empty() && !r.expand_suits {return Err("Flop/Turn manual locks require expand_suits=true to keep asymmetric public-card branches separate".into());}
    policy::validate(&r.profile)
}

fn estimate_public_nodes(tree:&mut ActionTree,street:usize,factor:u64,hands:u64)->(usize,u64) {
    if tree.is_terminal_node() {return (1,128*factor);}
    let (street,factor)=if tree.is_chance_node(){(street+1,factor*(52-street) as u64)}else{(street,factor)};
    let actions=tree.available_actions().to_vec();
    let mut n=1;
    let mut bytes=(256+actions.len() as u64*hands*24)*factor;
    for action in actions {tree.play(action).unwrap();let (count,size)=estimate_public_nodes(tree,street,factor,hands);n+=count;bytes+=size;tree.undo().unwrap();}
    (n,bytes)
}

// Traverse only the small public tree. Never allocate the expanded solver game.
fn diagnose_public_tree(tree:&mut ActionTree,street:usize,factor:u64,hands:u64,raises:usize,rows:&mut [Value;3]) {
    let terminal=tree.is_terminal_node();
    let chance=!terminal && tree.is_chance_node();
    let (street,factor,raises)=if chance {(street+1,factor*(52-street) as u64,0)} else {(street,factor,raises)};
    let actions=if terminal {vec![]}else{tree.available_actions().to_vec()};
    let bytes=if terminal {128*factor}else{(256+actions.len() as u64*hands*24)*factor};
    let row=&mut rows[street-3];
    for (key,amount) in [("public_nodes",1),("expanded_node_upper_bound",factor),("preflight_bytes",bytes)] {
        row[key]=json!(row[key].as_u64().unwrap_or(0)+amount);
    }
    row["max_raises_per_line"]=json!(row["max_raises_per_line"].as_u64().unwrap_or(0).max(raises as u64));
    for action in actions {
        let next=raises+usize::from(matches!(action,Action::Raise(_)));
        tree.play(action).unwrap();diagnose_public_tree(tree,street,factor,hands,next,rows);tree.undo().unwrap();
    }
}

fn report_node(game:&mut PostFlopGame)->Value {
    game.cache_normalized_weights();
    let terminal=game.is_terminal_node(); let chance=game.is_chance_node();
    let bets=game.total_bet_amount();
    if terminal || chance {
        return json!({"path":game.history(),"board":game.current_board().iter().map(|&c|card_to_string(c).unwrap()).collect::<Vec<_>>(),"terminal":terminal,"chance":chance,
            "contributions":bets,"pot":game.tree_config().starting_pot+bets[0]+bets[1],
            "terminal_root_net_ev":if terminal {Some((0..2).map(|p|game.expected_values(p).iter().zip(game.normalized_weights(p)).map(|(v,w)|if *w>0.0 {Some(v-bets[p] as f32)}else{None}).collect::<Vec<_>>()).collect::<Vec<_>>())}else{None},
            "possible_cards":if chance {(0..52).filter(|c|game.possible_cards() & (1u64<<c)!=0).map(|c|json!({"id":c,"card":card_to_string(c as u8).unwrap()})).collect::<Vec<_>>()}else{vec![]}});
    }
    let actor=game.current_player();
    let parent=game.checkpoint_interpreter();
    let pot=game.tree_config().starting_pot+bets[0]+bets[1];
    let call_amount=(bets[actor^1]-bets[actor]).max(0);
    let actions=game.available_actions();
    let mut action_details=Vec::new();
    for (index,action) in actions.iter().enumerate() {
        game.play(index);
        let additional=(game.total_bet_amount()[actor]-bets[actor]).max(0);
        let aggressive=matches!(action,Action::Bet(_)|Action::Raise(_)|Action::AllIn(_));
        let aggression=if aggressive {(additional-call_amount).max(0)} else {0};
        let fraction=if aggressive {Some(aggression as f64/(pot+call_amount) as f64)}else{None};
        action_details.push(json!({"additional_contribution":additional,"call_amount":call_amount,
            "aggression_amount":aggression,"pot_after_call":pot+call_amount,"pot_fraction":fraction,
            "is_overbet":aggressive && aggression>pot+call_amount}));
        game.restore_interpreter(&parent);
    }
    json!({"actor":actor,"path":game.history(),"board":game.current_board().iter().map(|&c|card_to_string(c).unwrap()).collect::<Vec<_>>(),"terminal":false,"chance":false,
        "contributions":bets,"pot":game.tree_config().starting_pot+bets[0]+bets[1],"remaining_stacks":bets.map(|v|game.tree_config().effective_stack-v),
        "ev_basis":"conditional node EV in chips; previous contributions sunk; zero posterior weight means undefined EV (display null)",
        "actions":game.available_actions().iter().map(|a|format!("{a:?}")).collect::<Vec<_>>(),
        "action_details":action_details,
        "strategy_action_major":game.strategy(),"action_ev_action_major":game.expected_values_detail(actor),
        "players":(0..2).map(|p|json!({"combos":holes_to_strings(game.private_cards(p)).unwrap(),
            "equity":game.equity(p),"ev":game.expected_values(p),"raw_reach":game.weights(p),
            "blocker_adjusted_weights":game.normalized_weights(p)})).collect::<Vec<_>>()})
}

fn query_node(game:&mut PostFlopGame,path:&[usize])->Result<Value,String> {
    game.back_to_root();
    for &action in path {
        if game.is_terminal_node(){return Err("query continues past terminal".into());}
        if game.is_chance_node(){if action>=52 || game.possible_cards() & (1u64<<action)==0{return Err("illegal chance card".into());}}
        else if action>=game.available_actions().len(){return Err("illegal action index".into());}
        game.play(action);
    }
    Ok(report_node(game))
}

// Hold the loaded policy: one JSON path per stdin line, one report per stdout line, until stdin closes.
fn serve(game:&mut PostFlopGame)->Result<(),String> {
    let mut out=io::stdout();
    writeln!(out,"{}",json!({"ready":true})).and_then(|_|out.flush()).map_err(|e|e.to_string())?;
    for line in io::stdin().lock().lines() {
        let line=line.map_err(|e|e.to_string())?;
        let reply=match serde_json::from_str::<Vec<usize>>(&line).map_err(|e|e.to_string()).and_then(|path|query_node(game,&path)) {
            Ok(node)=>json!({"node":node}),Err(error)=>json!({"error":error})};
        writeln!(out,"{reply}").and_then(|_|out.flush()).map_err(|e|e.to_string())?;
    }
    Ok(())
}

fn run(req:Request)->Result<Value,String> {
    validate(&req)?;
    if !(1..=64).contains(&req.threads) {return Err("threads must be 1..64".into());}
    rayon::ThreadPoolBuilder::new().num_threads(req.threads).stack_size(memory::THREAD_STACK_BYTES).build_global().map_err(|e|e.to_string())?;
    let started=Instant::now();
    progress("building",json!({}));
    let cards:Vec<u8>=req.board.iter().map(|s|card_from_str(s)).collect::<Result<_,_>>()?;
    let mut unique=cards.clone(); unique.sort(); unique.dedup();
    if unique.len()!=cards.len() {return Err("duplicate board cards".into());}
    let card_config=CardConfig { range:[req.players[0].parse()?,req.players[1].parse()?], flop:[cards[0],cards[1],cards[2]],turn:*cards.get(3).unwrap_or(&NOT_DEALT),river:*cards.get(4).unwrap_or(&NOT_DEALT) };
    let mut sizes=Vec::new();
    for i in 0..3 { sizes.push(BetSizeOptions::try_from((req.bets[i].as_str(),req.raises.get(i).map(String::as_str).unwrap_or("")))?); }
    let mut ip_sizes=Vec::new();
    for i in 0..3 {ip_sizes.push(BetSizeOptions::try_from((req.bets_ip.get(i).unwrap_or(&req.bets[i]).as_str(),req.raises_ip.get(i).or(req.raises.get(i)).map(String::as_str).unwrap_or("")))?);}
    let config=TreeConfig {initial_state:match cards.len(){3=>BoardState::Flop,4=>BoardState::Turn,_=>BoardState::River},starting_pot:req.pot,effective_stack:req.stack,
        rake_rate:req.rake_rate,rake_cap:req.rake_cap,flop_bet_sizes:[sizes[0].clone(),ip_sizes[0].clone()],turn_bet_sizes:[sizes[1].clone(),ip_sizes[1].clone()],river_bet_sizes:[sizes[2].clone(),ip_sizes[2].clone()],
        turn_donk_sizes:req.donks.get(0).map(|s|DonkSizeOptions::try_from(s.as_str())).transpose()?,
        river_donk_sizes:req.donks.get(1).map(|s|DonkSizeOptions::try_from(s.as_str())).transpose()?,
        add_allin_threshold:req.add_allin_threshold,force_allin_threshold:req.force_allin_threshold,merging_threshold:req.merging_threshold};
    // Size the small public action tree before expanding private cards and chance nodes.
    // Phase-0 guard intentionally caps size rather than silently pruning requested actions.
    if req.players.iter().any(|s|s.len()>32768) || req.bets.iter().chain(&req.raises).chain(&req.bets_ip).chain(&req.raises_ip).chain(&req.donks).any(|s|s.split(',').count()>3) {return Err("prototype tree/range text limit exceeded; reduce sizes explicitly".into());}
    // Prevent pathological tiny repeated raises before asking the upstream builder to expand.
    let spr_limit=if req.raise_limit.is_some() {40} else {20};
    if req.stack>req.pot*spr_limit {return Err(format!("stack/pot must be <= {spr_limit} (a raise limit allows 40); no tree truncation performed"));}
    for r in req.raises.iter().chain(&req.raises_ip) { for token in r.split(',').map(str::trim).filter(|t|!t.is_empty()) {
        if token!="a" && !token.ends_with('x') && !token.ends_with('%') {return Err("raise sizes require a multiplier (>=2x), a pot percentage or a; amounts are reported as Raise-to".into());}
        if let Some(n)=token.strip_suffix('x') {if n.parse::<f64>().map_err(|_|"invalid raise multiplier")?<2.0{return Err("raise multiplier must be >=2x".into());}}
    }}
    let dead=cards.iter().fold(0u64,|m,c|m | (1u64<<c));
    let hands=card_config.range.iter().map(|r|r.get_hands_weights(dead).0.len()).max().unwrap();
    let mut tree=ActionTree::new(config)?;
    for line in &req.lines {tree.add_line(&line.iter().map(|a|parse_action(a)).collect::<Result<Vec<_>,_>>()?)?;}
    if let Some(limit)=req.raise_limit {cap_raises(&mut tree,limit,0)?;tree.back_to_root();}
    let (public_nodes,estimated_tree_bytes)=estimate_public_nodes(&mut tree,cards.len(),1,hands as u64);
    // Deliberately loose upper bound; includes locks, scratch buffers and reports.
    let preflight=64*1024*1024+estimated_tree_bytes;
    if req.runtime.estimate_only || std::env::args().any(|s|s=="--estimate") {
        let mut rows=[json!({"street":"Flop"}),json!({"street":"Turn"}),json!({"street":"River"})];
        diagnose_public_tree(&mut tree,cards.len(),1,hands as u64,0,&mut rows);
        return Ok(json!({"estimate_only":true,"solver_game_allocated":false,"public_nodes":public_nodes,
            "effective_combos":card_config.range.iter().map(|r|r.get_hands_weights(dead).0.len()).collect::<Vec<_>>(),
            "spr":req.stack as f64/req.pot as f64,"streets":rows,"fixed_overhead_bytes":64*1024*1024,
            "preflight_upper_bound_bytes":preflight,"budget_bytes":req.memory_budget_mb*1024*1024,
            "fits_conservative_preflight":preflight<=req.memory_budget_mb*1024*1024,
            "estimate_seconds":started.elapsed().as_secs_f64(),"measured_native_peak_rss_bytes":peak_rss(),
            "limitations":"Conservative upper bound, not measured solver memory. Assumes all public runouts, max seat hand count and 24 bytes per action-hand; ignores suit-isomorphism savings. Raise count excludes all-in actions."}));
    }
    let expanded=req.expand_suits && !(req.auto_suits && req.profile.overrides.is_empty());
    let mut game=PostFlopGame::prepare_config(card_config,tree,expanded)?;
    let sparse_storage=req.compression && req.profile.overrides.is_empty() && !req.runtime.dense_storage && req.runtime.solve_locks.is_empty();
    game.set_sparse_storage(sparse_storage)?;
    let plan=game.memory_plan(req.hero^1);
    let elements=2*plan[1]+plan[2]+plan[3];
    let planned_engine=plan[0]+plan[4]+elements*if req.compression {2}else{4};
    let arena_node_count=plan[0]/std::mem::size_of::<postflop_solver::MutexLike<PostFlopNode>>() as u64;
    let visited_bytes=((arena_node_count+63)/64)*8;
    let locked=req.mode=="locked";
    let equilibrium=req.mode=="equilibrium"||locked;
    if equilibrium && req.profile.incentives.is_some() {return Err("incentives need a fixed or preview model".into());}
    let lock_nodes=req.profile.overrides.iter().map(|o|&o.path).collect::<std::collections::HashSet<_>>().len() as u64;
    let locks=if locked {lock_nodes*64*1024}else if !equilibrium && req.runtime.inspect_file.is_none() {if req.compression && req.profile.overrides.is_empty() {visited_bytes}else{plan[5]*4+plan[6]*128}}else{0};
    // Explicit native allocations plus separately accounted allocator, stack,
    // page rounding and scratch costs. Unknown allocator environments retain
    // the legacy conservative model; the supervisor's AS cap is unchanged.
    let headroom=memory::memory_headroom(planned_engine,plan[4],locks,req.threads);
    let estimated_peak=planned_engine.saturating_add(locks).saturating_add(headroom.total_overhead_bytes);
    let memory_plan=json!({"arena_bytes":plan[0],"action_elements":plan[1],"ip_elements":plan[2],"chance_elements":plan[3],
        "card_misc_bytes":plan[4],"strategy_storage_bytes":elements*if req.compression {2}else{4},"lock_budget_bytes":locks,
        "planned_engine_bytes":planned_engine,"estimated_peak_bytes":estimated_peak,"compression":req.compression,"expanded_suits":expanded,
        "allocator_headroom_bytes":headroom.allocator_bytes,"thread_stack_bytes":headroom.thread_bytes,
        "allocation_padding_bytes":headroom.padding_bytes,"transient_headroom_bytes":headroom.transient_bytes,
        "allocator_profile":headroom.profile,"visited_bitset_bytes":visited_bytes,
        "budget_bytes":req.memory_budget_mb*1024*1024,"sparse_storage":sparse_storage});
    progress("memory_plan",memory_plan.clone());
    if req.runtime.storage_estimate_only {return Ok(json!({"estimate_only":true,"solver_game_allocated":false,"memory_plan":memory_plan,"measured_native_peak_rss_bytes":peak_rss()}));}
    if estimated_peak>req.memory_budget_mb*1024*1024 {return Err(format!("内存预检：预计峰值 {:.2} GiB，任务预算 {:.2} GiB；尚未分配完整树。引擎 {:.2} GiB，对手锁预算 {:.2} GiB；延长时间不会增加内存预算。",estimated_peak as f64/1073741824.0,req.memory_budget_mb as f64/1024.0,planned_engine as f64/1073741824.0,locks as f64/1073741824.0));}
    game.build_prepared()?;
    let memory=if req.compression {game.memory_usage().1}else{game.memory_usage().0};
    if memory!=planned_engine {return Err(format!("storage plan mismatch: predicted {planned_engine}, built {memory}"));}
    game.allocate_memory(req.compression);
    let tree_stats=snapshot::stats(&game,&*game.root(),req.compression);
    let mut manual_keys=std::collections::HashSet::new();
    for o in &req.profile.overrides {
        if let Some(scene)=&o.scene {
            let mut current=json!({"board":req.board,"players":req.players,"pot":req.pot,"stack":req.stack,"bets":req.bets,"raises":req.raises,"hero":req.hero});
            for (key,values) in [("bets_ip",&req.bets_ip),("raises_ip",&req.raises_ip),("donks",&req.donks)]{
                if !values.is_empty()||scene.get(key).is_some(){current[key]=json!(values);}
            }
            if *scene!=current{return Err("manual lock belongs to a different scene/tree; restore that scene or explicitly remove the stale locks".into());}
        }
        game.back_to_root();
        for &a in &o.path {
            if game.is_terminal_node(){return Err("invalid manual override path".into());}
            if game.is_chance_node(){if a>=52 || game.possible_cards() & (1u64<<a)==0 {return Err("invalid manual override chance card".into());}}
            else if a>=game.available_actions().len(){return Err("invalid manual override action".into());}
            game.play(a);
        }
        if game.is_terminal_node() || game.is_chance_node() || (!locked && game.current_player()==req.hero) || o.probabilities.len()!=game.available_actions().len(){return Err("manual override must target an opponent decision and every legal action".into());}
        if let Some(actions)=&o.actions {if *actions!=game.available_actions().iter().map(|a|format!("{a:?}")).collect::<Vec<_>>(){return Err("manual lock action labels no longer match tree".into());}}
        if let Some(board)=&o.board {if *board!=game.current_board().iter().map(|&c|card_to_string(c).unwrap()).collect::<Vec<_>>(){return Err("manual lock board no longer matches node".into());}}
        let a=card_from_str(&o.combo[..2])?;let b=card_from_str(&o.combo[2..])?;
        if game.current_board().contains(&a)||game.current_board().contains(&b){return Err("manual combo conflicts with node board".into());}
        if !game.private_cards(game.current_player()).iter().any(|&(x,y)|(x==a&&y==b)||(x==b&&y==a)){return Err("manual combo not in that seat's range".into());}
        if !manual_keys.insert((o.path.clone(),a.min(b),a.max(b))){return Err("conflicting duplicate manual override".into());}
    }
    // Only the listed combos stay fixed; every other hand and node is solved for both seats.
    if locked && req.runtime.inspect_file.is_none() {
        let mut nodes:std::collections::BTreeMap<&Vec<usize>,Vec<&policy::Override>>=Default::default();
        for o in &req.profile.overrides {nodes.entry(&o.path).or_default().push(o);}
        for (path,list) in nodes {
            game.back_to_root();
            for &a in path {game.play(a);}
            let cards=game.private_cards(game.current_player()).to_vec();
            let (actions,hands)=(game.available_actions().len(),cards.len());
            let mut strategy=vec![0.0f32;actions*hands];
            for o in list {
                let a=card_from_str(&o.combo[..2])?;let b=card_from_str(&o.combo[2..])?;
                let h=cards.iter().position(|&(x,y)|(x==a&&y==b)||(x==b&&y==a)).ok_or("manual combo not in that seat's range")?;
                for (i,&p) in o.probabilities.iter().enumerate() {strategy[i*hands+h]=p;}
            }
            game.lock_current_strategy(&strategy);
        }
    }
    for lock in &req.runtime.solve_locks {
        game.back_to_root();
        for &a in &lock.path {game.play(a);}
        let player=game.current_player();
        let names=holes_to_strings(game.private_cards(player))?;
        let (actions,hands)=(game.available_actions().len(),names.len());
        if actions!=2 || lock.action>1 {return Err("solve locks need a two-action node".into());}
        let mut strategy=vec![0.0f32;actions*hands];
        for (h,name) in names.iter().enumerate() {
            let p=lock.frequency.get(name).copied().unwrap_or(0.0).clamp(0.0,1.0);
            strategy[lock.action*hands+h]=p;strategy[(1-lock.action)*hands+h]=1.0-p;
        }
        game.lock_current_strategy(&strategy);
    }
    game.back_to_root();
    if let Some(i)=&req.profile.incentives {
        let on=|street:usize|i.streets.as_ref().map_or(true,|s|s.contains(&street));
        game.set_incentive(Some(Incentive {player:req.hero^1,check:i.check/100.0,bet:i.bet/100.0,fold:i.fold/100.0,call:i.call/100.0,streets:[on(3),on(4),on(5)]}));
    }
    let build_seconds=started.elapsed().as_secs_f64();
    if let Some(path)=&req.runtime.inspect_file {
        snapshot::load(&game,path,&req.runtime.inspect_key)?;
        finalize(&mut game);
        if std::env::args().any(|s|s=="--serve") {serve(&mut game)?;return Ok(json!({"schema_version":1,"served":true}));}
        return Ok(json!({"schema_version":1,"node":query_node(&mut game,&req.runtime.query_path)?}));
    }
    let target=if req.target_unit=="pot_pct" {req.target*req.pot as f32/100.0} else {req.target};
    let numerical_floor=req.pot as f32*1e-6;
    let working_target=target.max(numerical_floor);
    if let Some(count)=req.runtime.benchmark_iterations {
        let baseline_start=Instant::now();
        let measure=Instant::now();
        let mut actual=exploitability(&game).0;
        let mut measurement_seconds=measure.elapsed().as_secs_f64();
        let mut iteration_seconds=0.0;
        progress("baseline",json!({"iteration":0,"actual_chips":actual,"target_chips":target,"diagnostic":true,"elapsed_seconds":baseline_start.elapsed().as_secs_f64()}));
        for t in 0..count {
            let iteration_start=Instant::now();
            solve_step(&game,t);
            iteration_seconds+=iteration_start.elapsed().as_secs_f64();
            if (t+1)%req.runtime.benchmark_check_every.unwrap_or(10).max(1)==0 || t+1==count {
                let measure=Instant::now();
                actual=exploitability(&game).0;
                measurement_seconds+=measure.elapsed().as_secs_f64();
                progress("baseline",json!({"iteration":t+1,"actual_chips":actual,"target_chips":target,"elapsed_seconds":baseline_start.elapsed().as_secs_f64(),"iteration_seconds":iteration_seconds,"measurement_seconds":measurement_seconds,"diagnostic":true}));
            }
        }
        return Ok(json!({"schema_version":1,"benchmark":true,"config":req,"engine_revision":REV,
            "tree":{"suit_isomorphism":!expanded,"public_nodes":public_nodes,"expanded_canonical_nodes":tree_stats[0],"terminal_nodes":tree_stats[1],"chance_nodes":tree_stats[2],"policy_floats":tree_stats[3],"effective_combos":[game.private_cards(0).len(),game.private_cards(1).len()]},
            "precision":{"metric":"equilibrium_exploitability","actual_chips":actual,"actual_pot_pct":actual*100.0/req.pot as f32,"target_chips":target,"baseline_iterations":count,"stop_reason":"fixed_iteration_diagnostic","target_met":actual<=target},
            "timing":{"build_seconds":build_seconds,"baseline_seconds":baseline_start.elapsed().as_secs_f64(),"iteration_seconds":iteration_seconds,"measurement_seconds":measurement_seconds,"total_seconds":started.elapsed().as_secs_f64()},
            "memory":{"plan":memory_plan,"engine_bytes":memory,"estimated_peak_bytes":estimated_peak,"measured_native_peak_rss_bytes":peak_rss(),"measured_native_peak_vms_bytes":process_memory("VmPeak:")},
            "limitations":["diagnostic: fixed iterations, not a target-precision solve", "no final policy, model, best response or snapshot generated"]}));
    }
    let baseline_start=Instant::now();
    let mut iterations=0;
    let mut cache_hit=false;
    let mut resumed_iterations=0;
    if let Some(path)=&req.runtime.baseline_file {if std::path::Path::new(path).exists() {
        let meta=snapshot::load(&game,path,&req.runtime.baseline_key)?;
        iterations=meta["iterations"].as_u64().ok_or("invalid baseline iterations")? as u32;
        cache_hit=true;
    }}
    if !cache_hit {if let Some(path)=&req.runtime.checkpoint_file {if std::path::Path::new(path).exists() {
        let meta=checkpoint::load(&game,path,&req.runtime.checkpoint_key)?;
        iterations=meta["iterations"].as_u64().ok_or("invalid CFR iterations")? as u32;
        if iterations>req.max_iterations {return Err("CFR checkpoint exceeds requested iteration ceiling".into());}
        resumed_iterations=iterations;
    }}}
    // Evaluate only the actual loaded state; a throwaway all-zero policy traversal
    // before reading a multi-gigabyte snapshot/checkpoint provides no information.
    let (mut actual,mut baseline_mes)=baseline_gap(&game,&req);
    if resumed_iterations>0 {progress("resuming",json!({"iterations":iterations,"actual_chips":actual}));}
    progress("baseline",json!({"cache_hit":cache_hit,"actual_chips":actual,"resumed_iterations":resumed_iterations}));
    // One exploitability pass costs several iterations, so the gap between checks grows with the run.
    let mut next_check=iterations+10;
    // The other seat can look converged against an early strategy of the biased seat.
    let floor=if req.profile.incentives.is_some() {100}else{0};
    while !cache_hit && iterations<req.max_iterations && (actual>working_target || iterations<floor) {
        solve_step(&game,iterations); iterations+=1;
        if iterations>=next_check || iterations==req.max_iterations {next_check=iterations+(iterations/5).max(10);(actual,baseline_mes)=baseline_gap(&game,&req);progress("baseline",json!({"iteration":iterations,"actual_chips":actual,"target_chips":target,"elapsed_seconds":baseline_start.elapsed().as_secs_f64()}));}
    }
    let baseline_seconds=baseline_start.elapsed().as_secs_f64();
    let baseline_ev=compute_current_ev(&game).map(|x|x+req.pot as f32/2.0);
    let baseline_strategy=game.strategy();
    let baseline_actual=actual;
    let save_start=Instant::now();
    // Raw CFR buffers, before templates/finalize. Final policies cannot resume.
    if !cache_hit && actual>working_target {if let Some(path)=&req.runtime.checkpoint_file {
        progress("saving_checkpoint",json!({"iterations":iterations}));
        checkpoint::save(&game,path,&json!({"key":req.runtime.checkpoint_key,"iterations":iterations}))?;
    }}
    if !cache_hit {if let Some(path)=&req.runtime.baseline_file {snapshot::save(&game,path,&json!({"key":req.runtime.baseline_key,"iterations":iterations,"actual_chips":actual}))?;}}
    let baseline_save_seconds=save_start.elapsed().as_secs_f64();
    let mut coverage=Coverage::default();
    let mut same_model_baseline=baseline_ev[req.hero];
    let compile_start=Instant::now();
    if !equilibrium {
        progress("compiling_model",json!({}));
        if req.compression && req.profile.overrides.is_empty() {coverage.compiled=vec![0;(visited_bytes/8) as usize];}
        lock_tree(&mut game,&req,&mut Vec::new(),&mut coverage,false);
        coverage.compiled.clear();coverage.compiled.shrink_to_fit();
        game.back_to_root();
        same_model_baseline=compute_current_ev(&game)[req.hero]+req.pot as f32/2.0;
    }
    let compile_seconds=compile_start.elapsed().as_secs_f64();
    let save_start=Instant::now();
    let baseline_alias=equilibrium && req.runtime.baseline_file.is_some();
    if !baseline_alias {if let Some(prefix)=&req.runtime.output_prefix {snapshot::save(&game,&format!("{prefix}.model.policy"),&json!({"key":req.runtime.inspect_key}))?;}}
    let model_save_seconds=save_start.elapsed().as_secs_f64();
    let response_start=Instant::now();
    let response_iterations=0;
    let mut exported_br=None;
    if req.mode=="fixed" {
        progress("best_response",json!({}));
        exported_br=Some(response::export_best_response(&game,req.hero)+req.pot as f32/2.0);
    }
    let response_seconds=response_start.elapsed().as_secs_f64();
    progress("evaluating_policy",json!({}));
    let evaluation_start=Instant::now();
    let current=if equilibrium {baseline_ev}else{compute_current_ev(&game).map(|x|x+req.pot as f32/2.0)};
    let best=if equilibrium {baseline_mes[req.hero]}else{compute_player_mes_ev(&game,req.hero)}+req.pot as f32/2.0;
    if req.mode=="fixed" {actual=best-current[req.hero];}
    let evaluation_error=exported_br.map(|v|(v-current[req.hero]).abs()).unwrap_or(0.0);
    let evaluation_tolerance=req.pot as f32*2e-5;
    if evaluation_error>evaluation_tolerance{return Err(format!("exported policy evaluation mismatch: {evaluation_error}"));}
    let mut verified=Coverage::default();
    if !equilibrium {
        lock_tree(&mut game,&req,&mut Vec::new(),&mut verified,true);
        if coverage.digest!=verified.digest {return Err("opponent lock changed while solving".into());}
    }
    let evaluation_seconds=evaluation_start.elapsed().as_secs_f64();
    let save_start=Instant::now();
    if !baseline_alias {if let Some(prefix)=&req.runtime.output_prefix {snapshot::save(&game,&format!("{prefix}.response.policy"),&json!({"key":req.runtime.inspect_key}))?;}}
    let solution_save_seconds=save_start.elapsed().as_secs_f64();
    progress("reporting",json!({}));
    let report_start=Instant::now();
    game.back_to_root(); finalize(&mut game);
    let root=report_node(&mut game);
    Ok(json!({"schema_version":1,"engine_revision":REV,"adapter_version":"br-policy-v4-memory","compiler_version":"traits-logit-v2", "config":req,
        "tree":{"suit_isomorphism":!expanded,"manual_lock_count":req.profile.overrides.len(),"public_nodes":public_nodes,"expanded_canonical_nodes":tree_stats[0],"terminal_nodes":tree_stats[1],"chance_nodes":tree_stats[2],"policy_floats":tree_stats[3],"effective_combos":[game.private_cards(0).len(),game.private_cards(1).len()],"raises":req.raises,"sizing_limits":"max 3 sizes per street; raise >=2x or all-in; SPR <=20; no rake"},
        "cache":{"baseline_hit":cache_hit,"resumed_iterations":resumed_iterations},"policy_validation":{"exported_br_ev":exported_br,"reevaluated_ev":current[req.hero],"absolute_error":evaluation_error,"tolerance_chips":evaluation_tolerance,"method":"separate upstream sum-product traversal of exported full-tree policy; no maximization"},
        "ev_convention":"root chips: pot share plus opponent future contributions minus own future contributions; no future rake",
        "precision":{"metric":if req.mode=="fixed" {"hero_response_gap"} else if req.mode=="preview" {"not_optimized"}else {"exploitability"},"target_chips":target,"actual_chips":actual,"actual_pot_pct":actual*100.0/req.pot as f32,"numerical_floor_chips":numerical_floor,"stop_reason":if req.mode=="preview" {"model_preview"}else if target<numerical_floor && actual<=working_target {"numerical_floor"} else if actual<=target {"target_met"} else {"iteration_limit"},"baseline_stop_reason":if target<numerical_floor && baseline_actual<=working_target {"numerical_floor"}else if baseline_actual<=target {"target_met"}else{"iteration_limit"},"baseline_iterations":iterations,"response_iterations":response_iterations,"baseline_exploitability_chips":baseline_actual,"baseline_metric":if req.profile.incentives.is_some() {"other_seat_response_gap"}else{"exploitability"}},
        "ev":current,"hero_best_response_ev":best,"same_model_baseline_hero_ev":same_model_baseline,"hero_improvement":current[req.hero]-same_model_baseline,
        "baseline_root_strategy":baseline_strategy,"coverage":coverage,"opponent_unchanged":req.mode=="fixed" && coverage.digest==verified.digest,
        "timing":{"build_seconds":build_seconds,"baseline_seconds":baseline_seconds,"compile_seconds":compile_seconds,"response_seconds":response_seconds,"evaluation_seconds":evaluation_seconds,"report_seconds":report_start.elapsed().as_secs_f64(),"save_seconds":baseline_save_seconds+model_save_seconds+solution_save_seconds,"total_seconds":started.elapsed().as_secs_f64()},
        "memory":{"plan":memory_plan,"engine_bytes":memory,"estimated_peak_bytes":estimated_peak,"preflight_upper_bound_bytes":preflight,"measured_native_peak_rss_bytes":peak_rss(),"measured_native_peak_vms_bytes":process_memory("VmPeak:")},"root":root,
        "limitations":["two players, OOP acts first, equal effective stacks", "suit-invariant traits; manual override restrictions disclosed", "final policies, not resumable CFR state", "coarse made-hand traits; research assumptions"]}))
}

fn peak_rss()->Option<u64> {
    process_memory("VmHWM:")
}
fn process_memory(counter:&str)->Option<u64> {
    std::fs::read_to_string("/proc/self/status").ok()?.lines().find(|l|l.starts_with(counter))?
        .split_whitespace().nth(1)?.parse::<u64>().ok().map(|kb|kb*1024)
}

fn main() {
    let mut input=String::new();
    // A session keeps stdin open for its queries, so its request is the first line.
    let read=if std::env::args().any(|s|s=="--serve") {io::stdin().read_line(&mut input).map(|_|())} else {io::stdin().read_to_string(&mut input).map(|_|())};
    let result=read.map_err(|e|e.to_string())
        .and_then(|_|serde_json::from_str::<Request>(&input).map_err(|e|e.to_string())).and_then(run);
    match result {Ok(report)=>println!("{}",report),Err(error)=>{eprintln!("{}",json!({"error":error}));std::process::exit(1);}}
}

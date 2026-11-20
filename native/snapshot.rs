//! Full-tree FINAL policy snapshots, not resumable CFR state. Canonical DFS order.
use postflop_solver::*;
use serde_json::Value;
use std::{fs::{self,File},io::{Read,Write,BufReader,BufWriter},path::Path};
use crate::response::{probabilities,set_probabilities};

// One I/O scratch buffer for the entire DFS. Sparse views expand only the
// current node's logical cells; no complete policy copy is created.
const IO_CHUNK:usize=16*1024;

pub fn stats<G:Game>(game:&G,node:&G::Node,compressed:bool)->[u64;4] {
    let mut s=[1,u64::from(node.is_terminal()),u64::from(node.is_chance()),0];
    if node.is_terminal(){return s;}
    // Report logical action/combination cells, independent of physical packing.
    if !node.is_chance(){s[3]=(node.num_actions()*game.num_private_hands(node.player())) as u64;}
    for a in 0..node.num_actions(){let child=stats(game,&*node.play(a),compressed);for i in 0..4{s[i]+=child[i];}}
    s
}

pub fn save(game:&PostFlopGame,path:&str,metadata:&Value)->Result<(),String> {
    let target=Path::new(path); if let Some(parent)=target.parent(){fs::create_dir_all(parent).map_err(|e|e.to_string())?;}
    let tmp=format!("{path}.tmp");
    let mut file=BufWriter::with_capacity(1024*1024,File::create(&tmp).map_err(|e|e.to_string())?);
    let header=serde_json::to_vec(metadata).unwrap();
    file.write_all(b"PLPOL003").map_err(|e|e.to_string())?;
    file.write_all(&(header.len() as u64).to_le_bytes()).map_err(|e|e.to_string())?;
    file.write_all(&header).map_err(|e|e.to_string())?;
    write_node(game,&game.root(),&mut file,&mut [0;IO_CHUNK]).map_err(|e|e.to_string())?;
    file.flush().map_err(|e|e.to_string())?; file.get_ref().sync_all().map_err(|e|e.to_string())?;
    fs::rename(tmp,target).map_err(|e|e.to_string())
}
fn write_node<G:Game,W:Write>(game:&G,node:&G::Node,w:&mut W,scratch:&mut [u8;IO_CHUNK])->std::io::Result<()> {
    if node.is_terminal(){return Ok(());}
    if !node.is_chance() && node.num_actions()>1 {
        if game.is_compression_enabled() && game.locking_strategy(node).is_empty() {
            // Preserve raw integers, avoiding a normalize/requantize round trip.
            let p=dense_strategy_compressed(game,node);
            w.write_all(&[1])?;w.write_all(&(p.len() as u64).to_le_bytes())?;
            w.write_all(&node.strategy_scale().to_le_bytes())?;
            write_words(w,&p,scratch)?;
        } else {
            let p=probabilities(game,node);
            w.write_all(&[0])?;w.write_all(&(p.len() as u64).to_le_bytes())?;
            write_words(w,&p,scratch)?;
        }
    }
    for a in 0..node.num_actions(){write_node(game,&node.play(a),w,scratch)?;}
    Ok(())
}
pub fn load(game:&PostFlopGame,path:&str,key:&str)->Result<Value,String> {
    let mut file=BufReader::with_capacity(1024*1024,File::open(path).map_err(|e|e.to_string())?);
    let mut magic=[0;8]; file.read_exact(&mut magic).map_err(|e|e.to_string())?;
    if &magic!=b"PLPOL002" && &magic!=b"PLPOL003" {return Err("invalid policy snapshot version".into());}
    let len=read_u64(&mut file).map_err(|e|e.to_string())?;
    if len>1024*1024 {return Err("invalid snapshot header size".into());}
    let mut header=vec![0;len as usize]; file.read_exact(&mut header).map_err(|e|e.to_string())?;
    let meta:Value=serde_json::from_slice(&header).map_err(|e|e.to_string())?;
    if meta["key"].as_str()!=Some(key) {return Err("snapshot configuration fingerprint mismatch".into());}
    read_node(game,&mut *game.root(),&mut file,game.is_compression_enabled(),&magic==b"PLPOL003",&mut [0;IO_CHUNK]).map_err(|e|e.to_string())?;
    let mut tail=[0]; if file.read(&mut tail).map_err(|e|e.to_string())?!=0 {return Err("trailing snapshot data".into());}
    Ok(meta)
}
fn read_u64<R:Read>(r:&mut R)->std::io::Result<u64> {let mut b=[0;8];r.read_exact(&mut b)?;Ok(u64::from_le_bytes(b))}
fn read_node<G:Game,R:Read>(game:&G,node:&mut G::Node,r:&mut R,compressed:bool,typed:bool,scratch:&mut [u8;IO_CHUNK])->std::io::Result<()> {
    if node.is_terminal(){return Ok(());}
    if !node.is_chance() && node.num_actions()>1 {
        let mut encoding=[0];if typed {r.read_exact(&mut encoding)?;}
        if encoding[0]>1 {return Err(std::io::Error::new(std::io::ErrorKind::InvalidData,"unknown strategy encoding"));}
        let len=read_u64(r)?;
        let expected=node.num_actions()*game.num_private_hands(node.player());
        if len!=expected as u64{return Err(std::io::Error::new(std::io::ErrorKind::InvalidData,"tree shape mismatch"));}
        if encoding[0]==1 {
            let mut b=[0;4];r.read_exact(&mut b)?;let scale=f32::from_le_bytes(b);
            if !scale.is_finite()||scale<0.0 {return Err(std::io::Error::new(std::io::ErrorKind::InvalidData,"invalid strategy scale"));}
            if compressed {
                read_words::<u16,_,_>(r,&mut dense_strategy_compressed_mut(game,node),scratch,Ok)?;
                node.set_strategy_scale(scale);
            } else {
                // Final-policy snapshot: scale cancels on normalization. Integers
                // are exactly representable as f32; do not introduce extra rounding.
                read_words::<u16,_,_>(r,&mut dense_strategy_mut(game,node),scratch,|v|Ok(v as f32))?;
            }
        } else {
            let mut values=vec![0.0;expected];
            read_words::<f32,_,_>(r,&mut values,scratch,|v|if v.is_finite() && v>=0.0 {Ok(v)} else {Err(std::io::Error::new(std::io::ErrorKind::InvalidData,"invalid probability"))})?;
            set_probabilities(game,node,&values,compressed);
        }
    }
    for a in 0..node.num_actions(){read_node(game,&mut *node.play(a),r,compressed,typed,scratch)?;}
    Ok(())
}

trait Word:Copy {
    const WIDTH:usize;
    fn encode(self,bytes:&mut [u8]);
    fn decode(bytes:&[u8])->Self;
}
macro_rules! word {
    ($ty:ty,$width:expr)=>{
        impl Word for $ty {
            const WIDTH:usize=$width;
            fn encode(self,bytes:&mut [u8]) {bytes.copy_from_slice(&self.to_le_bytes());}
            fn decode(bytes:&[u8])->Self {Self::from_le_bytes(bytes.try_into().unwrap())}
        }
    };
}
word!(u16,2);
word!(f32,4);

fn write_words<T:Word,W:Write>(writer:&mut W,values:&[T],scratch:&mut [u8;IO_CHUNK])->std::io::Result<()> {
    for chunk in values.chunks(IO_CHUNK/T::WIDTH) {
        let bytes=&mut scratch[..chunk.len()*T::WIDTH];
        for (&value,out) in chunk.iter().zip(bytes.chunks_exact_mut(T::WIDTH)) {value.encode(out);}
        writer.write_all(bytes)?;
    }
    Ok(())
}

fn read_words<T:Word,V,R:Read>(reader:&mut R,values:&mut [V],scratch:&mut [u8;IO_CHUNK],convert:impl Fn(T)->std::io::Result<V>)->std::io::Result<()> {
    for chunk in values.chunks_mut(IO_CHUNK/T::WIDTH) {
        let bytes=&mut scratch[..chunk.len()*T::WIDTH];
        reader.read_exact(bytes)?;
        for (value,input) in chunk.iter_mut().zip(bytes.chunks_exact(T::WIDTH)) {*value=convert(T::decode(input))?;}
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::{io::{self,Cursor},path::PathBuf,sync::atomic::{AtomicU64,Ordering}};

    static TEMP_ID:AtomicU64=AtomicU64::new(0);
    struct Temp(PathBuf);
    impl Temp {
        fn new()->Self {Self(std::env::temp_dir().join(format!("pokerlab-snapshot-test-{}-{}.bin",std::process::id(),TEMP_ID.fetch_add(1,Ordering::Relaxed))))}
        fn path(&self)->&str {self.0.to_str().unwrap()}
    }
    impl Drop for Temp {fn drop(&mut self) {let _=fs::remove_file(&self.0);}}

    fn game(compressed:bool)->PostFlopGame {
        let cards=CardConfig {
            range:["AsAh,KsKh,QsQh,JsJh:0.4".parse().unwrap(),"AcAd,KcKd,QcQd,JcJd:0.7".parse().unwrap()],
            flop:flop_from_str("9h8h2c").unwrap(),turn:card_from_str("4s").unwrap(),river:card_from_str("3d").unwrap(),
        };
        let config=TreeConfig {
            initial_state:BoardState::River,starting_pot:20,effective_stack:30,
            river_bet_sizes:[("33%,75%","2x").try_into().unwrap(),("50%","2x").try_into().unwrap()],
            ..Default::default()
        };
        let mut game=PostFlopGame::with_config(cards,ActionTree::new(config).unwrap()).unwrap();
        game.allocate_memory(compressed);
        game
    }

    // The original scalar encoder retained only as an independent file-format
    // oracle. PLPOL002 had no node type tags and always stored f32 probabilities.
    fn scalar_node<G:Game,W:Write>(game:&G,node:&G::Node,w:&mut W,typed:bool)->io::Result<()> {
        if node.is_terminal() {return Ok(());}
        if !node.is_chance() && node.num_actions()>1 {
            if typed && game.is_compression_enabled() && game.locking_strategy(node).is_empty() {
                let p=dense_strategy_compressed(game,node);
                w.write_all(&[1])?;w.write_all(&(p.len() as u64).to_le_bytes())?;
                w.write_all(&node.strategy_scale().to_le_bytes())?;
                for v in p.iter() {w.write_all(&v.to_le_bytes())?;}
            } else {
                let p=probabilities(game,node);
                if typed {w.write_all(&[0])?;}
                w.write_all(&(p.len() as u64).to_le_bytes())?;
                for v in p {w.write_all(&v.to_le_bytes())?;}
            }
        }
        for a in 0..node.num_actions() {scalar_node(game,&node.play(a),w,typed)?;}
        Ok(())
    }
    fn scalar_file(game:&PostFlopGame,meta:&Value,typed:bool)->Vec<u8> {
        let header=serde_json::to_vec(meta).unwrap();
        let mut bytes=Vec::new();
        bytes.extend_from_slice(if typed {b"PLPOL003"} else {b"PLPOL002"});
        bytes.extend_from_slice(&(header.len() as u64).to_le_bytes());
        bytes.extend_from_slice(&header);
        scalar_node(game,&game.root(),&mut bytes,typed).unwrap();
        bytes
    }
    fn compare_nodes<G:Game>(a:&G,an:&G::Node,b:&G,bn:&G::Node,tolerance:f32) {
        assert_eq!(an.num_actions(),bn.num_actions());
        if an.is_terminal() {return;}
        if !an.is_chance() {
            let expected=probabilities(a,an);let actual=probabilities(b,bn);
            for (x,y) in expected.iter().zip(actual) {assert!((*x-y).abs()<=tolerance,"{x} != {y}");}
        }
        for action in 0..an.num_actions() {compare_nodes(a,&an.play(action),b,&bn.play(action),tolerance);}
    }

    fn chance_game(compressed:bool,sparse:bool,expanded:bool)->PostFlopGame {
        let cards=CardConfig {
            range:["AA:0.7,AKs:0.3".parse().unwrap(),"KK:0.4,KQs:0.8".parse().unwrap()],
            flop:flop_from_str("9h8h2h").unwrap(),turn:card_from_str("4s").unwrap(),river:NOT_DEALT,
        };
        let sizes:BetSizeOptions=("50%","2x").try_into().unwrap();
        let tree=ActionTree::new(TreeConfig {
            initial_state:BoardState::Turn,starting_pot:20,effective_stack:20,
            turn_bet_sizes:[sizes.clone(),sizes.clone()],
            river_bet_sizes:[sizes.clone(),sizes],
            ..Default::default()
        }).unwrap();
        let mut game=PostFlopGame::prepare_config(cards,tree,expanded).unwrap();
        game.set_sparse_storage(sparse).unwrap();
        game.build_prepared().unwrap();
        game.allocate_memory(compressed);
        game
    }

    fn packed_nodes(game:&PostFlopGame,node:&PostFlopNode)->usize {
        if node.is_terminal(){return 0;}
        let mut count=0;
        if !node.is_chance() {
            let raw_len=if game.is_compression_enabled(){node.strategy_compressed().len()}else{node.strategy().len()};
            count+=usize::from(raw_len<node.num_actions()*game.num_private_hands(node.player()));
        }
        for action in 0..node.num_actions(){count+=packed_nodes(game,&node.play(action));}
        count
    }

    #[test]
    fn sparse_snapshot_keeps_dense_v3_bytes_and_loads_both_legacy_formats() {
        // Future-card collisions exercise physical packing, unlike a River-only
        // fixture whose conflicting starting hands were removed on construction.
        let meta=json!({"key":"sparse-chance-fixture","iterations":7});
        for compressed in [false,true] {
            for expanded in [false,true] {
                let dense=chance_game(compressed,false,expanded);
                let sparse=chance_game(compressed,true,expanded);
                assert_eq!(packed_nodes(&dense,&dense.root()),0);
                assert!(packed_nodes(&sparse,&sparse.root())>0);
                for iteration in 0..7 {solve_step(&dense,iteration);solve_step(&sparse,iteration);}
                assert_eq!(scalar_file(&dense,&meta,true),scalar_file(&sparse,&meta,true));
                assert_eq!(stats(&dense,&dense.root(),compressed),stats(&sparse,&sparse.root(),compressed));
                let file=Temp::new();
                save(&sparse,file.path(),&meta).unwrap();
                assert_eq!(fs::read(&file.0).unwrap(),scalar_file(&dense,&meta,true));
                for typed in [false,true] {
                    let bytes=scalar_file(&dense,&meta,typed);
                    fs::write(&file.0,&bytes).unwrap();
                    for target_sparse in [false,true] {
                        let restored=chance_game(compressed,target_sparse,expanded);
                        assert_eq!(load(&restored,file.path(),"sparse-chance-fixture").unwrap(),meta);
                        compare_nodes(&dense,&dense.root(),&restored,&restored.root(),2e-5);
                        let expected=compute_current_ev(&dense);let actual=compute_current_ev(&restored);
                        for player in 0..2 {assert!((expected[player]-actual[player]).abs()<0.002);}
                        if typed && compressed {assert_eq!(scalar_file(&restored,&meta,true),bytes);}
                    }
                }
            }
        }
    }

    #[test]
    fn legacy_policy_with_distinct_blocked_hand_rows_preserves_every_legal_word() {
        fn alter_blocked_policy(dense:&PostFlopGame,dn:&mut PostFlopNode,sparse:&PostFlopGame,sn:&PostFlopNode)->bool {
            if dn.is_terminal(){return false;}
            if !dn.is_chance() && dn.num_actions()>1 {
                let hands=dense.num_private_hands(dn.player());
                if let Some(legal)=sparse.storage_hand_indices(sn,sn.player()) {
                    if legal.len()+1<hands {
                        let actions=dn.num_actions();
                        let mut policy=probabilities(dense,dn);
                        for hand in 0..hands {
                            if legal.binary_search(&(hand as u16)).is_ok(){continue;}
                            // A previous opponent compiler may have assigned
                            // arbitrary different actions to impossible hands.
                            for action in 0..actions {policy[action*hands+hand]=0.0;}
                            let first=(hand+1) as f32/(hands+1) as f32;
                            policy[hand]=first;policy[(actions-1)*hands+hand]=1.0-first;
                        }
                        set_probabilities(dense,dn,&policy,true);
                        return true;
                    }
                }
            }
            for action in 0..dn.num_actions() {
                if alter_blocked_policy(dense,&mut dn.play(action),sparse,&sn.play(action)){return true;}
            }
            false
        }
        fn compare_legal(dense:&PostFlopGame,dn:&PostFlopNode,sparse:&PostFlopGame,sn:&PostFlopNode) {
            if dn.is_terminal(){return;}
            if !dn.is_chance() && dn.num_actions()>1 {
                let hands=dense.num_private_hands(dn.player());
                let expected=dense_strategy_compressed(dense,dn);
                let actual=dense_strategy_compressed(sparse,sn);
                assert_eq!(dn.strategy_scale().to_bits(),sn.strategy_scale().to_bits());
                let legal=sparse.storage_hand_indices(sn,sn.player());
                for hand in 0..hands {
                    if legal.map_or(false,|indices|indices.binary_search(&(hand as u16)).is_err()){continue;}
                    for action in 0..dn.num_actions(){assert_eq!(expected[action*hands+hand],actual[action*hands+hand]);}
                }
            }
            for action in 0..dn.num_actions(){compare_legal(dense,&dn.play(action),sparse,&sn.play(action));}
        }
        let dense=chance_game(true,false,false);
        let sparse=chance_game(true,true,false);
        for iteration in 0..7 {solve_step(&dense,iteration);}
        assert!(alter_blocked_policy(&dense,&mut dense.root(),&sparse,&sparse.root()));
        let file=Temp::new();let meta=json!({"key":"old-final-policy"});
        save(&dense,file.path(),&meta).unwrap();
        load(&sparse,file.path(),"old-final-policy").unwrap();
        compare_legal(&dense,&dense.root(),&sparse,&sparse.root());
        assert_eq!(compute_current_ev(&dense).map(f32::to_bits),compute_current_ev(&sparse).map(f32::to_bits));
        // This is a final-policy load: never resume CFR from merged blocked
        // rows. Checkpoints use uniform CFR ghosts and are tested separately.
    }

    #[test]
    fn chunked_snapshot_is_byte_identical_to_scalar_v3_and_loads_v2() {
        let meta=json!({"key":"snapshot-fixture","iterations":11});
        for compressed in [false,true] {
            for locked in [false,true] {
                let mut original=game(compressed);
                for iteration in 0..11 {solve_step(&original,iteration);}
                if locked {
                    let hands=original.num_private_hands(0);
                    let actions=original.root().num_actions();
                    let mut p=vec![0.0;hands*actions];
                    for hand in 0..hands {p[hand]=0.237;p[hands+hand]=0.763;}
                    original.lock_current_strategy(&p);
                }
                let file=Temp::new();
                save(&original,file.path(),&meta).unwrap();
                assert_eq!(fs::read(&file.0).unwrap(),scalar_file(&original,&meta,true));
                for typed in [false,true] {
                    let bytes=scalar_file(&original,&meta,typed);
                    fs::write(&file.0,&bytes).unwrap();
                    for target_compressed in [false,true] {
                        let restored=game(target_compressed);
                        assert_eq!(load(&restored,file.path(),"snapshot-fixture").unwrap(),meta);
                        compare_nodes(&original,&original.root(),&restored,&restored.root(),2e-5);
                        let a=compute_current_ev(&original);let b=compute_current_ev(&restored);
                        for player in 0..2 {assert!((a[player]-b[player]).abs()<0.002);}
                        if typed && compressed && target_compressed && !locked {
                            // Raw u16 arrays/scales survive exactly, without a
                            // normalize/quantize cycle at any canonical node.
                            assert_eq!(scalar_file(&restored,&meta,true),bytes);
                        }
                    }
                }
            }
        }
    }

    #[test]
    fn malformed_snapshots_still_reject_shape_encoding_values_and_truncation() {
        let meta=json!({"key":"fixture"});let file=Temp::new();
        for compressed in [false,true] {
            let original=game(compressed);solve_step(&original,0);
            let bytes=scalar_file(&original,&meta,true);
            let start=16+u64::from_le_bytes(bytes[8..16].try_into().unwrap()) as usize;
            for end in [0,7,15,start,start+1,start+8,start+10,bytes.len()-1] {
                fs::write(&file.0,&bytes[..end]).unwrap();
                assert!(load(&game(compressed),file.path(),"fixture").is_err(),"accepted truncation {end}");
            }
            let mut bad=bytes.clone();bad[start]=2;fs::write(&file.0,&bad).unwrap();
            assert!(load(&game(compressed),file.path(),"fixture").unwrap_err().contains("encoding"));
            let mut bad=bytes.clone();bad[start+1..start+9].copy_from_slice(&u64::MAX.to_le_bytes());fs::write(&file.0,&bad).unwrap();
            assert!(load(&game(compressed),file.path(),"fixture").unwrap_err().contains("shape"));
            for value in [f32::NAN,f32::INFINITY,-1.0] {
                let mut bad=bytes.clone();bad[start+9..start+13].copy_from_slice(&value.to_le_bytes());fs::write(&file.0,&bad).unwrap();
                let message=load(&game(compressed),file.path(),"fixture").unwrap_err();
                assert!(message.contains(if compressed {"scale"} else {"probability"}));
            }
            let mut bad=bytes.clone();bad.push(1);fs::write(&file.0,&bad).unwrap();
            assert!(load(&game(compressed),file.path(),"fixture").unwrap_err().contains("trailing"));
            fs::write(&file.0,&bytes).unwrap();
            assert!(load(&game(compressed),file.path(),"other").unwrap_err().contains("fingerprint"));
        }
    }

    #[test]
    fn word_io_handles_chunk_boundaries_short_reads_and_partial_words() {
        struct ShortRead<R>(R);
        impl<R:Read> Read for ShortRead<R> {
            fn read(&mut self,out:&mut [u8])->io::Result<usize> {let n=out.len().min(7);self.0.read(&mut out[..n])}
        }
        for len in [0,1,IO_CHUNK/2-1,IO_CHUNK/2,IO_CHUNK/2+1,IO_CHUNK+3] {
            let values:Vec<u16>=(0..len).map(|i|i.wrapping_mul(13) as u16).collect();
            let expected:Vec<u8>=values.iter().flat_map(|v|v.to_le_bytes()).collect();
            let mut bytes=Vec::new();write_words(&mut bytes,&values,&mut [0;IO_CHUNK]).unwrap();
            assert_eq!(bytes,expected);
            let mut actual=vec![0;len];
            read_words::<u16,_,_>(&mut ShortRead(Cursor::new(&bytes)),&mut actual,&mut [0;IO_CHUNK],Ok).unwrap();
            assert_eq!(actual,values);
            if !bytes.is_empty() {assert!(read_words::<u16,_,_>(&mut Cursor::new(&bytes[..bytes.len()-1]),&mut actual,&mut [0;IO_CHUNK],Ok).is_err());}
        }
        for len in [IO_CHUNK/4-1,IO_CHUNK/4,IO_CHUNK/4+1] {
            let values:Vec<f32>=(0..len).map(|i|i as f32/73.0).collect();
            let expected:Vec<u8>=values.iter().flat_map(|v|v.to_le_bytes()).collect();
            let mut bytes=Vec::new();write_words(&mut bytes,&values,&mut [0;IO_CHUNK]).unwrap();
            assert_eq!(bytes,expected);
            let mut actual=vec![0.0;len];
            read_words::<f32,_,_>(&mut ShortRead(Cursor::new(&bytes)),&mut actual,&mut [0;IO_CHUNK],Ok).unwrap();
            assert_eq!(actual,values);
        }
    }

    #[test]
    #[ignore="small I/O microbenchmark; not full-solver performance evidence"]
    fn buffered_word_io_microbenchmark() {
        use std::{hint::black_box,time::Instant};
        const REPEATS:usize=16;
        let values:Vec<u16>=(0..2*1024*1024).map(|i|i as u16).collect();
        let measure_write=|chunked:bool| {
            let start=Instant::now();let mut last=Vec::new();
            for _ in 0..REPEATS {
                let mut writer=BufWriter::with_capacity(1024*1024,Vec::with_capacity(values.len()*2));
                if chunked {write_words(&mut writer,black_box(&values),&mut [0;IO_CHUNK]).unwrap();}
                else {for v in black_box(&values) {writer.write_all(&v.to_le_bytes()).unwrap();}}
                last=black_box(writer.into_inner().unwrap());
            }
            (start.elapsed().as_secs_f64(),last)
        };
        let (scalar_write,a)=measure_write(false);let (chunk_write,b)=measure_write(true);assert_eq!(a,b);
        let measure_read=|chunked:bool| {
            let start=Instant::now();let mut out=vec![0;values.len()];
            for _ in 0..REPEATS {
                let mut reader=BufReader::with_capacity(1024*1024,Cursor::new(black_box(&a)));
                if chunked {read_words::<u16,_,_>(&mut reader,&mut out,&mut [0;IO_CHUNK],Ok).unwrap();}
                else {for v in &mut out {let mut bytes=[0;2];reader.read_exact(&mut bytes).unwrap();*v=u16::from_le_bytes(bytes);}}
                black_box(&out);
            }
            assert_eq!(out,values);start.elapsed().as_secs_f64()
        };
        let scalar_read=measure_read(false);let chunk_read=measure_read(true);
        println!("64 MiB u16 in-memory BufWriter/BufReader: scalar_write={scalar_write:.6}s chunk_write={chunk_write:.6}s scalar_read={scalar_read:.6}s chunk_read={chunk_read:.6}s; no disk I/O or solver traversal measured");
    }
}

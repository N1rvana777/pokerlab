//! Resumable, pre-finalize DCFR state. This is NOT a final-policy snapshot.
//!
//! The caller must use the returned `iterations` as the next `solve_step` index,
//! and include engine revision, algorithm and complete tree/card configuration
//! in `key`. Saving/loading a finalized or node-locked game is forbidden.
//! A failed load may have partially written arrays: discard that game on error.
use postflop_solver::*;
use serde_json::Value;
use std::{
    fs::{self, File, OpenOptions},
    io::{self, BufReader, BufWriter, Read, Write},
    path::Path,
    sync::atomic::{AtomicU64, Ordering},
};

const MAGIC: &[u8; 8] = b"PLCFR001";
const END: &[u8; 8] = b"CFRDONE1";
const MAX_HEADER: usize = 1024 * 1024;
const CHUNK: usize = 16 * 1024;
static TEMP_ID: AtomicU64 = AtomicU64::new(0);

fn invalid(message: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

fn validate_metadata(metadata: &Value) -> Result<(), String> {
    if !metadata.is_object()
        || metadata["key"].as_str().map_or(true, |key| key.is_empty())
        || metadata["iterations"].as_u64().map_or(true, |n| n > u32::MAX as u64)
    {
        return Err("checkpoint requires a fingerprint and a u32 iteration count".into());
    }
    Ok(())
}

fn ensure_ready(game: &PostFlopGame) -> Result<(), String> {
    if game.is_solved() || !game.is_ready() {
        return Err("CFR checkpoints require allocated, unfinalized state".into());
    }
    Ok(())
}

/// Atomically replaces the checkpoint after a full, synced write (Linux/WSL).
/// Memory overhead is one 1 MiB I/O buffer, one 16 KiB scratch buffer, current
/// node's dense logical views and DFS depth; no complete game arrays or output
/// bytes are cloned.
pub fn save(game: &PostFlopGame, path: &str, metadata: &Value) -> Result<(), String> {
    ensure_ready(game)?;
    validate_metadata(metadata)?;
    let mut metadata = metadata.clone();
    metadata["compression"] = Value::Bool(game.is_compression_enabled());
    let header = serde_json::to_vec(&metadata).map_err(|e| e.to_string())?;
    if header.len() > MAX_HEADER {
        return Err("invalid checkpoint header size".into());
    }
    let target = Path::new(path);
    if let Some(parent) = target.parent().filter(|p| !p.as_os_str().is_empty()) {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let tmp = format!("{path}.{}.{}.tmp", std::process::id(), TEMP_ID.fetch_add(1, Ordering::Relaxed));
    let file = OpenOptions::new().write(true).create_new(true).open(&tmp).map_err(|e| e.to_string())?;
    let result = (|| -> io::Result<()> {
        let mut writer = BufWriter::with_capacity(MAX_HEADER, file);
        writer.write_all(MAGIC)?;
        writer.write_all(&(header.len() as u64).to_le_bytes())?;
        writer.write_all(&header)?;
        write_node(game, &game.root(), &mut writer, &mut [0; CHUNK])?;
        writer.write_all(END)?;
        writer.flush()?;
        writer.get_ref().sync_all()?;
        drop(writer);
        fs::rename(&tmp, target)
    })();
    if result.is_err() {
        // Only our uniquely named temporary file; never remove the old target.
        let _ = fs::remove_file(&tmp);
    }
    result.map_err(|e| e.to_string())
}

pub fn load(game: &PostFlopGame, path: &str, key: &str) -> Result<Value, String> {
    ensure_ready(game)?;
    let mut reader = BufReader::with_capacity(MAX_HEADER, File::open(path).map_err(|e| e.to_string())?);
    let mut magic = [0; 8];
    reader.read_exact(&mut magic).map_err(|e| e.to_string())?;
    if &magic != MAGIC {
        return Err("invalid CFR checkpoint version (final policies cannot resume CFR)".into());
    }
    let size = read_u64(&mut reader).map_err(|e| e.to_string())?;
    if size > MAX_HEADER as u64 {
        return Err("invalid checkpoint header size".into());
    }
    let mut header = vec![0; size as usize];
    reader.read_exact(&mut header).map_err(|e| e.to_string())?;
    let metadata: Value = serde_json::from_slice(&header).map_err(|e| e.to_string())?;
    validate_metadata(&metadata)?;
    if metadata["key"].as_str() != Some(key) {
        return Err("checkpoint configuration fingerprint mismatch".into());
    }
    if metadata["compression"].as_bool() != Some(game.is_compression_enabled()) {
        return Err("checkpoint compression mode mismatch".into());
    }
    read_node(game, &mut game.root(), &mut reader, &mut [0; CHUNK]).map_err(|e| e.to_string())?;
    reader.read_exact(&mut magic).map_err(|e| e.to_string())?;
    if &magic != END {
        return Err("invalid checkpoint end marker".into());
    }
    let mut tail = [0];
    if reader.read(&mut tail).map_err(|e| e.to_string())? != 0 {
        return Err("trailing checkpoint data".into());
    }
    Ok(metadata)
}

fn write_node<G: Game, W: Write>(game: &G, node: &G::Node, writer: &mut W, scratch: &mut [u8; CHUNK]) -> io::Result<()> {
    if node.is_terminal() {
        return Ok(());
    }
    if !node.is_chance() {
        if !game.locking_strategy(node).is_empty() {
            return Err(invalid("CFR checkpoints cannot contain fixed opponent or manual locks"));
        }
        if node.num_actions() > 1 {
            writer.write_all(&[node.player() as u8])?;
            writer.write_all(&(node.num_actions() as u64).to_le_bytes())?;
            if game.is_compression_enabled() {
                let strategies=dense_strategy_compressed(game,node);
                let regrets=dense_regrets_compressed(game,node);
                writer.write_all(&(strategies.len() as u64).to_le_bytes())?;
                writer.write_all(&(regrets.len() as u64).to_le_bytes())?;
                write_words(writer, &[node.strategy_scale(), node.regret_scale()], scratch, nonnegative)?;
                write_words(writer, &strategies, scratch, |_| true)?;
                write_words(writer, &regrets, scratch, |_| true)?;
            } else {
                let strategies=dense_strategy(game,node);
                let regrets=dense_regrets(game,node);
                writer.write_all(&(strategies.len() as u64).to_le_bytes())?;
                writer.write_all(&(regrets.len() as u64).to_le_bytes())?;
                write_words(writer, &strategies, scratch, nonnegative)?;
                write_words(writer, &regrets, scratch, f32::is_finite)?;
            }
        }
    }
    for action in 0..node.num_actions() {
        write_node(game, &node.play(action), writer, scratch)?;
    }
    Ok(())
}

fn read_node<G: Game, R: Read>(game: &G, node: &mut G::Node, reader: &mut R, scratch: &mut [u8; CHUNK]) -> io::Result<()> {
    if node.is_terminal() {
        return Ok(());
    }
    if !node.is_chance() {
        if !game.locking_strategy(node).is_empty() {
            return Err(invalid("CFR checkpoints cannot load into a locked game"));
        }
        if node.num_actions() > 1 {
            let mut player = [0];
            reader.read_exact(&mut player)?;
            let actions = read_u64(reader)?;
            let strategies = read_u64(reader)?;
            let regrets = read_u64(reader)?;
            let strategy_len=node.num_actions()*game.num_private_hands(node.player());
            let regret_len=strategy_len;
            if player[0] as usize != node.player() || actions != node.num_actions() as u64
                || strategies != strategy_len as u64 || regrets != regret_len as u64
            {
                return Err(invalid("checkpoint tree shape mismatch"));
            }
            if game.is_compression_enabled() {
                let mut scales = [0.0; 2];
                read_words(reader, &mut scales, scratch, nonnegative)?;
                read_words(reader, &mut dense_strategy_compressed_mut(game,node), scratch, |_| true)?;
                read_words(reader, &mut dense_regrets_compressed_mut(game,node), scratch, |_| true)?;
                node.set_strategy_scale(scales[0]);
                node.set_regret_scale(scales[1]);
            } else {
                read_words(reader, &mut dense_strategy_mut(game,node), scratch, nonnegative)?;
                read_words(reader, &mut dense_regrets_mut(game,node), scratch, f32::is_finite)?;
            }
        }
    }
    for action in 0..node.num_actions() {
        read_node(game, &mut node.play(action), reader, scratch)?;
    }
    Ok(())
}

fn read_u64<R: Read>(reader: &mut R) -> io::Result<u64> {
    let mut bytes = [0; 8];
    reader.read_exact(&mut bytes)?;
    Ok(u64::from_le_bytes(bytes))
}
fn nonnegative(value: f32) -> bool { value.is_finite() && value >= 0.0 }

trait Word: Copy {
    const WIDTH: usize;
    fn encode(self, bytes: &mut [u8]);
    fn decode(bytes: &[u8]) -> Self;
}
macro_rules! word {
    ($ty:ty, $width:expr) => {
        impl Word for $ty {
            const WIDTH: usize = $width;
            fn encode(self, bytes: &mut [u8]) { bytes.copy_from_slice(&self.to_le_bytes()); }
            fn decode(bytes: &[u8]) -> Self { Self::from_le_bytes(bytes.try_into().unwrap()) }
        }
    };
}
word!(f32, 4);
word!(u16, 2);
word!(i16, 2);

fn write_words<T: Word, W: Write>(writer: &mut W, values: &[T], scratch: &mut [u8; CHUNK], valid: impl Fn(T) -> bool) -> io::Result<()> {
    for chunk in values.chunks(CHUNK / T::WIDTH) {
        let bytes = &mut scratch[..chunk.len() * T::WIDTH];
        for (&value, bytes) in chunk.iter().zip(bytes.chunks_exact_mut(T::WIDTH)) {
            if !valid(value) { return Err(invalid("invalid non-finite or negative CFR state")); }
            value.encode(bytes);
        }
        writer.write_all(bytes)?;
    }
    Ok(())
}
fn read_words<T: Word, R: Read>(reader: &mut R, values: &mut [T], scratch: &mut [u8; CHUNK], valid: impl Fn(T) -> bool) -> io::Result<()> {
    for chunk in values.chunks_mut(CHUNK / T::WIDTH) {
        let bytes = &mut scratch[..chunk.len() * T::WIDTH];
        reader.read_exact(bytes)?;
        for (value, bytes) in chunk.iter_mut().zip(bytes.chunks_exact(T::WIDTH)) {
            let decoded = T::decode(bytes);
            if !valid(decoded) { return Err(invalid("invalid non-finite or negative CFR state")); }
            *value = decoded;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::path::PathBuf;

    struct Temp(PathBuf);
    impl Temp {
        fn new() -> Self {
            Self(std::env::temp_dir().join(format!("pokerlab-checkpoint-test-{}-{}.bin", std::process::id(), TEMP_ID.fetch_add(1, Ordering::Relaxed))))
        }
        fn path(&self) -> &str { self.0.to_str().unwrap() }
    }
    impl Drop for Temp { fn drop(&mut self) { let _ = fs::remove_file(&self.0); } }

    fn game(compressed: bool) -> PostFlopGame {
        let cards = CardConfig {
            range: ["AsAh,KsKh,QsQh,JsJh:0.4".parse().unwrap(), "AcAd,KcKd,QcQd,JcJd:0.7".parse().unwrap()],
            flop: flop_from_str("9h8h2c").unwrap(),
            turn: card_from_str("4s").unwrap(),
            river: card_from_str("3d").unwrap(),
        };
        let config = TreeConfig {
            initial_state: BoardState::River,
            starting_pot: 20,
            effective_stack: 30,
            river_bet_sizes: [("33%,75%", "2x").try_into().unwrap(), ("50%", "2x").try_into().unwrap()],
            ..Default::default()
        };
        let mut game = PostFlopGame::with_config(cards, ActionTree::new(config).unwrap()).unwrap();
        game.allocate_memory(compressed);
        game
    }

    fn raw_state(game: &PostFlopGame) -> Vec<u8> {
        let mut bytes = Vec::new();
        write_node(game, &game.root(), &mut bytes, &mut [0; CHUNK]).unwrap();
        bytes
    }

    #[test]
    fn resume_matches_uninterrupted_dcfr_f32_and_u16() {
        // Cross the discount/reset boundary at iteration 16; restarting the
        // iteration counter or restoring normalized policies will fail this.
        for compressed in [false, true] {
            let original = game(compressed);
            for iteration in 0..13 { solve_step(&original, iteration); }
            let path = Temp::new();
            save(&original, path.path(), &json!({"key":"river-fixture", "iterations":13})).unwrap();
            let resumed = game(compressed);
            let metadata = load(&resumed, path.path(), "river-fixture").unwrap();
            assert_eq!(metadata["iterations"], 13);
            assert_eq!(raw_state(&original), raw_state(&resumed));
            for iteration in 13..31 {
                solve_step(&original, iteration);
                solve_step(&resumed, iteration);
            }
            assert_eq!(raw_state(&original), raw_state(&resumed));
            assert_eq!(compute_exploitability(&original).to_bits(), compute_exploitability(&resumed).to_bits());
            // Replacing an existing checkpoint is atomic on the WSL platform.
            save(&original, path.path(), &json!({"key":"river-fixture", "iterations":31})).unwrap();
            assert_eq!(load(&game(compressed), path.path(), "river-fixture").unwrap()["iterations"], 31);
        }
    }

    #[test]
    fn resume_matches_uninterrupted_flop_and_turn_chance_trees() {
        fn chance_game(street: BoardState, compressed: bool, sparse: bool, expanded: bool) -> PostFlopGame {
            let cards = CardConfig {
                range: ["AsAh,JsJh".parse().unwrap(), "KsKh,QcQd".parse().unwrap()],
                flop: flop_from_str("9h8h2c").unwrap(),
                turn: if street == BoardState::Turn { card_from_str("4s").unwrap() } else { NOT_DEALT },
                river: NOT_DEALT,
            };
            let sizes: BetSizeOptions = ("50%", "").try_into().unwrap();
            let tree = ActionTree::new(TreeConfig {
                initial_state: street,
                starting_pot: 20,
                effective_stack: 20,
                flop_bet_sizes: [sizes.clone(), sizes.clone()],
                turn_bet_sizes: [sizes.clone(), sizes.clone()],
                river_bet_sizes: [sizes.clone(), sizes],
                ..Default::default()
            }).unwrap();
            let mut game = PostFlopGame::prepare_config(cards, tree, expanded).unwrap();
            game.set_sparse_storage(sparse).unwrap();
            game.build_prepared().unwrap();
            let bytes = if compressed { game.memory_usage().1 } else { game.memory_usage().0 };
            // Two instances coexist; keep this regression a small resource test.
            assert!(bytes < 10 * 1024 * 1024, "chance fixture exceeds 10 MiB: {bytes}");
            game.allocate_memory(compressed);
            game
        }
        for street in [BoardState::Turn, BoardState::Flop] {
            for compressed in [false, true] {
              for expanded in [false,true] {
                let original = chance_game(street, compressed, false, expanded);
                let stats = crate::snapshot::stats(&original, &*original.root(), compressed);
                assert!(stats[2] > 0, "fixture must retain real public-card branches");
                for iteration in 0..3 { solve_step(&original, iteration); }
                let path = Temp::new();
                save(&original, path.path(), &json!({"key":"chance-fixture", "iterations":3})).unwrap();
                let resumed = chance_game(street, compressed, true, expanded);
                let metadata = load(&resumed, path.path(), "chance-fixture").unwrap();
                assert_eq!(metadata["iterations"], 3);
                assert_eq!(raw_state(&original), raw_state(&resumed));
                // Global indices 3..7 cross the DCFR power-of-four reset.
                for iteration in 3..7 {
                    solve_step(&original, iteration);
                    solve_step(&resumed, iteration);
                }
                assert_eq!(raw_state(&original), raw_state(&resumed));
                assert_eq!(compute_exploitability(&original).to_bits(), compute_exploitability(&resumed).to_bits());
                // PLCFR001 has a dense logical layout in both directions.
                // Save the packed state, then continue from a dense allocation.
                save(&resumed,path.path(),&json!({"key":"chance-fixture","iterations":7})).unwrap();
                drop(original);
                let roundtrip=chance_game(street,compressed,false,expanded);
                assert_eq!(load(&roundtrip,path.path(),"chance-fixture").unwrap()["iterations"],7);
                assert_eq!(raw_state(&resumed),raw_state(&roundtrip));
                for iteration in 7..9 {solve_step(&resumed,iteration);solve_step(&roundtrip,iteration);}
                assert_eq!(raw_state(&resumed),raw_state(&roundtrip));
                assert_eq!(compute_exploitability(&resumed).to_bits(),compute_exploitability(&roundtrip).to_bits());
              }
            }
        }
    }

    #[test]
    fn rejects_wrong_type_fingerprint_shape_and_corrupt_data() {
        for compressed in [false, true] {
            let original = game(compressed);
            solve_step(&original, 0);
            let path = Temp::new();
            save(&original, path.path(), &json!({"key":"expected", "iterations":1})).unwrap();
            let bytes = fs::read(&path.0).unwrap();
            assert!(load(&game(compressed), path.path(), "different").unwrap_err().contains("fingerprint"));
            assert!(load(&game(!compressed), path.path(), "expected").unwrap_err().contains("compression"));
            let header_size = u64::from_le_bytes(bytes[8..16].try_into().unwrap()) as usize;
            let record_start = 16 + header_size;
            let mut corrupted = bytes.clone();
            corrupted[record_start] = 3; // impossible player index
            fs::write(&path.0, &corrupted).unwrap();
            assert!(load(&game(compressed), path.path(), "expected").unwrap_err().contains("shape"));
            let mut corrupted = bytes.clone();
            // First scale (u16) or first cumulative strategy (f32).
            corrupted[record_start + 25..record_start + 29].copy_from_slice(&f32::NAN.to_le_bytes());
            fs::write(&path.0, &corrupted).unwrap();
            assert!(load(&game(compressed), path.path(), "expected").unwrap_err().contains("non-finite"));
            let mut corrupted = bytes.clone();
            corrupted.extend_from_slice(b"extra");
            fs::write(&path.0, &corrupted).unwrap();
            assert!(load(&game(compressed), path.path(), "expected").unwrap_err().contains("trailing"));
            fs::write(&path.0, &bytes[..bytes.len() - 10]).unwrap();
            assert!(load(&game(compressed), path.path(), "expected").is_err());
            let mut corrupted = bytes.clone();
            corrupted[..8].copy_from_slice(b"PLPOL003");
            fs::write(&path.0, &corrupted).unwrap();
            assert!(load(&game(compressed), path.path(), "expected").unwrap_err().contains("cannot resume"));
        }
    }

    #[test]
    fn checkpoint_rejects_finalized_state_and_preserves_previous_file_on_failed_save() {
        let mut original = game(false);
        let path = Temp::new();
        save(&original, path.path(), &json!({"key":"fixture", "iterations":0})).unwrap();
        let previous = fs::read(&path.0).unwrap();
        original.root().strategy_mut()[0] = f32::INFINITY;
        assert!(save(&original, path.path(), &json!({"key":"fixture", "iterations":1})).is_err());
        assert_eq!(fs::read(&path.0).unwrap(), previous);
        original.root().strategy_mut()[0] = 0.0;
        finalize(&mut original);
        assert!(save(&original, path.path(), &json!({"key":"fixture", "iterations":0})).unwrap_err().contains("unfinalized"));
        assert!(load(&original, path.path(), "fixture").unwrap_err().contains("unfinalized"));
    }

    #[test]
    fn checkpoint_rejects_manual_locks_and_invalid_iteration_metadata() {
        let mut original = game(true);
        let path = Temp::new();
        assert!(save(&original, path.path(), &json!({"key":"fixture", "iterations":-1})).is_err());
        assert!(save(&original, path.path(), &json!({"key":"fixture", "iterations":4294967296u64})).is_err());
        save(&original, path.path(), &json!({"key":"fixture", "iterations":0})).unwrap();
        let count = original.root().strategy_compressed().len();
        original.lock_current_strategy(&vec![1.0; count]);
        assert!(save(&original, path.path(), &json!({"key":"fixture", "iterations":0})).unwrap_err().contains("locks"));
        assert!(load(&original, path.path(), "fixture").unwrap_err().contains("locked"));
    }
}

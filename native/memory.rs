//! Preflight overhead estimates for the native allocator layout.
//!
//! The engine separately counts its arrays, node arena, card tables, and model
//! allocations. These estimates cover additional address-space/allocator costs;
//! they are not a promise that RSS cannot exceed the estimate. The supervisor's
//! address-space limit and Windows/WSL safety reserves remain necessary.

const MIB: u64 = 1024 * 1024;
pub const THREAD_STACK_BYTES: usize = 2 * 1024 * 1024;
const MAIN_STACK_BYTES: u64 = 8 * MIB;
const ARENA_RESERVATION_BYTES: u64 = 2 * 64 * MIB;
// Four storage buffers and the node arena. Two 4 KiB pages per allocation
// allow for page rounding and allocation headers. Auxiliary allocations remain
// covered by their heap allowance and the separate transient allowance.
const LARGE_ALLOCATION_PADDING_BYTES: u64 = 5 * 2 * 4096;
// Includes both bounded idle caches: DCFR scratch at most 1 MiB and sparse
// dense-view scratch at most 1 MiB per thread (16 workers plus the caller).
// Checked-out buffers match requested capacities exactly; recursive active
// scratch and the remaining temporaries share this allowance.
const TRANSIENT_BYTES: u64 = 256 * MIB;
const COMPONENT_MODEL_MIN_ENGINE_BYTES: u64 = 512 * MIB;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MemoryHeadroom {
    pub allocator_bytes: u64,
    pub thread_bytes: u64,
    pub padding_bytes: u64,
    pub transient_bytes: u64,
    pub total_overhead_bytes: u64,
    pub profile: &'static str,
}

/// Only the launcher-controlled Linux/glibc configuration has the bounded
/// allocator model. The caller must also set Rayon worker stacks explicitly to
/// `THREAD_STACK_BYTES`; environment variables alone do not size thread stacks.
pub fn controlled_allocator_profile() -> bool {
    let names = [
        "MALLOC_ARENA_MAX",
        "MALLOC_MMAP_THRESHOLD_",
        "MALLOC_TRIM_THRESHOLD_",
        "MALLOC_MMAP_MAX_",
        "POKERLAB_ALLOCATOR_PROFILE",
        "GLIBC_TUNABLES",
        "LD_PRELOAD",
    ];
    // Malformed environment values also reject the profile; they must not be
    // mistaken for absence, especially for preload/tunable overrides.
    let values = names.map(|name| match std::env::var(name) {
        Ok(value) => Some(value),
        Err(std::env::VarError::NotPresent) => None,
        Err(std::env::VarError::NotUnicode(_)) => Some("<non-unicode>".to_owned()),
    });
    profile_matches(
        cfg!(all(target_os = "linux", target_env = "gnu")),
        [values[0].as_deref(), values[1].as_deref(), values[2].as_deref(),
         values[3].as_deref(), values[4].as_deref(), values[5].as_deref(),
         values[6].as_deref()],
    )
}

fn profile_matches(linux_gnu: bool, values: [Option<&str>; 7]) -> bool {
    linux_gnu
        && values[0] == Some("2")
        && values[1] == Some("131072")
        && values[2] == Some("131072")
        && values[3] == Some("65536")
        && values[4] == Some("glibc-bounded-v1")
        && values[5].unwrap_or("").is_empty()
        && values[6].unwrap_or("").is_empty()
}

pub fn memory_headroom(
    planned_engine: u64,
    card_misc: u64,
    locks: u64,
    threads: usize,
) -> MemoryHeadroom {
    calculate_headroom(
        planned_engine,
        card_misc,
        locks,
        threads,
        controlled_allocator_profile(),
    )
}

// u128 intermediates avoid overflow without rounding down the original 15%
// formula. Saturation deliberately makes an impossible-size request fail its
// budget check rather than wrapping into a small apparently-safe estimate.
fn fifteen_percent(value: u128) -> u64 {
    (value.saturating_mul(15) / 100).min(u64::MAX as u128) as u64
}

fn calculate_headroom(
    planned_engine: u64,
    card_misc: u64,
    locks: u64,
    threads: usize,
    controlled: bool,
) -> MemoryHeadroom {
    // Preserve the existing small-tree admission behavior: the explicit worst
    // case arena/stack reservations are overly conservative at this scale.
    let detailed = controlled && planned_engine >= COMPONENT_MODEL_MIN_ENGINE_BYTES;
    let (allocator_bytes, thread_bytes, padding_bytes, profile) = if detailed {
        (
            ARENA_RESERVATION_BYTES.saturating_add(fifteen_percent(
                card_misc as u128 + locks as u128,
            )),
            (threads as u64)
                .saturating_mul(THREAD_STACK_BYTES as u64)
                .saturating_add(MAIN_STACK_BYTES),
            LARGE_ALLOCATION_PADDING_BYTES,
            "glibc-bounded-v1",
        )
    } else {
        (
            fifteen_percent(planned_engine as u128 + locks as u128),
            0,
            0,
            if controlled { "small-tree-legacy-15pct-v1" } else { "legacy-15pct-v1" },
        )
    };
    MemoryHeadroom {
        allocator_bytes,
        thread_bytes,
        padding_bytes,
        transient_bytes: TRANSIENT_BYTES,
        total_overhead_bytes: allocator_bytes
            .saturating_add(thread_bytes)
            .saturating_add(padding_bytes)
            .saturating_add(TRANSIENT_BYTES),
        profile,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profile_requires_every_launcher_setting_and_linux_glibc() {
        let correct = [Some("2"), Some("131072"), Some("131072"), Some("65536"), Some("glibc-bounded-v1"), None, None];
        assert!(profile_matches(true, correct));
        assert!(!profile_matches(false, correct));
        for index in 0..5 {
            for replacement in [None, Some(""), Some("unexpected")] {
                let mut wrong = correct;
                wrong[index] = replacement;
                assert!(!profile_matches(true, wrong));
            }
        }
        let mut wrong = correct;
        wrong[0] = Some("02");
        assert!(!profile_matches(true, wrong));
        wrong = correct;
        wrong[3] = Some("0");
        assert!(!profile_matches(true, wrong));
    }

    #[test]
    fn allocator_overrides_reject_the_controlled_profile() {
        let correct = [Some("2"), Some("131072"), Some("131072"), Some("65536"), Some("glibc-bounded-v1"), None, None];
        for index in [5, 6] {
            for value in ["glibc.malloc.arena_max=8", "libjemalloc.so", " ", "<non-unicode>"] {
                let mut overridden = correct;
                overridden[index] = Some(value);
                assert!(!profile_matches(true, overridden));
            }
            let mut empty = correct;
            empty[index] = Some("");
            assert!(profile_matches(true, empty));
        }
    }

    #[test]
    fn controlled_overhead_counts_components_without_taxing_large_arrays() {
        let first = calculate_headroom(14_856_895_090, 4_464_992, 95_098_944, 16, true);
        assert_eq!(first.allocator_bytes, 128 * MIB + 14_934_590);
        assert_eq!(first.thread_bytes, 40 * MIB);
        assert_eq!(first.padding_bytes, 40_960);
        assert_eq!(first.transient_bytes, 256 * MIB);
        assert_eq!(first.total_overhead_bytes, 459_571_774);
        assert_eq!(first.profile, "glibc-bounded-v1");
        // Large contiguous array growth is already counted by planned_engine;
        // it must not silently create a second percentage-based charge.
        assert_eq!(first, calculate_headroom(2 * 14_856_895_090, 4_464_992, 95_098_944, 16, true));
    }

    #[test]
    fn legacy_profile_preserves_the_previous_formula() {
        let plan = 14_856_895_090;
        let locks = 95_098_944;
        let headroom = calculate_headroom(plan, 4_464_992, locks, 16, false);
        assert_eq!(headroom.allocator_bytes, (plan + locks) * 15 / 100);
        assert_eq!(headroom.thread_bytes, 0);
        assert_eq!(headroom.padding_bytes, 0);
        assert_eq!(headroom.total_overhead_bytes, 2_242_799_105 + 256 * MIB);
        assert_eq!(headroom.profile, "legacy-15pct-v1");
    }

    #[test]
    fn stacks_and_small_allocations_keep_their_explicit_allowance() {
        let small = calculate_headroom(512 * MIB, 0, 0, 1, true);
        let large = calculate_headroom(512 * MIB, 1000, 2000, 16, true);
        assert_eq!(large.thread_bytes - small.thread_bytes, 15 * THREAD_STACK_BYTES as u64);
        assert_eq!(large.allocator_bytes - small.allocator_bytes, 450);
        assert_eq!(small.thread_bytes, 10 * MIB);
        assert_eq!(small.transient_bytes, TRANSIENT_BYTES);
    }

    #[test]
    fn small_tree_retains_existing_admission_threshold() {
        let before = calculate_headroom(512 * MIB - 1, 1000, 2000, 16, false);
        let after = calculate_headroom(512 * MIB - 1, 1000, 2000, 16, true);
        assert_eq!(after.total_overhead_bytes, before.total_overhead_bytes);
        assert_eq!(after.allocator_bytes, before.allocator_bytes);
        assert_eq!(after.thread_bytes, 0);
        assert_eq!(after.padding_bytes, 0);
        assert_eq!(after.profile, "small-tree-legacy-15pct-v1");
        assert_eq!(calculate_headroom(512 * MIB, 1000, 2000, 16, true).profile, "glibc-bounded-v1");
    }

    #[test]
    fn arithmetic_cannot_wrap_to_a_smaller_allowance() {
        assert_eq!(fifteen_percent(u64::MAX as u128), (u64::MAX as u128 * 15 / 100) as u64);
        assert_eq!(fifteen_percent(u128::MAX), u64::MAX);
        let huge = calculate_headroom(u64::MAX, u64::MAX, u64::MAX, usize::MAX, true);
        assert_eq!(huge.total_overhead_bytes, u64::MAX);
    }
}

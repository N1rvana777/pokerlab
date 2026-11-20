"""Python wrapper for the C hand evaluator via ctypes.

INTERVIEW NOTE — ctypes是什么:
    ctypes是Python的标准库模块，让你能调用C编译出来的DLL/SO文件里的函数。
    不需要任何额外依赖，不需要Cython，不需要写Python C Extension。
    就是: 写C → 编译成DLL → Python加载DLL → 调用函数。

    这是最简单的Python-C互操作方式。在Game Mathematician的工作中，
    你经常需要把性能关键的模拟代码用C#/C++写，然后从Python/Excel调用。

Usage:
    from pokerlab.math.ceval import count_7card_by_rank_c

    # Returns dict mapping HandRank -> count (or None if C lib not compiled)
    counts = count_7card_by_rank_c()
"""

import ctypes
import sys
from pathlib import Path
from pokerlab.math.evaluator import HandRank


def _find_library() -> ctypes.CDLL | None:
    """Try to load the compiled C evaluator library.

    Looks for eval7.dll (Windows) or eval7.so (Linux/Mac) in the csrc/ directory.
    Returns None if not found (C code hasn't been compiled yet).
    """
    # Look relative to this file's location → up to project root → csrc/
    project_root = Path(__file__).parent.parent.parent.parent
    csrc_dir = project_root / "csrc"

    if sys.platform == "win32":
        lib_path = csrc_dir / "eval7.dll"
    else:
        lib_path = csrc_dir / "eval7.so"

    if not lib_path.exists():
        return None

    try:
        return ctypes.CDLL(str(lib_path))
    except OSError:
        return None


def count_7card_by_rank_c() -> dict[HandRank, int] | None:
    """Enumerate all C(52,7) hands using the C extension.

    Returns
    -------
    dict[HandRank, int] or None
        Hand rank counts, or None if C library is not compiled.

    INTERVIEW NOTE:
    ctypes调用步骤:
    1. 加载DLL: ctypes.CDLL("eval7.dll")
    2. 创建C数组: (ctypes.c_longlong * 10)() — 10个long long的数组
    3. 调用C函数: lib.count_all_7card(counts)
    4. 读取结果: counts[0], counts[1], ..., counts[9]
    """
    lib = _find_library()
    if lib is None:
        return None

    # INTERVIEW NOTE:
    # ctypes.c_longlong 对应C的 long long (64位整数)
    # (ctypes.c_longlong * 10)() 创建一个10元素的long long数组，初始化为0
    CountsArray = ctypes.c_longlong * 10
    counts = CountsArray()

    # 设置C函数的参数类型 (可选但推荐，帮助ctypes做类型检查)
    lib.count_all_7card.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
    lib.count_all_7card.restype = None

    # 调用C函数 — 这一行会运行~30秒然后返回
    lib.count_all_7card(counts)

    # 把C数组转换成Python dict
    rank_order = [
        HandRank.HIGH_CARD, HandRank.ONE_PAIR, HandRank.TWO_PAIR,
        HandRank.THREE_OF_A_KIND, HandRank.STRAIGHT, HandRank.FLUSH,
        HandRank.FULL_HOUSE, HandRank.FOUR_OF_A_KIND,
        HandRank.STRAIGHT_FLUSH, HandRank.ROYAL_FLUSH,
    ]
    return {rank: int(counts[rank.value]) for rank in rank_order}


def is_c_available() -> bool:
    """Check if the C evaluator library is compiled and loadable."""
    return _find_library() is not None

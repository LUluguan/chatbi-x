"""评测统计：配对检验与置信区间。

边际准确率的置信区间可能重叠而配对检验显著——配对视角才是正确呈现方式。
"""

import math


def mcnemar_exact_bilateral(b: int, c: int) -> float:
    """McNemar 精确检验（双侧）：两组不一致对计数 b/c，H0 下各占 1/2。

    p = min(1, 2 * Σ_{k≤min(b,c)} C(n,k) / 2^n)，n = b + c。
    """
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1))
    return min(1.0, 2.0 * tail / 2 ** n)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """比例的 95% Wilson 得分区间。"""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))

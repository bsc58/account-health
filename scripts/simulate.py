import math

import numpy as np


def _rs(seed):
    return np.random.RandomState(seed)


def _compound_mdd(returns):
    logp = np.cumsum(np.log1p(np.maximum(returns, -0.999999)), axis=1)
    peak = np.maximum(np.maximum.accumulate(logp, axis=1), 0.0)
    return 1.0 - np.exp(np.min(logp - peak, axis=1))


def normal_mdd(mean, sd, steps, paths, chunk, seed):
    rs = _rs(seed)
    out = np.empty(paths)
    done = 0
    while done < paths:
        size = min(chunk, paths - done)
        out[done:done + size] = _compound_mdd(mean + sd * rs.standard_normal((size, steps)))
        done += size
    return out


def bootstrap_mdd(returns, steps, block, paths, chunk, seed):
    base = np.asarray(returns, dtype=float)
    base = base - base.mean()
    n = len(base)
    blocks = -(-steps // block)
    offsets = np.arange(block)
    rs = _rs(seed)
    out = np.empty(paths)
    done = 0
    while done < paths:
        size = min(chunk, paths - done)
        starts = rs.randint(0, n, size=(size, blocks))
        index = ((starts[:, :, None] + offsets[None, None, :]) % n).reshape(size, -1)[:, :steps]
        out[done:done + size] = _compound_mdd(base[index])
        done += size
    return out


def exceed(mdds, level):
    return float(np.mean(mdds >= level))


def max_compatible(prob_at, grid, floor):
    if prob_at(grid[0]) < floor:
        return None
    lo = 0
    hi = len(grid) - 1
    if prob_at(grid[hi]) >= floor:
        return grid[hi]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if prob_at(grid[mid]) >= floor:
            lo = mid
        else:
            hi = mid
    return grid[lo]


def loss_streaks(win_rate, n, paths, seed):
    rs = _rs(seed)
    best = np.zeros(paths, dtype=np.int64)
    cur = np.zeros(paths, dtype=np.int64)
    for _ in range(n):
        loss = rs.random_sample(paths) >= win_rate
        cur = (cur + 1) * loss
        best = np.maximum(best, cur)
    return best


def money_mdd(pnl):
    cum = np.cumsum(pnl, axis=-1)
    peak = np.maximum(np.maximum.accumulate(cum, axis=-1), 0.0)
    return np.max(peak - cum, axis=-1)


def reshuffle_mdd(pnls, paths, chunk, seed):
    values = np.asarray(pnls, dtype=float)
    n = len(values)
    rs = _rs(seed)
    out = np.empty(paths)
    done = 0
    while done < paths:
        size = min(chunk, paths - done)
        order = np.argsort(rs.random_sample((size, n)), axis=1, kind="stable")
        out[done:done + size] = money_mdd(values[order])
        done += size
    return out


def mean_ci(values, resamples, level, chunk, seed):
    data = np.asarray(values, dtype=float)
    n = len(data)
    center = float(data.mean())
    error = float(data.std(ddof=1)) / math.sqrt(n)
    if error <= 0:
        return center, center
    rs = _rs(seed)
    ratios = np.empty(resamples)
    done = 0
    while done < resamples:
        size = min(chunk, resamples - done)
        draw = data[rs.randint(0, n, size=(size, n))]
        spread = draw.std(axis=1, ddof=1) / math.sqrt(n)
        ratios[done:done + size] = np.divide(draw.mean(axis=1) - center, spread, out=np.zeros(size), where=spread > 0)
        done += size
    tail = (1.0 - level) / 2.0 * 100.0
    return center - float(np.percentile(ratios, 100.0 - tail)) * error, center - float(np.percentile(ratios, tail)) * error

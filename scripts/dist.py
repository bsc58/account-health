import math
import statistics

TINY = 1e-300


def _beta_fraction(a, b, x):
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (d if abs(d) > TINY else TINY)
    h = d
    for m in range(1, 1000):
        even = m * (b - m) * x / ((a - 1.0 + 2 * m) * (a + 2 * m))
        odd = -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 1.0 + 2 * m))
        for term in (even, odd):
            d = 1.0 + term * d
            d = 1.0 / (d if abs(d) > TINY else TINY)
            c = 1.0 + term / c
            c = c if abs(c) > TINY else TINY
            step = d * c
            h *= step
        if abs(step - 1.0) < 1e-15:
            break
    return h


def beta_inc(a, b, x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_fraction(a, b, x) / a
    return 1.0 - front * _beta_fraction(b, a, 1.0 - x) / b


def t_upper(t, df):
    return 0.5 * beta_inc(df / 2.0, 0.5, df / (df + t * t))


def t_upper_quantile(tail, df):
    lo = 0.0
    hi = 1.0
    while t_upper(hi, df) > tail:
        lo = hi
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_upper(mid, df) > tail:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def chi2_quantile(p, df):
    z = statistics.NormalDist().inv_cdf(p)
    spread = 2.0 / (9.0 * df)
    return df * (1.0 - spread + z * math.sqrt(spread)) ** 3


def sd_interval(values, level):
    data = sorted(float(value) for value in values)
    n = len(data)
    z = statistics.NormalDist().inv_cdf(1.0 - (1.0 - level) / 2.0)
    mean = sum(data) / n
    cut = int(n / (2.0 * math.sqrt(n - 4)))
    core = data[cut:n - cut]
    center = sum(core) / len(core)
    squares = sum((value - mean) ** 2 for value in data)
    kurtosis = n * sum((value - center) ** 4 for value in data) / squares ** 2
    scale = n / (n - z)
    error = scale * math.sqrt((kurtosis - (n - 3.0) / n) / (n - 1.0))
    middle = math.log(scale * squares / (n - 1.0))
    return math.sqrt(math.exp(middle - z * error)), math.sqrt(math.exp(middle + z * error))

"""Statistics for a population that is not a sample of independent things.

Endpoints run on a handful of SDKs, platforms and bulk publishers. A rate computed as
though each endpoint were an independent draw overstates its own precision, sometimes
severely: simulation over the shapes this corpus plausibly takes puts the real coverage of a
nominal 95% Wilson interval between 20% and 89% (`scripts/wilson_coverage_under_clustering.py`,
seeded; the range was quoted as 46%-82% here and 45%-82% in R10.4 until 30 July 2026, when the
simulation behind it was written and turned out never to have existed). R10.4 therefore forbids
publishing a naive interval on its own, and R11.2 decides which quantity carries the paper
by asking whether its *cluster-robust* interval shows variance. Both of those need the
arithmetic in this module, so it is written before the data exists rather than after — a
threshold chosen once the numbers are in is not a threshold.

Standard library only, on purpose. The Student-t quantile is implemented here rather than
pulled from SciPy because m is small enough that the difference from a normal quantile
matters, and because an artefact that reproduces on a bare `python:3.11-slim` is worth more
than one that needs a scientific stack.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# --- Student-t ----------------------------------------------------------------


def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betacf(a: float, b: float, x: float, *, max_iter: int = 300, eps: float = 3e-16) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(a * math.log(x) + b * math.log1p(-x) - _log_beta(a, b))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - math.exp(
        b * math.log1p(-x) + a * math.log(x) - _log_beta(b, a)
    ) * _betacf(b, a, 1.0 - x) / b


def student_t_cdf(t: float, df: float) -> float:
    if df <= 0:
        raise ValueError("degrees of freedom must be positive")
    x = df / (df + t * t)
    tail = 0.5 * regularized_incomplete_beta(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def student_t_ppf(p: float, df: float) -> float:
    """Inverse CDF by bisection. Exact enough for interval endpoints and, unlike a table,
    defined for every m the corpus might produce."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    lo, hi = -1e4, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if student_t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --- proportions --------------------------------------------------------------


def wilson_interval(k: float, n: float, conf: float = 0.95) -> tuple[float, float]:
    """The independent-observations interval.

    Reported only alongside a cluster-robust one (R10.4). It is here because the gap
    between the two is itself worth showing: it is the size of the mistake the paper would
    have made by treating endpoints as independent.

    `k` and `n` are counts in every published use. They are typed as floats because
    `cluster_robust_proportion` also evaluates this expression at the *effective* sample
    size, which is not an integer, when a symmetric interval would otherwise be clamped
    onto a boundary the data excludes.
    """
    if n <= 0:
        return (0.0, 0.0)
    z = student_t_ppf(1.0 - (1.0 - conf) / 2.0, 1e6)   # ~ normal quantile
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


#: Floating-point slack for comparisons between two quantities that are equal in exact
#: arithmetic. It is a guard against the last bit and is deliberately far too small to
#: absorb any excess a reader could interpret; the rule it serves is stated in
#: `ProportionEstimate.n_eff_interpretable`.
RELATIVE_EPSILON = 1e-9


@dataclass(frozen=True)
class ProportionEstimate:
    """A rate, with the number of clusters it actually rests on.

    `m` is reported next to every rate because it is the quantity a reviewer needs and the
    one a bare percentage hides: "8% of 1,700 endpoints" and "8% across 12 platforms" are
    different claims, and only the second is honest when a dozen operators produced the
    population.
    """

    k: int
    n: int
    m: int
    p_hat: float
    lo: float
    hi: float
    deff: float | None
    n_eff: float | None
    method: str
    naive_lo: float = 0.0
    naive_hi: float = 0.0
    # Kish's effective cluster size, sum(n_i^2) / sum(n_i). Under the exchangeable model
    # deff = 1 + (kish - 1) * ICC with ICC <= 1, so kish * m/(m-1) is the largest design
    # effect the cluster *sizes* alone can produce. Exceeding it is not an arithmetic
    # error: it means the outcome depends on cluster size, with the large clusters
    # sitting on the minority side of the rate.
    kish: float | None = None
    # Share of the between-cluster sum of squares carried by the single largest
    # contributor, and that contributor's own (successes, total). When one cluster carries
    # most of it the interval is a statement about that cluster, and the number of
    # clusters printed beside it invites the opposite reading.
    top_cluster_variance_share: float | None = None
    top_cluster: tuple[int, int] | None = None
    # The cluster-size distribution itself, which is what a reader has to see before any
    # of the above means anything: largest, the share of observations in the ten largest,
    # the share of clusters holding exactly one, and the coefficient of variation.
    size_profile: dict | None = None

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def size_outcome_ceiling(self) -> float | None:
        """The largest design effect the cluster sizes alone can account for."""
        if self.kish is None or self.m < 2:
            return None
        return self.kish * self.m / (self.m - 1)

    @property
    def n_eff_interpretable(self) -> bool:
        """Whether `n_eff` may be printed as an effective number of observations.

        `n_eff` below `m` is *not* the test, tempting as it looks: a ratio estimator
        weights clusters by size, so a corpus with a few large clusters can genuinely
        carry less information than an equally weighted mean over its m clusters would.
        That case is real and the figure means what it says.

        The test is whether the design effect stays inside `size_outcome_ceiling`. Above
        it the excess comes from the largest clusters sitting on the minority side of the
        rate, not from within-cluster homogeneity, and "as if it were n_eff independent
        observations" is then the wrong sentence to attach to the number -- the width is
        a statement about a handful of named clusters. The interval is unaffected; only
        the gloss on the derived statistic is.
        """
        ceiling = self.size_outcome_ceiling
        if self.deff is None or ceiling is None:
            return True
        # Compared against the ceiling itself, with only a floating-point guard.
        #
        # Until 14 August 2026 this read `<= ceiling * 1.10`, on the reasoning that the
        # identity is exact only for equal cluster sizes so a marginal excess is not
        # evidence of anything. The reasoning is defensible and the constant was still
        # wrong to keep: Section 4.5 states the criterion as a bright line and reports the
        # count of intervals failing it as machine-derived, so a free parameter no reader
        # could see was setting that count. It was setting it here too. C05 at the endpoint
        # unit sits at 10.71 against a ceiling of 10.62 and went unflagged for that reason
        # alone, while one cluster carries 57% of its between-cluster sum of squares, which
        # is the condition the flag exists to announce.
        #
        # The guard that remains is numerical and nothing else. Where the cluster is the
        # unit, DEFF and the ceiling are the same quantity -- both reduce to m / (m - 1) --
        # and they agree to about fifteen digits rather than exactly, so a bare `<=` flags
        # or spares those rows by the accident of the last bit. It did: of the eight rows a
        # zero-tolerance rule marked, five were collapsed-unit rows agreeing to four decimal
        # places, and two otherwise identical rows fell on opposite sides. RELATIVE_EPSILON
        # is far below any excess that could carry meaning and far above float noise.
        return self.deff <= ceiling * (1.0 + RELATIVE_EPSILON)

    def as_record(self) -> dict:
        return {
            "k": self.k, "n": self.n, "m": self.m,
            "p_hat": self.p_hat, "ci_lo": self.lo, "ci_hi": self.hi,
            "deff": self.deff, "n_eff": self.n_eff, "method": self.method,
            "naive_ci_lo": self.naive_lo, "naive_ci_hi": self.naive_hi,
            "kish": self.kish,
            "size_outcome_ceiling": self.size_outcome_ceiling,
            "top_cluster_variance_share": self.top_cluster_variance_share,
            "top_cluster": list(self.top_cluster) if self.top_cluster else None,
            "size_profile": self.size_profile,
            "n_eff_interpretable": self.n_eff_interpretable,
        }


def cluster_robust_proportion(
    clusters: list[tuple[int, int]], conf: float = 0.95
) -> ProportionEstimate:
    """Proportion with a cluster-robust interval, t(m-1)-based per R10.4.

    `clusters` is one (successes, total) pair per cluster. The estimator is the linearised
    variance of a ratio over clusters,

        V_cl = m / ((m - 1) * N^2) * sum_i (k_i - p_hat * n_i)^2,   N = sum_i n_i

    against the simple-random-sample variance V_srs = p(1 - p) / N, with

        DEFF = V_cl / V_srs,    n_eff = N / DEFF.

    The t quantile rather than z is not pedantry: with a dozen platforms the difference is
    the difference between an interval that covers and one that does not.

    Note that clustering does not only widen. When the property is spread evenly across
    clusters the design effect falls below 1 and the interval is *narrower* than the naive
    one. That is why this is a measurement rather than a safety margin.

    Two properties of the ratio are reported alongside it because reading DEFF without
    them is what produced a published "effective sample size" of 123 over 1,814 clusters.
    `kish` is sum(n_i^2) / N, the largest design effect the cluster sizes can generate,
    since DEFF = 1 + (kish - 1) * ICC and ICC <= 1. `top_cluster_variance_share` is how
    much of the sum of squares the single largest contributor carries. When DEFF exceeds
    `kish` the ratio is describing one dominant cluster rather than within-cluster
    homogeneity, `n_eff_interpretable` is False, and n_eff must not be printed as a
    sample size. The interval itself stands: one apex declaring eighty issuers really can
    move a rate, and saying so is the correction's whole purpose.
    """
    m = len(clusters)
    total = sum(n for _, n in clusters)
    successes = sum(k for k, _ in clusters)
    if total == 0:
        return ProportionEstimate(0, 0, m, 0.0, 0.0, 0.0, None, None, "empty")
    p_hat = successes / total
    naive = wilson_interval(successes, total, conf)
    kish = sum(n * n for _, n in clusters) / total
    sizes = sorted((n for _, n in clusters), reverse=True)
    mean_size = total / m
    size_profile = {
        "max": sizes[0],
        "top10_share": sum(sizes[:10]) / total,
        "singleton_share": sum(1 for x in sizes if x == 1) / m,
        "cv": (math.sqrt(sum((x - mean_size) ** 2 for x in sizes) / m) / mean_size
               if mean_size else 0.0),
    }

    if m < 2:
        return ProportionEstimate(
            successes, total, m, p_hat, naive[0], naive[1], None, None,
            "wilson (single cluster: no between-cluster variance to estimate)",
            naive[0], naive[1], kish, 1.0, clusters[0] if clusters else None,
            size_profile,
        )

    contributions = [(k - p_hat * n) ** 2 for k, n in clusters]
    ssq = sum(contributions)
    top_share: float | None = None
    top_cluster: tuple[int, int] | None = None
    if ssq > 0:
        worst = max(range(m), key=contributions.__getitem__)
        top_share = contributions[worst] / ssq
        top_cluster = clusters[worst]
    var = m / ((m - 1) * total**2) * ssq
    simple_var = p_hat * (1 - p_hat) / total

    # The between-cluster estimator sees only how much clusters differ from each other.
    # When they agree it reports almost no uncertainty at all -- which is wrong, because
    # sampling variation inside each cluster has not gone anywhere. Measured on synthetic
    # inputs it produced n_eff up to 313x the number of observations, and an interval of
    # [49.7%, 50.1%] on 1000 observations. An earlier exact `var == 0.0` guard did not help:
    # moving one endpoint made the variance merely tiny rather than zero, and the guard
    # stopped firing while the interval stayed absurd.
    #
    # So the simple-random-sample variance is a floor. Clustering may widen an interval and
    # it may reveal that the effective sample is smaller than it looks; what it may not do
    # is manufacture precision that no sample of this size could have. `deff` and `n_eff`
    # keep reporting the raw ratio, because a design effect below 1 is a real and
    # interesting property -- it just does not get to narrow the published interval.
    floored = var < simple_var
    var_published = max(var, simple_var)

    se = math.sqrt(var_published)
    t = student_t_ppf(1.0 - (1.0 - conf) / 2.0, m - 1)
    lo, hi = max(0.0, p_hat - t * se), min(1.0, p_hat + t * se)

    deff = var / simple_var if simple_var > 0 else None
    n_eff = total / deff if deff is not None and deff > 0 else None
    method = f"cluster-robust t({m - 1})"
    if floored:
        method += " (floored at the simple-random-sample variance)"

    # A symmetric interval around a proportion near a boundary is clamped into [0, 1]
    # afterwards, and the clamp then prints a bound the data excludes: nine successes in
    # 202 observations were published as "[0.0%, 9.0%]", which asserts that none of them
    # may have happened. Where the clamp binds and the count is neither 0 nor n, the
    # published interval becomes Wilson evaluated at the effective sample size -- which is
    # boundary-respecting by construction and still carries the clustering correction,
    # rather than dropping it to rescue the bound. The substitution is recorded in
    # `method` so a reader can see which figures it touched.
    if (lo == 0.0 or hi == 1.0) and 0 < successes < total and deff and deff > 0:
        # Not rounded to integers: with a large design effect the effective successes can
        # fall below 0.5, and rounding them to zero would hand back the very bound this
        # replaces. Wilson's expression is continuous in both arguments.
        #
        # The divisor is floored at one for the same reason the variance is. A design
        # effect below one means the clustering happens to have produced a spread narrower
        # than simple random sampling would, and dividing by it would evaluate Wilson at
        # *more* observations than were collected -- manufacturing precision no sample of
        # this size could have, which is exactly what the floor above exists to forbid. The
        # published `deff` still reports the raw ratio; only the substitution is floored.
        lo, hi = wilson_interval(successes / max(deff, 1.0), total / max(deff, 1.0), conf)
        method += "; boundary-respecting Wilson at the effective sample size"

    return ProportionEstimate(
        successes, total, m, p_hat, lo, hi, deff, n_eff, method, naive[0], naive[1],
        kish, top_share, top_cluster, size_profile,
    )


def wild_cluster_bootstrap_ci(
    clusters: list[tuple[int, int]],
    conf: float = 0.95,
    reps: int = 2000,
    seed: int = 20260728,
) -> tuple[float, float]:
    """Rademacher wild cluster bootstrap-t, for m < 30 where even t(m-1) is optimistic.

    Seeded by default so a published interval can be reproduced exactly; the seed is the
    freeze date, chosen before any data existed so it cannot have been picked for its
    output.
    """
    m = len(clusters)
    if m < 2:
        return wilson_interval(sum(k for k, _ in clusters), sum(n for _, n in clusters), conf)
    total = sum(n for _, n in clusters)
    p_hat = sum(k for k, _ in clusters) / total
    residuals = [k - p_hat * n for k, n in clusters]

    rng = random.Random(seed)
    stats: list[float] = []
    for _ in range(reps):
        weights = [1.0 if rng.random() < 0.5 else -1.0 for _ in range(m)]
        boot = [
            p_hat * n + w * r
            for (_, n), w, r in zip(clusters, weights, residuals, strict=True)
        ]
        boot_p = sum(boot) / total
        ssq = sum((b - boot_p * n) ** 2 for b, (_, n) in zip(boot, clusters, strict=True))
        var = m / ((m - 1) * total**2) * ssq
        se = math.sqrt(var)
        stats.append((boot_p - p_hat) / se if se > 0 else 0.0)

    stats.sort()
    alpha = (1.0 - conf) / 2.0
    lo_q = stats[max(0, int(alpha * reps) - 1)]
    hi_q = stats[min(reps - 1, int((1.0 - alpha) * reps))]
    base = cluster_robust_proportion(clusters, conf)
    se_hat = (base.hi - base.p_hat) / student_t_ppf(1.0 - alpha, m - 1) if m > 1 else 0.0
    lo, hi = max(0.0, p_hat - hi_q * se_hat), min(1.0, p_hat - lo_q * se_hat)
    if hi - lo <= 0.0:
        # Degenerate: every bootstrap replicate landed on the point estimate, which happens
        # near p=0 and p=1 and whenever the clusters are near-identical. A zero-width
        # interval is not a precise answer, it is the absence of one — and R11.2 reads
        # these bounds to pick the paper's headline, so it must never be handed a point.
        return wilson_interval(base.k, base.n, conf)
    return (lo, hi)


# --- R10.1: the same rate in three units ---------------------------------------

UNITS = ("endpoint", "apex", "implementation")


def _cluster_key(report, unit: str) -> str:
    if unit == "endpoint":
        return report.endpoint.endpoint_id
    if unit == "apex":
        return report.endpoint.apex_domain or f"?{report.endpoint.endpoint_id}"
    if unit == "implementation":
        return (report.evidence or {}).get("implementation_fingerprint") \
            or f"?{report.endpoint.endpoint_id}"
    raise ValueError(f"unknown unit: {unit}")


def _collapse_to_one_per(reports: list, unit: str) -> list:
    """One report per apex or per implementation, picked deterministically.

    R10.1 asks for the rate computed with the apex as the unit, not merely for endpoints
    grouped by apex: a bulk publisher with three hundred listings would otherwise still set
    the point estimate, and only the interval would notice. Which of an apex's endpoints
    represents it has to be fixed in advance, so it is the lowest endpoint id — an
    arbitrary rule, but arbitrary and declared beats defensible and chosen afterwards.
    """
    chosen: dict[str, object] = {}
    for report in sorted(reports, key=lambda r: r.endpoint.endpoint_id):
        chosen.setdefault(_cluster_key(report, unit), report)
    return list(chosen.values())


#: The only two answers that are an authorization challenge. RFC 9728 3.1 hangs the
#: metadata requirement on the challenge, so this is the population C05's specification
#: sentence actually addresses.
CHALLENGE_STATUSES = (401, 403)


def challenged(report) -> bool:
    """Did this endpoint answer with an authorization challenge?

    Kept separate from `OAuthEvidence.requires_authorization` on purpose: that field is
    set during scoring and is not what a reader can check, whereas the first response's
    status code is in every stored report and in every raw artefact.
    """
    return report.http_status in CHALLENGE_STATUSES


def rate_by_unit(reports: list, check_id, unit: str, conf: float = 0.95,
                 challenged_only: bool = False) -> ProportionEstimate:
    """One check's pass rate with `unit` as the unit of analysis.

    The denominator follows the funnel rules rather than counting every report. Four
    populations leave it, and all four left the funnel's denominator already; until 6 August
    2026 only the first two left this one, so the two tables the manuscript prints side by
    side were computed under different rules and disagreed by 21 endpoints on C05, 196 on C12
    and 717 on C13. Two external reviews read that disagreement as the study contradicting
    itself, which is the correct reading of it.

    An endpoint the check does not apply to (NOT_APPLICABLE) leaves, because carrying it
    counts composition as non-conformance. One that could not be observed (ERROR) leaves,
    because an access block is not a conformance observation. One the access policy declined
    to ask -- excluded by robots.txt, by the opt-out list, or because a redirect carried the
    request to another origin -- leaves, because retaining it publishes our own politeness
    policy as a property of the ecosystem. And UNSPECIFIED leaves, because the outcome
    records the instrument declining to score, and Section 4.3 undertakes that instrument
    uncertainty is not scored against an operator; a denominator that keeps it does exactly
    that. What keeping it would cost is not hidden: the C12 sensitivity pair puts it back.

    For the endpoint unit every endpoint is an observation and the interval is clustered by
    apex, so the point estimate is the raw rate while the interval knows the endpoints are
    not independent. For the apex and implementation units the population is collapsed
    first, which moves the point estimate too — and the gap between the two is the finding
    a single number would hide.

    `challenged_only` narrows the population to endpoints that answered 401 or 403. It
    exists because the rules above do not produce the denominator the manuscript claimed
    for C05. An endpoint that never challenged and published nothing leaves as
    NOT_APPLICABLE, but one that never challenged and *did* publish is scored, so the
    denominator is "challenged **or** published" — which is the widening Section 6.1 said
    it had avoided, and it is circular in the direction that flatters the study, since the
    only way in without a challenge is by satisfying the numerator. Found on 14 August 2026
    by a referee who ran the instrument rather than reading it; 1,375 of C05's 2,976
    endpoints, 46.2%, had not challenged. Both populations are now reported, this one as
    the primary and the wider one as a declared sensitivity arm.
    """
    from .models import Outcome

    applicable = [
        r for r in reports
        if r.robots_allowed and not r.opted_out and not r.crossed_origin()
        and (not challenged_only or challenged(r))
        and (o := r.outcome_of(check_id)) is not None
        and o not in (Outcome.NOT_APPLICABLE, Outcome.ERROR, Outcome.UNSPECIFIED)
    ]
    if unit == "endpoint":
        population, cluster_by = applicable, "apex"
    else:
        population, cluster_by = _collapse_to_one_per(applicable, unit), "endpoint"

    buckets: dict[str, list[int]] = {}
    for report in population:
        bucket = buckets.setdefault(_cluster_key(report, cluster_by), [0, 0])
        bucket[1] += 1
        if report.outcome_of(check_id) is Outcome.PASS:
            bucket[0] += 1
    return cluster_robust_proportion([(k, n) for k, n in buckets.values()], conf)


def denominator_composition(reports: list, check_id) -> dict:
    """What a check's denominator is actually made of, by first-response status.

    A rate is only as honest as the population under it, and for C05 the two were not the
    same thing: the manuscript described the denominator as endpoints that answered an
    authorization challenge and it was not that. Printing the composition is the cheapest
    guard against the same class of error, because a reader can see the population instead
    of taking its description on trust.

    Returns the whole denominator, the challenging and non-challenging halves, and a
    per-status breakdown, each with its own pass count.
    """
    from .models import Outcome

    applicable = [
        r for r in reports
        if r.robots_allowed and not r.opted_out and not r.crossed_origin()
        and (o := r.outcome_of(check_id)) is not None
        and o not in (Outcome.NOT_APPLICABLE, Outcome.ERROR, Outcome.UNSPECIFIED)
    ]
    by_status: dict[str, list[int]] = {}
    for report in applicable:
        bucket = by_status.setdefault(str(report.http_status), [0, 0])
        bucket[1] += 1
        if report.outcome_of(check_id) is Outcome.PASS:
            bucket[0] += 1

    def half(predicate) -> dict:
        rows = [r for r in applicable if predicate(r)]
        k = sum(1 for r in rows if r.outcome_of(check_id) is Outcome.PASS)
        return {"n": len(rows), "k": k, "rate": (k / len(rows)) if rows else None}

    total = half(lambda r: True)
    return {
        "total": total,
        "challenged": half(challenged),
        "not_challenged": half(lambda r: not challenged(r)),
        "by_status": {s: {"n": n, "k": k, "rate": k / n}
                      for s, (k, n) in sorted(by_status.items(),
                                              key=lambda kv: -kv[1][1])},
        # How much of the denominator is there without having answered a challenge. The
        # manuscript's description of the population is only true when this is zero.
        "not_challenged_share": (total["n"] - half(challenged)["n"]) / total["n"]
        if total["n"] else None,
    }


def challenge_share(reports: list, check_id) -> dict:
    """How many endpoints in a check's arm answered an authorization challenge.

    Separate from `denominator_composition` because the base is different: this counts
    over every endpoint the arm reached, not over the check's denominator. Section 6.1
    presented C05's denominator, 33.5% of the corpus, as the endpoints that "opted into
    authorization at all"; the share that actually challenged is this number, and the
    Zhou et al. comparison bracket was built on the first where it meant the second.
    """
    arm = [r for r in reports if r.outcome_of(check_id) is not None]
    n_challenged = sum(1 for r in arm if challenged(r))
    return {
        "arm": len(arm),
        "challenged": n_challenged,
        "share": (n_challenged / len(arm)) if arm else None,
    }


def sampling_bias(reports: list, check_id, not_sampled_by_host: dict[str, int],
                  cap: int) -> dict:
    """What the per-host cap costs the endpoint-unit rate, measured rather than asserted.

    Section 9.6 claimed the sampling bias has "a known sign" and gave no number, in a
    sentence whose own reasoning said the opposite -- an uncapped rate would be pulled
    toward "whatever a handful of large platforms happen to do" is a statement that the
    direction depends on facts nobody had looked up. They are lookable-up: the endpoints
    measured on a capped host are a deterministic selection by identifier, so under the
    assumption that they are exchangeable with their host's unmeasured remainder, each one
    stands for `frame / measured` of that host and the uncapped rate can be estimated.

    The assumption is the whole of what this rests on and it is not testable from inside a
    capped host, since the remainder was never asked. It is stated in the manuscript beside
    the number.
    """
    from urllib.parse import urlsplit

    from .models import Outcome

    applicable = [
        r for r in reports
        if r.robots_allowed and not r.opted_out and not r.crossed_origin()
        and (o := r.outcome_of(check_id)) is not None
        and o not in (Outcome.NOT_APPLICABLE, Outcome.ERROR, Outcome.UNSPECIFIED)
    ]
    measured: dict[str, list[int]] = {}
    for report in applicable:
        host = urlsplit(report.endpoint.url).hostname or ""
        bucket = measured.setdefault(host, [0, 0])
        bucket[1] += 1
        if report.outcome_of(check_id) is Outcome.PASS:
            bucket[0] += 1

    published_k = sum(k for k, _ in measured.values())
    published_n = sum(n for _, n in measured.values())
    weighted_k = weighted_n = 0.0
    capped_k = capped_n = 0
    for host, (k, n) in measured.items():
        dropped = not_sampled_by_host.get(host, 0)
        # The frame holds the endpoints the cap admitted plus the ones it dropped. Only
        # those admitted and applicable are in `n`, so the weight is per applicable
        # observation rather than per admitted one.
        weight = (cap + dropped) / cap if dropped else 1.0
        weighted_k += k * weight
        weighted_n += n * weight
        if dropped:
            capped_k += k
            capped_n += n

    uncapped_k = published_k - capped_k
    uncapped_n = published_n - capped_n
    return {
        "published_rate": published_k / published_n if published_n else None,
        "reweighted_rate": weighted_k / weighted_n if weighted_n else None,
        "capped_rate": capped_k / capped_n if capped_n else None,
        "uncapped_rate": uncapped_k / uncapped_n if uncapped_n else None,
        "capped_n": capped_n,
        "uncapped_n": uncapped_n,
        "capped_hosts_measured": sum(1 for h in measured if not_sampled_by_host.get(h)),
    }


def three_unit_table(reports: list, check_id, conf: float = 0.95,
                     challenged_only: bool = False) -> dict[str, dict]:
    """R10.1: no rate is published as a single number.

    "8% of 1,700 endpoints" and "8% across 34 implementations" are different claims, and a
    reviewer cannot tell which one the study is entitled to make unless both are on the
    page. Most of the objection that endpoints are not independent is answered by this
    table alone, without any modelling.
    """
    return {unit: rate_by_unit(reports, check_id, unit, conf, challenged_only).as_record()
            for unit in UNITS}


# --- the declared trust graph (R11.1 candidate 3) ------------------------------


def _apex(host_or_url: str) -> str | None:
    from .collectors import apex_domain
    return apex_domain(host_or_url)


@dataclass(frozen=True)
class DelegationGraph:
    """The resource -> issuer edges an endpoint population declares.

    This is the one candidate in R11.1 that is not a rate, so R11.2's variance test does
    not apply to it and it survives whatever the other numbers turn out to be. It is
    therefore both the fallback headline and the figure that gets drawn either way.
    """

    edges: list[tuple[str, str]]                  # (resource apex, issuer)
    issuer_counts: dict[str, int]
    cross_operator: int
    same_operator: int
    unknown_operator: int
    # Issuer URLs named identically by two or more distinct resource apexes. Descriptive:
    # see the note in build_delegation_graph.
    shared_across_apexes: list[str]

    @property
    def total(self) -> int:
        return self.cross_operator + self.same_operator + self.unknown_operator

    def concentration(self) -> dict:
        """How much of the ecosystem's trust rests on how few issuers.

        HHI and top-k share, computed over issuers weighted by the resources naming them.
        A handful of issuers carrying most of the population is a systemic property of the
        agent web, not a defect of any operator — which is exactly why it can be reported
        without accusing anybody.
        """
        # top-10 as well as 1, 3 and 5, because the results section asks for it by name and
        # nothing computed it. A promised quantity with no producer is the same defect as a
        # check with no code path: the draft reads as though the number exists, and the gap
        # only surfaces when somebody tries to print it. Found on 5 August 2026 while wiring
        # the manuscript's markers to the run, which is the first time anything had.
        total = sum(self.issuer_counts.values())
        if total == 0:
            return {"issuers": 0, "hhi": None, "top1_share": None, "top3_share": None,
                    "top5_share": None, "top10_share": None, "effective_issuers": None}
        shares = sorted((c / total for c in self.issuer_counts.values()), reverse=True)
        hhi = sum(s * s for s in shares)
        return {
            "issuers": len(self.issuer_counts),
            "hhi": hhi,
            "top1_share": sum(shares[:1]),
            "top3_share": sum(shares[:3]),
            "top5_share": sum(shares[:5]),
            "top10_share": sum(shares[:10]),
            "effective_issuers": 1.0 / hhi if hhi > 0 else None,
        }

    def cross_operator_clusters(self) -> list[tuple[int, int]]:
        """Cross-operator delegation as (successes, total) per resource apex, so the rate
        gets the same cluster-robust treatment as every other rate (R10.4)."""
        buckets: dict[str, list[int]] = {}
        for resource_apex, issuer in self.edges:
            bucket = buckets.setdefault(resource_apex, [0, 0])
            bucket[1] += 1
            issuer_apex = _apex(issuer)
            if issuer_apex is not None and issuer_apex != resource_apex:
                bucket[0] += 1
        return [(k, n) for k, n in buckets.values()]


def build_delegation_graph(reports: list) -> DelegationGraph:
    """Read the declared edges out of stored evidence. No network, no re-scoring.

    "Cross-operator" is decided by apex domain, the primary unit under R10.2, and the
    known bias is recorded rather than corrected: the public suffix list's private section
    is off, so two tenants of one platform share an apex and a delegation between them
    reads as same-operator. That direction under-counts the finding, which is the safe way
    to be wrong.
    """
    edges: list[tuple[str, str]] = []
    issuer_counts: dict[str, int] = {}
    cross = same = unknown = 0
    multi_tenant: list[str] = []

    for report in reports:
        evidence = report.evidence or {}
        resource_apex = report.endpoint.apex_domain
        for issuer in evidence.get("authorization_servers") or []:
            if not isinstance(issuer, str):
                continue
            issuer_counts[issuer] = issuer_counts.get(issuer, 0) + 1
            if resource_apex is None:
                unknown += 1
                continue
            edges.append((resource_apex, issuer))
            issuer_apex = _apex(issuer)
            if issuer_apex is None:
                unknown += 1
            elif issuer_apex == resource_apex:
                same += 1
            else:
                cross += 1

    # An *identical* issuer URL named by resources under several different apexes contains,
    # by construction, nothing that distinguishes those resources from one another: whatever
    # subdomain or path it carries is the same for all of them. That is the configuration
    # RFC 9728 7.6's adversary-in-the-middle warning describes, and it is observable without
    # guessing which URL components are "tenant" components — a guess that would be the
    # authors' rubric and would also be wrong, since `shared.idp.example` has a subdomain
    # that separates nothing. The signal is in the sharing, not in the URL's shape.
    #
    # This is descriptive, not an accusation: one operator may legitimately serve several
    # apexes from one issuer. The report says how many apexes share each issuer and lets
    # that be read, rather than asserting the apexes are unrelated.
    by_issuer: dict[str, set[str]] = {}
    for resource_apex, issuer in edges:
        by_issuer.setdefault(issuer, set()).add(resource_apex)
    multi_tenant = [issuer for issuer, apexes in by_issuer.items() if len(apexes) >= 2]

    return DelegationGraph(
        edges=edges,
        issuer_counts=issuer_counts,
        cross_operator=cross,
        same_operator=same,
        unknown_operator=unknown,
        shared_across_apexes=sorted(multi_tenant),
    )


def fisher_exact_2x2(a: int, b: int, c: int, d: int) -> dict:
    """Two-sided Fisher's exact test for [[a, b], [c, d]].

    Written out rather than imported because this module is stdlib-only by design, and a
    2x2 exact test is a sum over one hypergeometric row.

    It exists because Section 6.5 asserted a contrast it had never tested. All 12 issuers
    publishing the protected-resources field sit outside the crossing population and none
    inside it, and the manuscript read that as the two populations partitioning. With 12
    positives spread over about two thousand issuers, a crossing subset of two hundred
    containing none of them is roughly what independence predicts, so the partition was
    evidence of the base rate rather than of any association. The level -- the mitigation is
    close to absent everywhere -- survives; the contrast does not.
    """
    from math import comb

    row1, row2 = a + b, c + d
    col1 = a + c
    total = row1 + row2
    if not row1 or not row2 or not col1 or not (b + d):
        return {"a": a, "b": b, "c": c, "d": d, "p_value": None,
                "method": "undefined: a margin is empty"}

    def prob(k: int) -> float:
        return comb(row1, k) * comb(row2, col1 - k) / comb(total, col1)

    observed = prob(a)
    # Floating point makes equally extreme tables compare unequal, which would drop the
    # mirror-image table out of the tail and halve the p-value.
    tolerance = observed * (1 + 1e-9)
    p = sum(prob(k) for k in range(max(0, col1 - row2), min(row1, col1) + 1)
            if prob(k) <= tolerance)
    return {
        "a": a, "b": b, "c": c, "d": d,
        "p_value": min(1.0, p),
        "rate_row1": a / row1,
        "rate_row2": c / row2,
        "method": "two-sided Fisher exact, hypergeometric point probabilities",
    }


def cross_check_feasibility(reports: list) -> dict:
    """R11.1 candidate 2: how often RFC 9728 §7.6's own mitigation is available.

    §7.6 recommends cross-checking the resource's issuer list against the issuer's resource
    list. §4 defines `protected_resources` so that the second list can exist, and makes it
    OPTIONAL. Whether anyone publishes it is the empirical question, and it separates into
    two: whether the check is *possible*, and whether it *passes*.
    """
    possible = passes = total_issuers = 0
    issuers_seen: set[str] = set()
    for report in reports:
        evidence = report.evidence or {}
        declared_resource = evidence.get("declared_resource")
        for issuer, doc in (evidence.get("as_documents") or {}).items():
            if issuer in issuers_seen:
                continue
            issuers_seen.add(issuer)
            total_issuers += 1
            listed = doc.get("protected_resources") if isinstance(doc, dict) else None
            if not isinstance(listed, list):
                continue
            possible += 1
            if declared_resource and any(
                isinstance(r, str) and _relation_identical(r, declared_resource) for r in listed
            ):
                passes += 1
    return {
        "issuers": total_issuers,
        "cross_check_possible": possible,
        "cross_check_passes": passes,
    }


def _relation_identical(a: str, b: str) -> bool:
    from .checks_oauth import _relation
    return _relation(a, b) == "identical"


# --- R11.2 --------------------------------------------------------------------

VARIANCE_FLOOR = 0.02
VARIANCE_CEILING = 0.98

# The widest cluster-robust interval a quantity may carry and still lead the paper.
#
# Fixed at ten points before any data existed, and the number is not arbitrary: the issuer
# candidates are clustered on identity *products*, and at perfect intra-cluster correlation
# -- the realistic case, since `iss` support is a property of the product rather than the
# tenant -- +/-10pp needs about a hundred independent clusters. If the ecosystem turns out
# to rest on a dozen IdPs, no issuer-level rate can be a headline, and the paper should say
# that rather than publish +/-30pp as a finding. Declaring the threshold now is what makes
# that outcome a result instead of a disappointment.
MAX_HEADLINE_HALF_WIDTH = 0.10


@dataclass
class VarianceTest:
    passed: bool
    reason: str
    estimate: ProportionEstimate = field(repr=False, default=None)  # type: ignore[assignment]


def passes_variance_test(estimate: ProportionEstimate) -> VarianceTest:
    """Decision rule R11.2, as amended on 29 July 2026 before any data existed.

    A candidate cannot be the paper's headline if it is "essentially nobody" or
    "essentially everybody" -- both are one-sentence findings -- or if it is too imprecise
    to be a headline at all. Applied to the cluster-robust interval, never the naive one,
    because the naive one is too narrow to fail the test honestly.

    The precision gate and the point-estimate check were added after the rule was measured
    against its own code and found to do almost nothing. Two results, both real:

        m=60, k=59 -> 98.3% [95.0, 100.0] -> passed
        m=15, k=8  -> 53.3% [24.7,  81.9] -> passed

    The first is "essentially everybody" and the rule was written to reject it; it survived
    because the interval reaches below the ceiling even though the estimate does not. The
    second is an interval 57 points wide, which cannot lead a paper. Worse, the original
    form was anti-conservative by construction: a *wider* interval escapes both bands more
    easily, so imprecision made a candidate more likely to be chosen. A selection rule that
    rewards not knowing is worse than no rule, because it launders the choice.
    """
    if estimate.n == 0:
        return VarianceTest(False, "no observations", estimate)
    half_width = (estimate.hi - estimate.lo) / 2
    if half_width > MAX_HEADLINE_HALF_WIDTH:
        return VarianceTest(
            False, f"interval [{estimate.lo:.3f}, {estimate.hi:.3f}] is +/-{half_width:.1%}, "
                   f"wider than the +/-{MAX_HEADLINE_HALF_WIDTH:.0%} a headline may carry "
                   f"(m={estimate.m})", estimate)
    if estimate.hi <= VARIANCE_FLOOR or estimate.p_hat <= VARIANCE_FLOOR:
        return VarianceTest(
            False, f"{estimate.p_hat:.1%} [{estimate.lo:.3f}, {estimate.hi:.3f}] is at or "
                   f"below {VARIANCE_FLOOR:.0%}: essentially nobody", estimate)
    if estimate.lo >= VARIANCE_CEILING or estimate.p_hat >= VARIANCE_CEILING:
        return VarianceTest(
            False, f"{estimate.p_hat:.1%} [{estimate.lo:.3f}, {estimate.hi:.3f}] is at or "
                   f"above {VARIANCE_CEILING:.0%}: essentially everybody", estimate)
    return VarianceTest(
        True, f"{estimate.p_hat:.1%} [{estimate.lo:.3f}, {estimate.hi:.3f}] is informative at "
              f"publishable precision (+/-{half_width:.1%}, m={estimate.m})", estimate)


def select_headline(candidates: list[tuple[str, ProportionEstimate]]) -> tuple[str, str]:
    """R11.2: the highest-ranked candidate that passes the variance test.

    `candidates` must already be in the order frozen in decision-rules.md R11.1; this
    function deliberately does not sort, so it cannot reorder them by how good they look.
    """
    for name, estimate in candidates:
        verdict = passes_variance_test(estimate)
        if verdict.passed:
            return name, verdict.reason
    return (
        "ecosystem topology (fallback)",
        "no rate candidate was informative; the topology result is not a rate and the rule "
        "therefore does not apply to it",
    )


# --- the issuer as a unit of analysis (R11.5) ----------------------------------
#
# R11.5 fixes the unit for headline candidates 1, 2 and 5 as the *unique issuer*, and
# nothing here could express that until 29 July 2026: `rate_by_unit` reads a check outcome
# off an endpoint report, and `_cluster_key` raises on any unit but endpoint/apex/
# implementation. So the rule that selects the paper's headline -- and through R11.4 its
# title -- had no implementation, while three status rounds recorded this layer as
# finished. `select_headline` above had no caller anywhere in `src/`.
#
# The issuer level is built separately rather than forced through the report-shaped code,
# because an issuer is not an endpoint: several endpoints declare the same issuer, one
# endpoint declares several, and the observation lives in stored evidence rather than in a
# CheckResult. Pretending otherwise would have produced a number that looked like R11.5
# and was not.


def issuer_documents(reports: list, denominator: str) -> dict[str, dict | None]:
    """Every unique issuer in the population, mapped to its metadata document or None.

    `denominator` is R11.5's choice and it is not cosmetic:

    * ``"declared"`` -- every issuer any resource named **and that we requested**. An issuer
      that was asked and never answered maps to None and counts against the rate, because a
      client cannot use a defence it cannot reach. This is the denominator for C16 and C17.
    * ``"observed"`` -- only issuers whose document was retrieved. This is the denominator
      for C18, where the question is what a reachable issuer chose to publish.

    Both are computed for every candidate as the pre-declared sensitivity pair (R9.5), so
    the choice above decides which one is the headline, not which one exists.

    **Issuers in `as_not_fetched` leave both denominators (defect D8, fixed 30 July 2026).**
    That field records issuers we declined to request -- not a public HTTPS host, or past the
    ten-per-endpoint request cap -- and this function did not read it, so an issuer we never
    contacted arrived here as `None` and was scored as "does not advertise". The rate that
    absorbed it is C16, which R11.1 ranks as the *first* headline candidate: our own scope
    policy was pushing the paper's leading number downward, and the harder we throttled the
    worse the ecosystem would have looked. The identical defect was found and fixed inside
    `checks_oauth.py` on 29 July for the per-endpoint verdict; the analysis layer, which
    computes the number that actually gets published, was not fixed with it. We cannot report
    on what we declined to ask.
    """
    if denominator not in ("declared", "observed"):
        raise ValueError(f"unknown denominator: {denominator}")

    documents: dict[str, dict | None] = {}
    withheld: set[str] = set()
    for report in reports:
        evidence = report.evidence or {}
        for issuer in (evidence.get("as_not_fetched") or {}):
            if isinstance(issuer, str):
                withheld.add(issuer)

    for report in reports:
        evidence = report.evidence or {}
        as_documents = evidence.get("as_documents") or {}
        for issuer in evidence.get("authorization_servers") or []:
            if not isinstance(issuer, str):
                continue
            doc = as_documents.get(issuer)
            # Withheld by our own policy for *every* endpoint that named it. An issuer one
            # resource declared past the cap and another declared inside it was still
            # observed, so it stays: the two loops are separate because the exclusion is a
            # property of the issuer across the corpus, not of one declaration.
            if issuer in withheld and not isinstance(doc, dict):
                continue
            if doc is None and denominator == "observed":
                continue
            # First document wins, deterministically: the same issuer serves the same
            # document to every resource that names it, and if it does not, that is a
            # finding for the topology rather than a reason to count the issuer twice.
            documents.setdefault(issuer, doc if isinstance(doc, dict) else None)
    return documents


def manski_bounds(p_hat: float, unobserved: int, observed: int) -> tuple[float, float]:
    """Worst-case identified set for a rate measured on only part of its population.

    Section 9.2 bounds the study's principal threat to validity rather than assuming it away.
    Blocking is not independent of what is being measured -- mature deployments are the ones
    behind a WAF -- so R4's decision to send every access block to `ERROR` protects the
    conformance rates from a classification bias by converting it into a *selection* bias, and
    a selection bias has to be bounded or admitted.

    These are Manski's worst-case bounds and they assume nothing whatever about the
    unobserved units: with an unobserved fraction `b`, everything we could not see might have
    passed, or none of it might have. The identified set is therefore
    `[p(1-b), p(1-b)+b]`, of width exactly `b`. That width does not shrink with more
    observations, which is the point: it measures ignorance rather than sampling noise, and
    where it is wider than the cluster-robust interval the honest reading is that a second
    vantage point buys more than a larger corpus.

    That last sentence is true and was, until 10 August 2026, quoted without the measurement
    that bounds it. `unreachable_composition` supplies it: most of `b` is hosts that no longer
    resolve, which no vantage point recovers. A second vantage buys the access blocks and
    whatever share of the timeouts is bot management -- worth having, since a block correlates
    with the maturity being measured in a way a dead host does not, but not the whole of `b`.
    """
    total = observed + unobserved
    if total <= 0:
        return (0.0, 0.0)
    b = unobserved / total
    low = p_hat * (1.0 - b)
    return (low, min(1.0, low + b))


def exposure_analysis(reports: list, conf: float = 0.95) -> dict:
    """The intersection the paper's thesis is about, which nothing computed until now.

    The argument is that the delegation surface is *narrow* and, *where it is entered*,
    unevidenced. Both halves were measured and neither was measured on the population the
    sentence is about: the topology rate is over declarations, and the evidence rates are over
    every issuer the corpus names. Three referees independently asked for the same missing
    quantity -- of the issuers reached by a declaration that leaves the resource's own
    registrable domain, how many publish the field that would let a client corroborate the
    pointer, and how many advertise the mix-up defence?

    Four groups of quantity come out of this, and each answers an objection that was raised:

    * `exposed_*` -- the crossing population expressed at the units a reader can hold. The
      discussion said "a twentieth of the corpus" while the rate was over declarations, which
      is a different denominator and roughly three and a half times larger. Endpoints and
      apexes that declare at least one crossing issuer are counted here so the sentence can be
      written over the population it names.
    * `crossing_issuers` -- the C16/C18 rates restricted to issuers named by a crossing
      declaration. This is the paper's thesis stated over its own population.
    * `concentration_by_unit` -- the same concentration statistic at the issuer URL, the
      issuer host and the issuer registrable domain. Reported at three units because the
      published figure is at the URL unit, where one registrable domain appeared four times
      in the top ten, so dispersion at that unit is partly an artefact of identifier
      granularity.
    * `concentration_crossing` -- concentration over crossing edges only. The comparison the
      related-work section sets up is about reliance on infrastructure the resource does not
      operate, and self-edges cannot answer it: when most declarations stay inside their own
      domain, a low index follows mechanically from the number of distinct domains.

    No new measurement. Every input is already in the stored evidence.
    """
    graph = build_delegation_graph(reports)

    # -- the crossing population, at three units ---------------------------------------
    crossing_edges = [
        (resource_apex, issuer) for resource_apex, issuer in graph.edges
        if (issuer_apex := _apex(issuer)) is not None and issuer_apex != resource_apex
    ]
    crossing_issuers = {issuer for _, issuer in crossing_edges}
    crossing_apexes = {resource_apex for resource_apex, _ in crossing_edges}

    # An endpoint is exposed when any issuer it declares leaves its own registrable domain.
    exposed_endpoints = 0
    declaring_endpoints = 0
    for report in reports:
        declared = (report.evidence or {}).get("authorization_servers") or []
        declared = [d for d in declared if isinstance(d, str)]
        if not declared:
            continue
        declaring_endpoints += 1
        resource_apex = report.endpoint.apex_domain
        if resource_apex and any(
            (ia := _apex(d)) is not None and ia != resource_apex for d in declared
        ):
            exposed_endpoints += 1

    # -- evidence rates restricted to the crossing issuers -------------------------------
    documents = issuer_documents(reports, "declared")
    crossing_docs = {i: d for i, d in documents.items() if i in crossing_issuers}

    def _rate(predicate, docs: dict) -> dict:
        # Clustered on the issuer's own registrable domain, as every issuer-level rate is.
        buckets: dict[str, list[int]] = {}
        for issuer, document in docs.items():
            key = _apex(issuer) or issuer
            bucket = buckets.setdefault(key, [0, 0])
            bucket[1] += 1
            if predicate(document):
                bucket[0] += 1
        clusters = [(k, n) for k, n in buckets.values()]
        return cluster_robust_proportion(clusters, conf=conf).as_record()

    # -- concentration at three issuer units, and over crossing edges only ---------------
    def _concentration(edges: list, key) -> dict:
        counts: dict[str, int] = {}
        for _, issuer in edges:
            identifier = key(issuer)
            if identifier is None:
                continue
            counts[identifier] = counts.get(identifier, 0) + 1
        total = sum(counts.values())
        if total == 0:
            return {"issuers": 0, "hhi": None, "top10_share": None, "effective_issuers": None}
        shares = sorted((c / total for c in counts.values()), reverse=True)
        hhi = sum(s * s for s in shares)
        return {
            "issuers": len(counts), "edges": total, "hhi": hhi,
            "top1_share": sum(shares[:1]), "top10_share": sum(shares[:10]),
            "effective_issuers": 1.0 / hhi if hhi > 0 else None,
        }

    def _host(issuer: str) -> str | None:
        from urllib.parse import urlsplit
        return urlsplit(issuer).hostname

    # -- the same concentration with one observation per declaring apex -------------------
    #
    # The published crossing-edge figures count one observation per edge, and a single apex
    # declaring the same issuer from eighty endpoints therefore contributes eighty. That is
    # not the shape of the web-centralisation result the discussion compares against, which
    # counts one observation per site. Here each (declaring apex, issuer domain) pair counts
    # once, which is the comparable construction.
    def _concentration_per_declarer(edges: list, key) -> dict:
        pairs = {(resource_apex, key(issuer)) for resource_apex, issuer in edges
                 if key(issuer) is not None}
        counts: dict[str, int] = {}
        for _, identifier in pairs:
            counts[identifier] = counts.get(identifier, 0) + 1
        total = sum(counts.values())
        if total == 0:
            return {"issuers": 0, "hhi": None, "top1_share": None, "top10_share": None}
        shares = sorted((c / total for c in counts.values()), reverse=True)
        hhi = sum(s * s for s in shares)
        declarers = {resource_apex for resource_apex, _ in pairs}
        largest = max(counts.items(), key=lambda kv: kv[1])
        return {
            "issuers": len(counts), "pairs": total, "hhi": hhi,
            "top1_share": shares[0], "top3_share": sum(shares[:3]),
            "top10_share": sum(shares[:10]),
            "declarers": len(declarers),
            # The quantity Kumar et al. report: the share of sites relying on the single
            # largest provider. Ours is the share of declaring apexes, which is the same
            # construction at the same unit.
            "largest_provider": largest[0],
            "largest_provider_declarers": largest[1],
            "largest_provider_declarer_share": largest[1] / len(declarers),
        }

    # -- how far one declaring apex reaches into the issuer population --------------------
    #
    # An edge count and an issuer count are different quantities and the manuscript printed
    # both without distinguishing them, which invites the reading that the apex declaring
    # eighty crossing edges also contributes eighty of the crossing issuers. It does not:
    # those eighty edges are eighty endpoints naming one issuer. Measured rather than
    # argued, because the inference is reasonable and wrong.
    issuers_by_declarer: dict[str, set] = {}
    for resource_apex, issuer in crossing_edges:
        issuers_by_declarer.setdefault(resource_apex, set()).add(issuer)
    dominant_declarer, dominant_issuers = (
        max(issuers_by_declarer.items(), key=lambda kv: len(kv[1]))
        if issuers_by_declarer else (None, set())
    )
    # Issuers no other apex declares: removing the dominant declarer removes exactly these.
    sole = {i for i in dominant_issuers
            if all(ra == dominant_declarer for ra, j in crossing_edges if j == i)}
    remaining_docs = {i: d for i, d in crossing_docs.items() if i not in sole}

    # -- does the crossing population differ, or only look as though it does? -------------
    #
    # Section 6.5 called the split between the two populations "the sharpest way to state
    # the result" and never tested it. The test is a 2x2 over the issuers whose metadata was
    # actually retrieved, because an issuer that was never reached can be on neither side of
    # a comparison about what issuers publish.
    def _contingency(predicate) -> dict:
        observed = {i: d for i, d in documents.items() if d}
        rows = {"crossing": [0, 0], "other": [0, 0]}
        for issuer, document in observed.items():
            row = rows["crossing" if issuer in crossing_issuers else "other"]
            row[1] += 1
            if predicate(document):
                row[0] += 1
        (ck, cn), (ok, on) = rows["crossing"], rows["other"]
        return fisher_exact_2x2(ck, cn - ck, ok, on - ok)

    units = {"url": lambda i: i, "host": _host, "registrable_domain": _apex}
    return {
        "declaring_endpoints": declaring_endpoints,
        "exposed_endpoints": exposed_endpoints,
        "exposed_apexes": len(crossing_apexes),
        "crossing_edges": len(crossing_edges),
        "crossing_issuers": len(crossing_issuers),
        "crossing_issuers_with_document": sum(1 for d in crossing_docs.values() if d),
        "c16_crossing": _rate(_advertises_iss, crossing_docs),
        "c18_crossing": _rate(_publishes_protected_resources, crossing_docs),
        "c16_all": _rate(_advertises_iss, documents),
        "c18_all": _rate(_publishes_protected_resources, documents),
        "c18_crossing_contrast": _contingency(_publishes_protected_resources),
        "c16_crossing_contrast": _contingency(_advertises_iss),
        "concentration_by_unit": {
            name: _concentration(graph.edges, key) for name, key in units.items()
        },
        "concentration_crossing": {
            name: _concentration(crossing_edges, key) for name, key in units.items()
        },
        "concentration_crossing_per_declarer": {
            name: _concentration_per_declarer(crossing_edges, key)
            for name, key in units.items()
        },
        "dominant_declarer": {
            "apex": dominant_declarer,
            "edges": sum(1 for ra, _ in crossing_edges if ra == dominant_declarer),
            "issuers": len(dominant_issuers),
            "sole_issuers": len(sole),
            "issuer_share": (len(dominant_issuers) / len(crossing_issuers)
                             if crossing_issuers else None),
        },
        # The apex carrying the most crossing *declarations*, which is a different apex from
        # the one above and a different quantity from the one Section 6.4 named. That
        # sentence read "one apex declares 80 issuers"; the eighty are declarations, and
        # they name one issuer between them. The distinction is the whole difference between
        # a bulk publisher's single choice and eighty independent ones.
        "top_edge_declarer": (
            {
                "apex": top_edge_apex,
                "edges": len([1 for ra, _ in crossing_edges if ra == top_edge_apex]),
                "issuers": len({i for ra, i in crossing_edges if ra == top_edge_apex}),
                "edge_share": len([1 for ra, _ in crossing_edges if ra == top_edge_apex])
                / len(crossing_edges),
            }
            if (top_edge_apex := (
                max(({ra for ra, _ in crossing_edges}),
                    key=lambda a: sum(1 for r, _ in crossing_edges if r == a))
                if crossing_edges else None)) else {}
        ),
        "c18_crossing_ex_dominant": _rate(_publishes_protected_resources, remaining_docs),
        "c16_crossing_ex_dominant": _rate(_advertises_iss, remaining_docs),
    }


def unreachable_composition(reports: list) -> dict:
    """What is actually inside the unobserved fraction Section 9.2 bounds.

    Written on 10 August 2026, after an external reviewer read Section 9.2's sentence about
    WAFs and concluded that the study loses mature enterprise deployments to bot management.
    The sentence invited that reading and the corpus does not support it: the share is
    dominated by hosts that no longer exist. Until this function there was no number either
    way, which is the defect. Section 9.2 named a mechanism, attached the whole unobserved
    fraction to it by implication, and nothing in the run said how much of the fraction the
    mechanism could account for.

    The categories come from `ErrorKind`, not from free text, so a new member or a renamed
    one shows up as an uncategorised count rather than being silently folded into another
    bucket. Three groupings matter and they are reported separately because they are
    different kinds of missing:

    * `blocked` -- the host answered and refused us. This is the only bucket the WAF
      mechanism can live in, and R4 sends it to ERROR precisely because it correlates with
      the maturity being measured.
    * `dead` -- DNS, TLS and connection failures. Nothing answered. A second vantage point
      cannot recover these, because there is nothing at the other end to recover.
    * `scope_gated` -- `OUT_OF_SCOPE`: our per-host ceiling was spent, or a redirect pointed
      somewhere the scope statement forbids. `fetcher.ErrorKind` already says of this member
      that it is "our decision, so it leaves every denominator exactly as the two above do",
      meaning robots and opt-out. It did not leave the one in Section 9.2, which is the same
      class of defect as the kill switch counting robots exclusions on 30 July 2026: our own
      configuration published as a property of the ecosystem.

    `timeout` is deliberately left in neither `blocked` nor `dead`. A silent drop by a bot
    manager and an abandoned host that never completes a handshake are indistinguishable from
    outside, and inventing a split would be exactly the assumption a Manski bound exists to
    avoid. It is reported on its own so a reader can put it on whichever side they argue for.

    The population is the one Section 9.2's `b` is computed over: endpoints that did not
    answer, excluding those robots.txt or the opt-out list removed, since those are counted
    in the exclusion ledger instead.
    """
    from .fetcher import ErrorKind

    # The two strings `checks_oauth` writes when a fetch produced no status. Reconstructed
    # from the enum rather than copied, so that renaming a member breaks the mapping loudly
    # instead of quietly emptying a bucket.
    by_detail = {f"not observed: {kind.value} (R4/R5)": kind.value for kind in ErrorKind}
    by_detail["access block (R4)"] = ErrorKind.BLOCKED.value

    DEAD = {ErrorKind.DNS.value, ErrorKind.TLS.value, ErrorKind.CONNECTION.value}

    counts: dict[str, int] = {}
    total = 0
    for report in reports:
        if report.reachable is not False or report.robots_allowed is False or report.opted_out:
            continue
        total += 1
        kind = None
        for check in report.checks:
            kind = by_detail.get(check.detail)
            if kind is not None:
                break
        counts[kind or "uncategorised"] = counts.get(kind or "uncategorised", 0) + 1

    scope_gated = counts.get(ErrorKind.OUT_OF_SCOPE.value, 0)
    blocked = counts.get(ErrorKind.BLOCKED.value, 0)
    return {
        "total": total,
        "by_kind": dict(sorted(counts.items())),
        "blocked": blocked,
        "dead": sum(counts.get(k, 0) for k in DEAD),
        "timeout": counts.get(ErrorKind.TIMEOUT.value, 0),
        "scope_gated": scope_gated,
        # What Section 9.2's narrowest row should be computed over: endpoints unobserved for
        # a reason that belongs to the deployment rather than to us.
        "operator_caused": total - scope_gated,
        "uncategorised": counts.get("uncategorised", 0),
    }


def withheld_issuer_ledger(reports: list) -> dict:
    """Issuers we declined to request, grouped by the reason we gave at the time.

    The exclusion ledger for the issuer denominators, and it exists for the same reason as
    the endpoint one in §5.1: a denominator that shrinks without a count beside it cannot be
    audited, and R4 permits our politeness policy to remove observations only on condition
    that the removal is reported. The reasons are the strings `checks_oauth` recorded --
    "not a public HTTPS host" and "beyond the N-issuer per-endpoint request cap" -- so the
    ledger says which of our own rules cost us how much, rather than reporting one opaque
    total.

    An issuer withheld by one endpoint and observed via another is *not* withheld: it appears
    under `also_observed_elsewhere` and stays in the denominator, because we did in the end
    see its document.
    """
    withheld: dict[str, set[str]] = {}
    observed: set[str] = set()
    for report in reports:
        evidence = report.evidence or {}
        for issuer, reason in (evidence.get("as_not_fetched") or {}).items():
            if isinstance(issuer, str):
                withheld.setdefault(issuer, set()).add(str(reason))
        for issuer in (evidence.get("as_documents") or {}):
            if isinstance(issuer, str):
                observed.add(issuer)

    excluded = {i: sorted(r) for i, r in withheld.items() if i not in observed}
    by_reason: dict[str, int] = {}
    for reasons in excluded.values():
        for reason in reasons:
            by_reason[reason] = by_reason.get(reason, 0) + 1
    return {
        "excluded_from_denominators": len(excluded),
        "also_observed_elsewhere": sorted(set(withheld) & observed),
        "by_reason": dict(sorted(by_reason.items())),
        "issuers": dict(sorted(excluded.items())),
    }


def issuer_rate(
    reports: list, predicate, denominator: str, conf: float = 0.95
) -> ProportionEstimate:
    """A rate over unique issuers, clustered on the issuer's apex domain.

    Clustering matters more here than anywhere else in this module, and in the opposite
    direction to the endpoint rates: `iss` support is a property of an identity *product*,
    so every tenant of one managed IdP answers identically. Treating those as independent
    observations is how a study reports +/-4pp on a quantity it has really observed a dozen
    times. The apex is the collectable proxy for the product; where it is unresolvable the
    issuer forms its own cluster, which is the conservative direction.
    """
    documents = issuer_documents(reports, denominator)
    buckets: dict[str, list[int]] = {}
    for issuer, doc in documents.items():
        key = _apex(issuer) or f"?{issuer}"
        bucket = buckets.setdefault(key, [0, 0])
        bucket[1] += 1
        if predicate(doc):
            bucket[0] += 1
    return cluster_robust_proportion([(k, n) for k, n in buckets.values()], conf)


def _advertises_iss(doc: dict | None) -> bool:
    """C16 -- RFC 9207 §2.3. An unreachable issuer advertises nothing (R11.5).

    §2.3 carries the obligation ("The server MUST indicate its support for the iss parameter
    by setting the metadata parameter ... to true"); §3, cited here until 30 July 2026, only
    defines the parameter and its false-by-default. The flag read below is the same either
    way, but the rate this function feeds is R11.1's rank-1 headline candidate, so the
    citation attached to it is the one a reviewer checks.
    """
    return bool(doc) and doc.get("authorization_response_iss_parameter_supported") is True


def _offers_client_bootstrap(doc: dict | None) -> bool:
    """C17 -- CIMD or RFC 7591 registration, either usable by a non-interactive client."""
    if not doc:
        return False
    return (doc.get("client_id_metadata_document_supported") is True
            or isinstance(doc.get("registration_endpoint"), str))


def _publishes_protected_resources(doc: dict | None) -> bool:
    """C18 -- RFC 9728 §4. An empty list is not a published list: it enumerates nothing, so
    §7.6's cross-check stays as impossible as if the member were absent."""
    if not doc:
        return False
    listed = doc.get("protected_resources")
    return isinstance(listed, list) and len(listed) > 0


# --- R11 executed rather than described ----------------------------------------

# The candidate list, in the order frozen by R11.1. Rank 3 is the topology, which is not a
# rate and so is not in this list: R11.2 makes it the fallback when no rate qualifies, and
# `select_headline` returns it in exactly that case. Nothing may be appended here after
# collection begins.
HEADLINE_CANDIDATES: tuple[tuple[int, str, str], ...] = (
    (1, "C16 -- issuers advertising the RFC 9207 mix-up defence", "declared"),
    # Rank 2's label named the metadata field verbatim and rank 4's did not say which half of
    # the pair the printed estimate belongs to. Both were reworded on 6 August 2026 for the
    # manuscript; the ranks, the checks referred to and the unit each is read at are
    # untouched, and those are what R11.1 froze.
    (2, "C18 -- issuers publishing the protected-resource list of RFC 9728, Section 4",
     "observed"),
    (4, "C12/C13 -- mechanical conformance of declared identifiers, weaker half", "apex"),
    (5, "C17 -- issuers offering non-interactive client bootstrap", "declared"),
)


def headline_candidates(reports: list, conf: float = 0.95) -> list[tuple[str, ProportionEstimate]]:
    """R11.1's ranked candidates, each as an estimate the variance test can be applied to.

    Rank 4 is reported at all three of R10.1's units, but the variance test needs one
    estimate, and R11.5's table says "R10.1's three units" without saying which governs.
    That gap is closed here in the only direction that is not a choice made later: the apex,
    which R10.2 already fixes as the *primary* unit of analysis. The other two units are
    still reported in full by `three_unit_table`; what is pinned here is only which one the
    selection rule reads.
    """
    from .models import CheckId

    c12 = rate_by_unit(reports, CheckId.PRM_RESOURCE_IDENTITY_MATCH, "apex", conf)
    c13 = rate_by_unit(reports, CheckId.AS_CORRESPONDENCE, "apex", conf)
    # The pair is one candidate under R11.1, so it needs one estimate. The weaker of the two
    # governs: a resource whose identifier matches but whose issuer does not answer as
    # itself has not given its clients a verifiable chain, and reporting the better half
    # would be choosing the flattering number, which is the whole thing R11 forbids.
    conformance = c12 if c12.p_hat <= c13.p_hat else c13

    by_rank = {
        1: issuer_rate(reports, _advertises_iss, "declared", conf),
        2: issuer_rate(reports, _publishes_protected_resources, "observed", conf),
        4: conformance,
        5: issuer_rate(reports, _offers_client_bootstrap, "declared", conf),
    }
    return [(label, by_rank[rank]) for rank, label, _ in HEADLINE_CANDIDATES]


def analyse(reports: list, conf: float = 0.95) -> dict:
    """Everything R11 and R12 require, as one record written before the paper is touched.

    The point is not convenience. R11.2 selects the headline, and a selection that happens
    inside somebody's head while reading a summary is indistinguishable from choosing the
    best number. Emitting the ranked candidates, each interval, each verdict and the reason
    the winner won makes the selection an event with a transcript -- which is the only form
    of it a reviewer can check.
    """
    from .models import CheckId

    candidates = headline_candidates(reports, conf)
    graph = build_delegation_graph(reports)
    winner, reason = select_headline(candidates)

    return {
        "headline": {"selected": winner, "reason": reason},
        "candidates": [
            {
                "rank": rank,
                "label": label,
                "denominator": denominator,
                "estimate": estimate.as_record(),
                "variance_test": {
                    "passed": passes_variance_test(estimate).passed,
                    "reason": passes_variance_test(estimate).reason,
                },
            }
            for (rank, label, denominator), (_, estimate) in zip(
                HEADLINE_CANDIDATES, candidates, strict=True
            )
        ],
        # R9.5's sensitivity pair: the alternative denominator is printed for every issuer
        # candidate, so that the pre-declared choice is visible next to what it excluded.
        "sensitivity_alternative_denominator": {
            "C16_observed": issuer_rate(reports, _advertises_iss, "observed", conf).as_record(),
            "C18_declared": issuer_rate(
                reports, _publishes_protected_resources, "declared", conf).as_record(),
            "C17_observed": issuer_rate(
                reports, _offers_client_bootstrap, "observed", conf).as_record(),
        },
        "topology": {
            "concentration": graph.concentration(),
            "relation": {
                "same_operator": graph.same_operator,
                "cross_operator": graph.cross_operator,
                "unknown_operator": graph.unknown_operator,
                "total": graph.total,
            },
            "cross_operator_rate": cluster_robust_proportion(
                graph.cross_operator_clusters(), conf).as_record(),
            "issuers_shared_across_apexes": len(graph.shared_across_apexes),
        },
        # What our own scope policy removed from the issuer denominators, by reason. R4's rule
        # that a politeness decision must never be written up as the operator's failure only
        # holds if the decision is counted somewhere: an exclusion that leaves no trace is
        # indistinguishable from an observation. Before 30 July 2026 these issuers were not
        # excluded at all -- they were scored as "does not advertise", against C16, the
        # first-ranked headline candidate.
        "withheld_issuers": withheld_issuer_ledger(reports),
        "cross_check": cross_check_feasibility(reports),
        "three_unit": {
            check.value: three_unit_table(reports, check, conf)
            for check in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                          CheckId.AS_CORRESPONDENCE)
        },
        # C05 restricted to the population its specification sentence addresses. The wider
        # denominator above admits any endpoint that published, challenge or not, which is
        # the circularity Section 6.1 undertook to avoid and did not; both are published so
        # the cost of the choice is visible rather than argued.
        "three_unit_challenged": {
            CheckId.PRM_PRESENT.value: three_unit_table(
                reports, CheckId.PRM_PRESENT, conf, challenged_only=True),
        },
        "denominator_composition": {
            check.value: denominator_composition(reports, check)
            for check in (CheckId.PRM_PRESENT, CheckId.PRM_RESOURCE_IDENTITY_MATCH,
                          CheckId.AS_CORRESPONDENCE)
        },
        "challenge_share": challenge_share(reports, CheckId.PRM_PRESENT),
        "issuers": {
            "declared": len(issuer_documents(reports, "declared")),
            "observed": len(issuer_documents(reports, "observed")),
        },
        "endpoints": len(reports),
    }

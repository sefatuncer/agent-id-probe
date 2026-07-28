"""Statistics for a population that is not a sample of independent things.

Endpoints run on a handful of SDKs, platforms and bulk publishers. A rate computed as
though each endpoint were an independent draw overstates its own precision, sometimes
severely: simulation over the shapes this corpus plausibly takes put the real coverage of a
nominal 95% Wilson interval between 46% and 82%. Decision rule R10.4 therefore forbids
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


def wilson_interval(k: int, n: int, conf: float = 0.95) -> tuple[float, float]:
    """The independent-observations interval.

    Reported only alongside a cluster-robust one (R10.4). It is here because the gap
    between the two is itself worth showing: it is the size of the mistake the paper would
    have made by treating endpoints as independent.
    """
    if n <= 0:
        return (0.0, 0.0)
    z = student_t_ppf(1.0 - (1.0 - conf) / 2.0, 1e6)   # ~ normal quantile
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


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

    @property
    def width(self) -> float:
        return self.hi - self.lo

    def as_record(self) -> dict:
        return {
            "k": self.k, "n": self.n, "m": self.m,
            "p_hat": self.p_hat, "ci_lo": self.lo, "ci_hi": self.hi,
            "deff": self.deff, "n_eff": self.n_eff, "method": self.method,
            "naive_ci_lo": self.naive_lo, "naive_ci_hi": self.naive_hi,
        }


def cluster_robust_proportion(
    clusters: list[tuple[int, int]], conf: float = 0.95
) -> ProportionEstimate:
    """Proportion with a cluster-robust interval, t(m-1)-based per R10.4.

    `clusters` is one (successes, total) pair per cluster. The t quantile rather than z is
    not pedantry: with a dozen platforms the difference is the difference between an
    interval that covers and one that does not.

    Note that clustering does not only widen. When the property is spread evenly across
    clusters the design effect falls below 1 and the interval is *narrower* than the naive
    one. That is why this is a measurement rather than a safety margin.
    """
    m = len(clusters)
    total = sum(n for _, n in clusters)
    successes = sum(k for k, _ in clusters)
    if total == 0:
        return ProportionEstimate(0, 0, m, 0.0, 0.0, 0.0, None, None, "empty")
    p_hat = successes / total
    naive = wilson_interval(successes, total, conf)

    if m < 2:
        return ProportionEstimate(
            successes, total, m, p_hat, naive[0], naive[1], None, None,
            "wilson (single cluster: no between-cluster variance to estimate)",
            naive[0], naive[1],
        )

    ssq = sum((k - p_hat * n) ** 2 for k, n in clusters)
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
    return ProportionEstimate(
        successes, total, m, p_hat, lo, hi, deff, n_eff, method, naive[0], naive[1],
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


def rate_by_unit(reports: list, check_id, unit: str, conf: float = 0.95) -> ProportionEstimate:
    """One check's pass rate with `unit` as the unit of analysis.

    The denominator follows the funnel rules rather than counting every report: an endpoint
    the check does not apply to (NOT_APPLICABLE) or could not be observed on (ERROR) leaves,
    because carrying it would count composition and access blocks as non-conformance.

    For the endpoint unit every endpoint is an observation and the interval is clustered by
    apex, so the point estimate is the raw rate while the interval knows the endpoints are
    not independent. For the apex and implementation units the population is collapsed
    first, which moves the point estimate too — and the gap between the two is the finding
    a single number would hide.
    """
    from .models import Outcome

    applicable = [
        r for r in reports
        if (o := r.outcome_of(check_id)) is not None
        and o not in (Outcome.NOT_APPLICABLE, Outcome.ERROR)
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


def three_unit_table(reports: list, check_id, conf: float = 0.95) -> dict[str, dict]:
    """R10.1: no rate is published as a single number.

    "8% of 1,700 endpoints" and "8% across 34 implementations" are different claims, and a
    reviewer cannot tell which one the study is entitled to make unless both are on the
    page. Most of the objection that endpoints are not independent is answered by this
    table alone, without any modelling.
    """
    return {unit: rate_by_unit(reports, check_id, unit, conf).as_record() for unit in UNITS}


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
        total = sum(self.issuer_counts.values())
        if total == 0:
            return {"issuers": 0, "hhi": None, "top1_share": None,
                    "top3_share": None, "top5_share": None, "effective_issuers": None}
        shares = sorted((c / total for c in self.issuer_counts.values()), reverse=True)
        hhi = sum(s * s for s in shares)
        return {
            "issuers": len(self.issuer_counts),
            "hhi": hhi,
            "top1_share": sum(shares[:1]),
            "top3_share": sum(shares[:3]),
            "top5_share": sum(shares[:5]),
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


@dataclass
class VarianceTest:
    passed: bool
    reason: str
    estimate: ProportionEstimate = field(repr=False, default=None)  # type: ignore[assignment]


def passes_variance_test(estimate: ProportionEstimate) -> VarianceTest:
    """Decision rule R11.2.

    A candidate cannot be the paper's headline if its whole interval sits in [0, 2%] or in
    [98%, 100%]: "essentially nobody" and "essentially everybody" are one-sentence findings,
    not a paper. Applied to the cluster-robust interval, never the naive one, because the
    naive one is too narrow to fail the test honestly.
    """
    if estimate.n == 0:
        return VarianceTest(False, "no observations", estimate)
    if estimate.hi <= VARIANCE_FLOOR:
        return VarianceTest(
            False, f"interval [{estimate.lo:.3f}, {estimate.hi:.3f}] lies within "
                   f"[0, {VARIANCE_FLOOR:.0%}]: essentially nobody", estimate)
    if estimate.lo >= VARIANCE_CEILING:
        return VarianceTest(
            False, f"interval [{estimate.lo:.3f}, {estimate.hi:.3f}] lies within "
                   f"[{VARIANCE_CEILING:.0%}, 1]: essentially everybody", estimate)
    return VarianceTest(True, f"interval [{estimate.lo:.3f}, {estimate.hi:.3f}] shows variance",
                        estimate)


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
        "ecosystem topology (R11.2 fallback)",
        "no rate candidate showed variance; the topology result is not a rate and is "
        "therefore not subject to the variance test",
    )

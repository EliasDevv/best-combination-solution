"""Weighted set cover: reduce, prune dominated, greedy bound, branch & bound."""

from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from time import perf_counter

from .index import BitIndex
from .pricing import months_needed, package_cost_cents
from .types import PackageCoverage, Query, Requirement, Solution

_TIME_BUDGET_S = 0.05  # on expiry the incumbent is returned with exact=False
_MEMO_MAX_ENTRIES = 100_000


@dataclass(frozen=True, slots=True)
class Candidate:
    """One package as the search sees it: a bit mask and a weight, nothing else."""

    mask: int  # search-space bits (doubled for "both")
    weight: int  # objective-transformed cost
    cost_cents: int
    coverage: PackageCoverage


def _iter_bits(mask: int) -> Iterator[int]:
    while mask:
        low = mask & -mask
        yield low.bit_length() - 1
        mask ^= low


def _date_range_mask(index: BitIndex, date_from: date | None, date_to: date | None) -> int:
    # bits are (starts_at, id)-sorted, so a date range is one contiguous run; bisect both ends
    n = len(index.game_ids)
    all_games = (1 << n) - 1
    if n == 0 or (date_from is None and date_to is None):
        return all_games
    tz = index.game_starts[0].tzinfo
    lo = 0
    hi = n
    if date_from is not None:
        lo = bisect_left(index.game_starts, datetime.combine(date_from, time.min, tzinfo=tz))
    if date_to is not None:
        first_excluded = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
        hi = bisect_left(index.game_starts, first_excluded)
    return ((1 << hi) - 1) ^ ((1 << lo) - 1)


def relevant_coverages(index: BitIndex, query: Query) -> tuple[int, list[PackageCoverage]]:
    """Stage 1: resolve the query to a target mask and price every package on it.

    Returns ``(target, coverages)``. The target is the union of the query's
    team masks (empty means every game) clipped to the date range. Each
    surviving package is clipped to that target and priced over the months of
    its *own* clipped coverage, which is what keeps the objective additive and
    the later branch & bound exact.

    Two kinds of package drop out here: those covering nothing in the target,
    and those with no bookable price under the query's billing mode. Both are
    unusable, so nothing downstream has to keep checking for them.
    """
    n = len(index.game_ids)
    if query.team_masks:
        team_union = 0
        for mask in query.team_masks:
            team_union |= mask
    else:
        team_union = (1 << n) - 1
    target = team_union & _date_range_mask(index, query.date_from, query.date_to)

    coverages: list[PackageCoverage] = []
    for package_id, info in index.packages.items():
        live = index.live_mask[package_id] & target
        highlights = index.highlight_mask[package_id] & target
        if query.requirement == "live":
            relevant = live
        elif query.requirement == "highlights":
            relevant = highlights
        else:
            relevant = live | highlights
        if relevant == 0:
            continue
        # intersecting ~a dozen month masks beats iterating thousands of set bits
        months = months_needed(
            frozenset(m for m, m_mask in index.month_mask.items() if relevant & m_mask)
        )
        cost = package_cost_cents(info, months, query.billing)
        if cost is None:
            continue
        coverages.append(
            PackageCoverage(
                package=info, live_mask=live, highlight_mask=highlights, cost_cents=cost
            )
        )
    return target, coverages


def build_candidates(
    target_mask: int,
    coverages: list[PackageCoverage],
    requirement: Requirement,
    objective: str,
    game_count: int,
) -> tuple[int, list[Candidate]]:
    """Stage 2: turn priced coverages into the search's bit space and weights.

    Returns ``(search_target, candidates)``. For ``live``/``highlights`` the
    bit space is the game bits as-is. For ``both`` it is *doubled* — low half
    live, high half highlights — so the two needs of one game can be met by
    different packages; the target then keeps only games some package can
    serve both ways, because buying for the rest would cover nothing.

    ``objective`` is folded into the weight rather than the search: for
    ``min_packages`` every weight gets ``BIG + cost`` with ``BIG`` above the
    sum of all costs, so package count dominates and price only breaks ties.
    One search path serves both objectives.
    """
    if requirement == "both":
        # doubled bit space: low half = live, high half = highlights; target keeps
        # only pairable games (both halves coverable by someone)
        live_any = 0
        highlight_any = 0
        for cov in coverages:
            live_any |= cov.live_mask
            highlight_any |= cov.highlight_mask
        pairable = live_any & highlight_any
        search_target = pairable | (pairable << game_count)
    else:
        search_target = target_mask

    # min_packages: weight = big + cost, so package count dominates, price tie-breaks
    big = 1 + sum(cov.cost_cents for cov in coverages if cov.cost_cents is not None)
    candidates: list[Candidate] = []
    for cov in coverages:
        assert cov.cost_cents is not None  # guaranteed by relevant_coverages
        if requirement == "live":
            mask = cov.live_mask
        elif requirement == "highlights":
            mask = cov.highlight_mask
        else:
            pairable = search_target & ((1 << game_count) - 1)
            mask = (cov.live_mask & pairable) | ((cov.highlight_mask & pairable) << game_count)
        if mask == 0:
            continue
        weight = cov.cost_cents if objective == "min_price" else big + cov.cost_cents
        candidates.append(
            Candidate(mask=mask, weight=weight, cost_cents=cov.cost_cents, coverage=cov)
        )
    return search_target, candidates


def prune_dominated(candidates: list[Candidate]) -> list[Candidate]:
    """Drop every package a cheaper-or-equal package already subsumes.

    Walking cheapest-first, a candidate is discarded when some kept candidate
    covers all of its bits: paying more for a subset can never help. Safe for
    the optimum — any solution using a dominated package stays valid, and no
    more expensive, after the swap — and it is what keeps the branching factor
    small enough for an exact search.
    """
    ordered = sorted(candidates, key=lambda c: (c.weight, c.coverage.package.id))
    kept: list[Candidate] = []
    for cand in ordered:
        if any(cand.mask & ~other.mask == 0 for other in kept):
            continue
        kept.append(cand)
    return kept


def _solution_from(chosen: list[Candidate], target_mask: int, exact: bool = True) -> Solution:
    covered = 0
    cost = 0
    ids: list[int] = []
    for cand in chosen:
        covered |= cand.mask
        cost += cand.cost_cents
        ids.append(cand.coverage.package.id)
    covered &= target_mask
    coverage = covered.bit_count() / target_mask.bit_count() if target_mask else 1.0
    return Solution(
        package_ids=tuple(sorted(ids)),
        cost_cents=cost,
        covered_mask=covered,
        coverage=coverage,
        exact=exact,
    )


def _greedy_prefixes(target_mask: int, candidates: list[Candidate]) -> list[list[Candidate]]:
    uncovered = target_mask
    available = list(candidates)
    chosen: list[Candidate] = []
    prefixes: list[list[Candidate]] = []
    while uncovered and available:
        best: Candidate | None = None
        best_new = 0
        for cand in available:
            new = (cand.mask & uncovered).bit_count()
            if new == 0:
                continue
            if best is None:
                best, best_new = cand, new
                continue
            # cand.weight/new < best.weight/best_new, without floats
            lhs = cand.weight * best_new
            rhs = best.weight * new
            if lhs < rhs or (
                lhs == rhs
                and (cand.weight, cand.coverage.package.id)
                < (best.weight, best.coverage.package.id)
            ):
                best, best_new = cand, new
        if best is None:
            break
        chosen.append(best)
        available.remove(best)
        uncovered &= ~best.mask
        prefixes.append(list(chosen))
    return prefixes


def greedy_cover(target_mask: int, candidates: list[Candidate]) -> Solution:
    """Classic ln(n)-approximation: repeatedly take the best weight-per-new-bit.

    Not the answer — the incumbent branch & bound starts from, which is what
    lets it prune from the first node instead of groping for a first solution.
    Ratios are compared by integer cross-multiplication, so no float rounding
    can make the choice non-deterministic.
    """
    prefixes = _greedy_prefixes(target_mask, candidates)
    return _solution_from(prefixes[-1] if prefixes else [], target_mask)


def branch_and_bound(
    target_mask: int,
    candidates: list[Candidate],
    upper_bound: Solution,
) -> Solution:
    """Stage 4: the exact minimum-weight cover, given a starting incumbent.

    Branches on the *rarest* uncovered bit — the one fewest candidates can
    serve — because that is where the choice is most constrained and the tree
    narrowest. Three prunes keep it small: the incumbent weight, an admissible
    lower bound (best weight-per-bit ratio × uncovered count, rounded up), and
    a memo mapping an uncovered mask to the cheapest weight already seen
    reaching it.

    Bits no candidate can cover are removed from the search up front, so an
    impossible game never blocks the rest; coverage is reported against the
    full target regardless. If the 50 ms budget expires the best solution
    found so far is returned with ``exact=False`` — never a timeout, never a
    guess dressed as an optimum.
    """
    if target_mask == 0 or not candidates:
        return upper_bound
    # uncoverable bits are dropped; the search covers the coverable subset
    coverable = 0
    for cand in candidates:
        coverable |= cand.mask
    effective = target_mask & coverable
    if effective == 0:
        return upper_bound

    by_id = {cand.coverage.package.id: cand for cand in candidates}
    incumbent = [by_id[pid] for pid in upper_bound.package_ids if pid in by_id]
    incumbent_cover = 0
    for cand in incumbent:
        incumbent_cover |= cand.mask
    best_weight: float
    best_chosen: list[Candidate] | None
    if incumbent and effective & ~incumbent_cover == 0:
        best_weight = sum(cand.weight for cand in incumbent)
        best_chosen = incumbent
    else:
        best_weight = float("inf")
        best_chosen = None

    # branch on the rarest bit (covered by the fewest candidates)
    ordered = sorted(candidates, key=lambda c: (c.weight, c.coverage.package.id))
    bit_candidates: dict[int, list[Candidate]] = {bit: [] for bit in _iter_bits(effective)}
    for cand in ordered:
        for bit in _iter_bits(cand.mask & effective):
            bit_candidates[bit].append(cand)
    branch_order = sorted(bit_candidates, key=lambda bit: (len(bit_candidates[bit]), bit))

    deadline = perf_counter() + _TIME_BUDGET_S
    nodes = 0
    expired = False
    memo: dict[int, float] = {}

    def dfs(uncovered: int, weight: int, chosen: list[Candidate]) -> None:
        nonlocal best_weight, best_chosen, nodes, expired
        if expired or weight >= best_weight:
            return
        if uncovered == 0:
            best_weight = weight
            best_chosen = list(chosen)
            return
        nodes += 1
        if nodes % 1024 == 0 and perf_counter() > deadline:
            expired = True
            return
        seen = memo.get(uncovered)
        if seen is not None and seen <= weight:
            return
        if len(memo) < _MEMO_MAX_ENTRIES:
            memo[uncovered] = weight

        # admissible lower bound: each uncovered bit costs at least the best
        # weight-per-bit ratio on offer
        uncovered_count = uncovered.bit_count()
        best_ratio_w = 0
        best_ratio_c = 1
        found = False
        for cand in ordered:
            gain = (cand.mask & uncovered).bit_count()
            if gain == 0:
                continue
            if not found or cand.weight * best_ratio_c < best_ratio_w * gain:
                best_ratio_w, best_ratio_c, found = cand.weight, gain, True
        if not found:
            return  # unreachable: effective bits are coverable
        lower = (uncovered_count * best_ratio_w + best_ratio_c - 1) // best_ratio_c
        if weight + lower >= best_weight:
            return

        branch_bit = next(bit for bit in branch_order if uncovered >> bit & 1)
        for cand in bit_candidates[branch_bit]:
            chosen.append(cand)
            dfs(uncovered & ~cand.mask, weight + cand.weight, chosen)
            chosen.pop()
            if expired:
                return

    dfs(effective, 0, [])
    if best_chosen is None:
        return upper_bound
    return _solution_from(best_chosen, target_mask, exact=not expired)


def _fold_covered_games(covered_mask: int, requirement: Requirement, game_count: int) -> int:
    if requirement != "both":
        return covered_mask
    low = (1 << game_count) - 1
    return (covered_mask & low) & (covered_mask >> game_count)  # covered iff both halves set


def solve_reduced(
    game_count: int, query: Query, target: int, coverages: list[PackageCoverage]
) -> Solution:
    """Stages 2–4 on an already-reduced query: candidates, greedy, exact search.

    Split out from ``solve`` so a caller that already ran stage 1 — the
    ``compare`` facade, which shares one reduction with the Pareto front — does
    not pay for it twice.

    Two empty answers, deliberately different: an empty target is full
    coverage of nothing (``coverage=1.0``), while a target no package can
    serve is honest zero coverage. For ``both``, the covered mask is folded
    back from the doubled bit space to one bit per game, so a game counts only
    when both halves are covered.
    """
    if target == 0:
        return Solution(package_ids=(), cost_cents=0, covered_mask=0, coverage=1.0)
    search_target, candidates = build_candidates(
        target, coverages, query.requirement, query.objective, game_count
    )
    if not candidates or search_target == 0:
        return Solution(package_ids=(), cost_cents=0, covered_mask=0, coverage=0.0)
    pruned = prune_dominated(candidates)
    upper = greedy_cover(search_target, pruned)
    best = branch_and_bound(search_target, pruned, upper)
    covered_games = _fold_covered_games(best.covered_mask, query.requirement, game_count)
    return Solution(
        package_ids=best.package_ids,
        cost_cents=best.cost_cents,
        covered_mask=covered_games,
        coverage=covered_games.bit_count() / target.bit_count(),
        exact=best.exact,
    )


def solve(index: BitIndex, query: Query) -> Solution:
    """Optimal cover of the coverable subset; coverage is measured against the full target."""
    target, coverages = relevant_coverages(index, query)
    return solve_reduced(len(index.game_ids), query, target, coverages)

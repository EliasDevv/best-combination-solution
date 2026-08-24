"""Benchmark the four challenge reference queries.

Two measurements per query:

- **solver**: one full ``solver.compare.compare`` pass (reduction + exact
  solve + Pareto front) on the warm index, median over the runs;
- **endpoint**: the complete uncached ``POST /api/compare`` view path via
  Django's test client — validation, solve, payload build, saved-search
  write — with the response cache cleared before every request.

The budget (see the README) is **p95 < 100 ms server-side for /api/compare**, so
the endpoint p95 column is the number that counts; the solver column exists
to localize regressions.
"""

import json
import math
import time
from statistics import median
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.test import Client

from catalog.normalize import normalize_team_name
from catalog.selectors import build_index_from_db
from solver.compare import compare
from solver.index import BitIndex, warm_index
from solver.types import Query

# The four reference queries from the challenge statement.
BENCHMARK_QUERIES: list[dict[str, Any]] = [
    {
        "label": "RB Leipzig (all games)",
        "teams": ["RB Leipzig"],
        "objective": "min_price",
    },
    {
        "label": "Hatayspor + Deutschland + RB Leipzig + Real Madrid",
        "teams": ["Hatayspor", "Deutschland", "RB Leipzig", "Real Madrid"],
        "objective": "min_price",
    },
    {
        "label": "All teams, fewest services",
        "teams": [],  # empty = every team
        "objective": "min_packages",
    },
    {
        "label": "Oxford United + Los Angeles FC + AS Rom",
        "teams": ["Oxford United", "Los Angeles FC", "AS Rom"],
        "objective": "min_price",
    },
]

RUNS_PER_QUERY = 20
WARMUP_RUNS = 2


def _p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


class Command(BaseCommand):
    help = "Measure solver and full /api/compare runtime for the four reference queries."

    def handle(self, *args: Any, **options: Any) -> None:
        # The test client sends Host: testserver, which dev ALLOWED_HOSTS
        # does not include — this is a local measurement tool, not a server.
        if "testserver" not in settings.ALLOWED_HOSTS:
            settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
        client = Client()

        try:
            index = warm_index(build_index_from_db)
        except Exception:
            self.stderr.write("Could not build the index (empty database?); run import_dataset.")
            raise

        rows: list[tuple[str, ...]] = []
        for spec in BENCHMARK_QUERIES:
            solver_ms = self._time_solver(index, spec)
            endpoint_p50, endpoint_p95, payload_bytes, summary = self._time_endpoint(client, spec)
            rows.append(
                (
                    spec["label"],
                    f"{median(solver_ms):.1f} ms",
                    f"{endpoint_p50:.1f} ms",
                    f"{endpoint_p95:.1f} ms",
                    f"{payload_bytes / 1024:.0f} KiB",
                    summary,
                )
            )

        header = ("Query", "Solver med", "Endpoint p50", "Endpoint p95", "Payload", "Result")
        widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
        self.stdout.write("")
        self.stdout.write("  ".join(h.ljust(w) for h, w in zip(header, widths, strict=True)))
        self.stdout.write("-" * (sum(widths) + 2 * (len(header) - 1)))
        for row in rows:
            self.stdout.write("  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)))
        self.stdout.write(
            f"\n{RUNS_PER_QUERY} uncached endpoint runs per query (cache cleared before each), "
            f"{WARMUP_RUNS} warm-up runs discarded; budget: endpoint p95 < 100 ms."
        )

    def _time_solver(self, index: BitIndex, spec: dict[str, Any]) -> list[float]:
        query = self._build_query(index, spec)
        timings: list[float] = []
        for _ in range(WARMUP_RUNS + RUNS_PER_QUERY):
            start = time.perf_counter()
            compare(index, query)
            timings.append((time.perf_counter() - start) * 1000)
        return timings[WARMUP_RUNS:]

    def _time_endpoint(self, client: Client, spec: dict[str, Any]) -> tuple[float, float, int, str]:
        body = json.dumps({"teams": spec["teams"], "objective": spec["objective"]})
        timings: list[float] = []
        payload_bytes = 0
        summary = "?"
        for run in range(WARMUP_RUNS + RUNS_PER_QUERY):
            cache.clear()  # measure the uncached path every time
            start = time.perf_counter()
            response = client.post("/api/compare", data=body, content_type="application/json")
            elapsed = (time.perf_counter() - start) * 1000
            if response.status_code != 200:
                return 0.0, 0.0, 0, f"HTTP {response.status_code}"
            if run >= WARMUP_RUNS:
                timings.append(elapsed)
            payload_bytes = len(response.content)
            best = response.json()["best_combination"]
            exact = "" if best["exact"] else ", not proven optimal"
            summary = f"{len(best['package_ids'])} pkgs, {best['cost_cents'] / 100:.2f} EUR{exact}"
        return median(timings), _p95(timings), payload_bytes, summary

    def _build_query(self, index: BitIndex, spec: dict[str, Any]) -> Query:
        team_masks: tuple[int, ...] = ()
        if spec["teams"]:
            resolved = []
            for team in spec["teams"]:
                mask = index.team_mask.get(normalize_team_name(team), 0)
                if mask == 0:
                    self.stderr.write(f"warning: no games found for team {team!r}")
                resolved.append(mask)
            team_masks = tuple(resolved)
        return Query(
            team_masks=team_masks,
            date_from=None,
            date_to=None,
            requirement="live",
            objective=spec["objective"],
            billing="monthly_chained",
        )

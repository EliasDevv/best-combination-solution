"""Generate a synthetic dataset with the shape of the real CHECK24 CSVs.

The zero-configuration fallback: ``docker-entrypoint.sh`` seeds with this
whenever ``data/`` holds no CSVs, so a fresh clone comes up with a working app
and ``benchmark`` has something to measure. Deterministic for a given
``--seed``. Where the real CSVs *are* present, ``import_dataset`` supersedes
it — the two are mutually exclusive, both replacing the dataset wholesale.

Team and tournament names are invented and need not match the real dataset;
names outside ``COUNTRY_BY_COMPETITION`` (frontend ``competitions.ts``) simply
group under "Other" in the competitions filter.
"""

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Game, StreamingOffer, StreamingPackage

BATCH_SIZE = 1000

# Tournaments with team-pool sizes; reference teams from the challenge are
# pinned into specific pools so the four benchmark queries return real work.
TOURNAMENTS: list[tuple[str, int, list[str]]] = [
    ("Bundesliga", 18, ["RB Leipzig", "Bayern München", "Borussia Dortmund"]),
    ("2. Bundesliga", 18, []),
    ("UEFA Champions League", 32, ["RB Leipzig", "Real Madrid", "AS Rom"]),
    ("UEFA Europa League", 32, ["AS Rom"]),
    ("Premier League", 20, ["Oxford United"]),
    ("Süper Lig", 20, ["Hatayspor"]),
    ("MLS", 28, ["Los Angeles FC"]),
    ("Freundschaftsspiele", 24, ["Deutschland", "Real Madrid"]),
]


class Command(BaseCommand):
    help = "Replace the dataset with deterministic synthetic data (pre-CSV benchmarking)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--games", type=int, default=5000)
        parser.add_argument("--packages", type=int, default=40)
        parser.add_argument("--seed", type=int, default=42)

    def handle(self, *args: Any, **options: Any) -> None:
        rng = random.Random(options["seed"])
        n_games: int = options["games"]
        n_packages: int = options["packages"]

        pools: dict[str, list[str]] = {}
        for name, size, pinned in TOURNAMENTS:
            generic = [f"{name} Team {i:02d}" for i in range(1, size - len(pinned) + 1)]
            pools[name] = pinned + generic

        season_start = datetime(2024, 7, 15, tzinfo=UTC)
        games = []
        for game_id in range(1, n_games + 1):
            tournament = rng.choice(TOURNAMENTS)[0]
            home, away = rng.sample(pools[tournament], 2)
            starts_at = season_start + timedelta(
                days=rng.randint(0, 320), hours=rng.choice([13, 15, 17, 18, 20]), minutes=30
            )
            games.append(
                Game(
                    id=game_id,
                    team_home=home,
                    team_away=away,
                    starts_at=starts_at,
                    tournament_name=tournament,
                )
            )

        packages = []
        package_tournaments: dict[int, set[str]] = {}
        for package_id in range(1, n_packages + 1):
            monthly = rng.randint(5, 60) * 100 - 1 if rng.random() > 0.20 else None
            yearly = None
            if rng.random() > 0.15:
                base = monthly if monthly is not None else rng.randint(5, 60) * 100 - 1
                yearly = int(base * rng.uniform(0.6, 0.95))
            # Keep a couple of fully unbookable packages in the data — the
            # comparison table shows them, the solver must skip them.
            if package_id <= 2:
                monthly = yearly = None
            packages.append(
                StreamingPackage(
                    id=package_id,
                    name=f"Streaming Package {package_id:02d}",
                    monthly_price_cents=monthly,
                    monthly_price_yearly_subscription_in_cents=yearly,
                )
            )
            covered = rng.sample([t[0] for t in TOURNAMENTS], rng.randint(1, 4))
            package_tournaments[package_id] = set(covered)

        offers = []
        for game in games:
            for package in packages:
                if game.tournament_name not in package_tournaments[package.id]:
                    continue
                if rng.random() > 0.75:
                    continue
                live = rng.random() < 0.8
                highlights = rng.random() < 0.7
                if not live and not highlights:
                    continue
                offers.append(
                    StreamingOffer(
                        game_id=game.id,
                        streaming_package_id=package.id,
                        live=live,
                        highlights=highlights,
                    )
                )

        with transaction.atomic():
            StreamingOffer.objects.all().delete()
            Game.objects.all().delete()
            StreamingPackage.objects.all().delete()
            Game.objects.bulk_create(games, batch_size=BATCH_SIZE)
            StreamingPackage.objects.bulk_create(packages, batch_size=BATCH_SIZE)
            StreamingOffer.objects.bulk_create(offers, batch_size=BATCH_SIZE)

        self.stdout.write(
            self.style.SUCCESS(
                f"Synthetic dataset: {len(games)} games, {len(packages)} packages, "
                f"{len(offers)} offers (seed {options['seed']})."
            )
        )

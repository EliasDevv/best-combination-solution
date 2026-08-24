"""Import the three challenge CSV files into the database.

Idempotent: existing rows are wiped inside a single transaction before the
fresh data is inserted, so re-running the command always yields exactly the
CSV contents. Uses ``bulk_create`` with batching for speed.
"""

import csv
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.models import Game, StreamingOffer, StreamingPackage
from catalog.normalize import find_suspicious_collisions

BATCH_SIZE = 1000

# The challenge dataset ships with a "bc_" prefix; accept both spellings.
_FILE_CANDIDATES = {
    "games": ("bc_game.csv", "game.csv", "games.csv"),
    "packages": ("bc_streaming_package.csv", "streaming_package.csv", "streaming_packages.csv"),
    "offers": ("bc_streaming_offer.csv", "streaming_offer.csv", "streaming_offers.csv"),
}


def _find_csv(directory: Path, kind: str) -> Path:
    for candidate in _FILE_CANDIDATES[kind]:
        path = directory / candidate
        if path.exists():
            return path
    raise CommandError(
        f"No {kind} CSV found in {directory} (looked for: {', '.join(_FILE_CANDIDATES[kind])})"
    )


def _parse_int_or_none(value: str) -> int | None:
    value = value.strip()
    return int(value) if value else None


def _parse_bool(value: str) -> bool:
    return value.strip() in {"1", "true", "True"}


def _parse_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _read_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


class Command(BaseCommand):
    help = "Import games, streaming packages and streaming offers from CSV files."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--path",
            type=Path,
            default=settings.REPO_ROOT / "data",
            help="Directory containing the CSV files (default: <repo>/data).",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        directory: Path = options["path"]
        if not directory.is_dir():
            raise CommandError(f"Not a directory: {directory}")

        games_csv = _find_csv(directory, "games")
        packages_csv = _find_csv(directory, "packages")
        offers_csv = _find_csv(directory, "offers")

        self.stdout.write(f"Reading CSVs from {directory} ...")
        game_rows = _read_rows(games_csv)
        package_rows = _read_rows(packages_csv)
        offer_rows = _read_rows(offers_csv)

        games = [
            Game(
                id=int(row["id"]),
                team_home=row["team_home"].strip(),
                team_away=row["team_away"].strip(),
                starts_at=_parse_datetime(row["starts_at"]),
                tournament_name=row["tournament_name"].strip(),
            )
            for row in game_rows
        ]
        packages = [
            StreamingPackage(
                id=int(row["id"]),
                name=row["name"].strip(),
                monthly_price_cents=_parse_int_or_none(row["monthly_price_cents"]),
                monthly_price_yearly_subscription_in_cents=_parse_int_or_none(
                    row["monthly_price_yearly_subscription_in_cents"]
                ),
            )
            for row in package_rows
        ]
        # Normalization drops noise tokens ("FC", "SV", ...); two raw names
        # differing in those tokens could be distinct clubs silently merged
        # into one team mask — surface them for a human decision.
        team_names = {name for game in games for name in (game.team_home, game.team_away)}
        for key, raw_names in sorted(find_suspicious_collisions(team_names).items()):
            self.stdout.write(
                self.style.WARNING(
                    f"Possible team-name collision on key {key!r}: {', '.join(raw_names)} "
                    "— these share one team mask; verify they are the same club."
                )
            )

        # The challenge dataset contains offers pointing at package ids that are
        # absent from the package CSV; importing them would violate the FK.
        game_ids = {game.id for game in games}
        package_ids = {package.id for package in packages}
        offers = []
        skipped = 0
        for row in offer_rows:
            game_id = int(row["game_id"])
            package_id = int(row["streaming_package_id"])
            if game_id not in game_ids or package_id not in package_ids:
                skipped += 1
                continue
            offers.append(
                StreamingOffer(
                    game_id=game_id,
                    streaming_package_id=package_id,
                    live=_parse_bool(row["live"]),
                    highlights=_parse_bool(row["highlights"]),
                )
            )
        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    f"Skipped {skipped} offers referencing unknown games or packages."
                )
            )

        with transaction.atomic():
            self.stdout.write("Clearing existing data ...")
            StreamingOffer.objects.all().delete()
            Game.objects.all().delete()
            StreamingPackage.objects.all().delete()

            self.stdout.write(f"Importing {len(games)} games ...")
            Game.objects.bulk_create(games, batch_size=BATCH_SIZE)
            self.stdout.write(f"Importing {len(packages)} packages ...")
            StreamingPackage.objects.bulk_create(packages, batch_size=BATCH_SIZE)
            self.stdout.write(f"Importing {len(offers)} offers ...")
            StreamingOffer.objects.bulk_create(offers, batch_size=BATCH_SIZE)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {Game.objects.count()} games, "
                f"{StreamingPackage.objects.count()} packages, "
                f"{StreamingOffer.objects.count()} offers."
            )
        )
        self.stdout.write("Note: restart the server so the BitIndex is rebuilt from the new data.")

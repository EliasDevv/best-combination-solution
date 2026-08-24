/** Presentation model for the competitions filter.
 *
 * The API knows a competition by one opaque string — the dataset's
 * `tournament_name`, e.g. `"2. Bundesliga 23/24"` — and compare requests must
 * echo it back verbatim. For the dropdown we split that string into the parts
 * a reader scans by (competition, season) and bucket it under a country, so a
 * 40-entry flat list becomes a handful of short groups. Nothing here changes
 * what is sent to the server: `Competition.value` is always the original name.
 */

/** Season suffix the dataset appends to every name: "23/24" or "2024". */
const SEASON_SUFFIX = /\s+(\d{2}\/\d{2}|\d{4})$/;

/** Country is not in the dataset, so the competition itself carries it. */
const COUNTRY_BY_COMPETITION: Readonly<Record<string, string>> = {
  'UEFA Champions League': 'Europe',
  'UEFA Europa League': 'Europe',
  'UEFA Conference League': 'Europe',
  'UEFA Super Cup': 'Europe',
  Europameisterschaft: 'Europe',
  Bundesliga: 'Germany',
  '2. Bundesliga': 'Germany',
  '3. Liga': 'Germany',
  'DFB Pokal': 'Germany',
  Supercup: 'Germany',
  'Premier League': 'England',
  'FA Cup': 'England',
  'EFL Cup': 'England',
  'EFL Trophy': 'England',
  'Community Shield': 'England',
  LaLiga: 'Spain',
  'Copa del Rey': 'Spain',
  Supercopa: 'Spain',
  'Supercup ESP': 'Spain',
  'Serie A': 'Italy',
  'Coppa Italia': 'Italy',
  'Super Cup': 'Italy',
  'Ligue 1': 'France',
  'Coupe de France': 'France',
  'Trophée des Champions': 'France',
  Eredivisie: 'Netherlands',
  'Liga Portugal': 'Portugal',
  'Süper Lig': 'Turkey',
  'Bundesliga AUT': 'Austria',
  'Super League': 'Switzerland',
  'Saudi Prof. League': 'Saudi Arabia',
  'Major League Soccer': 'USA',
};

/** Continental competitions lead; the catch-all trails. Countries sort A–Z. */
const FIRST_GROUP = 'Europe';
const LAST_GROUP = 'Other';

export interface Competition {
  /** The `tournament_name` the API expects — never derived, never rewritten. */
  value: string;
  /** Name without the season, e.g. "2. Bundesliga". */
  name: string;
  /** "23/24", "2024", or '' when the name carries no season. */
  season: string;
  country: string;
}

export interface CompetitionGroup {
  country: string;
  items: Competition[];
}

export function parseCompetition(value: string): Competition {
  const match = SEASON_SUFFIX.exec(value);
  const name = match ? value.slice(0, match.index) : value;
  return {
    value,
    name,
    season: match ? match[1] : '',
    country: COUNTRY_BY_COMPETITION[name] ?? LAST_GROUP,
  };
}

function compareGroups(a: string, b: string): number {
  if (a === b) {
    return 0;
  }
  if (a === FIRST_GROUP || b === LAST_GROUP) {
    return -1;
  }
  if (b === FIRST_GROUP || a === LAST_GROUP) {
    return 1;
  }
  return a.localeCompare(b);
}

/**
 * Group competitions by country, keeping only those matching `query`.
 *
 * The query is a plain substring match against the full name, season included,
 * so "bundesliga 24/25" narrows to one season. Empty groups are dropped.
 */
export function groupCompetitions(values: readonly string[], query = ''): CompetitionGroup[] {
  const needle = query.trim().toLowerCase();
  const groups = new Map<string, Competition[]>();

  for (const value of values) {
    const competition = parseCompetition(value);
    if (needle && !value.toLowerCase().includes(needle)) {
      continue;
    }
    const items = groups.get(competition.country);
    if (items) {
      items.push(competition);
    } else {
      groups.set(competition.country, [competition]);
    }
  }

  return [...groups.entries()]
    .map(([country, items]) => ({
      country,
      items: items.sort((a, b) => a.name.localeCompare(b.name) || a.season.localeCompare(b.season)),
    }))
    .sort((a, b) => compareGroups(a.country, b.country));
}

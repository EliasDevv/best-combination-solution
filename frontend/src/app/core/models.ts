export type Requirement = 'live' | 'highlights' | 'both';
export type Objective = 'min_price' | 'min_packages';
export type Billing = 'monthly_chained' | 'yearly' | 'flexible';

export interface CompareRequest {
  teams: string[];
  tournaments?: string[];
  date_from?: string | null;
  date_to?: string | null;
  requirement?: Requirement;
  objective?: Objective;
  billing?: Billing;
}

export interface Game {
  id: number;
  home: string;
  away: string;
  starts_at: string;
  tournament: string;
}

export interface PackageResult {
  id: number;
  name: string;
  live_idx: number[]; // indices into games[], not game ids
  highlight_idx: number[];
  cost_cents: number | null; // null = not bookable, not free
}

export interface Combination {
  package_ids: number[];
  cost_cents: number;
  coverage: number;
  exact: boolean; // false = solver hit its time budget, result not proven optimal
}

export interface ParetoPoint {
  coverage: number;
  cost_cents: number;
  package_ids: number[];
}

export interface CompareResponse {
  games: Game[];
  packages: PackageResult[];
  best_combination: Combination;
  pareto: ParetoPoint[];
  unknown_teams: string[];
}

export interface TeamsResponse {
  teams: string[];
}

export interface TournamentsResponse {
  tournaments: string[];
}

export interface SavedSearch {
  id: string;
  created_at: string;
  params: CompareRequest;
  result_summary: Combination;
}

export interface SearchesResponse {
  searches: SavedSearch[];
}

import { DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Router } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { ComparisonStore } from '../../core/comparison.store';
import { Billing, Objective, PackageResult, Requirement } from '../../core/models';
import { RecentSearchesComponent } from '../searches/recent-searches.component';
import { TeamSearchComponent } from '../team-search/team-search.component';
import { ComparisonMatrixComponent } from './comparison-matrix.component';
import { CompetitionsDropdownComponent } from './competitions-dropdown.component';
import { DateFieldComponent } from './date-field.component';

const REQUIREMENT_OPTIONS: ReadonlyArray<{ value: Requirement; label: string }> = [
  { value: 'both', label: 'Live + Highlights' },
  { value: 'live', label: 'Live' },
  { value: 'highlights', label: 'Highlights' },
];

interface LedgerLine {
  pkg: PackageResult;
  covered: number;
}

interface ParetoRow {
  coverage: number;
  cost_cents: number;
  names: string;
}

/** Game counts, grouped the German way: 3161 → "3.161". `DecimalPipe` renders
 * en-US ("3,161") and switching its locale would drag the decimal separator of
 * every price along with it. */
function grouped(value: number): string {
  return value.toLocaleString('de-DE');
}

/** Games a package covers under the active requirement. */
function coveredBy(pkg: PackageResult, requirement: Requirement): number {
  if (requirement === 'live') {
    return pkg.live_idx.length;
  }
  if (requirement === 'highlights') {
    return pkg.highlight_idx.length;
  }
  const highlights = new Set(pkg.highlight_idx);
  return pkg.live_idx.filter((idx) => highlights.has(idx)).length;
}

@Component({
  selector: 'app-comparison',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DecimalPipe,
    TeamSearchComponent,
    ComparisonMatrixComponent,
    CompetitionsDropdownComponent,
    DateFieldComponent,
    RecentSearchesComponent,
  ],
  template: `
    <section class="comparison">
      <div class="hero" [class.compact]="hasResults()">
        <header class="page-head">
          <h1>Find the cheapest package combination</h1>
          <p class="tagline">
            Select teams to see which streaming packages cover their games and what the cheapest
            combination costs.
          </p>
        </header>

        <div class="search-row">
          <app-team-search (teamSelected)="addTeam($event)" />
          @if (!allGames()) {
            <button type="button" class="primary" (click)="setAllGames(true)">
              Compare all games
            </button>
          }

          <div class="selected-teams">
            @if (allGames()) {
              <span class="chip chip-all">
                All teams
                <button
                  type="button"
                  (click)="setAllGames(false)"
                  aria-label="Remove all-teams filter"
                >
                  ×
                </button>
              </span>
            }
            @for (team of teams(); track team) {
              <span class="chip">
                {{ team }}
                <button type="button" (click)="removeTeam(team)" aria-label="Remove team">×</button>
              </span>
            }
          </div>
        </div>
      </div>

      @if (teams().length > 0 || allGames()) {
        <form class="controls">
          <div class="segmented" role="group" aria-label="Coverage">
            @for (option of coverageOptions; track option.value) {
              <button
                type="button"
                [attr.aria-pressed]="requirement() === option.value"
                (click)="setValue('require', option.value)"
              >
                {{ option.label }}
              </button>
            }
          </div>
          <label class="field-inline">
            Objective:
            <select [value]="objective()" (change)="setParam('objective', $event)">
              <option value="min_price">Cheapest price</option>
              <option value="min_packages">Fewest services</option>
            </select>
          </label>
          <label class="field-inline">
            Billing:
            <select [value]="billing()" (change)="setParam('billing', $event)">
              <option value="monthly_chained">Monthly, chained</option>
              <option value="yearly">Yearly</option>
              <option value="flexible">Flexible</option>
            </select>
          </label>
          <div class="date-range">
            <app-date-field
              label="From"
              [value]="dateFrom()"
              (valueChange)="setValue('from', $event ?? '')"
            />
            <span class="dash">–</span>
            <app-date-field
              label="To"
              [value]="dateTo()"
              (valueChange)="setValue('to', $event ?? '')"
            />
          </div>
          @if (allTournaments().length > 0) {
            <app-competitions-dropdown
              [all]="allTournaments()"
              [selected]="tournaments()"
              (applied)="setTournaments($event)"
            />
          }
        </form>
      }

      @if (store.loading()) {
        <p class="status">Crunching packages…</p>
      } @else if (store.error()) {
        <p class="status error">{{ store.error() }}</p>
      } @else if (store.response()) {
        @if (store.unknownTeams().length > 0) {
          <p class="status error">
            No games found for: {{ store.unknownTeams().join(', ') }} — check the spelling or
            pick a suggestion from the search box.
          </p>
        }
        @if (summary(); as best) {
          <aside class="summary-card">
            <div class="summary-head">
              <h2>Best combination</h2>
              <span class="coverage">
                Covers
                <strong>
                  {{ grouped(store.coveredGames()) }} of {{ grouped(store.games().length) }} games
                </strong>
              </span>
            </div>
            @if (best.package_ids.length > 0) {
              <div class="ledger">
                @for (line of ledger(); track line.pkg.id) {
                  <div class="ledger-row">
                    <span class="name">{{ line.pkg.name }}</span>
                    <span class="meta">
                      covers {{ grouped(line.covered) }}
                      {{ line.covered === 1 ? 'game' : 'games' }}
                    </span>
                    <span class="amount">
                      @if (line.pkg.cost_cents !== null) {
                        {{ line.pkg.cost_cents / 100 | number: '1.2-2' }} €
                      } @else {
                        <span class="muted">—</span>
                      }
                    </span>
                  </div>
                }
                <div class="ledger-row total">
                  <span class="name">Total</span>
                  <span class="amount">{{ best.cost_cents / 100 | number: '1.2-2' }} €</span>
                </div>
                @if (repriced()) {
                  <p class="ledger-footnote">
                    Packages are only charged for the months they're needed in this combination.
                  </p>
                }
              </div>
              @if (!best.exact) {
                <p class="summary-note">
                  Best combination found within the solver's time budget — a cheaper one may
                  exist.
                </p>
              }
              @if (best.coverage < 1) {
                <p class="summary-note">
                  <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
                    <path
                      d="M6.5 1.5L12 11.5H1L6.5 1.5Z"
                      fill="none"
                      stroke="#8a5b00"
                      stroke-width="1.2"
                      stroke-linejoin="round"
                    />
                    <path d="M6.5 5.2V7.8" stroke="#8a5b00" stroke-width="1.2" stroke-linecap="round" />
                    <circle cx="6.5" cy="9.6" r="0.65" fill="#8a5b00" />
                  </svg>
                  <span>
                    {{ uncoveredGames() | number }}
                    {{ uncoveredGames() === 1 ? 'game is' : 'games are' }} not streamed by any
                    package matching your filters.
                  </span>
                </p>
              }
            } @else {
              <p class="summary-note">No bookable package covers any of these games.</p>
            }
          </aside>
        }

        @if (store.games().length > 0) {
          <app-comparison-matrix
            [games]="store.games()"
            [packages]="store.rankedPackages()"
            [bestCombination]="store.bestCombination()"
          />
        } @else if (emptyReason()) {
          <p class="status">{{ emptyReason() }}</p>
        }

        @if (store.pareto().length > 1) {
          <section class="pareto">
            <h2>Cheaper alternatives</h2>
            <table>
              <thead>
                <tr>
                  <th>Coverage</th>
                  <th>Price</th>
                  <th>Packages</th>
                </tr>
              </thead>
              <tbody>
                @for (row of paretoRows(); track $index) {
                  <tr [class.current]="$index === 0">
                    <td>{{ row.coverage * 100 | number: '1.0-0' }}%</td>
                    <td>{{ row.cost_cents / 100 | number: '1.2-2' }} €</td>
                    <td>{{ row.names }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </section>
        }
      } @else {
        <app-recent-searches />
      }
    </section>
  `,
})
export class ComparisonComponent {
  readonly coverageOptions = REQUIREMENT_OPTIONS;

  readonly store = inject(ComparisonStore);
  private readonly api = inject(ApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  private readonly params = toSignal(this.route.queryParamMap);

  readonly teams = computed(() => (this.params()?.get('teams') ?? '').split(',').filter(Boolean));
  readonly allGames = computed(() => this.params()?.get('all') === '1');
  readonly tournaments = computed(() =>
    (this.params()?.get('tournaments') ?? '').split(',').filter(Boolean),
  );
  readonly requirement = computed(
    () => (this.params()?.get('require') as Requirement) ?? 'live',
  );
  readonly objective = computed(() => (this.params()?.get('objective') as Objective) ?? 'min_price');
  readonly billing = computed(
    () => (this.params()?.get('billing') as Billing) ?? 'monthly_chained',
  );
  readonly dateFrom = computed(() => this.params()?.get('from') ?? null);
  readonly dateTo = computed(() => this.params()?.get('to') ?? null);

  readonly allTournaments = signal<string[]>([]);

  readonly uncoveredGames = computed(() => this.store.games().length - this.store.coveredGames());

  readonly grouped = grouped;

  /** Results on screen: the centred head shrinks so the ledger starts above the fold. */
  readonly hasResults = computed(() => this.store.response() !== null);

  /** The ledger summarises games — with none to summarise the card would only
   * report "no bookable package", naming the wrong cause. */
  readonly summary = computed(() =>
    this.store.games().length > 0 ? this.store.bestCombination() : null,
  );

  /** Why the result is empty, in the user's terms. Empty string when the
   * unknown-teams warning above already says it. */
  readonly emptyReason = computed(() => {
    if (this.store.unknownTeams().length >= this.teams().length && this.teams().length > 0) {
      return '';
    }
    if (this.dateFrom() || this.dateTo()) {
      return 'No games in the selected date range.';
    }
    if (this.tournaments().length > 0) {
      return 'No games in the selected competitions.';
    }
    return 'No games match your selection.';
  });

  /** One row per package in the best combination, with its covered-game count
   * resolved once. Counting in the template instead would rebuild a Set of
   * highlight indices — thousands of entries for the all-games query — on
   * every change-detection pass. */
  readonly ledger = computed<LedgerLine[]>(() => {
    const requirement = this.requirement();
    return this.store.bestPackages().map((pkg) => ({ pkg, covered: coveredBy(pkg, requirement) }));
  });

  /** Pareto rows with their package ids already resolved to names. */
  readonly paretoRows = computed<ParetoRow[]>(() => {
    const names = this.store.packageNames();
    return this.store.pareto().map((point) => ({
      coverage: point.coverage,
      cost_cents: point.cost_cents,
      names: point.package_ids.map((id) => names.get(id) ?? `#${id}`).join(' + '),
    }));
  });

  /** True when the combination total differs from the sum of standalone prices. */
  readonly repriced = computed(() => {
    const best = this.store.bestCombination();
    if (!best) {
      return false;
    }
    const standalone = this.store
      .bestPackages()
      .reduce((sum, pkg) => sum + (pkg.cost_cents ?? 0), 0);
    return standalone !== best.cost_cents;
  });

  constructor() {
    this.api.getTournaments().subscribe((res) => this.allTournaments.set(res.tournaments));

    // url is the source of truth: actions navigate, query-param changes load
    effect(() => {
      const teams = this.teams();
      if (teams.length === 0 && !this.allGames()) {
        this.store.reset();
        return;
      }
      this.store.load({
        teams,
        tournaments: this.tournaments(),
        requirement: this.requirement(),
        objective: this.objective(),
        billing: this.billing(),
        date_from: this.dateFrom(),
        date_to: this.dateTo(),
      });
    });
  }

  addTeam(team: string): void {
    this.navigate({ teams: this.joinOrNull([...new Set([...this.teams(), team])]), all: null });
  }

  removeTeam(team: string): void {
    this.navigate({ teams: this.joinOrNull(this.teams().filter((t) => t !== team)) });
  }

  setAllGames(enabled: boolean): void {
    this.navigate(enabled ? { all: '1', teams: null } : { all: null });
  }

  /** One navigation per Apply, not per checkbox — each one costs a compare. */
  setTournaments(names: string[]): void {
    this.navigate({ tournaments: this.joinOrNull(names) });
  }

  setParam(param: string, event: Event): void {
    const value = (event.target as HTMLInputElement | HTMLSelectElement).value;
    this.setValue(param, value);
  }

  setValue(param: string, value: string): void {
    this.navigate({ [param]: value || null });
  }

  private joinOrNull(values: string[]): string | null {
    return values.length ? values.join(',') : null;
  }

  private navigate(queryParams: Record<string, string | null>): void {
    this.router.navigate([], {
      relativeTo: this.route,
      queryParams,
      queryParamsHandling: 'merge',
    });
  }
}

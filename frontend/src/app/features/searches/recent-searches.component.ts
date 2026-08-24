import { DecimalPipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { RouterLink } from '@angular/router';

import { ApiService } from '../../core/api.service';
import { CompareRequest, SavedSearch } from '../../core/models';

const MAX_SHOWN = 10;

// defaults omitted so links match what the app itself puts in the url
export function searchQueryParams(params: CompareRequest): Record<string, string> {
  const query: Record<string, string> = {};
  if (params.teams.length > 0) {
    query['teams'] = params.teams.join(',');
  } else {
    query['all'] = '1';
  }
  if (params.tournaments?.length) {
    query['tournaments'] = params.tournaments.join(',');
  }
  if (params.requirement && params.requirement !== 'live') {
    query['require'] = params.requirement;
  }
  if (params.objective && params.objective !== 'min_price') {
    query['objective'] = params.objective;
  }
  if (params.billing && params.billing !== 'monthly_chained') {
    query['billing'] = params.billing;
  }
  if (params.date_from) {
    query['from'] = params.date_from;
  }
  if (params.date_to) {
    query['to'] = params.date_to;
  }
  return query;
}

@Component({
  selector: 'app-recent-searches',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DecimalPipe, RouterLink],
  template: `
    @if (searches().length > 0) {
      <section class="recent-searches">
        <div class="head">
          <h2>Recent searches</h2>
          <button type="button" class="clear" (click)="clear()">Clear</button>
        </div>
        <ul>
          @for (search of searches(); track search.id) {
            <li>
              <svg
                class="clock"
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
                aria-hidden="true"
              >
                <circle cx="7" cy="7" r="5.4" stroke="currentColor" stroke-width="1.3" />
                <path
                  d="M7 4.1V7l2 1.5"
                  stroke="currentColor"
                  stroke-width="1.3"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
              <a [routerLink]="['/compare']" [queryParams]="queryParams(search)">
                {{ label(search) }}
              </a>
              <span class="figures">
                {{ search.result_summary.coverage * 100 | number: '1.0-0' }}% covered
              </span>
              <span class="figures price">
                {{ search.result_summary.cost_cents / 100 | number: '1.2-2' }} €
              </span>
              <button
                type="button"
                class="remove"
                [attr.aria-label]="'Remove search: ' + label(search)"
                (click)="remove(search)"
              >
                ×
              </button>
            </li>
          }
        </ul>
      </section>
    }
  `,
  // presentation lives in styles.scss with the rest of the design tokens
})
export class RecentSearchesComponent {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);

  readonly searches = signal<SavedSearch[]>([]);

  constructor() {
    this.api
      .getSavedSearches()
      .pipe(takeUntilDestroyed())
      .subscribe({
        next: (response) => this.searches.set(response.searches.slice(0, MAX_SHOWN)),
        error: () => this.searches.set([]), // optional panel, failures just hide it
      });
  }

  queryParams(search: SavedSearch): Record<string, string> {
    return searchQueryParams(search.params);
  }

  label(search: SavedSearch): string {
    return search.params.teams.length > 0 ? search.params.teams.join(', ') : 'All games';
  }

  /** Drop the row immediately, put it back if the server rejects the delete. */
  remove(search: SavedSearch): void {
    const previous = this.searches();
    this.searches.set(previous.filter((entry) => entry.id !== search.id));
    this.api
      .deleteSavedSearch(search.id)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ error: () => this.searches.set(previous) });
  }

  /** Wipe the whole history, same optimistic pattern as a single removal. */
  clear(): void {
    const previous = this.searches();
    this.searches.set([]);
    this.api
      .clearSavedSearches()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({ error: () => this.searches.set(previous) });
  }
}

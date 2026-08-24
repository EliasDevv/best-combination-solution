import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  output,
  signal,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, debounceTime, distinctUntilChanged, map, of, switchMap, tap } from 'rxjs';

import { ApiService } from '../../core/api.service';

/** A suggestion split around the matched query, so the hit can be emphasised. */
interface TeamMatch {
  team: string;
  before: string;
  hit: string;
  after: string;
}

@Component({
  selector: 'app-team-search',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(document:click)': 'onDocumentClick($event)',
  },
  template: `
    <div class="team-search">
      <div class="field">
        <input
          #input
          type="search"
          placeholder="Search..."
          [value]="query()"
          (input)="onInput($event)"
          (keydown.enter)="submit()"
          (keydown.escape)="dismiss()"
          aria-label="Search teams"
        />
        <button type="button" class="search-button" (click)="submit()" aria-label="Search">
          <svg width="17" height="17" viewBox="0 0 17 17" fill="none" aria-hidden="true">
            <circle cx="7.25" cy="7.25" r="5.25" stroke="currentColor" stroke-width="1.7" />
            <path
              d="M11.25 11.25L15 15"
              stroke="currentColor"
              stroke-width="1.7"
              stroke-linecap="round"
            />
          </svg>
        </button>
      </div>
      @if (!dismissed()) {
        @if (matches().length > 0) {
          <ul class="suggestions">
            @for (match of matches(); track match.team) {
              <li>
                <button type="button" (click)="select(match.team)"
                  >{{ match.before }}<strong>{{ match.hit }}</strong>{{ match.after }}</button
                >
              </li>
            }
          </ul>
        } @else if (showEmptyState()) {
          <ul class="suggestions">
            <li class="empty" aria-live="polite">No teams found for '{{ settledQuery() }}'</li>
          </ul>
        }
      }
    </div>
  `,
})
export class TeamSearchComponent {
  private readonly api = inject(ApiService);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly query$ = new Subject<string>();
  private readonly input = viewChild.required<ElementRef<HTMLInputElement>>('input');

  readonly teamSelected = output<string>();

  readonly query = signal('');
  readonly suggestions = signal<string[]>([]);
  readonly loading = signal(false);
  readonly dismissed = signal(false);
  // Last query whose API response has arrived; '' while none has settled.
  readonly settledQuery = signal('');

  readonly showEmptyState = computed(
    () =>
      !this.loading() &&
      this.settledQuery() !== '' &&
      this.settledQuery() === this.query() &&
      this.suggestions().length === 0,
  );

  readonly matches = computed<TeamMatch[]>(() => {
    const needle = this.settledQuery().trim().toLowerCase();
    return this.suggestions().map((team) => {
      const at = needle ? team.toLowerCase().indexOf(needle) : -1;
      if (at < 0) {
        return { team, before: team, hit: '', after: '' };
      }
      return {
        team,
        before: team.slice(0, at),
        hit: team.slice(at, at + needle.length),
        after: team.slice(at + needle.length),
      };
    });
  });

  constructor() {
    this.query$
      .pipe(
        debounceTime(200),
        distinctUntilChanged(),
        switchMap((value) => {
          if (value.trim().length < 2) {
            return of({ value, teams: [] as string[], searched: false });
          }
          return this.api.searchTeams(value).pipe(
            tap({ subscribe: () => this.loading.set(true) }),
            map((res) => ({ value, teams: res.teams, searched: true })),
          );
        }),
        takeUntilDestroyed(),
      )
      .subscribe(({ value, teams, searched }) => {
        this.loading.set(false);
        this.suggestions.set(teams);
        this.settledQuery.set(searched ? value : '');
      });
  }

  onInput(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.query.set(value);
    this.dismissed.set(false);
    this.query$.next(value);
  }

  select(team: string): void {
    this.teamSelected.emit(team);
    this.query.set('');
    this.suggestions.set([]);
    this.settledQuery.set('');
    this.loading.set(false);
    this.query$.next('');
  }

  /** Button/Enter: take the top suggestion, or put the caret back in the field. */
  submit(): void {
    const [first] = this.matches();
    if (first && !this.dismissed()) {
      this.select(first.team);
      return;
    }
    this.input().nativeElement.focus();
  }

  dismiss(): void {
    this.dismissed.set(true);
  }

  /**
   * Anything clicked outside the field closes the dropdown.
   *
   * Escape alone was not enough: the panel is absolutely positioned above the
   * page, so a "no teams found" left standing after the user gave up on the
   * typo and reached for "Compare all games" would hang over the results.
   */
  onDocumentClick(event: MouseEvent): void {
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.dismissed.set(true);
    }
  }
}

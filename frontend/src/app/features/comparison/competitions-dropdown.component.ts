import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  effect,
  inject,
  input,
  output,
  signal,
  untracked,
  viewChild,
} from '@angular/core';

import { CompetitionGroup, groupCompetitions } from './competitions';

/**
 * Multi-select competitions filter: search, country groups, sticky footer.
 *
 * Selections are staged locally while the panel is open and only leave the
 * component on Apply — every commit costs the parent a compare request, so a
 * six-checkbox edit must not fire six of them. Escape or a click outside
 * discards the draft, which is what the Apply button promises.
 */
@Component({
  selector: 'app-competitions-dropdown',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(document:click)': 'onDocumentClick($event)',
    '(document:keydown.escape)': 'cancel()',
  },
  template: `
    <button
      type="button"
      class="trigger"
      [class.open]="open()"
      [attr.aria-expanded]="open()"
      aria-haspopup="dialog"
      (click)="toggleOpen()"
    >
      Competitions
      @if (count() > 0) {
        <span class="count">{{ count() }}</span>
      }
      <svg class="chevron" width="14" height="14" viewBox="0 0 20 20" aria-hidden="true">
        <path
          d="M5.5 8L10 12.5L14.5 8"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </button>

    @if (open()) {
      <div class="panel" role="dialog" aria-label="Filter by competition">
        <div class="panel-search">
          <div class="search-field">
            <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
              <circle cx="7.2" cy="7.2" r="4.6" fill="none" stroke="currentColor" stroke-width="1.6" />
              <path d="M10.8 10.8L14 14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
            <input
              #search
              type="search"
              placeholder="Search competitions"
              [value]="query()"
              (input)="onQuery($event)"
              aria-label="Search competitions"
            />
          </div>
        </div>

        <div class="panel-list">
          @for (group of groups(); track group.country) {
            <p class="group-head">{{ group.country }}</p>
            @for (item of group.items; track item.value) {
              <label class="option">
                <input
                  type="checkbox"
                  [checked]="isChecked(item.value)"
                  (change)="toggle(item.value)"
                />
                <span class="option-name">{{ item.name }}</span>
                <span class="option-season">{{ item.season }}</span>
              </label>
            }
          } @empty {
            <p class="option-empty" aria-live="polite">
              No competitions match '{{ query().trim() }}'
            </p>
          }
        </div>

        <div class="panel-foot">
          <button type="button" class="clear" [disabled]="count() === 0" (click)="clear()">
            Clear all
          </button>
          <button type="button" class="apply" (click)="apply()">Apply</button>
        </div>
      </div>
    }
  `,
})
export class CompetitionsDropdownComponent {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly search = viewChild<ElementRef<HTMLInputElement>>('search');

  /** Every selectable `tournament_name`, as returned by GET /api/tournaments. */
  readonly all = input.required<readonly string[]>();
  /** The committed selection; re-read whenever the panel opens. */
  readonly selected = input<readonly string[]>([]);

  readonly applied = output<string[]>();

  readonly open = signal(false);
  readonly query = signal('');
  private readonly draft = signal<ReadonlySet<string>>(new Set<string>());

  readonly groups = computed<CompetitionGroup[]>(() =>
    groupCompetitions(this.all(), this.query()),
  );
  readonly count = computed(() => this.draft().size);

  constructor() {
    // A parent-driven change (a shared link, the browser's back button) must
    // win over a stale draft, so the buffer follows the input while closed.
    // `open` is read untracked: closing the panel is not itself a reason to
    // re-read a selection the parent has not committed yet.
    effect(() => {
      const committed = this.selected();
      if (!untracked(this.open)) {
        this.draft.set(new Set(committed));
      }
    });

    effect(() => {
      if (this.open()) {
        this.search()?.nativeElement.focus();
      }
    });
  }

  isChecked(value: string): boolean {
    return this.draft().has(value);
  }

  toggleOpen(): void {
    if (this.open()) {
      this.cancel();
    } else {
      this.open.set(true);
    }
  }

  toggle(value: string): void {
    const next = new Set(this.draft());
    if (!next.delete(value)) {
      next.add(value);
    }
    this.draft.set(next);
  }

  clear(): void {
    this.draft.set(new Set<string>());
  }

  apply(): void {
    this.applied.emit([...this.draft()]);
    this.close();
  }

  /** Leave without committing: drop the draft back to the committed selection. */
  cancel(): void {
    if (!this.open()) {
      return;
    }
    this.draft.set(new Set(this.selected()));
    this.close();
  }

  private close(): void {
    this.open.set(false);
    this.query.set('');
  }

  onQuery(event: Event): void {
    this.query.set((event.target as HTMLInputElement).value);
  }

  onDocumentClick(event: MouseEvent): void {
    if (!this.host.nativeElement.contains(event.target as Node)) {
      this.cancel();
    }
  }
}

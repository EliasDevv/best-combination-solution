import { DatePipe, DecimalPipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

import { Combination, Game, PackageResult } from '../../core/models';

interface MatrixColumn {
  pkg: PackageResult;
  live: Set<number>;
  highlights: Set<number>;
  inBest: boolean;
}

interface RollupCell {
  live: number;
  highlights: number;
  total: number;
  /** '✓' all, '◐' some, '·' none — resolved here, not per change detection. */
  liveSymbol: string;
  highlightSymbol: string;
  /** '12 of 34 games' — reused for the tooltip and the a11y label. */
  liveLabel: string;
  highlightLabel: string;
}

interface TournamentGroup {
  name: string;
  indices: number[];
  cells: RollupCell[];
  expanded: boolean;
}

/** Hover label anchored to a cell; coordinates are relative to the host element. */
interface Tip {
  text: string;
  x: number;
  y: number;
  below: boolean;
}

/** Half the tooltip's width — used to keep it inside the matrix' own box. */
const TIP_HALF_WIDTH = 60;
/** Below this viewport offset the tooltip would collide with the sticky header. */
const TIP_FLIP_ABOVE = 140;

function symbol(count: number, total: number): string {
  if (count === total) {
    return '✓';
  }
  return count > 0 ? '◐' : '·';
}

function coverageLabel(count: number, total: number): string {
  return `${count} of ${total} ${total === 1 ? 'game' : 'games'}`;
}

@Component({
  selector: 'app-comparison-matrix',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, DecimalPipe],
  host: { '(mouseleave)': 'hideTip()' },
  template: `
    <div class="matrix-scroll" (mouseover)="showTip($event)" (scroll)="hideTip()">
      <table class="matrix">
        <thead>
          <tr>
            <th class="corner" scope="col">
              <span class="corner-label">Your competitions</span>
            </th>
            @for (col of columns(); track col.pkg.id) {
              <th class="pkg-head" colspan="2" scope="colgroup" [class.best]="col.inBest">
                @if (col.inBest) {
                  <span class="badge">Best combination</span>
                }
                <span class="pkg-name" [title]="col.pkg.name">{{ col.pkg.name }}</span>
                <span class="pkg-price">
                  @if (col.pkg.cost_cents !== null) {
                    {{ col.pkg.cost_cents / 100 | number: '1.2-2' }} €
                  } @else {
                    <span class="muted" title="Not bookable for this billing mode">—</span>
                  }
                </span>
              </th>
            }
          </tr>
          <tr class="sub-head">
            <th class="corner" scope="col"></th>
            @for (col of columns(); track col.pkg.id) {
              <th scope="col" [class.best]="col.inBest">Live</th>
              <th scope="col" class="pair-end" [class.best]="col.inBest">Highl.</th>
            }
          </tr>
        </thead>
        <tbody>
          @for (group of groups(); track group.name; let gi = $index) {
            <tr class="group-row">
              <th scope="row">
                <button
                  type="button"
                  class="group-toggle"
                  (click)="toggle(group.name)"
                  [attr.aria-expanded]="group.expanded"
                >
                  <span class="chevron" [class.open]="group.expanded">▸</span>
                  {{ group.name }}
                  <span class="count">{{ group.indices.length }}</span>
                </button>
              </th>
              @for (cell of group.cells; track $index) {
                <td
                  class="rollup"
                  data-kind="live"
                  [attr.data-col]="$index"
                  [attr.data-group]="gi"
                  [attr.aria-label]="cell.liveLabel"
                  [class.full]="cell.live === cell.total"
                  [class.partial]="cell.live > 0 && cell.live < cell.total"
                >
                  {{ cell.liveSymbol }}
                </td>
                <td
                  class="rollup pair-end"
                  data-kind="highlights"
                  [attr.data-col]="$index"
                  [attr.data-group]="gi"
                  [attr.aria-label]="cell.highlightLabel"
                  [class.full]="cell.highlights === cell.total"
                  [class.partial]="cell.highlights > 0 && cell.highlights < cell.total"
                >
                  {{ cell.highlightSymbol }}
                </td>
              }
            </tr>
            @if (group.expanded) {
              @for (idx of group.indices; track idx) {
                <tr class="game-row">
                  <th scope="row">
                    <span class="pairing">{{ games()[idx].home }} – {{ games()[idx].away }}</span>
                    <time class="kickoff">{{ games()[idx].starts_at | date: 'dd/MM/yy, HH:mm' }}</time>
                  </th>
                  @for (col of columns(); track col.pkg.id) {
                    <td class="cell" [class.on]="col.live.has(idx)">
                      {{ col.live.has(idx) ? '✓' : '·' }}
                    </td>
                    <td class="cell pair-end" [class.on]="col.highlights.has(idx)">
                      {{ col.highlights.has(idx) ? '✓' : '·' }}
                    </td>
                  }
                </tr>
              }
            }
          }
        </tbody>
      </table>
    </div>
    @if (tip(); as t) {
      <span
        class="matrix-tip"
        aria-hidden="true"
        [class.below]="t.below"
        [style.left.px]="t.x"
        [style.top.px]="t.y"
        >{{ t.text }}</span
      >
    }
  `,
})
export class ComparisonMatrixComponent {
  readonly games = input.required<Game[]>();
  readonly packages = input.required<PackageResult[]>();
  readonly bestCombination = input<Combination | null>(null);

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly expanded = signal<ReadonlySet<string>>(new Set());

  readonly tip = signal<Tip | null>(null);

  readonly columns = computed<MatrixColumn[]>(() => {
    const best = new Set(this.bestCombination()?.package_ids ?? []);
    return this.packages().map((pkg) => ({
      pkg,
      live: new Set(pkg.live_idx),
      highlights: new Set(pkg.highlight_idx),
      inBest: best.has(pkg.id),
    }));
  });

  readonly groups = computed<TournamentGroup[]>(() => {
    const byName = new Map<string, number[]>();
    this.games().forEach((game, idx) => {
      const indices = byName.get(game.tournament);
      if (indices) {
        indices.push(idx);
      } else {
        byName.set(game.tournament, [idx]);
      }
    });
    const columns = this.columns();
    const expanded = this.expanded();
    return [...byName.entries()].map(([name, indices]) => ({
      name,
      indices,
      expanded: expanded.has(name),
      cells: columns.map((col) => {
        let live = 0;
        let highlights = 0;
        for (const idx of indices) {
          live += Number(col.live.has(idx));
          highlights += Number(col.highlights.has(idx));
        }
        const total = indices.length;
        return {
          live,
          highlights,
          total,
          liveSymbol: symbol(live, total),
          highlightSymbol: symbol(highlights, total),
          liveLabel: coverageLabel(live, total),
          highlightLabel: coverageLabel(highlights, total),
        };
      }),
    }));
  });

  toggle(name: string): void {
    const next = new Set(this.expanded());
    if (!next.delete(name)) {
      next.add(name);
    }
    this.expanded.set(next);
  }

  /** One delegated listener for the whole table — cells only carry their coordinates. */
  showTip(event: MouseEvent): void {
    const cell =
      event.target instanceof Element ? event.target.closest<HTMLElement>('td[data-col]') : null;
    if (!cell) {
      this.hideTip();
      return;
    }
    const group = this.groups()[Number(cell.dataset['group'])];
    const rollup = group?.cells[Number(cell.dataset['col'])];
    if (!rollup) {
      this.hideTip();
      return;
    }
    const text = cell.dataset['kind'] === 'live' ? rollup.liveLabel : rollup.highlightLabel;
    this.tip.set({ text, ...this.anchor(cell) });
  }

  hideTip(): void {
    this.tip.set(null);
  }

  /** Centres the tooltip over the cell, clamped to the matrix' box so it stays readable. */
  private anchor(cell: HTMLElement): Pick<Tip, 'x' | 'y' | 'below'> {
    const rect = cell.getBoundingClientRect();
    const box = this.host.nativeElement.getBoundingClientRect();
    const below = rect.top < TIP_FLIP_ABOVE;
    let x = rect.left + rect.width / 2 - box.left;
    if (box.width > 2 * TIP_HALF_WIDTH) {
      x = Math.min(Math.max(x, TIP_HALF_WIDTH), box.width - TIP_HALF_WIDTH);
    }
    return { x, y: (below ? rect.bottom + 4 : rect.top - 4) - box.top, below };
  }
}

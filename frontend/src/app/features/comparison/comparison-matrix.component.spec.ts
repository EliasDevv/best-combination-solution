import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CompareResponse } from '../../core/models';
import { ComparisonMatrixComponent } from './comparison-matrix.component';

// same sample data as backend/tests/conftest.py
const RESPONSE: CompareResponse = {
  games: [
    {
      id: 1,
      home: 'Bayern München',
      away: 'RB Leipzig',
      starts_at: '2024-08-24T16:30:00Z',
      tournament: 'Bundesliga',
    },
    {
      id: 2,
      home: 'RB Leipzig',
      away: 'Borussia Dortmund',
      starts_at: '2024-08-31T16:30:00Z',
      tournament: 'Bundesliga',
    },
    {
      id: 3,
      home: 'Real Madrid',
      away: 'RB Leipzig',
      starts_at: '2024-09-17T19:00:00Z',
      tournament: 'UEFA Champions League',
    },
  ],
  packages: [
    { id: 7, name: 'Sky Sport', live_idx: [0, 1], highlight_idx: [0, 1], cost_cents: 4499 },
    { id: 12, name: 'DAZN', live_idx: [2], highlight_idx: [], cost_cents: 29988 },
  ],
  best_combination: { package_ids: [7, 12], cost_cents: 34487, coverage: 1.0, exact: true },
  pareto: [],
  unknown_teams: [],
};

describe('ComparisonMatrixComponent', () => {
  let fixture: ComponentFixture<ComparisonMatrixComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [ComparisonMatrixComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(ComparisonMatrixComponent);
    fixture.componentRef.setInput('games', RESPONSE.games);
    fixture.componentRef.setInput('packages', RESPONSE.packages);
    fixture.componentRef.setInput('bestCombination', RESPONSE.best_combination);
    fixture.detectChanges();
  });

  it('groups games by tournament with rollup coverage counts', () => {
    const groups = fixture.componentInstance.groups();
    expect(groups.map((g) => g.name)).toEqual(['Bundesliga', 'UEFA Champions League']);
    // Sky covers both Bundesliga games live, DAZN none
    expect(groups[0].cells[0].live).toBe(2);
    expect(groups[0].cells[0].total).toBe(2);
    expect(groups[0].cells[1].live).toBe(0);
    // DAZN has the CL game live, no highlights
    expect(groups[1].cells[1].live).toBe(1);
    expect(groups[1].cells[1].highlights).toBe(0);
  });

  it('marks best-combination package headers', () => {
    const heads = fixture.nativeElement.querySelectorAll('th.pkg-head');
    expect(heads.length).toBe(2);
    expect(heads[0].classList).toContain('best');
    expect(heads[0].textContent).toContain('Sky Sport');
    expect(heads[0].textContent).toContain('Best combination');
  });

  it('renders full/partial/none rollup symbols', () => {
    const firstGroupCells = fixture.nativeElement.querySelectorAll('tr.group-row')[0].querySelectorAll('td');
    expect(firstGroupCells[0].textContent.trim()).toBe('✓'); // Sky live, full
    expect(firstGroupCells[2].textContent.trim()).toBe('·'); // DAZN live, none
  });

  it('labels rollup cells with the covered count', () => {
    const cells = fixture.nativeElement.querySelectorAll('tr.group-row')[0].querySelectorAll('td');
    expect(cells[0].getAttribute('aria-label')).toBe('2 of 2 games');
    expect(cells[2].getAttribute('aria-label')).toBe('0 of 2 games');
  });

  it('shows the covered count on rollup hover and hides it again', () => {
    const cell = fixture.nativeElement
      .querySelectorAll('tr.group-row')[0]
      .querySelectorAll('td')[1]; // Sky highlights, Bundesliga
    cell.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    fixture.detectChanges();

    expect(fixture.componentInstance.tip()).toEqual(
      jasmine.objectContaining({ text: '2 of 2 games' }),
    );
    expect(fixture.nativeElement.querySelector('.matrix-tip').textContent).toBe('2 of 2 games');

    fixture.componentInstance.hideTip();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.matrix-tip')).toBeNull();
  });

  it('shows no tooltip outside the rollup cells', () => {
    fixture.componentInstance.toggle('Bundesliga');
    fixture.detectChanges();

    const cell = fixture.nativeElement.querySelectorAll('tr.game-row')[0].querySelectorAll('td')[0];
    cell.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    expect(fixture.componentInstance.tip()).toBeNull();
  });

  it('expands a tournament into game rows on toggle', () => {
    expect(fixture.nativeElement.querySelectorAll('tr.game-row').length).toBe(0);
    fixture.componentInstance.toggle('Bundesliga');
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('tr.game-row');
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain('Bayern München – RB Leipzig');
  });
});

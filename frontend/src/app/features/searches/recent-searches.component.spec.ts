import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { SavedSearch } from '../../core/models';
import { RecentSearchesComponent, searchQueryParams } from './recent-searches.component';

describe('searchQueryParams', () => {
  it('joins teams and omits defaults', () => {
    expect(
      searchQueryParams({
        teams: ['RB Leipzig', 'Real Madrid'],
        tournaments: [],
        requirement: 'live',
        objective: 'min_price',
        billing: 'monthly_chained',
        date_from: null,
        date_to: null,
      }),
    ).toEqual({ teams: 'RB Leipzig,Real Madrid' });
  });

  it('maps empty teams to all=1 and keeps non-defaults', () => {
    expect(
      searchQueryParams({
        teams: [],
        tournaments: ['Bundesliga'],
        requirement: 'both',
        objective: 'min_packages',
        billing: 'yearly',
        date_from: '2024-08-01',
        date_to: null,
      }),
    ).toEqual({
      all: '1',
      tournaments: 'Bundesliga',
      require: 'both',
      objective: 'min_packages',
      billing: 'yearly',
      from: '2024-08-01',
    });
  });
});

describe('RecentSearchesComponent', () => {
  let fixture: ComponentFixture<RecentSearchesComponent>;
  let http: HttpTestingController;

  const SEARCH: SavedSearch = {
    id: '5a2b9d1e-0000-0000-0000-000000000000',
    created_at: '2024-08-01T12:00:00Z',
    params: { teams: ['RB Leipzig'] },
    result_summary: { package_ids: [7], cost_cents: 4499, coverage: 1.0, exact: true },
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(RecentSearchesComponent);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('renders saved searches as links with price and coverage', () => {
    http.expectOne('/api/searches').flush({ searches: [SEARCH] });
    fixture.detectChanges();

    const element: HTMLElement = fixture.nativeElement;
    const link = element.querySelector('a');
    expect(link?.textContent).toContain('RB Leipzig');
    expect(element.textContent).toContain('44.99');
    expect(element.textContent).toContain('100% covered');
  });

  it('renders nothing when loading the list fails', () => {
    http.expectOne('/api/searches').error(new ProgressEvent('error'));
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).querySelector('.recent-searches')).toBeNull();
  });
});

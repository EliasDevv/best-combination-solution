import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ComparisonStore } from './comparison.store';
import { CompareResponse } from './models';

const RESPONSE: CompareResponse = {
  games: [],
  packages: [],
  best_combination: { package_ids: [], cost_cents: 0, coverage: 1.0, exact: true },
  pareto: [],
  unknown_teams: [],
};

describe('ComparisonStore', () => {
  let store: ComparisonStore;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    store = TestBed.inject(ComparisonStore);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('loads a comparison', () => {
    store.load({ teams: ['RB Leipzig'] });
    expect(store.loading()).toBeTrue();

    http.expectOne('/api/compare').flush(RESPONSE);
    expect(store.loading()).toBeFalse();
    expect(store.response()).toEqual(RESPONSE);
  });

  it('cancels the in-flight request when a newer one starts', () => {
    store.load({ teams: ['A'] });
    const stale = http.expectOne('/api/compare');

    store.load({ teams: ['B'] });
    expect(stale.cancelled).toBeTrue();

    const freshResponse = { ...RESPONSE, unknown_teams: ['marker'] };
    http.expectOne('/api/compare').flush(freshResponse);
    expect(store.response()).toEqual(freshResponse);
  });

  it('surfaces the backend error message and recovers on the next load', () => {
    store.load({ teams: ['A'] });
    http
      .expectOne('/api/compare')
      .flush({ detail: 'index broken' }, { status: 500, statusText: 'Server Error' });
    expect(store.error()).toBe('index broken');
    expect(store.loading()).toBeFalse();

    store.load({ teams: ['B'] });
    expect(store.error()).toBeNull();
    http.expectOne('/api/compare').flush(RESPONSE);
    expect(store.response()).toEqual(RESPONSE);
  });
});

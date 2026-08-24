import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subject, catchError, of, switchMap } from 'rxjs';

import { ApiService } from './api.service';
import { CompareRequest, CompareResponse, PackageResult, Requirement } from './models';

function errorMessage(err: unknown): string {
  if (err instanceof HttpErrorResponse) {
    // status 0 is the browser refusing to say more: the request never reached
    // a server (backend down, wrong port, CORS). A bare "(0)" helps nobody.
    if (err.status === 0) {
      return 'Cannot reach the server — is the backend running on http://localhost:8000?';
    }
    const detail: unknown = err.error?.detail;
    if (typeof detail === 'string') {
      return detail;
    }
    const fieldError = firstFieldError(err.error);
    return fieldError ?? `Request failed (${err.status})`;
  }
  return err instanceof Error ? err.message : 'Request failed';
}

/** DRF reports validation errors as `{field: ["message", ...]}` — show the first. */
function firstFieldError(body: unknown): string | null {
  if (typeof body !== 'object' || body === null) {
    return null;
  }
  for (const messages of Object.values(body)) {
    if (typeof messages === 'string') {
      return messages;
    }
    if (Array.isArray(messages) && typeof messages[0] === 'string') {
      return messages[0];
    }
  }
  return null;
}

@Injectable({ providedIn: 'root' })
export class ComparisonStore {
  private readonly api = inject(ApiService);

  private readonly _request = signal<CompareRequest | null>(null);
  private readonly _response = signal<CompareResponse | null>(null);
  private readonly _loading = signal(false);
  private readonly _error = signal<string | null>(null);

  readonly request = this._request.asReadonly();
  readonly response = this._response.asReadonly();
  readonly loading = this._loading.asReadonly();
  readonly error = this._error.asReadonly();

  readonly games = computed(() => this._response()?.games ?? []);
  readonly bestCombination = computed(() => this._response()?.best_combination ?? null);
  readonly pareto = computed(() => this._response()?.pareto ?? []);
  readonly unknownTeams = computed(() => this._response()?.unknown_teams ?? []);
  readonly requirement = computed<Requirement>(() => this._request()?.requirement ?? 'live');

  readonly packageNames = computed<Map<number, string>>(
    () => new Map((this._response()?.packages ?? []).map((pkg) => [pkg.id, pkg.name])),
  );

  /** The best combination's packages, in the order the solver returned them. */
  readonly bestPackages = computed<PackageResult[]>(() => {
    const response = this._response();
    if (!response) {
      return [];
    }
    const byId = new Map(response.packages.map((pkg) => [pkg.id, pkg]));
    return response.best_combination.package_ids
      .map((id) => byId.get(id))
      .filter((pkg): pkg is PackageResult => pkg !== undefined);
  });

  /** Games the best combination covers; coverage is exact, so rounding is safe. */
  readonly coveredGames = computed(() =>
    Math.round((this.bestCombination()?.coverage ?? 0) * this.games().length),
  );

  // column order: best combination first, then coverage desc, then price asc (null last)
  readonly rankedPackages = computed<PackageResult[]>(() => {
    const response = this._response();
    if (!response) {
      return [];
    }
    const requirement = this.requirement();
    const best = new Set(response.best_combination.package_ids);
    const relevant = (pkg: PackageResult): number => {
      if (requirement === 'live') {
        return pkg.live_idx.length;
      }
      if (requirement === 'highlights') {
        return pkg.highlight_idx.length;
      }
      const highlights = new Set(pkg.highlight_idx);
      return pkg.live_idx.filter((idx) => highlights.has(idx)).length;
    };
    return [...response.packages].sort(
      (a, b) =>
        Number(best.has(b.id)) - Number(best.has(a.id)) ||
        relevant(b) - relevant(a) ||
        (a.cost_cents ?? Number.MAX_SAFE_INTEGER) - (b.cost_cents ?? Number.MAX_SAFE_INTEGER) ||
        a.id - b.id,
    );
  });

  private readonly load$ = new Subject<CompareRequest>();

  constructor() {
    this.load$
      .pipe(
        // switchMap cancels stale in-flight compares
        switchMap((request) =>
          this.api.compare(request).pipe(
            // per-request, so one failure doesn't kill the stream
            catchError((err: unknown) => {
              this._error.set(errorMessage(err));
              this._loading.set(false);
              return of(null);
            }),
          ),
        ),
        takeUntilDestroyed(),
      )
      .subscribe((response) => {
        if (response !== null) {
          this._response.set(response);
          this._loading.set(false);
        }
      });
  }

  load(request: CompareRequest): void {
    this._request.set(request);
    this._loading.set(true);
    this._error.set(null);
    this.load$.next(request);
  }

  reset(): void {
    this._request.set(null);
    this._response.set(null);
    this._loading.set(false);
    this._error.set(null);
  }
}

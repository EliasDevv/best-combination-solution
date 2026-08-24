import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  CompareRequest,
  CompareResponse,
  SearchesResponse,
  TeamsResponse,
  TournamentsResponse,
} from './models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = '/api';

  searchTeams(query: string): Observable<TeamsResponse> {
    const params = new HttpParams().set('q', query);
    return this.http.get<TeamsResponse>(`${this.baseUrl}/teams`, { params });
  }

  getTournaments(): Observable<TournamentsResponse> {
    return this.http.get<TournamentsResponse>(`${this.baseUrl}/tournaments`);
  }

  compare(request: CompareRequest): Observable<CompareResponse> {
    return this.http.post<CompareResponse>(`${this.baseUrl}/compare`, request);
  }

  getSavedSearches(): Observable<SearchesResponse> {
    return this.http.get<SearchesResponse>(`${this.baseUrl}/searches`);
  }

  deleteSavedSearch(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/searches/${id}`);
  }

  clearSavedSearches(): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/searches`);
  }
}

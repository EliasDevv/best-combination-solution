import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { Subject } from 'rxjs';

import { ApiService } from '../../core/api.service';
import { TeamsResponse } from '../../core/models';
import { TeamSearchComponent } from './team-search.component';

describe('TeamSearchComponent', () => {
  let fixture: ComponentFixture<TeamSearchComponent>;
  let teams$: Subject<TeamsResponse>;

  function type(value: string): void {
    const input: HTMLInputElement = fixture.nativeElement.querySelector('input');
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  function emptyState(): HTMLElement | null {
    return fixture.nativeElement.querySelector('.suggestions .empty');
  }

  beforeEach(async () => {
    teams$ = new Subject<TeamsResponse>();
    const api = jasmine.createSpyObj<ApiService>('ApiService', ['searchTeams']);
    api.searchTeams.and.callFake(() => teams$.asObservable());
    await TestBed.configureTestingModule({
      imports: [TeamSearchComponent],
      providers: [{ provide: ApiService, useValue: api }],
    }).compileComponents();
    fixture = TestBed.createComponent(TeamSearchComponent);
    fixture.detectChanges();
  });

  it('shows an empty state once the search settles with zero results', fakeAsync(() => {
    type('gerd');
    tick(200);
    teams$.next({ teams: [] });
    fixture.detectChanges();
    expect(emptyState()?.textContent).toContain("No teams found for 'gerd'");
  }));

  it('shows no empty state while the request is still pending', fakeAsync(() => {
    type('gerd');
    fixture.detectChanges();
    expect(emptyState()).toBeNull(); // debouncing
    tick(200);
    fixture.detectChanges();
    expect(emptyState()).toBeNull(); // request in flight, no response yet
  }));

  it('does not add a team on Enter when there are no matches', fakeAsync(() => {
    const emitted: string[] = [];
    fixture.componentInstance.teamSelected.subscribe((team) => emitted.push(team));
    type('gerd');
    tick(200);
    teams$.next({ teams: [] });
    fixture.detectChanges();
    const input: HTMLInputElement = fixture.nativeElement.querySelector('input');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    fixture.detectChanges();
    expect(emitted).toEqual([]);
    expect(emptyState()).not.toBeNull();
  }));

  it('hides the empty state as soon as the query changes', fakeAsync(() => {
    type('gerd');
    tick(200);
    teams$.next({ teams: [] });
    fixture.detectChanges();
    expect(emptyState()).not.toBeNull();
    type('gerds');
    fixture.detectChanges();
    expect(emptyState()).toBeNull();
    tick(200); // flush the pending debounce timer
  }));

  it('closes the dropdown when the click lands outside the field', fakeAsync(() => {
    type('byern munich');
    tick(200);
    teams$.next({ teams: [] });
    fixture.detectChanges();
    expect(emptyState()).not.toBeNull();

    // e.g. giving up on the typo and reaching for "Compare all games"
    document.body.click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.suggestions')).toBeNull();
  }));

  it('keeps the dropdown open for clicks inside the field', fakeAsync(() => {
    type('bay');
    tick(200);
    teams$.next({ teams: ['FC Bayern München'] });
    fixture.detectChanges();

    const input: HTMLInputElement = fixture.nativeElement.querySelector('input');
    input.click();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.suggestions')).not.toBeNull();
  }));

  it('closes the dropdown on Escape and reopens on the next input', fakeAsync(() => {
    type('bay');
    tick(200);
    teams$.next({ teams: ['FC Bayern München'] });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.suggestions')).not.toBeNull();
    const input: HTMLInputElement = fixture.nativeElement.querySelector('input');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.suggestions')).toBeNull();
    type('baye');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.suggestions')).not.toBeNull();
    tick(200);
    teams$.next({ teams: [] });
  }));
});

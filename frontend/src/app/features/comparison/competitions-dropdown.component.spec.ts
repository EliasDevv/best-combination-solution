import { ComponentFixture, TestBed } from '@angular/core/testing';

import { CompetitionsDropdownComponent } from './competitions-dropdown.component';

const ALL = [
  'Bundesliga 24/25',
  '2. Bundesliga 24/25',
  'Premier League 24/25',
  'UEFA Champions League 24/25',
];

describe('CompetitionsDropdownComponent', () => {
  let fixture: ComponentFixture<CompetitionsDropdownComponent>;
  let applied: string[][];

  function el<T extends HTMLElement>(selector: string): T {
    return fixture.nativeElement.querySelector(selector) as T;
  }

  function texts(selector: string): string[] {
    return [...fixture.nativeElement.querySelectorAll(selector)].map((node) =>
      (node as HTMLElement).textContent!.trim(),
    );
  }

  function options(): HTMLInputElement[] {
    return [...fixture.nativeElement.querySelectorAll('.option input')] as HTMLInputElement[];
  }

  function click(selector: string): void {
    el(selector).click();
    fixture.detectChanges();
  }

  function openPanel(): void {
    click('.trigger');
  }

  function check(index: number): void {
    options()[index].click();
    fixture.detectChanges();
  }

  function type(value: string): void {
    const input = el<HTMLInputElement>('.search-field input');
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  beforeEach(async () => {
    applied = [];
    await TestBed.configureTestingModule({
      imports: [CompetitionsDropdownComponent],
    }).compileComponents();
    fixture = TestBed.createComponent(CompetitionsDropdownComponent);
    fixture.componentRef.setInput('all', ALL);
    fixture.componentRef.setInput('selected', []);
    fixture.componentInstance.applied.subscribe((names) => applied.push(names));
    fixture.detectChanges();
  });

  it('starts closed and opens on the trigger', () => {
    expect(el('.panel')).toBeNull();
    expect(el('.trigger').getAttribute('aria-expanded')).toBe('false');
    openPanel();
    expect(el('.panel')).not.toBeNull();
    expect(el('.trigger').getAttribute('aria-expanded')).toBe('true');
  });

  it('renders country group heads with the season split off the name', () => {
    openPanel();
    expect(texts('.group-head')).toEqual(['Europe', 'England', 'Germany']);
    expect(texts('.option-name')).toContain('2. Bundesliga');
    expect(texts('.option-season')).toContain('24/25');
  });

  it('stages selections and emits them once on Apply', () => {
    openPanel();
    check(0);
    check(1);
    expect(applied).toEqual([]); // no compare request per checkbox
    click('.apply');
    expect(applied).toEqual([['UEFA Champions League 24/25', 'Premier League 24/25']]);
    expect(el('.panel')).toBeNull();
  });

  it('shows the staged count on the trigger', () => {
    openPanel();
    check(0);
    expect(el('.trigger .count').textContent!.trim()).toBe('1');
  });

  it('discards the draft when closed without applying', () => {
    fixture.componentRef.setInput('selected', ['Bundesliga 24/25']);
    fixture.detectChanges();
    openPanel();
    check(0);
    expect(el('.trigger .count').textContent!.trim()).toBe('2');

    document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();
    expect(applied).toEqual([]);
    expect(el('.panel')).toBeNull();
    expect(el('.trigger .count').textContent!.trim()).toBe('1');
  });

  it('discards the draft on Escape', () => {
    openPanel();
    check(0);
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();
    expect(el('.panel')).toBeNull();
    expect(el('.trigger .count')).toBeNull();
  });

  it('keeps the panel open when clicking inside it', () => {
    openPanel();
    el('.panel').dispatchEvent(new MouseEvent('click', { bubbles: true }));
    fixture.detectChanges();
    expect(el('.panel')).not.toBeNull();
  });

  it('reflects the committed selection when reopened', () => {
    fixture.componentRef.setInput('selected', ['Premier League 24/25']);
    fixture.detectChanges();
    openPanel();
    const checked = options().filter((input) => input.checked);
    expect(checked.length).toBe(1);
    expect(el('.trigger .count').textContent!.trim()).toBe('1');
  });

  it('filters the list by the search query and reports a miss', () => {
    openPanel();
    type('bundes');
    expect(texts('.group-head')).toEqual(['Germany']);
    expect(texts('.option-name')).toEqual(['2. Bundesliga', 'Bundesliga']);
    type('zzz');
    expect(el('.option-empty').textContent).toContain("No competitions match 'zzz'");
  });

  it('keeps a filtered-out selection when applying', () => {
    openPanel();
    check(0); // UEFA Champions League
    type('premier');
    check(0); // Premier League
    click('.apply');
    expect(applied).toEqual([['UEFA Champions League 24/25', 'Premier League 24/25']]);
  });

  it('clears the draft without emitting, and disables the button when empty', () => {
    openPanel();
    expect(el<HTMLButtonElement>('.clear').disabled).toBeTrue();
    check(0);
    expect(el<HTMLButtonElement>('.clear').disabled).toBeFalse();
    click('.clear');
    expect(applied).toEqual([]);
    expect(options().some((input) => input.checked)).toBeFalse();
    click('.apply');
    expect(applied).toEqual([[]]);
  });

  it('resets the search when the panel closes', () => {
    openPanel();
    type('bundes');
    click('.apply');
    openPanel();
    expect(el<HTMLInputElement>('.search-field input').value).toBe('');
    expect(texts('.group-head').length).toBe(3);
  });
});

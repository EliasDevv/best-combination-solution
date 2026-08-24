import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DateFieldComponent } from './date-field.component';

describe('DateFieldComponent', () => {
  let fixture: ComponentFixture<DateFieldComponent>;
  let emitted: (string | null)[];

  function textField(): HTMLInputElement {
    return fixture.nativeElement.querySelector('.date-text') as HTMLInputElement;
  }

  function nativeField(): HTMLInputElement {
    return fixture.nativeElement.querySelector('.date-pick input') as HTMLInputElement;
  }

  function glyph(): HTMLElement {
    return fixture.nativeElement.querySelector('.date-pick') as HTMLElement;
  }

  function type(value: string): void {
    const input = textField();
    input.value = value;
    input.dispatchEvent(new Event('input'));
    fixture.detectChanges();
  }

  /** Type `text` one character at a time, the way the mask sees it. */
  function typeEach(text: string): void {
    const input = textField();
    for (const char of text) {
      input.value += char;
      input.dispatchEvent(new InputEvent('input', { inputType: 'insertText', data: char }));
    }
    fixture.detectChanges();
  }

  function backspace(): void {
    const input = textField();
    input.value = input.value.slice(0, -1);
    input.dispatchEvent(new InputEvent('input', { inputType: 'deleteContentBackward' }));
    fixture.detectChanges();
  }

  function blur(): void {
    textField().dispatchEvent(new Event('blur'));
    fixture.detectChanges();
  }

  beforeEach(async () => {
    emitted = [];
    await TestBed.configureTestingModule({ imports: [DateFieldComponent] }).compileComponents();
    fixture = TestBed.createComponent(DateFieldComponent);
    fixture.componentRef.setInput('label', 'From');
    fixture.detectChanges();
    fixture.componentInstance.valueChange.subscribe((value) => emitted.push(value));
  });

  it('shows an ISO value as dd/mm/yy, not the browser locale format', () => {
    fixture.componentRef.setInput('value', '2025-09-15');
    fixture.detectChanges();
    expect(textField().value).toBe('15/09/25');
    expect(textField().placeholder).toBe('dd/mm/yy');
    expect(textField().type).toBe('text');
  });

  it('starts empty when there is no value', () => {
    expect(textField().value).toBe('');
  });

  it('emits ISO on blur and pads what was typed', () => {
    type('1/9/25');
    expect(emitted).toEqual([]); // nothing per keystroke
    blur();
    expect(emitted).toEqual(['2025-09-01']);
    expect(textField().value).toBe('01/09/25');
  });

  it('types the separators for you', () => {
    typeEach('31');
    expect(textField().value).toBe('31/');
    typeEach('12');
    expect(textField().value).toBe('31/12/');
    typeEach('25');
    expect(textField().value).toBe('31/12/25');
    blur();
    expect(emitted).toEqual(['2025-12-31']);
  });

  it('leaves the caret after the separator it added', () => {
    typeEach('31');
    expect(textField().selectionStart).toBe(3);
  });

  it('lets backspace take the separator off again', () => {
    typeEach('3112');
    expect(textField().value).toBe('31/12/');
    backspace();
    expect(textField().value).toBe('31/12');
    backspace();
    expect(textField().value).toBe('31/1');
  });

  it('keeps a rejected character out of the field', () => {
    typeEach('1x');
    expect(textField().value).toBe('1');
  });

  it('emits null when the field is cleared', () => {
    fixture.componentRef.setInput('value', '2025-09-15');
    fixture.detectChanges();
    type('');
    blur();
    expect(emitted).toEqual([null]);
  });

  it('restores the committed value when the input makes no sense', () => {
    fixture.componentRef.setInput('value', '2025-09-15');
    fixture.detectChanges();
    type('31/02/25');
    blur();
    expect(emitted).toEqual([]);
    expect(textField().value).toBe('15/09/25');
  });

  it('does not re-emit a value that has not changed', () => {
    fixture.componentRef.setInput('value', '2025-09-15');
    fixture.detectChanges();
    blur();
    expect(emitted).toEqual([]);
  });

  it('takes the ISO value straight from the calendar picker', () => {
    const native = nativeField();
    native.value = '2025-12-24';
    native.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(emitted).toEqual(['2025-12-24']);
  });

  it('opens the platform picker once, from the glyph and not from the input', () => {
    const showPicker = spyOn(nativeField(), 'showPicker');
    glyph().click();
    expect(showPicker).toHaveBeenCalledTimes(1);
  });

  it('keeps the native picker out of the hit test, so it cannot open a second one', () => {
    expect(getComputedStyle(nativeField()).pointerEvents).toBe('none');
  });

  it('keeps the native picker out of the reading order', () => {
    fixture.componentRef.setInput('value', '2025-09-15');
    fixture.detectChanges();
    expect(nativeField().type).toBe('date');
    expect(nativeField().getAttribute('aria-label')).toBe('From — pick from calendar');
    expect(textField().getAttribute('aria-label')).toBe('From');
  });
});

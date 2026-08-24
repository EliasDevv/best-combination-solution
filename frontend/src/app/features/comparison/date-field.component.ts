import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  effect,
  input,
  output,
  signal,
  viewChild,
} from '@angular/core';

import { formatDayFirst, maskDayFirst, parseDayFirst } from './dates';

/**
 * One end of the date range: a dd/mm/yy text field plus a calendar button.
 *
 * The text field exists because a native `input[type=date]` cannot be pinned to
 * a format (see `dates.ts`). The native input is still here — transparent, laid
 * over the calendar glyph — purely so the platform date picker stays available;
 * it is never what the user reads. Value in and out is ISO, `null` when unset.
 *
 * Clicks are handled by the glyph, never by that input: the browser opens the
 * picker by itself when a click lands on the input's own calendar indicator,
 * and the `showPicker()` that follows would shut it again. `styles.scss` takes
 * the input out of the hit test so exactly one of the two ever runs.
 */
@Component({
  selector: 'app-date-field',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <input
      type="text"
      class="date-text"
      inputmode="numeric"
      autocomplete="off"
      maxlength="10"
      placeholder="dd/mm/yy"
      [attr.aria-label]="label()"
      [value]="text()"
      (input)="onInput($event)"
      (blur)="commit()"
      (keydown.enter)="$event.preventDefault(); commit()"
    />
    <span class="date-pick" (click)="openPicker()">
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <rect
          x="1.6"
          y="2.6"
          width="10.8"
          height="9.8"
          rx="1.6"
          stroke="currentColor"
          stroke-width="1.2"
        />
        <path d="M1.6 5.6h10.8M4.6 1.4v2.2M9.4 1.4v2.2" stroke="currentColor" stroke-width="1.2" />
      </svg>
      <input
        #native
        type="date"
        [value]="value() ?? ''"
        [attr.aria-label]="label() + ' — pick from calendar'"
        (keydown.enter)="openPicker()"
        (change)="pick($any($event.target).value)"
      />
    </span>
  `,
  // presentation lives in styles.scss with the rest of the design tokens
})
export class DateFieldComponent {
  readonly label = input.required<string>();
  readonly value = input<string | null>(null);
  readonly valueChange = output<string | null>();

  private readonly native = viewChild.required<ElementRef<HTMLInputElement>>('native');

  readonly text = signal('');

  constructor() {
    effect(() => this.text.set(formatDayFirst(this.value())));
  }

  /**
   * Reshape the field on every keystroke, so the separators type themselves.
   *
   * The masked text goes back into the element directly: Angular skips the
   * `[value]` write whenever the mask returns what the signal already holds
   * (typing a rejected character), and the field would keep showing it.
   */
  onInput(event: Event): void {
    const field = event.target as HTMLInputElement;
    const typed = field.value;
    const caret = field.selectionStart ?? typed.length;
    const deleting = (event as InputEvent).inputType?.startsWith('delete') ?? false;
    const masked = maskDayFirst(typed, deleting);

    this.text.set(masked);
    if (masked !== typed) {
      // Editing mid-string is rare here; keeping the caret on the same digit
      // covers it, and the end of the text covers everything else.
      const position = caret === typed.length ? masked.length : caretAt(masked, typed, caret);
      field.value = masked;
      field.setSelectionRange(position, position);
    }
  }

  /** Commit on blur or Enter — one navigation per edit, not per keystroke. */
  commit(): void {
    const typed = this.text().trim();
    const iso = typed ? parseDayFirst(typed) : null;
    if (typed && iso === null) {
      this.text.set(formatDayFirst(this.value())); // unreadable input: snap back
      return;
    }
    if (iso !== this.value()) {
      this.valueChange.emit(iso);
    }
    this.text.set(formatDayFirst(iso)); // normalises "1/9/25" to "01/09/25"
  }

  pick(iso: string): void {
    this.valueChange.emit(iso || null);
  }

  /** Clicking a date input does not open its picker in Chrome; asking does. */
  openPicker(): void {
    const input = this.native().nativeElement;
    if (typeof input.showPicker === 'function') {
      input.showPicker();
    }
  }
}

/** Where `caret` in the typed text lands once the mask has moved separators. */
function caretAt(masked: string, typed: string, caret: number): number {
  const digits = typed.slice(0, caret).replace(/\D/g, '').length;
  if (digits === 0) {
    return 0;
  }
  let seen = 0;
  for (let i = 0; i < masked.length; i++) {
    if (masked[i] >= '0' && masked[i] <= '9' && ++seen === digits) {
      return masked[i + 1] === '/' ? i + 2 : i + 1;
    }
  }
  return masked.length;
}

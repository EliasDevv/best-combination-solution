/** Day-first date entry for the compare filters.
 *
 * `input[type=date]` renders in the *browser's* locale — Chrome and Firefox
 * both ignore `<html lang>` — so a native field shows mm/dd/yyyy to anyone
 * whose browser is set to US English, and no amount of `LOCALE_ID` changes
 * that. These helpers back a plain text field pinned to dd/mm/yy instead.
 *
 * Nothing outside this module sees that format: the URL, the store and the API
 * keep speaking ISO `yyyy-mm-dd`, which is also what the date picker hands us.
 */

/** Two-digit years read as 20yy — the dataset starts at season 23/24. */
const CENTURY = 2000;

/** "15/09/25", "1.9.2025", "15-09-25" — any of . / - as the separator. */
const DAY_FIRST = /^(\d{1,2})[./-](\d{1,2})[./-](\d{2}|\d{4})$/;

/** Typing a date without separators is common enough to accept: "150925". */
const DIGITS_ONLY = /^(\d{2})(\d{2})(\d{2}|\d{4})$/;

const ISO = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * Parse day-first user input into an ISO date, or `null` if it is not one.
 *
 * Empty input is *not* handled here — a cleared field means "drop the filter",
 * which the caller distinguishes from the `null` this returns for a typo.
 */
export function parseDayFirst(text: string): string | null {
  const trimmed = text.trim();
  const match = DAY_FIRST.exec(trimmed) ?? DIGITS_ONLY.exec(trimmed);
  if (!match) {
    return null;
  }
  const day = Number(match[1]);
  const month = Number(match[2]);
  const year = match[3].length === 2 ? CENTURY + Number(match[3]) : Number(match[3]);

  // Rejects the impossible (31/02) and the out-of-range (13 as a month):
  // Date rolls those over instead of failing, so compare the parts back.
  const date = new Date(Date.UTC(year, month - 1, day));
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return null;
  }
  return date.toISOString().slice(0, 10);
}

/** How many digits each segment of dd/mm/yyyy holds. */
const SEGMENT_LENGTHS = [2, 2, 4];

const SEPARATORS = './-';

/**
 * Split typed text into [day, month, year] digit runs.
 *
 * A separator ends a segment, and so does filling one: the third digit of
 * "3109" starts the month, which is what puts the slash in by itself.
 */
function segments(text: string): string[] {
  const parts = [''];
  for (const char of text) {
    const last = parts.length - 1;
    if (char >= '0' && char <= '9') {
      if (parts[last].length < SEGMENT_LENGTHS[last]) {
        parts[last] += char;
      } else if (last < 2) {
        parts.push(char);
      }
    } else if (SEPARATORS.includes(char) && last < 2 && parts[last] !== '') {
      parts.push('');
    }
  }
  return parts;
}

/**
 * Reshape what is in the field into dd/mm/yy while it is being typed.
 *
 * Separators appear on their own once a segment is full ("31" → "31/"), and a
 * separator the user types themselves pads a single digit ("1/" → "01/"), so
 * both "1/9/25" and "150925" end up as the same eight characters. Anything
 * that is not a digit or a separator is dropped.
 *
 * While `deleting`, nothing is added back — otherwise backspace would fight
 * the mask over the separator it just removed.
 */
export function maskDayFirst(text: string, deleting = false): string {
  const parts = segments(text);
  const last = parts.length - 1;
  const masked = parts
    .map((part, i) => (!deleting && i < last && part.length === 1 ? `0${part}` : part))
    .join('/');
  const full = parts[last].length === SEGMENT_LENGTHS[last];
  return !deleting && last < 2 && full ? `${masked}/` : masked;
}

/** Render an ISO date as dd/mm/yy; anything else (or null) as an empty field. */
export function formatDayFirst(iso: string | null): string {
  const match = iso ? ISO.exec(iso) : null;
  return match ? `${match[3]}/${match[2]}/${match[1].slice(2)}` : '';
}

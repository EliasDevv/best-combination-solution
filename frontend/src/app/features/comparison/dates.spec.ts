import { formatDayFirst, maskDayFirst, parseDayFirst } from './dates';

describe('formatDayFirst', () => {
  it('renders an ISO date as dd/mm/yy', () => {
    expect(formatDayFirst('2025-09-15')).toBe('15/09/25');
    expect(formatDayFirst('2024-01-01')).toBe('01/01/24');
  });

  it('renders an empty field for no value or a non-ISO one', () => {
    expect(formatDayFirst(null)).toBe('');
    expect(formatDayFirst('')).toBe('');
    expect(formatDayFirst('15/09/25')).toBe('');
  });
});

describe('maskDayFirst', () => {
  it('adds the separator once a segment is full', () => {
    expect(maskDayFirst('3')).toBe('3');
    expect(maskDayFirst('31')).toBe('31/');
    expect(maskDayFirst('31/0')).toBe('31/0');
    expect(maskDayFirst('31/01')).toBe('31/01/');
    expect(maskDayFirst('31/01/2')).toBe('31/01/2');
  });

  it('pads a single digit the user separated themselves', () => {
    expect(maskDayFirst('1/')).toBe('01/');
    expect(maskDayFirst('1/9/')).toBe('01/09/');
    expect(maskDayFirst('1/9/25')).toBe('01/09/25');
    expect(maskDayFirst('1.9.2025')).toBe('01/09/2025');
  });

  it('reads bare digits as dd mm yy', () => {
    expect(maskDayFirst('150925')).toBe('15/09/25');
    expect(maskDayFirst('15092025')).toBe('15/09/2025');
  });

  it('drops what cannot be part of a date', () => {
    expect(maskDayFirst('')).toBe('');
    expect(maskDayFirst('15x')).toBe('15/');
    expect(maskDayFirst('/15')).toBe('15/');
    expect(maskDayFirst('15//09')).toBe('15/09/');
    expect(maskDayFirst('15/09/2025/7')).toBe('15/09/2025');
  });

  it('adds nothing back while the user is deleting', () => {
    expect(maskDayFirst('31', true)).toBe('31');
    expect(maskDayFirst('31/01', true)).toBe('31/01');
    expect(maskDayFirst('1/9', true)).toBe('1/9');
  });
});

describe('parseDayFirst', () => {
  it('reads day-first input, padded or not', () => {
    expect(parseDayFirst('15/09/25')).toBe('2025-09-15');
    expect(parseDayFirst('1/9/25')).toBe('2025-09-01');
    expect(parseDayFirst(' 15/09/25 ')).toBe('2025-09-15');
  });

  it('accepts dots and dashes as separators', () => {
    expect(parseDayFirst('15.09.25')).toBe('2025-09-15');
    expect(parseDayFirst('15-09-2025')).toBe('2025-09-15');
  });

  it('accepts a four-digit year and bare digits', () => {
    expect(parseDayFirst('15/09/2025')).toBe('2025-09-15');
    expect(parseDayFirst('150925')).toBe('2025-09-15');
    expect(parseDayFirst('15092025')).toBe('2025-09-15');
  });

  it('reads day before month, never the other way round', () => {
    expect(parseDayFirst('09/11/24')).toBe('2024-11-09');
  });

  it('rejects dates that do not exist', () => {
    expect(parseDayFirst('31/02/25')).toBeNull();
    expect(parseDayFirst('15/13/25')).toBeNull();
    expect(parseDayFirst('00/09/25')).toBeNull();
  });

  it('keeps a leap day and rejects it off-cycle', () => {
    expect(parseDayFirst('29/02/24')).toBe('2024-02-29');
    expect(parseDayFirst('29/02/25')).toBeNull();
  });

  it('rejects what is not a date at all', () => {
    expect(parseDayFirst('')).toBeNull();
    expect(parseDayFirst('tomorrow')).toBeNull();
    expect(parseDayFirst('2025-09-15')).toBeNull();
    expect(parseDayFirst('15/09')).toBeNull();
  });
});

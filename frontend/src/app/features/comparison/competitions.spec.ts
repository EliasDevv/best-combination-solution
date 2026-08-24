import { groupCompetitions, parseCompetition } from './competitions';

describe('parseCompetition', () => {
  it('splits the two season formats the dataset uses', () => {
    expect(parseCompetition('2. Bundesliga 23/24')).toEqual({
      value: '2. Bundesliga 23/24',
      name: '2. Bundesliga',
      season: '23/24',
      country: 'Germany',
    });
    expect(parseCompetition('Europameisterschaft 2024')).toEqual({
      value: 'Europameisterschaft 2024',
      name: 'Europameisterschaft',
      season: '2024',
      country: 'Europe',
    });
  });

  it('keeps the whole name when there is no season suffix', () => {
    const parsed = parseCompetition('Premier League');
    expect(parsed.name).toBe('Premier League');
    expect(parsed.season).toBe('');
  });

  it('does not mistake digits inside the name for a season', () => {
    expect(parseCompetition('3. Liga 24/25').name).toBe('3. Liga');
  });

  it('buckets an unmapped competition instead of dropping it', () => {
    expect(parseCompetition('Copa Libertadores 2024').country).toBe('Other');
  });
});

describe('groupCompetitions', () => {
  const ALL = [
    'Bundesliga 24/25',
    'Bundesliga AUT 24/25',
    '2. Bundesliga 23/24',
    'Premier League 24/25',
    'UEFA Champions League 24/25',
    'Copa Libertadores 2024',
  ];

  it('leads with Europe, sorts countries A-Z and trails with Other', () => {
    expect(groupCompetitions(ALL).map((g) => g.country)).toEqual([
      'Europe',
      'Austria',
      'England',
      'Germany',
      'Other',
    ]);
  });

  it('sorts within a group by name, then season', () => {
    const germany = groupCompetitions([
      'Bundesliga 24/25',
      '2. Bundesliga 24/25',
      '2. Bundesliga 23/24',
    ])[0];
    expect(germany.items.map((i) => i.value)).toEqual([
      '2. Bundesliga 23/24',
      '2. Bundesliga 24/25',
      'Bundesliga 24/25',
    ]);
  });

  it('matches name and season as one string', () => {
    const values = (query: string): string[] =>
      groupCompetitions(ALL, query).flatMap((g) => g.items.map((i) => i.value));
    expect(values('bundesliga')).toEqual([
      'Bundesliga AUT 24/25',
      '2. Bundesliga 23/24',
      'Bundesliga 24/25',
    ]);
    expect(values('bundesliga 24/25')).toEqual(['Bundesliga 24/25']);
    expect(values('23/24')).toEqual(['2. Bundesliga 23/24']);
    expect(values('aut')).toEqual(['Bundesliga AUT 24/25']);
  });

  it('drops groups the query empties out', () => {
    expect(groupCompetitions(ALL, 'premier').map((g) => g.country)).toEqual(['England']);
    expect(groupCompetitions(ALL, 'zzz')).toEqual([]);
  });
});

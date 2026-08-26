// Parity guard for the client-side condition mirror. The case table lives with
// the backend fixtures (backend/tests/fixtures/condition_cases.json) and the
// backend (backend/services/card_fields.py) is authoritative — if these
// assertions fail, the mirror drifted, not the backend.
import { describe, expect, it } from 'vitest'
import {
  CONDITION_LABELS,
  CONDITION_VALUES,
  conditionLabel,
  conditionOptions,
  normalizeCondition,
} from './condition.js'
import table from '../../../backend/tests/fixtures/condition_cases.json'

describe('normalizeCondition parity with backend normalize_condition', () => {
  for (const { name, input, expected } of table.cases) {
    it(name, () => {
      expect(normalizeCondition(input)).toBe(expected)
    })
  }
})

describe('the canonical list is the shared contract', () => {
  it('matches the fixture, in order — the dropdown renders this order', () => {
    expect(CONDITION_VALUES).toEqual(table.canonical)
  })

  it('labels every canonical value, with the fixture wording', () => {
    expect(CONDITION_LABELS).toEqual(table.labels)
  })

  it('folds every canonical value to itself, so the form can fold on render', () => {
    for (const value of CONDITION_VALUES) {
      expect(normalizeCondition(value)).toBe(value)
      expect(normalizeCondition(normalizeCondition(value))).toBe(value)
    }
  })
})

describe('normalizeCondition safety', () => {
  it('returns non-strings untouched', () => {
    expect(normalizeCondition(null)).toBe(null)
    expect(normalizeCondition(undefined)).toBe(undefined)
    expect(normalizeCondition(7)).toBe(7)
  })

  it('does not resolve inherited Object properties as grades', () => {
    // A plain-object lookup table answers to 'constructor' and 'toString'; a
    // card whose condition read "constructor" would otherwise come back as a
    // function and be saved as one.
    expect(normalizeCondition('constructor')).toBe('constructor')
    expect(normalizeCondition('toString')).toBe('toString')
    expect(normalizeCondition('__proto__')).toBe('__proto__')
  })
})

describe('conditionOptions', () => {
  it('offers exactly the canonical grades for a canonical value', () => {
    expect(conditionOptions('NM')).toEqual(CONDITION_VALUES)
  })

  it('appends an unrecognized value so a select cannot silently rewrite it', () => {
    // Without this, a <select> whose value matches no <option> renders as the
    // first option — a card stored as "PSA 10" would save back as "RAW".
    expect(conditionOptions('PSA 10')).toEqual([...CONDITION_VALUES, 'PSA 10'])
  })

  it('offers a blank option when nothing is set', () => {
    expect(conditionOptions('')).toEqual(['', ...CONDITION_VALUES])
    expect(conditionOptions(null)).toEqual(['', ...CONDITION_VALUES])
    expect(conditionOptions(undefined)).toEqual(['', ...CONDITION_VALUES])
  })

  it('never duplicates a value it already offers', () => {
    for (const value of CONDITION_VALUES) {
      const options = conditionOptions(value)
      expect(new Set(options).size).toBe(options.length)
    }
  })
})

describe('conditionLabel', () => {
  it('labels canonical grades from the shared table', () => {
    expect(conditionLabel('NM')).toBe('NM — near mint')
  })

  it('shows an unrecognized value verbatim', () => {
    expect(conditionLabel('PSA 10')).toBe('PSA 10')
  })

  it('names the blank option', () => {
    expect(conditionLabel('')).toBe('— not set —')
  })
})

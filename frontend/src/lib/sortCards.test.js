import { describe, it, expect } from 'vitest'
import { cardMatchesSearch, sortCards } from './sortCards'

const cards = [
  { id: 1, player_name: 'Wander Franco', team: 'Rays', brand: 'Bowman', set_name: 'Chrome', card_number: 'BCP-100', year: 2021, listed_price: 25, notes: null, parallel_color: 'Gold' },
  { id: 2, player_name: 'Julio Rodriguez', team: 'Mariners', brand: 'Topps', set_name: 'Update', card_number: 'US-44', year: 2022, listed_price: null, notes: 'PSA-worthy', parallel_color: null },
  { id: 3, player_name: 'Jackson Holliday', team: 'Orioles', brand: 'Bowman', set_name: 'Chrome', card_number: 'BCP-9', year: 2023, listed_price: 10, notes: null, parallel_color: null },
]

describe('cardMatchesSearch', () => {
  it('matches any field, case-insensitively', () => {
    expect(cardMatchesSearch(cards[0], 'wander')).toBe(true)
    expect(cardMatchesSearch(cards[0], 'RAYS')).toBe(true)
    expect(cardMatchesSearch(cards[0], 'gold')).toBe(true)
    expect(cardMatchesSearch(cards[1], 'psa')).toBe(true)
    expect(cardMatchesSearch(cards[2], '2023')).toBe(true)
  })

  it('does not match unrelated text, ignores blank queries', () => {
    expect(cardMatchesSearch(cards[0], 'mariners')).toBe(false)
    expect(cardMatchesSearch(cards[0], '   ')).toBe(true)
  })
})

describe('sortCards', () => {
  it('sorts strings case-insensitively and numerically', () => {
    expect(sortCards(cards, 'card_number', 'asc').map((c) => c.id)).toEqual([3, 1, 2])
    expect(sortCards(cards, 'player_name', 'asc').map((c) => c.id)).toEqual([3, 2, 1])
  })

  it('sorts numbers and keeps nulls last in both directions', () => {
    expect(sortCards(cards, 'listed_price', 'asc').map((c) => c.id)).toEqual([3, 1, 2])
    expect(sortCards(cards, 'listed_price', 'desc').map((c) => c.id)).toEqual([1, 3, 2])
  })

  it('does not mutate the input array', () => {
    const before = cards.map((c) => c.id)
    sortCards(cards, 'year', 'desc')
    expect(cards.map((c) => c.id)).toEqual(before)
  })
})

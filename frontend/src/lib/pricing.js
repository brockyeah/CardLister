/**
 * What a comps lookup is actually offering as a price, or null.
 *
 * The pricing chain never fails: when every source comes back empty it returns
 * a fixed `MOCK_PRICE` of $9.99 under `source: 'mock'`, with a note saying so.
 * That is a placeholder, not a comp — and on Railway it is the *common* case,
 * because the scrapers routinely 403 from a datacenter IP.
 *
 * The two pricing surfaces used to disagree about it. The Inventory comps modal
 * refused a mock, so it offered no "Set Price to $X" button; the Scanner wrote
 * any truthy `suggested_price` straight into the review form, so a card saved
 * from a failed lookup carried $9.99 as though a median of ten sales had
 * produced it — and the surface that disagreed was the one whose value gets
 * *persisted*, mirrored to the Sheet, and pasted into eBay. It also defeated
 * the no-price listing-text fix: a mocked $9.99 makes `has_price` true, so the
 * seller was given a confident wrong price instead of being told the card has
 * no price yet.
 *
 * Non-positive prices are refused for the same reason the listing-text endpoint
 * treats them as unset: a zero reads as a filled-in field rather than an empty
 * one. Both surfaces now ask this one function, so they cannot drift apart
 * again.
 */
export function usableSuggestedPrice(result) {
  if (!result || result.source === 'mock') return null
  const price = result.suggested_price
  // Guard the type, not just the value: the field is `Optional[float]` on the
  // wire and a string would survive a `> 0` comparison and then blow up on
  // `.toFixed()` at the call site.
  if (typeof price !== 'number' || !Number.isFinite(price) || price <= 0) return null
  return price
}

// Age label for a Prospect Wire headline.
//
// Split out of NewsSection because the byline it feeds used to print the
// article's source a second time (the emerald kicker above the headline
// already owns the attribution, so every item read "MLB.com … MLB.com · 2d
// ago"). Removing the duplicate leaves the byline carrying the age alone —
// which means the age has to be able to say "nothing", so the byline can be
// dropped entirely rather than rendering a bare separator.
//
// `age_days` comes from the backend as a day count, or null when the feed
// entry carried no parseable publish date.
export function formatArticleAge(ageDays) {
  if (typeof ageDays !== 'number' || !Number.isFinite(ageDays)) return ''
  // Negative is reachable: the server subtracts the entry's timestamp from
  // its own UTC clock, and a feed that stamps an item slightly ahead reads as
  // -1. "today" is what that means; "-1d ago" is what it used to render.
  if (ageDays <= 0) return 'today'
  return `${Math.round(ageDays)}d ago`
}

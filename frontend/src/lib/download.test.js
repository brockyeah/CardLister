import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { filenameFromContentDisposition, readBlobError, saveBlob } from './download.js'

const FALLBACK = 'cardlister-backup.db'

describe('filenameFromContentDisposition', () => {
  it('reads the quoted filename the API sends', () => {
    expect(filenameFromContentDisposition(
      'attachment; filename="cardlister-backup-20260821-134500.db"', FALLBACK,
    )).toBe('cardlister-backup-20260821-134500.db')
  })

  it('keeps the digits', () => {
    // The whole reason for preferring the server's name is the timestamp in
    // it, so a sanitizer that eats digits would be worse than no sanitizer.
    const name = filenameFromContentDisposition(
      'attachment; filename="cardlister-sold-2026.csv"', FALLBACK,
    )
    expect(name).toBe('cardlister-sold-2026.csv')
  })

  it('accepts an unquoted filename', () => {
    expect(filenameFromContentDisposition(
      'attachment; filename=cardlister-inventory.csv', FALLBACK,
    )).toBe('cardlister-inventory.csv')
  })

  it('prefers the RFC 5987 encoded form when both are present', () => {
    expect(filenameFromContentDisposition(
      "attachment; filename=\"fallback.db\"; filename*=UTF-8''caf%C3%A9-backup.db",
      FALLBACK,
    )).toBe('café-backup.db')
  })

  it('drops the charset and a language tag from an ext-value', () => {
    // RFC 5987's grammar is charset "'" [ language ] "'" value-chars, and the
    // language half is optional but legal — matching the literal `UTF-8''`
    // left `UTF-8'en'` sitting in the filename. (CodeRabbit, PR #54.)
    expect(filenameFromContentDisposition(
      "attachment; filename*=UTF-8'en'caf%C3%A9-backup.db", FALLBACK,
    )).toBe('café-backup.db')
    expect(filenameFromContentDisposition(
      "attachment; filename*=UTF-8'en-GB'cardlister-sold-2026.csv", FALLBACK,
    )).toBe('cardlister-sold-2026.csv')
  })

  it('treats a value with no ext-value structure as the whole filename', () => {
    // Not spec-legal, but dropping the name entirely would be worse than
    // taking a sender at its word.
    expect(filenameFromContentDisposition(
      'attachment; filename*=plain-backup.db', FALLBACK,
    )).toBe('plain-backup.db')
  })

  it('survives a malformed percent escape rather than failing the download', () => {
    expect(filenameFromContentDisposition(
      "attachment; filename*=UTF-8''100%-backup.db", FALLBACK,
    )).toBe('100%-backup.db')
  })

  it('takes the basename, so a path in the header cannot escape', () => {
    expect(filenameFromContentDisposition(
      'attachment; filename="../../etc/passwd"', FALLBACK,
    )).toBe('passwd')
  })

  it('strips characters a filesystem reserves', () => {
    expect(filenameFromContentDisposition(
      'attachment; filename="back:up<1>.db"', FALLBACK,
    )).toBe('backup1.db')
  })

  it('falls back when the header is missing, empty, or has no filename', () => {
    expect(filenameFromContentDisposition(undefined, FALLBACK)).toBe(FALLBACK)
    expect(filenameFromContentDisposition('', FALLBACK)).toBe(FALLBACK)
    expect(filenameFromContentDisposition('attachment', FALLBACK)).toBe(FALLBACK)
    expect(filenameFromContentDisposition('attachment; filename=""', FALLBACK)).toBe(FALLBACK)
  })

  it('falls back when sanitizing leaves nothing', () => {
    expect(filenameFromContentDisposition('attachment; filename="<>:"', FALLBACK)).toBe(FALLBACK)
  })
})

describe('readBlobError', () => {
  // Stand-in for a Blob: the node test environment has no DOM, and the only
  // thing readBlobError needs is `.text()`.
  const blobLike = (text) => ({ text: async () => text })

  it('replaces a JSON blob body with the parsed object', async () => {
    const err = { response: { status: 507, data: blobLike('{"detail":"Not enough disk space"}') } }
    await readBlobError(err)
    expect(err.response.data).toEqual({ detail: 'Not enough disk space' })
  })

  it('leaves a non-JSON body alone so the caller falls back', async () => {
    const body = blobLike('<html>502 Bad Gateway</html>')
    const err = { response: { status: 502, data: body } }
    await readBlobError(err)
    expect(err.response.data).toBe(body)
  })

  it('ignores an error with no response at all (network failure)', async () => {
    const err = { message: 'Network Error' }
    await expect(readBlobError(err)).resolves.toBe(err)
  })
})

describe('saveBlob', () => {
  // Deliberately NOT jsdom. CLAUDE.md keeps this suite pure-function and
  // node-environment, and adding jsdom + testing-library is called out there
  // as a real decision rather than a drop-in. saveBlob touches exactly four
  // DOM/URL calls, so stubbing those four pins the ordering the shipped fix is
  // about — append, then click, then revoke on a LATER task — without pulling
  // a DOM implementation into the repo. The ordering is the whole fix: revoking
  // in the same tick as click() races the browser's own read of the blob: URL,
  // and nothing else in the suite would notice it moving back.
  let anchor
  let log
  let realUrl

  beforeEach(() => {
    vi.useFakeTimers()
    log = []
    anchor = {
      href: '', download: '', rel: '', style: {}, connected: false,
      click() { log.push({ event: 'click', connected: anchor.connected }) },
      remove() { anchor.connected = false; log.push({ event: 'remove' }) },
    }
    realUrl = globalThis.URL
    vi.stubGlobal('URL', {
      createObjectURL: () => { log.push({ event: 'create' }); return 'blob:fake-url' },
      revokeObjectURL: (u) => log.push({ event: 'revoke', url: u }),
    })
    vi.stubGlobal('document', {
      createElement: () => anchor,
      body: { appendChild: (el) => { el.connected = true; log.push({ event: 'append' }) } },
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    globalThis.URL = realUrl
  })

  const events = () => log.map((e) => e.event)

  it('clicks an anchor that is attached to the document', () => {
    saveBlob({}, 'cardlister-backup.db')
    const click = log.find((e) => e.event === 'click')
    expect(click).toBeDefined()
    expect(click.connected).toBe(true)
    expect(events()).toEqual(['create', 'append', 'click'])
  })

  it('does not revoke the object URL in the same tick as the click', () => {
    // The regression this whole helper exists for: a click only *schedules*
    // the download, so a same-tick revoke can beat the browser to the URL.
    saveBlob({}, 'cardlister-backup.db')
    expect(events()).not.toContain('revoke')
  })

  it('removes the anchor and revokes the URL once the timer fires', () => {
    saveBlob({}, 'cardlister-backup.db')
    vi.advanceTimersByTime(30_000)
    expect(events()).toEqual(['create', 'append', 'click', 'remove', 'revoke'])
    expect(log.find((e) => e.event === 'revoke').url).toBe('blob:fake-url')
    expect(anchor.connected).toBe(false)
  })

  it('puts the filename on the download attribute', () => {
    saveBlob({}, 'cardlister-sold-2026.csv')
    expect(anchor.download).toBe('cardlister-sold-2026.csv')
    expect(anchor.href).toBe('blob:fake-url')
  })
})

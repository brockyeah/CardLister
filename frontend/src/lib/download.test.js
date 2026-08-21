import { describe, it, expect } from 'vitest'
import { filenameFromContentDisposition, readBlobError } from './download.js'

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

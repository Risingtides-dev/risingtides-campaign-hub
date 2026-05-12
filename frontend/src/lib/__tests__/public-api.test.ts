import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadCsv, fetchDashboard } from '@/lib/public-api'

const originalFetch = globalThis.fetch
const originalOpen = globalThis.open

afterEach(() => {
  globalThis.fetch = originalFetch
  globalThis.open = originalOpen
})

describe('fetchDashboard', () => {
  it('returns parsed JSON on success', async () => {
    const expected = { campaign: { slug: 'x' } }
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(expected),
    }) as unknown as typeof fetch
    await expect(fetchDashboard('tok1')).resolves.toEqual(expected)
  })

  it('builds the URL with the token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve({}),
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch
    await fetchDashboard('abc-123')
    expect(fetchMock.mock.calls[0][0]).toContain(
      '/api/public/dashboard/abc-123',
    )
  })

  it('throws with the body error message on non-OK', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      statusText: 'Not Found',
      json: () => Promise.resolve({ error: 'no such token' }),
    }) as unknown as typeof fetch
    await expect(fetchDashboard('tok')).rejects.toThrow('no such token')
  })

  it('falls back to a generic message when body is invalid', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      json: () => Promise.reject(new Error('not json')),
    }) as unknown as typeof fetch
    await expect(fetchDashboard('tok')).rejects.toThrow('Server Error')
  })
})

describe('downloadCsv', () => {
  it('opens the CSV URL in a new window', () => {
    const openSpy = vi.fn()
    globalThis.open = openSpy as unknown as typeof window.open
    downloadCsv('tok1')
    expect(openSpy).toHaveBeenCalledWith(
      expect.stringContaining('/api/public/dashboard/tok1/csv'),
      '_blank',
    )
  })
})

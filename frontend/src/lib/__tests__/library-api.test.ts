import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'

type FetchMock = ReturnType<typeof vi.fn>

function mockFetchOk<T>(body: T) {
  const fetchMock: FetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: () => Promise.resolve(body),
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  return fetchMock
}

function lastCall(mock: FetchMock) {
  const [url, init] = mock.mock.calls.at(-1) as [string, RequestInit | undefined]
  return { url, init }
}

describe('creator library api', () => {
  const originalFetch = globalThis.fetch
  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('requests the roster for the chosen window', async () => {
    const fetchMock = mockFetchOk({ window: 'w60', creators: [] })
    await api.getLibrary('w30')
    expect(lastCall(fetchMock).url).toContain('/api/library/creators?window=w30')
  })

  it('defaults the roster to the 60-day window', async () => {
    const fetchMock = mockFetchOk({ window: 'w60', creators: [] })
    await api.getLibrary()
    expect(lastCall(fetchMock).url).toContain('window=w60')
  })

  it('encodes usernames containing dots', async () => {
    // `4real.corey` and friends are real handles; an unencoded dot has
    // bitten routing before.
    const fetchMock = mockFetchOk({ ok: true, niches: [] })
    await api.setLibraryNiches('4real.corey', ['meme'])

    const { url, init } = lastCall(fetchMock)
    expect(url).toContain('4real.corey')
    expect(init?.method).toBe('PUT')
    expect(JSON.parse(String(init?.body))).toEqual({ niches: ['meme'] })
  })

  it('sends a cleared rate as null rather than omitting it', async () => {
    // Omitting the key would leave the manual rate in place; null is what
    // hands control back to the booking history.
    const fetchMock = mockFetchOk({ ok: true, creator: {} })
    await api.updateLibraryCreator('alice', { rate: null })

    const { init } = lastCall(fetchMock)
    expect(init?.method).toBe('PATCH')
    expect(JSON.parse(String(init?.body))).toEqual({ rate: null })
  })

  it('posts a batch of usernames when bulk tagging', async () => {
    const fetchMock = mockFetchOk({ ok: true, tagged: 3, requested: 3 })
    await api.applyNiche(7, ['alice', 'bob', 'carol'])

    const { url, init } = lastCall(fetchMock)
    expect(url).toContain('/api/library/niches/7/apply')
    expect(JSON.parse(String(init?.body))).toEqual({
      usernames: ['alice', 'bob', 'carol'],
    })
  })

  it('merges a niche into a target id', async () => {
    const fetchMock = mockFetchOk({ id: 2, name: 'gym motivation', count: 4 })
    await api.mergeNiche(1, 2)

    const { url, init } = lastCall(fetchMock)
    expect(url).toContain('/api/library/niches/1/merge')
    expect(JSON.parse(String(init?.body))).toEqual({ into: 2 })
  })

  it('reads the booking rate for a creator', async () => {
    const fetchMock = mockFetchOk({
      username: 'alice', rate: 40, source: 'booking',
      last_rate: 40, last_booked_at: '2026-08-01', campaigns: 2,
    })
    const result = await api.getLibraryRate('alice')

    expect(lastCall(fetchMock).url).toContain('/api/library/creators/alice/rate')
    expect(result.rate).toBe(40)
    expect(result.source).toBe('booking')
  })

  it('triggers a stats refresh with POST', async () => {
    const fetchMock = mockFetchOk({ ok: true, trackers: 255, creators: 375 })
    await api.refreshLibraryStats()

    const { url, init } = lastCall(fetchMock)
    expect(url).toContain('/api/library/refresh-stats')
    expect(init?.method).toBe('POST')
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from '@/lib/api'

type FetchMock = ReturnType<typeof vi.fn>

function mockFetchOk<T>(body: T, init?: { status?: number }) {
  const fetchMock: FetchMock = vi.fn().mockResolvedValue({
    ok: (init?.status ?? 200) < 400,
    status: init?.status ?? 200,
    statusText: 'OK',
    json: () => Promise.resolve(body),
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  return fetchMock
}

function mockFetchError(status: number, body?: unknown) {
  const fetchMock: FetchMock = vi.fn().mockResolvedValue({
    ok: false,
    status,
    statusText: `HTTP ${status}`,
    json: () => Promise.resolve(body ?? { error: `HTTP ${status}` }),
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  return fetchMock
}

describe('api client', () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  describe('request error handling', () => {
    it('throws ApiError with status on non-2xx responses', async () => {
      mockFetchError(500, { error: 'server boom' })
      await expect(api.getCampaigns()).rejects.toMatchObject({
        name: 'ApiError',
        status: 500,
        message: 'server boom',
      })
    })

    it('falls back to statusText when body is not JSON', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 502,
        statusText: 'Bad Gateway',
        json: () => Promise.reject(new Error('not json')),
      }) as unknown as typeof fetch

      await expect(api.getCampaigns()).rejects.toMatchObject({
        status: 502,
        message: 'Bad Gateway',
      })
    })

    it('ApiError is an Error subclass', async () => {
      mockFetchError(404)
      try {
        await api.getCampaigns()
      } catch (e) {
        expect(e).toBeInstanceOf(Error)
        expect(e).toBeInstanceOf(ApiError)
      }
    })
  })

  describe('GET endpoints', () => {
    it('getCampaigns hits /api/campaigns', async () => {
      const fetchMock = mockFetchOk([])
      await api.getCampaigns()
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toContain('/api/campaigns')
      expect(init?.method).toBeUndefined()
    })

    it('getCampaign substitutes the slug', async () => {
      const fetchMock = mockFetchOk({})
      await api.getCampaign('my-slug')
      expect(fetchMock.mock.calls[0][0]).toContain('/api/campaign/my-slug')
    })

    it('searchCampaigns URL-encodes the query', async () => {
      const fetchMock = mockFetchOk({})
      await api.searchCampaigns('hello world & friends')
      expect(fetchMock.mock.calls[0][0]).toContain(
        'q=hello%20world%20%26%20friends',
      )
    })

    it('getInbox without status omits query param', async () => {
      const fetchMock = mockFetchOk([])
      await api.getInbox()
      expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/inbox$/)
    })

    it('getInbox with status adds query param', async () => {
      const fetchMock = mockFetchOk([])
      await api.getInbox('approved')
      expect(fetchMock.mock.calls[0][0]).toContain('/api/inbox?status=approved')
    })

    it('getScrapeTaskQueue with no params omits query string', async () => {
      const fetchMock = mockFetchOk({})
      await api.getScrapeTaskQueue()
      expect(fetchMock.mock.calls[0][0]).toMatch(
        /\/api\/scrape-tasks\/queue$/,
      )
    })

    it('getScrapeTaskQueue forwards filter params', async () => {
      const fetchMock = mockFetchOk({})
      await api.getScrapeTaskQueue({
        campaign: 'sam_barber',
        limit: 10,
      })
      const url = fetchMock.mock.calls[0][0] as string
      expect(url).toContain('campaign=sam_barber')
      expect(url).toContain('limit=10')
    })

    it('listTrackers omits archived flag by default', async () => {
      const fetchMock = mockFetchOk([])
      await api.listTrackers()
      expect(fetchMock.mock.calls[0][0]).toMatch(/\/api\/trackers$/)
    })

    it('listTrackers includes archived flag when asked', async () => {
      const fetchMock = mockFetchOk([])
      await api.listTrackers(true)
      expect(fetchMock.mock.calls[0][0]).toContain(
        '/api/trackers?include_archived=true',
      )
    })
  })

  describe('POST/PUT/DELETE endpoints', () => {
    it('createCampaign sends JSON body', async () => {
      const fetchMock = mockFetchOk({ ok: true, slug: 'x' })
      await api.createCampaign({
        title: 'X - Y',
        official_sound: '',
        start_date: '2026-01-01',
        budget: 1000,
      })
      const [, init] = fetchMock.mock.calls[0]
      expect(init?.method).toBe('POST')
      expect(JSON.parse(init?.body as string)).toEqual({
        title: 'X - Y',
        official_sound: '',
        start_date: '2026-01-01',
        budget: 1000,
      })
    })

    it('editCampaign uses POST and slug in URL', async () => {
      const fetchMock = mockFetchOk({ ok: true })
      await api.editCampaign('my-slug', { title: 'new' })
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toContain('/api/campaign/my-slug/edit')
      expect(init?.method).toBe('POST')
    })

    it('removeCreator uses POST', async () => {
      const fetchMock = mockFetchOk({ ok: true })
      await api.removeCreator('slug', 'alice')
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toContain('/api/campaign/slug/creator/alice/remove')
      expect(init?.method).toBe('POST')
    })

    it('setCobrandLinks uses PUT and sends share/upload urls', async () => {
      const fetchMock = mockFetchOk({ ok: true })
      await api.setCobrandLinks('slug', { share_url: 's', upload_url: 'u' })
      const [, init] = fetchMock.mock.calls[0]
      expect(init?.method).toBe('PUT')
      expect(JSON.parse(init?.body as string)).toEqual({
        share_url: 's',
        upload_url: 'u',
      })
    })

    it('removeNetworkCreator uses DELETE', async () => {
      const fetchMock = mockFetchOk({ ok: true })
      await api.removeNetworkCreator('alice')
      const [, init] = fetchMock.mock.calls[0]
      expect(init?.method).toBe('DELETE')
    })

    it('archiveTracker uses DELETE', async () => {
      const fetchMock = mockFetchOk({ ok: true })
      await api.archiveTracker('t-id')
      const [url, init] = fetchMock.mock.calls[0]
      expect(url).toContain('/api/trackers/t-id')
      expect(init?.method).toBe('DELETE')
    })

    it('triggerCron passes job_type in body', async () => {
      const fetchMock = mockFetchOk({ status: 'ok', job_type: 'x' })
      await api.triggerCron('internal_scrape')
      const [, init] = fetchMock.mock.calls[0]
      expect(JSON.parse(init?.body as string)).toEqual({
        job_type: 'internal_scrape',
      })
    })

    it('sets Content-Type to application/json on all requests', async () => {
      const fetchMock = mockFetchOk([])
      await api.getCampaigns()
      const init = fetchMock.mock.calls[0][1] as RequestInit
      const headers = init.headers as Record<string, string>
      expect(headers['Content-Type']).toBe('application/json')
    })
  })
})

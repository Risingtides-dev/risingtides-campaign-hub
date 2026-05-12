import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import {
  useCampaigns,
  useCampaign,
  useSearch,
  useInbox,
  useCreators,
} from '@/lib/queries'

function wrapper(client?: QueryClient) {
  const qc = client ?? new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  }
}

function mockFetchSequence(responses: Array<{ status?: number; body: unknown }>) {
  const queue = [...responses]
  const fetchMock = vi.fn().mockImplementation(() => {
    const next = queue.shift() ?? { body: [] }
    return Promise.resolve({
      ok: (next.status ?? 200) < 400,
      status: next.status ?? 200,
      statusText: 'OK',
      json: () => Promise.resolve(next.body),
    })
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  return fetchMock
}

const originalFetch = globalThis.fetch

beforeEach(() => {
  // Reset before each test.
})

afterEach(() => {
  globalThis.fetch = originalFetch
})

describe('useCampaigns', () => {
  it('fetches campaigns and exposes them via data', async () => {
    mockFetchSequence([{ body: [{ slug: 'a', title: 'A' }] }])
    const { result } = renderHook(() => useCampaigns(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([{ slug: 'a', title: 'A' }])
  })

  it('surfaces an error when the API fails', async () => {
    mockFetchSequence([{ status: 500, body: { error: 'boom' } }])
    const { result } = renderHook(() => useCampaigns(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isError).toBe(true))
    expect((result.current.error as Error).message).toBe('boom')
  })
})

describe('useCampaign', () => {
  it('is disabled when slug is empty', async () => {
    const fetchMock = mockFetchSequence([])
    const { result } = renderHook(() => useCampaign(''), { wrapper: wrapper() })
    // Give react-query a tick.
    await new Promise((r) => setTimeout(r, 30))
    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('fetches when slug is supplied', async () => {
    const fetchMock = mockFetchSequence([{ body: { slug: 'x', title: 'X' } }])
    const { result } = renderHook(() => useCampaign('x'), {
      wrapper: wrapper(),
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(result.current.data?.slug).toBe('x')
  })
})

describe('useSearch', () => {
  it('is disabled for empty query', async () => {
    const fetchMock = mockFetchSequence([])
    renderHook(() => useSearch(''), { wrapper: wrapper() })
    await new Promise((r) => setTimeout(r, 30))
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('fires when query is non-empty', async () => {
    const fetchMock = mockFetchSequence([{ body: { campaigns: [] } }])
    const { result } = renderHook(() => useSearch('hello'), {
      wrapper: wrapper(),
    })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toContain('q=hello')
  })
})

describe('useInbox', () => {
  it('hits /api/inbox with no status query when unset', async () => {
    const fetchMock = mockFetchSequence([{ body: [] }])
    const { result } = renderHook(() => useInbox(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = fetchMock.mock.calls[0][0] as string
    expect(url).toMatch(/\/api\/inbox$/)
  })
})

describe('useCreators', () => {
  it('returns the array shape from the API', async () => {
    mockFetchSequence([{ body: [{ username: 'a' }, { username: 'b' }] }])
    const { result } = renderHook(() => useCreators(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(2)
  })
})

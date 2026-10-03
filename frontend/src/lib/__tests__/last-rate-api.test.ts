import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/lib/api'

describe('api.getLastRate', () => {
  const originalFetch = globalThis.fetch

  afterEach(() => {
    globalThis.fetch = originalFetch
  })

  it('requests the last-rate endpoint and returns the booking', async () => {
    const body = {
      last_rate: {
        total_rate: 300,
        posts_owed: 3,
        campaign: 'Sam Barber - Fever Dream',
        added_date: '2026-09-10',
      },
    }
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: () => Promise.resolve(body),
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch

    const result = await api.getLastRate('beaujenkins')

    expect(fetchMock.mock.calls[0][0]).toContain('/api/last-rate/beaujenkins')
    expect(result).toEqual(body)
  })
})

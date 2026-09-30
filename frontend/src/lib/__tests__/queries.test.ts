import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { keys, useEditCampaign } from '@/lib/queries'
import { api } from '@/lib/api'

vi.mock('@/lib/api', () => ({ api: { editCampaign: vi.fn() } }))

describe('query key factory', () => {
  it('static keys are stable arrays', () => {
    expect(keys.campaigns).toEqual(['campaigns'])
    expect(keys.creators).toEqual(['creators'])
    expect(keys.internalCreators).toEqual(['internal', 'creators'])
    expect(keys.scrapeTaskHealth).toEqual(['scrape-tasks', 'health'])
  })

  it('campaign(slug) returns a unique tuple per slug', () => {
    expect(keys.campaign('a')).toEqual(['campaign', 'a'])
    expect(keys.campaign('b')).toEqual(['campaign', 'b'])
  })

  it('nested keys share the parent prefix', () => {
    expect(keys.campaignLinks('x')).toEqual(['campaign', 'x', 'links'])
    expect(keys.cobrandStats('x')).toEqual(['campaign', 'x', 'cobrand'])
  })

  it('inbox key falls back to "all" when status omitted', () => {
    expect(keys.inbox()).toEqual(['inbox', 'all'])
    expect(keys.inbox('pending')).toEqual(['inbox', 'pending'])
  })

  it('scrapeTaskQueue key normalizes missing params to empty strings', () => {
    expect(keys.scrapeTaskQueue()).toEqual([
      'scrape-tasks',
      'queue',
      '',
      '',
    ])
    expect(keys.scrapeTaskQueue({ campaign: 'a' })).toEqual([
      'scrape-tasks',
      'queue',
      'a',
      '',
    ])
    expect(keys.scrapeTaskQueue({ campaign: 'a', since: '2026-01-01' })).toEqual(
      ['scrape-tasks', 'queue', 'a', '2026-01-01'],
    )
  })

  it('internalGroup keys are distinct from internalGroupStats', () => {
    expect(keys.internalGroup('g')).not.toEqual(keys.internalGroupStats('g', 30))
  })
})

it('awaits campaign invalidations but resolves without waiting for pop score refresh', async () => {
  const qc = new QueryClient()
  let release!: () => void
  const pending = new Promise<void>((resolve) => { release = resolve })
  vi.spyOn(qc, 'invalidateQueries').mockReturnValue(pending as never)
  vi.mocked(api.editCampaign).mockResolvedValue({} as never)
  const wrapper = ({ children }: { children: React.ReactNode }) => React.createElement(QueryClientProvider, { client: qc }, children)
  const { result } = renderHook(() => useEditCampaign('song'), { wrapper })
  let settled = false
  let mutation!: Promise<unknown>
  act(() => { mutation = result.current.mutateAsync({ title: 'fresh' }).then((v) => { settled = true; return v }) })
  await waitFor(() => expect(qc.invalidateQueries).toHaveBeenCalledTimes(2))
  expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: keys.campaign('song') })
  expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: keys.campaigns })
  expect(settled).toBe(false)
  release()
  await mutation
  expect(settled).toBe(true)
  expect(qc.invalidateQueries).toHaveBeenCalledWith({ queryKey: ['popScore', 'song'] })
})

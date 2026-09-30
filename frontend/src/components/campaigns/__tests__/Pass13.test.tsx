import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cloneElement } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { PopScoreCard } from '@/components/campaigns/PopScoreCard'
import { useEditCampaign, useOverridePopScore, usePopScore, useSetPopScoreTrack } from '@/lib/queries'
import type { PopScore } from '@/lib/types'
import espressoWalk from './fixtures/popscore_espresso_walk.json'

const containerWidth = vi.hoisted(() => ({ value: 600 }))

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  return { ...actual, ResponsiveContainer: ({ children }: { children: React.ReactElement }) => <div style={{ width: containerWidth.value, height: 240 }}>{cloneElement(children as React.ReactElement<{ width?: number; height?: number }>, { width: containerWidth.value, height: 240 })}</div> }
})

vi.mock('@/lib/queries', () => ({
  usePopScore: vi.fn(),
  useSetPopScoreTrack: vi.fn(),
  useOverridePopScore: vi.fn(),
  useEditCampaign: vi.fn(),
}))

const payload: PopScore = {
  linked: true, start_date: '2026-08-01', end_date: '2026-08-20', followup_days: 28,
  followup_end: '2026-09-17', followup_day: 6, phase: 'followup', data_as_of: '2026-08-25',
  track: { name: 'Example Song', artists: ['Artist One'], image_url: '' },
  popularity: { start: 61, end: 68, end_is_to_date: false, followup: 66, followup_is_to_date: false, change_campaign: 7, change_followup: -2 },
  streams: { start_total: 1_000_000, end_total: 1_400_000, end_is_to_date: false, followup_total: 1_650_000, followup_is_to_date: false, gained_campaign: 400_000, gained_followup: 250_000, growth_pct_campaign: 40, baseline_daily: 5000, campaign_daily: 14285.7, followup_daily: 8928.6, lift_pct_campaign: 185.7, lift_pct_followup: 78.6 },
  ugc: { start: 120, end: 480, followup: 600, now: 600, now_date: '2026-09-18', start_total: 120, end_total: 480, followup_total: 600, end_is_to_date: false, followup_is_to_date: false, gained_campaign: 3600, gained_followup: 120, change_since_start: 480, change_since_end: 120, baseline_daily: 120, campaign_daily: 480, followup_daily: 210, lift_pct_campaign: 300, lift_pct_followup: 75 },
  history: [{ date: '2026-08-01', value: 61 }, { date: '2026-08-20', value: 68 }],
  streams_history: [{ date: '2026-08-01', total: 1_000_000, daily: null }, { date: '2026-08-10', total: 1_200_000, daily: 20000 }, { date: '2026-08-20', total: 1_400_000, daily: 20000 }],
  ugc_history: [{ date: '2026-08-01', total: 120, daily: null }, { date: '2026-08-10', total: 300, daily: 18 }, { date: '2026-08-20', total: 480, daily: 18 }],
}
const mutate = vi.fn()
const overrideMutate = vi.fn()
function setup(data: PopScore = payload) {
  vi.mocked(usePopScore).mockReturnValue({ data, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
  vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate, isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
  vi.mocked(useOverridePopScore).mockReturnValue({ mutate: overrideMutate, isPending: false, isError: false } as unknown as ReturnType<typeof useOverridePopScore>)
  vi.mocked(useEditCampaign).mockReturnValue({ mutate, reset: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
  return render(<PopScoreCard slug="example" tracker_url="https://tracker.example" />)
}

describe('pass13 stale row', () => {
  beforeEach(() => vi.clearAllMocks())
  it('P13-A: pluralizes stale choices and shows each date, metric, and choice', () => {
    setup({ ...payload, stale_overrides: [{ metric: 'ugc', date: '2026-08-13', action: 'exclude' }, { metric: 'streams', date: '2026-08-15', action: 'include' }] })
    expect(screen.getAllByRole('button', { name: /Reset stale/ })).toHaveLength(2)
    expect(screen.getByText("2 saved choices no longer match Chartmetric's data")).toBeInTheDocument()
    expect(screen.getByText('Aug 13, 2026 · TikTok videos · not counted')).toBeInTheDocument()
    expect(screen.getByText('Aug 15, 2026 · Streams · counted')).toBeInTheDocument()
  })
  it('P13-B: disables pending stale Reset and reports failure beside the stale list', () => {
    vi.mocked(usePopScore).mockReturnValue({ data: { ...payload, stale_overrides: [{ metric: 'ugc', date: '2026-08-13', action: 'exclude' }] }, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate, isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
    vi.mocked(useOverridePopScore).mockReturnValue({ mutate: overrideMutate, isPending: true, isError: true, error: new Error('Override failed'), variables: { metric: 'ugc', date: '2026-08-13', action: 'auto' } } as unknown as ReturnType<typeof useOverridePopScore>)
    vi.mocked(useEditCampaign).mockReturnValue({ mutate, reset: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
    render(<PopScoreCard slug="example" tracker_url="https://tracker.example" />)
    expect(screen.getByRole('button', { name: /Reset stale ugc/ })).toBeDisabled()
    expect(screen.getByRole('alert')).toHaveTextContent('Override failed')
  })

  it('anchors an Espresso UGC follow-up label within the chart SVG width', () => {
    const data = { ...espressoWalk, phase: 'followup', ugc: { ...espressoWalk.ugc, followup_is_to_date: true } } as unknown as PopScore
    setup(data)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily new videos' }))
    const svg = screen.getByRole('img', { name: /Daily new videos trend chart/ }).querySelector('svg')!
    const label = [...svg.querySelectorAll('text')].find(node => node.textContent?.includes('+28'))
    expect(label).toBeTruthy()
    const x = Number(label?.getAttribute('x'))
    expect(label).toHaveAttribute('text-anchor', 'end')
    expect(x).toBeLessThanOrEqual(Number(svg.getAttribute('width')))
  })
})

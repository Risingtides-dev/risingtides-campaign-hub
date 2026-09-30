import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cloneElement } from 'react'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { PopScoreCard } from '@/components/campaigns/PopScoreCard'
import { renderTrendTooltipForRow } from '@/components/campaigns/PopScoreCard'
import { useEditCampaign, usePopScore, useSetPopScoreTrack } from '@/lib/queries'
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
function setup(data: PopScore = payload) {
  vi.mocked(usePopScore).mockReturnValue({ data, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
  vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate, isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
  vi.mocked(useEditCampaign).mockReturnValue({ mutate, reset: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
  return render(<PopScoreCard slug="example" tracker_url="https://tracker.example" />)
}


const ticks = () => document.querySelectorAll('.creator-post-tick').length
const bars = () => document.querySelectorAll('.recharts-bar-rectangle').length
let resizeCallback: ResizeObserverCallback | undefined
describe('pass7 probes', () => {
  beforeEach(() => { vi.clearAllMocks(); containerWidth.value = 600 })
  it('post ticks on dates not plotted in the series', () => {
    const ev = [
      { date: '2026-08-10', count: 2 },   // plotted in all series
      { date: '2026-08-18', count: 1 },   // missing from popularity history
      { date: '2026-09-29', count: 3 },   // ugc has it, streams does not (data lag)
      { date: '2026-09-30', count: 4 },   // today: after data_as_of
      { date: '2026-09-23', count: 5 },   // ugc recount day
    ]
    const real = { ...espressoWalk, end_date_auto: false, post_events: ev } as unknown as PopScore
    setup(real)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    expect(ticks()).toBe(ev.length)
    expect(document.querySelectorAll('.recharts-line-curve').length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Daily streams' }))
    expect(ticks()).toBe(ev.length)
    expect(bars()).toBe(real.streams_history!.filter(p => p.daily != null).length)
    fireEvent.click(screen.getByRole('button', { name: 'Daily new videos' }))
    expect(ticks()).toBe(ev.length)
    expect(bars()).toBe(real.ugc_history!.filter(p => p.daily != null).length)
  })
  it('tooltip on recount day with posts', () => {
    const popup = render(renderTrendTooltipForRow({ date: '2026-09-23', value: null, recountY: 0 }, 'ugc', [{ date: '2026-09-23', count: 5 }]))
    expect(popup.container.textContent).toContain('recount (not counted)')
    expect(popup.container.textContent).toContain('5 creator posts')
  })
  it('labels at 375 and after re-render', () => {
    class MockResizeObserver {
      constructor(callback: ResizeObserverCallback) { resizeCallback = callback }
      observe() {}
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', MockResizeObserver)
    const real = { ...espressoWalk, end_date_auto: true, end_date: '2026-09-30' } as unknown as PopScore
    setup(real)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    act(() => resizeCallback?.([{ contentRect: { width: 375 } } as ResizeObserverEntry], {} as ResizeObserver))
    expect([...document.querySelectorAll('.recharts-label tspan')].map(n => n.textContent)).toEqual(expect.arrayContaining(['S', 'E']))
    fireEvent.click(screen.getByRole('button', { name: 'Daily new videos' }))
    expect([...document.querySelectorAll('.recharts-label tspan')].map(n => n.textContent)).toEqual(expect.arrayContaining(['S', 'E']))
    expect([...document.querySelectorAll('span')].map(n => n.textContent).filter(t => t?.includes('End Sep 30, 2026'))).toHaveLength(1)
  })

  it('shows the end date only once with completion provenance', () => {
    const real = { ...espressoWalk, end_date_auto: true, end_date: '2026-09-30' } as unknown as PopScore
    setup(real)
    expect(screen.getByText('· set when finished')).toBeTruthy()
    expect([...document.querySelectorAll('span')].map(n => n.textContent).filter(t => t?.includes('End Sep 30, 2026'))).toHaveLength(1)
  })

  it('shows signed recount changes', () => {
    const real = { ...espressoWalk, ugc: { ...espressoWalk.ugc, recounts: [{ date: '2026-05-23', change: -2_800_000 }] } } as unknown as PopScore
    setup(real)
    expect(screen.getByText(/−2\.8M TikTok videos/)).toBeTruthy()
  })

  it('shows unusual jumps as muted counted notes', () => {
    const real = { ...espressoWalk, ugc: { ...espressoWalk.ugc, unusual: [{ date: '2026-08-02', change: 51_743 }] } } as unknown as PopScore
    setup(real)
    expect(document.body.textContent).toContain('Unusual one-day jump on Aug 2, 2026 (+51.7K TikTok videos) — counted')
  })
})

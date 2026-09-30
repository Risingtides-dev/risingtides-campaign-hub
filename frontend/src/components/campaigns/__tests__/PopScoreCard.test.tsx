import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cloneElement } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { PopScoreCard } from '@/components/campaigns/PopScoreCard'
import { chartAxisProps as componentChartAxisProps, formatTrendTooltip } from '@/components/campaigns/PopScoreCard'
import { chartAxisProps, chartTooltipProps, formatChartDateLabel, localTickDate } from '@/components/campaigns/chartDate'
import { useEditCampaign, usePopScore, useSetPopScoreTrack } from '@/lib/queries'
import type { PopScore } from '@/lib/types'
import espressoWalk from './fixtures/popscore_espresso_walk.json'
import blindingLightsWalk from './fixtures/popscore_blinding_lights_walk.json'

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

describe('<PopScoreCard /> attribution', () => {
  beforeEach(() => vi.clearAllMocks())

  it('keeps real espresso daily bars and only plotted recount marks; stream mode has no recount circles', () => {
    const real = { ...espressoWalk, end_date_auto: false } as unknown as PopScore
    setup(real)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily new videos' }))
    expect(document.querySelectorAll('.recharts-bar-rectangle')).toHaveLength(real.ugc_history!.filter(point => point.daily != null).length)
    expect(document.querySelectorAll('circle[fill="none"][stroke="#909098"]')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: 'Daily streams' }))
    expect(document.querySelectorAll('circle[fill="none"][stroke="#909098"]')).toHaveLength(0)
  })

  it('keeps bars and popularity line when plotted creator events are present', () => {
    const real = { ...blindingLightsWalk, end_date_auto: false, post_events: [{ date: blindingLightsWalk.streams_history[10].date, count: 1 }] } as unknown as PopScore
    setup(real)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily streams' }))
    expect(document.querySelectorAll('.recharts-bar-rectangle')).toHaveLength(real.streams_history!.filter(point => point.daily != null).length)
    expect(document.querySelectorAll('.creator-post-tick')).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Popularity' }))
    expect(document.querySelectorAll('.recharts-line-curve').length).toBeGreaterThan(0)
  })

  it('renders values from the full attribution payload', () => {
    setup()
    expect(screen.getByText('Song attribution')).toBeInTheDocument()
    expect(screen.getByText('Example Song')).toBeInTheDocument()
    expect(screen.getByText('Follow-up (day 6 of 28)')).toBeInTheDocument()
    expect(screen.getByText('61')).toBeInTheDocument()
    expect(screen.getByText('68')).toBeInTheDocument()
    expect(screen.getByText('1.4M')).toBeInTheDocument()
    expect(screen.getByText(/streams 5K → 14.3K\/day \(\+185.7%\)/)).toBeInTheDocument()
    expect(screen.getByText(/TikTok videos 120 → 480\/day, 3.6K new during the campaign/)).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '+28 days' })).toBeInTheDocument()
    expect(screen.getByText('Open Tides Tracker ↗')).toBeInTheDocument()
    expect(screen.getByText(/\+400K during campaign/)).toBeInTheDocument()
    expect(screen.getByText(/New TikTok videos\/day 120 → 480 during \(\+300.0%\) → 210 after · 3.6K new during the campaign/)).toBeInTheDocument()
  })

  it('shows four snapshot columns, muted changes, to-date markers, and same for equal readings', () => {
    setup({ ...payload, streams: { ...payload.streams!, end_is_to_date: true, followup_is_to_date: true, now: 1_650_000, now_date: '2026-09-18', followup_total: 1_650_000 }, ugc: { ...payload.ugc!, followup_is_to_date: true, now_date: '2026-09-18' } })
    expect(screen.getByRole('columnheader', { name: 'Start' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'End' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: '+28 days' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Now' })).toBeInTheDocument()
    expect(screen.getAllByText('to date').length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText('same as +28 days')).toHaveLength(2)
    expect(screen.getByText(/\+400K during campaign/)).toBeInTheDocument()
  })

  it('renders null metrics as dashes and null percentages as N/A, never zero', () => {
    setup({ ...payload, popularity: { ...payload.popularity!, start: null, end: null, change_campaign: null }, streams: { ...payload.streams!, start_total: null, growth_pct_campaign: null, baseline_daily: null } })
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('offers an end date and to-date labels when no end date is set', () => {
    setup({ ...payload, end_date: '', followup_end: '', phase: 'live', popularity: { ...payload.popularity!, end_is_to_date: true, followup: null }, streams: { ...payload.streams!, end_is_to_date: true, followup_total: null } })
    expect(screen.getByText(/End not set/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set an end date' })).toBeInTheDocument()
    expect(screen.getAllByText('to date').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Set an end date').length).toBeGreaterThan(0)
  })

  it('shows phase badge text', () => {
    setup({ ...payload, phase: 'complete' })
    expect(screen.getByText('Complete')).toBeInTheDocument()
  })

  it('shows the finished without an end date badge and keeps the end date setter', () => {
    setup({ ...payload, phase: 'finished_no_end', end_date: '', followup_end: '' })
    expect(screen.getByText('Finished · end date not set')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set an end date' })).toBeInTheDocument()
    expect(screen.queryByText('Live')).not.toBeInTheDocument()
  })

  it('switches the selected chart series with the toggle', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    const popularity = screen.getByRole('button', { name: 'Popularity' })
    const streams = screen.getByRole('button', { name: 'Daily streams' })
    expect(popularity).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('img', { name: /Popularity trend chart/ })).toBeInTheDocument()
    const plotLabels = [...document.querySelectorAll('.recharts-label tspan')].map(node => node.textContent)
    expect(plotLabels).toContain('Start')
    expect(plotLabels).toContain('End')
    expect([...document.querySelectorAll('.recharts-cartesian-axis-tick-value')].some(t => Number(t.textContent) < 61)).toBe(true)
    fireEvent.click(streams)
    expect(screen.getByRole('img', { name: /Daily streams trend chart/ })).toBeInTheDocument()
    expect(document.querySelectorAll('.recharts-bar-rectangle').length).toBeGreaterThan(0)
    expect(screen.queryByRole('img', { name: /Popularity trend chart/ })).not.toBeInTheDocument()
    expect(streams).toHaveAttribute('aria-pressed', 'true')
    expect(popularity).toHaveAttribute('aria-pressed', 'false')
    const ugc = screen.getByRole('button', { name: 'Daily new videos' })
    fireEvent.click(ugc)
    expect(screen.getByRole('img', { name: /Daily new videos trend chart/ })).toBeInTheDocument()
    expect(document.querySelectorAll('.recharts-bar-rectangle').length).toBeGreaterThan(0)
    expect(ugc).toHaveAttribute('aria-pressed', 'true')
  })


  it('keeps the trend control wired and summarizes the rendered chart for assistive tech', () => {
    setup()
    const control = screen.getByRole('button', { name: 'Show trend' })
    expect(control).toHaveAttribute('aria-expanded', 'false')
    expect(document.getElementById(control.getAttribute('aria-controls')!)).toBeInTheDocument()
    fireEvent.click(control)
    expect(control).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('img', { name: /Popularity trend chart for Example Song/ })).toBeInTheDocument()
  })

  it('shows recount copy under the rates and renders recount and event marks on the numeric timeline', () => {
    setup({ ...payload, post_events: [{ date: '2026-08-15', count: 3 }] })
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily streams' }))
    expect(document.querySelectorAll('.recharts-scatter-symbol').length).toBeGreaterThan(0)
    expect(document.querySelectorAll('.recharts-reference-line').length).toBeGreaterThan(0)
  })


  it('shows recount copy and a hollow recount marker without changing adjusted bars', () => {
    setup({ ...payload, ugc: { ...payload.ugc!, recounts: [{ date: '2026-08-10', change: 543000 }] } })
    expect(screen.getByText(/Chartmetric recount on Aug 10, 2026 \(\+543K TikTok videos\) not counted/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily new videos' }))
    expect(document.querySelector('circle[fill="none"][stroke="#909098"]')).toBeInTheDocument()
  })

  it('shows stream recounts with muted copy, a hollow mark, and recount tooltip wording', () => {
    setup({ ...payload, streams: { ...payload.streams!, recounts: [{ date: '2026-08-10', change: -543000 }] } })
    expect(screen.getByText(/Chartmetric recount on Aug 10, 2026 \(−543K streams\) not counted/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily streams' }))
    expect(document.querySelectorAll('circle[fill="none"][stroke="#909098"]')).toHaveLength(1)
    expect(formatTrendTooltip({ date: '2026-08-10', recount: true }, 'streams').value).toBe('recount (not counted)')
  })

  it('collapses recounts and unusual jumps at two, reports largest absolute signed change and keeps hover details', () => {
    setup({ ...payload,
      streams: { ...payload.streams!, adjusted: true, recounts: [{ date: '2026-05-20', change: 1_200_000 }, { date: '2026-05-23', change: -2_800_000 }], unusual: [{ date: '2026-05-24', change: -4_000 }, { date: '2026-05-25', change: 3_000 }] },
      ugc: { ...payload.ugc!, adjusted: false, recounts: [], unusual: [{ date: '2026-05-21', change: 20_000 }, { date: '2026-05-22', change: -30_000 }] },
    })
    const recount = screen.getByText(/Streams: 2 Chartmetric recounts not counted · largest −2.8M on May 23, 2026/)
    expect(recount).toHaveAttribute('title', expect.stringContaining('May 20, 2026 (+1.2M streams)'))
    expect(screen.getByText(/Streams: 2 unusual jumps counted · largest −4K on May 24, 2026/)).toBeInTheDocument()
    expect(screen.getByText(/TikTok videos: 2 unusual jumps counted · largest −30K on May 22, 2026/)).toBeInTheDocument()
  })

  it('shows recount footnote only with adjusted metrics, marks only those rows, and omits footnote before start', () => {
    const { container, rerender } = setup({ ...payload, streams: { ...payload.streams!, adjusted: true }, ugc: { ...payload.ugc!, adjusted: false } })
    const rows = [...container.querySelectorAll('tbody tr')]
    expect(rows[1].querySelector('sup')).toHaveTextContent('*')
    expect(rows[2].querySelector('sup')).toBeNull()
    expect(screen.getByText('* Totals are as reported; changes leave out Chartmetric recounts.')).toBeInTheDocument()
    vi.mocked(usePopScore).mockReturnValue({ data: { ...payload, phase: 'not_started', streams: { ...payload.streams!, adjusted: true }, ugc: { ...payload.ugc!, adjusted: false } }, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    rerender(<PopScoreCard slug="example" />)
    expect(screen.queryByText('* Totals are as reported; changes leave out Chartmetric recounts.')).not.toBeInTheDocument()
    expect(screen.getAllByText('Not started')).toHaveLength(1)
  })

  it('dims smoothed bars with a lighter dim fill and labels the estimate', () => {
    setup({ ...payload, streams_history: [{ date: '2026-08-01', total: 1000, daily: 800, smoothed: false }, { date: '2026-08-10', total: 9000, daily: 900, smoothed: true }, { date: '2026-08-20', total: 20000, daily: 1100 }] })
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily streams' }))
    expect(screen.getByText('light = estimated (Chartmetric skipped a day)')).toBeInTheDocument()
    const fills = [...document.querySelectorAll('.recharts-bar-rectangle path')].map(node => node.getAttribute('fill'))
    expect(fills[0]).toBe('#E100C355')
    expect(fills[1]).toBe('#E100C333')
  })


  it('formats rendered chart tooltip rows as dates, series values, estimates, and creator posts', () => {
    expect(formatTrendTooltip({ date: '2026-08-10', value: 992, smoothed: true, count: 3 }, 'streams')).toEqual({ date: 'Aug 10, 2026', value: '992', label: 'Daily streams', estimated: true, posts: 3 })
    expect(formatTrendTooltip({ date: '2026-08-10', value: 69 }, 'popularity')).toEqual({ date: 'Aug 10, 2026', value: '69', label: 'Popularity', estimated: false, posts: undefined })
    expect(formatTrendTooltip({ date: '2026-08-10', value: 592.5 }, 'streams').value).toBe('593')
    expect(formatTrendTooltip({ date: '2026-08-10', value: 1200 }, 'streams').value).toBe('1.2K')
  })

  it('disables Clear while the end-date mutation is pending and indicates refresh work', () => {
    vi.mocked(usePopScore).mockReturnValue({ data: payload, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate, isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
    vi.mocked(useEditCampaign).mockReturnValue({ mutate, reset: vi.fn(), isPending: true, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
    const { rerender } = render(<PopScoreCard slug="example" />)
    expect(screen.getAllByRole('button', { name: 'Clear' }).at(-1)).toBeDisabled()
    expect(screen.getByText('Updating…')).toBeInTheDocument()
    vi.mocked(usePopScore).mockReturnValue({ data: payload, isLoading: false, isFetching: true, isError: false } as ReturnType<typeof usePopScore>)
    rerender(<PopScoreCard slug="example" />)
    expect(screen.getAllByText('Updating…').length).toBeGreaterThan(0)
  })

  it('shows reading dates and only calls Now the same as +28 days when the dates match', () => {
    setup({ ...payload, streams: { ...payload.streams!, now: 92, now_date: '2026-09-28', followup_total: 92, followup_is_to_date: false }, followup_end: '2026-07-28' })
    expect(screen.getByText('as of Sep 28, 2026')).toBeInTheDocument()
    expect(screen.queryByText('same as +28 days')).not.toBeInTheDocument()
    expect(screen.getAllByText(/since end/).length).toBeGreaterThan(0)
  })

  it('adds to-date headline copy, formats small daily rates as integers, and shows auto-end provenance in any phase', () => {
    setup({ ...payload, phase: 'live', end_date: '2026-08-20', end_date_auto: true, streams: { ...payload.streams!, baseline_daily: 871.1, campaign_daily: 992.7 } })
    expect(screen.getByText(/\(to date\)/)).toBeInTheDocument()
    expect(screen.getByText(/Daily streams 871 → 993 during/)).toBeInTheDocument()
    expect(screen.getByText('· set when finished')).toBeInTheDocument()
  })

  it('saves, changes, clears an end date and shows edit errors', () => {
    const { rerender } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Change' }))
    fireEvent.change(screen.getByLabelText('End date'), { target: { value: '2026-08-22' } })
    expect(mutate).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(mutate).toHaveBeenCalledWith({ end_date: '2026-08-22' }, expect.any(Object))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(mutate).toHaveBeenCalledWith({ end_date: '' })
    vi.mocked(useEditCampaign).mockReturnValue({ mutate, isPending: false, isError: true, error: new Error('bad date') } as unknown as ReturnType<typeof useEditCampaign>)
    rerender(<PopScoreCard slug="example" />)
    expect(screen.getByRole('alert')).toHaveTextContent('bad date')
  })

  it('resets the end-date error when Change or Cancel is used', () => {
    setup()
    const reset = vi.mocked(useEditCampaign).mock.results[0].value.reset!
    fireEvent.click(screen.getByRole('button', { name: 'Change' }))
    expect(reset).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(reset).toHaveBeenCalledTimes(2)
  })

  it('shows popularity when streams fail', () => {
    setup({ ...payload, streams_error: 'Streams history is temporarily unavailable.' })
    expect(screen.getAllByText('Popularity').length).toBeGreaterThan(0)
    expect(screen.getByRole('status')).toHaveTextContent('Streams history is temporarily unavailable.')
    expect(screen.getByText('Streams', { exact: true })).toBeInTheDocument()
    expect(screen.queryByText(/Daily streams/)).not.toBeInTheDocument()
  })

  it('formats stream gains with proper signs and null placeholders', () => {
    setup({ ...payload, streams: { ...payload.streams!, gained_campaign: -45, gained_followup: null } })
    expect(screen.getByText('Streams')).toBeInTheDocument()
  })

  it('labels a shared start and end marker once', () => {
    setup({ ...payload, start_date: '2026-08-20', end_date: '2026-08-20', followup_end: '' })
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    expect(document.querySelectorAll('.recharts-reference-line').length).toBeGreaterThan(0)
  })

  it('formats the tooltip timestamp as a local calendar date', () => {
    const timestamp = new Date('2026-08-20T00:00:00').getTime()
    expect(formatChartDateLabel(timestamp)).toMatch(/Aug 20, 2026/)
    expect(formatChartDateLabel(timestamp)).not.toMatch(/^\d{13}$/)
  })

  it('uses the exported chart tick and tooltip formatter functions', () => {
    setup()
    expect(chartAxisProps.tickFormatter).toBe(localTickDate)
    expect(chartTooltipProps.labelFormatter).toBe(formatChartDateLabel)
  })

  it('uses the component axis formatter identity', () => {
    expect(componentChartAxisProps).toBe(chartAxisProps)
    expect(componentChartAxisProps.tickFormatter).toBe(localTickDate)
    expect(chartAxisProps.tickFormatter).toBe(localTickDate)
  })
})

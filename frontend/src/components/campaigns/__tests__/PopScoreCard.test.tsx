import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cloneElement } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { PopScoreCard } from '@/components/campaigns/PopScoreCard'
import { chartAxisProps as componentChartAxisProps, formatTrendTooltip } from '@/components/campaigns/PopScoreCard'
import { chartAxisProps, chartTooltipProps, formatChartDateLabel, localTickDate } from '@/components/campaigns/chartDate'
import { useEditCampaign, useOverridePopScore, usePopScore, useSetPopScoreTrack } from '@/lib/queries'
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

describe('<PopScoreCard /> attribution', () => {
  beforeEach(() => vi.clearAllMocks())

  it('prefills an outage link, disables empty Save, and confirms unlink separately', () => {
    vi.mocked(usePopScore).mockReturnValue({ data: undefined, isLoading: false, isError: true, error: Object.assign(new Error('Chartmetric down'), { body: { linked: true, link: 'https://open.spotify.com/track/2qSkIjg1o9h3YT9RAgYN75' } }) } as unknown as ReturnType<typeof usePopScore>)
    vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate, isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
    vi.mocked(useOverridePopScore).mockReturnValue({ mutate: overrideMutate, isPending: false, isError: false } as unknown as ReturnType<typeof useOverridePopScore>)
    vi.mocked(useEditCampaign).mockReturnValue({ mutate, reset: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
    const { rerender } = render(<PopScoreCard slug="example" />)
    const input = screen.getByRole('textbox', { name: 'Song link for pop score' }) as HTMLInputElement
    expect(input.value).toBe('https://open.spotify.com/track/2qSkIjg1o9h3YT9RAgYN75')
    expect(screen.getByText('Chartmetric down')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Unlink song' }))
    expect(screen.getByText(/Unlink — this also clears saved choices\?/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep song' }))
    expect(mutate).not.toHaveBeenCalledWith('')
    fireEvent.change(input, { target: { value: '' } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'https://open.spotify.com/track/2qSkIjg1o9h3YT9RAgYN75' } })
    vi.mocked(usePopScore).mockReturnValue({ data: { ...payload, link: input.value }, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    rerender(<PopScoreCard slug="example" />)
    fireEvent.click(screen.getByRole('button', { name: 'Change song' }))
    fireEvent.click(screen.getByRole('button', { name: 'Unlink song' }))
    expect(screen.getByText(/Unlink — this also clears saved choices\?/)).toBeInTheDocument()
    expect(mutate).not.toHaveBeenCalledWith('')
    fireEvent.click(screen.getByRole('button', { name: 'Yes, unlink' }))
    expect(mutate).toHaveBeenCalledWith('', expect.any(Object))
  })

  it('uses explicit unlink labels, 24px actions, spacing, and focuses Keep song', () => {
    setup()
    fireEvent.click(screen.getByRole('button', { name: 'Change song' }))
    fireEvent.click(screen.getByRole('button', { name: 'Unlink song' }))
    const yes = screen.getByRole('button', { name: 'Yes, unlink' })
    const keep = screen.getByRole('button', { name: 'Keep song' })
    expect(yes).toHaveClass('min-h-6')
    expect(keep).toHaveClass('min-h-6')
    expect(yes.parentElement).toHaveClass('gap-2')
    expect(keep).toHaveFocus()
  })

  it('clears the song input when the linked track is unlinked', () => {
    const { rerender } = setup({ ...payload, link: 'https://open.spotify.com/track/original' })
    fireEvent.click(screen.getByRole('button', { name: 'Change song' }))
    const input = screen.getByRole('textbox', { name: 'Song link for pop score' }) as HTMLInputElement
    expect(input.value).toBe('https://open.spotify.com/track/original')
    vi.mocked(usePopScore).mockReturnValue({ data: { ...payload, linked: false, link: '' }, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    rerender(<PopScoreCard slug="example" tracker_url="https://tracker.example" />)
    expect((screen.getByRole('textbox', { name: 'Song link for pop score' }) as HTMLInputElement).value).toBe('')
  })

  it('shows campaign growth in the headline, starred only when recounts were left out', () => {
    setup({ ...payload,
      streams: { ...payload.streams!, baseline_daily: 1_600_000, campaign_daily: 1_400_000, lift_pct_campaign: -10.1, growth_pct_campaign: 1.4, adjusted: false },
      ugc: { ...payload.ugc!, baseline_daily: 871, campaign_daily: 1100, growth_pct_campaign: 2.6, gained_campaign: 35_300, adjusted: true },
    })
    const headline = screen.getByText(/^Popularity .*·/).textContent ?? ''
    expect(headline).toMatch(/streams 1\.6M → 1\.4M\/day \(−10\.1%\), \+1\.4% growth(?!\*)/)
    expect(headline).toMatch(/TikTok videos 871 → 1\.1K\/day, \+2\.6% growth\*, 35\.3K new during the campaign/)
    expect(headline).not.toMatch(/total/)
  })

  it('omits null campaign total growth percentages from the headline', () => {
    setup({ ...payload,
      streams: { ...payload.streams!, growth_pct_campaign: null },
      ugc: { ...payload.ugc!, growth_pct_campaign: null },
    })
    const headline = screen.getByText(/^Popularity .*·/).textContent ?? ''
    expect(headline).toMatch(/streams 5K → 14\.3K\/day \(\+185\.7%\)(?! ?,)/)
    expect(headline).toMatch(/TikTok videos 120 → 480\/day, 3\.6K new during the campaign/)
    expect(headline).not.toMatch(/growth|N\/A/)
  })

  it('resets either displayed leg of a counted pair through the choice date', () => {
    setup({ ...payload, phase: 'complete', ugc: { ...payload.ugc!, unusual: [
      { date: '2026-01-16', change: 20_000, source: 'manual', with: '2026-01-17', choice_date: '2026-01-17' },
      { date: '2026-01-17', change: -20_000, source: 'manual', with: '2026-01-16', choice_date: '2026-01-17' },
    ] } })
    fireEvent.click(screen.getByRole('button', { name: /TikTok videos: 2 unusual jumps/ }))
    expect(screen.getByText(/Jan 16, 2026.*counted with Jan 17, 2026 · set by you/)).toBeInTheDocument()
    expect(screen.getByText(/Jan 17, 2026.*counted with Jan 16, 2026 · set by you/)).toBeInTheDocument()
    const resets = screen.getAllByRole('button', { name: /^Reset — / })
    fireEvent.click(resets[0])
    fireEvent.click(resets[1])
    expect(overrideMutate.mock.calls.map(call => call[0])).toEqual([
      { metric: 'ugc', date: '2026-01-17', action: 'auto' },
      { metric: 'ugc', date: '2026-01-17', action: 'auto' },
    ])
  })

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
    setup({ ...payload, ugc: { ...payload.ugc!, recounts: [{ date: '2026-08-10', change: 543000, source: 'auto' }] } })
    fireEvent.click(screen.getByRole('button', { name: /TikTok videos: 1 Chartmetric recount/ }))
    expect(screen.getByText(/Aug 10, 2026 \(\+543K TikTok videos\) · not counted/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily new videos' }))
    expect(document.querySelector('circle[fill="none"][stroke="#909098"]')).toBeInTheDocument()
  })

  it('shows stream recounts with muted copy, a hollow mark, and recount tooltip wording', () => {
    setup({ ...payload, streams: { ...payload.streams!, recounts: [{ date: '2026-08-10', change: -543000, source: 'auto' }] } })
    fireEvent.click(screen.getByRole('button', { name: /Streams: 1 Chartmetric recount/ }))
    expect(screen.getByText(/Aug 10, 2026 \(−543K streams\) · not counted/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily streams' }))
    expect(document.querySelectorAll('circle[fill="none"][stroke="#909098"]')).toHaveLength(1)
    expect(formatTrendTooltip({ date: '2026-08-10', recount: true }, 'streams').value).toBe('recount (not counted)')
  })

  it('collapses recounts and unusual jumps at two, reports largest absolute signed change and keeps hover details', () => {
    setup({ ...payload,
      streams: { ...payload.streams!, adjusted: true, recounts: [{ date: '2026-05-20', change: 1_200_000, source: 'auto' }, { date: '2026-05-23', change: -2_800_000, source: 'auto' }], unusual: [{ date: '2026-05-24', change: -4_000, source: 'auto' }, { date: '2026-05-25', change: 3_000, source: 'auto' }] },
      ugc: { ...payload.ugc!, adjusted: false, recounts: [], unusual: [{ date: '2026-05-21', change: 20_000, source: 'auto' }, { date: '2026-05-22', change: -30_000, source: 'auto' }] },
    })
    expect(screen.getByRole('button', { name: /Streams: 2 Chartmetric recounts not counted · largest −2.8M on May 23, 2026/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Streams: 2 unusual jumps counted · largest −4K on May 24, 2026/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /TikTok videos: 2 unusual jumps counted · largest −30K on May 22, 2026/ })).toBeInTheDocument()
  })

  it('uses 24px padded action targets and accessible action names for recount, unusual, and reset actions', () => {
    setup({ ...payload, streams: { ...payload.streams!, recounts: [{ date: '2026-08-12', change: -2000, source: 'auto' }, { date: '2026-08-13', change: 1000, source: 'manual' }], unusual: [{ date: '2026-08-14', change: 3000, source: 'auto' }] } })
    const list = screen.getByRole('button', { name: /Streams: 2 Chartmetric recounts/ })
    fireEvent.click(list)
    expect(list).toHaveAttribute('aria-expanded', 'true')
    const countButton = screen.getByRole('button', { name: 'Count it — Aug 12, 2026, Streams' })
    expect(countButton.className).toMatch(/min-h-6/)
    expect(countButton.className).toMatch(/px-1/)
    fireEvent.click(countButton)
    expect(overrideMutate).toHaveBeenCalledWith({ metric: 'streams', date: '2026-08-12', action: 'include' })
    expect(screen.getByText(/set by you/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reset — Aug 13, 2026, Streams' }))
    expect(overrideMutate).toHaveBeenCalledWith({ metric: 'streams', date: '2026-08-13', action: 'auto' })
    fireEvent.click(screen.getByRole('button', { name: /Streams: 1 unusual jump/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Leave it out — Aug 14, 2026, Streams' }))
    expect(overrideMutate).toHaveBeenCalledWith({ metric: 'streams', date: '2026-08-14', action: 'exclude' })
    fireEvent.click(list)
    expect(list).toHaveAttribute('aria-expanded', 'false')
  })

  it('renders mutation errors and disables override controls while pending', () => {
    const view = setup({ ...espressoWalk, streams: { ...espressoWalk.streams, recounts: [{ date: '2026-08-02', change: 1000, source: 'auto' }] }, ugc: { ...espressoWalk.ugc, recounts: [{ date: '2026-08-02', change: 1000, source: 'auto' }] } } as unknown as PopScore)
    vi.mocked(useOverridePopScore).mockReturnValue({ mutate: overrideMutate, variables: { metric: 'ugc', date: '2026-08-02', action: 'exclude' }, isPending: true, isError: true, error: new Error('Override failed') } as unknown as ReturnType<typeof useOverridePopScore>)
    view.rerender(<PopScoreCard slug="example" />)
    fireEvent.click(screen.getByRole('button', { name: /Streams: 1 Chartmetric recount/ }))
    expect(screen.getByRole('button', { name: 'Count it — Aug 2, 2026, Streams' })).toBeEnabled()
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByRole('alert').parentElement).toHaveAttribute('data-metric', 'ugc')
    fireEvent.click(screen.getByRole('button', { name: /TikTok videos: 1 Chartmetric recount/ }))
    expect(screen.getByRole('button', { name: 'Count it — Aug 2, 2026, TikTok videos' })).toBeDisabled()
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getAllByRole('alert')[0].parentElement).toHaveTextContent('TikTok videos: 1 Chartmetric recount')
    expect(screen.getAllByRole('alert')[0]).toHaveTextContent('Override failed')
  })

  it('renders stale choices with reset mapped to auto and TikTok overrides use ugc', () => {
    setup({ ...payload, stale_overrides: [{ metric: 'ugc', date: '2026-08-13', action: 'exclude' }], ugc: { ...payload.ugc!, unusual: [{ date: '2026-08-14', change: 3000, source: 'auto' }] } })
    expect(screen.getByText((_, element) => element?.textContent === "1 saved choice no longer matches Chartmetric's data")).toBeInTheDocument()
    expect(screen.getByText('Aug 13, 2026 · TikTok videos · not counted')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reset stale ugc choice for Aug 13, 2026' }))
    expect(overrideMutate).toHaveBeenCalledWith({ metric: 'ugc', date: '2026-08-13', action: 'auto' })
    fireEvent.click(screen.getByRole('button', { name: /TikTok videos: 1 unusual jump/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Leave it out — Aug 14, 2026, TikTok videos' }))
    expect(overrideMutate).toHaveBeenCalledWith({ metric: 'ugc', date: '2026-08-14', action: 'exclude' })
  })

  it('shows the partner date for a manually included rollback leg', () => {
    setup({ ...payload, ugc: { ...payload.ugc!, unusual: [
      { date: '2026-08-16', change: 20000, source: 'manual', with: '2026-08-17' },
      { date: '2026-08-17', change: -20000, source: 'manual', with: '2026-08-16' },
    ] } })
    fireEvent.click(screen.getByRole('button', { name: /TikTok videos: 2 unusual jumps counted/ }))
    expect(screen.getByText(/Aug 16, 2026.*with Aug 17, 2026/)).toBeInTheDocument()
    expect(screen.getByText(/Aug 17, 2026.*with Aug 16, 2026/)).toBeInTheDocument()
  })

  it('shows both now changes since start and since end', () => {
    setup({ ...payload, streams: { ...payload.streams!, now: 2_000_000, now_date: '2026-09-18', change_since_start: 1_000_000, change_since_end: 600_000 } })
    expect(screen.getByText('+1M since start · +600K since end')).toBeInTheDocument()
    expect(screen.queryByText('+600K since end', { exact: true })).not.toBeInTheDocument()
  })

  it('shows the available since-start value when since-end is missing', () => {
    setup({ ...payload, phase: 'live', end_date: '', streams: { ...payload.streams!, change_since_start: 1234, change_since_end: null } })
    expect(screen.getByText('+1.2K since start')).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Streams/ }).querySelectorAll('td')[3]).toHaveTextContent('+1.2K since start')
    expect(screen.getByRole('row', { name: /Streams/ }).querySelectorAll('td')[3]).not.toHaveTextContent('since end')
  })

  it('shows only the available since-end value on a finished campaign', () => {
    setup({ ...payload, phase: 'complete', streams: { ...payload.streams!, change_since_start: null, change_since_end: -1234 } })
    expect(screen.getByText('−1.2K since end')).toBeInTheDocument()
    expect(screen.getByRole('row', { name: /Streams/ }).querySelectorAll('td')[3]).toHaveTextContent('−1.2K since end')
    expect(screen.getByRole('row', { name: /Streams/ }).querySelectorAll('td')[3]).not.toHaveTextContent('since start')
  })

  it('breaks equal largest-change ties in favor of the later date', () => {
    setup({ ...payload, streams: { ...payload.streams!, unusual: [{ date: '2026-08-12', change: -5000, source: 'auto' }, { date: '2026-08-20', change: 5000, source: 'auto' }] } })
    expect(screen.getByRole('button', { name: /largest \+5K on Aug 20, 2026/ })).toBeInTheDocument()
  })

  it.each(['no_start', 'not_started'] as const)('hides stars, footnotes, and recount notes in %s phase', phase => {
    const { container } = setup({ ...payload, phase, streams: { ...payload.streams!, adjusted: true, recounts: [{ date: '2026-08-12', change: -1000, source: 'auto' }] } })
    expect(container.querySelector('tbody tr:nth-child(2) sup')).toBeNull()
    expect(screen.queryByText(/Totals are as reported/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Chartmetric recount/ })).not.toBeInTheDocument()
  })

  it('shows recount footnote only with adjusted metrics, marks only those rows, and omits footnote before start', () => {
    const { container, rerender } = setup({ ...payload, streams: { ...payload.streams!, adjusted: true }, ugc: { ...payload.ugc!, adjusted: false } })
    const rows = [...container.querySelectorAll('tbody tr')]
    expect(rows[0].querySelector('sup')).toBeNull()
    expect(rows[1].querySelector('sup')).toHaveTextContent('*')
    expect(rows[2].querySelector('sup')).toBeNull()
    expect(screen.getByText('* Totals are as reported; changes leave out Chartmetric recounts.')).toBeInTheDocument()
    vi.mocked(usePopScore).mockReturnValue({ data: { ...payload, phase: 'not_started', streams: { ...payload.streams!, adjusted: true }, ugc: { ...payload.ugc!, adjusted: false } }, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    rerender(<PopScoreCard slug="example" />)
    expect(screen.queryByText('* Totals are as reported; changes leave out Chartmetric recounts.')).not.toBeInTheDocument()
    expect(screen.getAllByText('Not started')).toHaveLength(1)
  })

  it('omits the recount footnote when neither metric row is adjusted', () => {
    setup({ ...payload, streams: { ...payload.streams!, adjusted: false }, ugc: { ...payload.ugc!, adjusted: false } })
    expect(screen.queryByText('* Totals are as reported; changes leave out Chartmetric recounts.')).not.toBeInTheDocument()
  })

  it('shows the footnote for an adjusted UGC row even when streams are not adjusted', () => {
    const { container } = setup({ ...payload, streams: { ...payload.streams!, adjusted: false }, ugc: { ...payload.ugc!, adjusted: true } })
    const rows = [...container.querySelectorAll('tbody tr')]
    expect(rows[0].querySelector('sup')).toBeNull()
    expect(rows[1].querySelector('sup')).toBeNull()
    expect(rows[2].querySelector('sup')).toHaveTextContent('*')
    expect(screen.getByText('* Totals are as reported; changes leave out Chartmetric recounts.')).toBeInTheDocument()
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

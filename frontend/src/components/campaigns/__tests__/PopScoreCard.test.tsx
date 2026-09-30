import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { PopScoreCard } from '@/components/campaigns/PopScoreCard'
import { useEditCampaign, usePopScore, useSetPopScoreTrack } from '@/lib/queries'
import type { PopScore } from '@/lib/types'

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
  history: [{ date: '2026-08-01', value: 61 }, { date: '2026-08-20', value: 68 }],
  streams_history: [{ date: '2026-08-01', total: 1_000_000, daily: null }, { date: '2026-08-10', total: 1_200_000, daily: 20000 }, { date: '2026-08-20', total: 1_400_000, daily: 20000 }],
}
const mutate = vi.fn()
function setup(data: PopScore = payload) {
  vi.mocked(usePopScore).mockReturnValue({ data, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
  vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate, isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
  vi.mocked(useEditCampaign).mockReturnValue({ mutate, isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
  return render(<PopScoreCard slug="example" tracker_url="https://tracker.example" />)
}

describe('<PopScoreCard /> attribution', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders values from the full attribution payload', () => {
    setup()
    expect(screen.getByText('Song attribution')).toBeInTheDocument()
    expect(screen.getByText('Example Song')).toBeInTheDocument()
    expect(screen.getByText('Follow-up (day 6 of 28)')).toBeInTheDocument()
    expect(screen.getByText('61')).toBeInTheDocument()
    expect(screen.getByText('68')).toBeInTheDocument()
    expect(screen.getByText('1.4M')).toBeInTheDocument()
    expect(screen.getByText(/Growth during campaign: \+40.0%/)).toBeInTheDocument()
    expect(screen.getByText(/\+400K during · \+250K after/)).toBeInTheDocument()
    expect(screen.getByText('Open Tides Tracker ↗')).toBeInTheDocument()
  })

  it('renders null metrics as dashes and null percentages as N/A, never zero', () => {
    setup({ ...payload, popularity: { ...payload.popularity!, start: null, end: null, change_campaign: null }, streams: { ...payload.streams!, start_total: null, growth_pct_campaign: null, baseline_daily: null } })
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getByText(/Growth during campaign: N\/A/)).toBeInTheDocument()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })

  it('offers an end date and to-date labels when no end date is set', () => {
    setup({ ...payload, end_date: '', followup_end: '', phase: 'live', popularity: { ...payload.popularity!, end_is_to_date: true, followup: null }, streams: { ...payload.streams!, end_is_to_date: true, followup_total: null } })
    expect(screen.getByText('End not set')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Set an end date' })).toBeInTheDocument()
    expect(screen.getAllByText('to date')).toHaveLength(2)
    expect(screen.getAllByText('Set an end date').length).toBeGreaterThan(0)
  })

  it('shows phase badge text', () => {
    setup({ ...payload, phase: 'complete' })
    expect(screen.getByText('Complete')).toBeInTheDocument()
  })

  it('switches the selected chart series with the toggle', () => {
    setup()
    const popularity = screen.getByRole('button', { name: 'Popularity' })
    const streams = screen.getByRole('button', { name: 'Daily streams' })
    expect(popularity).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(streams)
    expect(screen.getByTestId('attribution-chart')).toHaveAttribute('aria-label', 'Daily streams chart')
    expect(streams).toHaveAttribute('aria-pressed', 'true')
    expect(popularity).toHaveAttribute('aria-pressed', 'false')
  })

  it('saves, changes, clears an end date and shows edit errors', () => {
    const { rerender } = setup()
    fireEvent.click(screen.getByRole('button', { name: 'Change' }))
    fireEvent.change(screen.getByLabelText('End date'), { target: { value: '2026-08-22' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(mutate).toHaveBeenCalledWith({ end_date: '2026-08-22' }, expect.any(Object))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(mutate).toHaveBeenCalledWith({ end_date: '' })
    vi.mocked(useEditCampaign).mockReturnValue({ mutate, isPending: false, isError: true, error: new Error('bad date') } as unknown as ReturnType<typeof useEditCampaign>)
    rerender(<PopScoreCard slug="example" />)
    expect(screen.getByRole('alert')).toHaveTextContent('bad date')
  })

  it('shows popularity when streams fail', () => {
    setup({ ...payload, streams_error: 'Streams history is temporarily unavailable.' })
    expect(screen.getAllByText('Popularity').length).toBeGreaterThan(0)
    expect(screen.getByRole('status')).toHaveTextContent('Streams history is temporarily unavailable.')
    expect(screen.queryByText('Growth during campaign: +40.0%')).not.toBeInTheDocument()
  })
})

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { cloneElement } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { PopScoreCard } from '@/components/campaigns/PopScoreCard'
import { useEditCampaign, usePopScore, useSetPopScoreTrack } from '@/lib/queries'
import type { PopScore } from '@/lib/types'
import blinding from './fixtures/popscore_blinding_lights_walk.json'

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  return { ...actual, ResponsiveContainer: ({ children }: { children: React.ReactElement }) => <div style={{ width: 600, height: 240 }}>{cloneElement(children as React.ReactElement<{ width?: number; height?: number }>, { width: 600, height: 240 })}</div> }
})
vi.mock('@/lib/queries', () => ({ usePopScore: vi.fn(), useSetPopScoreTrack: vi.fn(), useOverridePopScore: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })), useEditCampaign: vi.fn() }))

function setup(data: PopScore) {
  vi.mocked(usePopScore).mockReturnValue({ data, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
  vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
  vi.mocked(useEditCampaign).mockReturnValue({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
  return render(<PopScoreCard slug="blinding" />)
}

describe('pass 9 attribution notes and chart boundary', () => {
  beforeEach(() => vi.useRealTimers())

  it('collapses seven Blinding Lights unusual jumps into an expandable list', () => {
    const unusual = [
      { date: '2026-06-14', change: 10700 }, { date: '2026-06-16', change: 51100 },
      { date: '2026-06-20', change: 12000 }, { date: '2026-07-02', change: 14000 },
      { date: '2026-07-15', change: 17000 }, { date: '2026-08-01', change: 19000 },
      { date: '2026-09-23', change: 22000 },
    ]
    const data = { ...blinding, ugc: { ...blinding.ugc, unusual } } as unknown as PopScore
    setup(data)
    const note = screen.getByRole('button', { name: 'TikTok videos: 7 unusual jumps counted · largest +51.1K on Jun 16, 2026' })
    expect(note).toBeTruthy()
    fireEvent.click(note)
    expect(screen.getAllByText(/2026|Jun|Jul|Sep/).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: /^Leave it out — .*?, TikTok videos$/ })).toHaveLength(7)
  })

  it('collapses long recount lists and marks adjusted metric rows with the explanatory footnote', () => {
    const data = { ...blinding,
      streams: { ...blinding.streams, adjusted: true },
      ugc: { ...blinding.ugc, adjusted: true, recounts: [
        { date: '2026-05-23', change: -2820230 }, { date: '2026-06-16', change: 51143 }, { date: '2026-09-23', change: 543100 },
      ] },
    } as unknown as PopScore
    const { container } = setup(data)
    expect([...container.querySelectorAll('th')].map(node => node.textContent)).toContain('Streams*')
    expect([...container.querySelectorAll('th')].map(node => node.textContent)).toContain('TikTok videos*')
    expect(screen.getByText('* Totals are as reported; changes leave out Chartmetric recounts.')).toBeInTheDocument()
    expect(screen.getByText('TikTok videos: 3 Chartmetric recounts not counted · largest −2.8M on May 23, 2026')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'TikTok videos: 3 Chartmetric recounts not counted · largest −2.8M on May 23, 2026' })).toBeInTheDocument()
  })

  it('draws post events through frozen today and excludes tomorrow', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-23T12:00:00'))
    const data = { ...blinding, post_events: [
      { date: '2026-09-23', count: 2 }, { date: '2026-09-24', count: 3 },
    ] } as unknown as PopScore
    setup(data)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    expect(document.querySelectorAll('.creator-post-tick')).toHaveLength(1)
  })
})

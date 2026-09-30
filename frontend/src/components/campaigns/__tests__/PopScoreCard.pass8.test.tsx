import { describe, expect, it, vi } from 'vitest'
import { cloneElement } from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { PopScoreCard } from '@/components/campaigns/PopScoreCard'
import { useEditCampaign, usePopScore, useSetPopScoreTrack } from '@/lib/queries'
import type { PopScore } from '@/lib/types'
import espressoWalk from './fixtures/popscore_espresso_walk.json'

const tooltipRow = vi.hoisted(() => ({ recountY: 0 as number | null }))
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>()
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactElement }) => <div style={{ width: 600, height: 240 }}>{cloneElement(children as React.ReactElement<{ width?: number; height?: number }>, { width: 600, height: 240 })}</div>,
    Tooltip: ({ content }: { content: (props: unknown) => React.ReactNode }) => <>{content({ active: true, payload: [{ payload: { date: '2026-09-23', value: null, recountY: tooltipRow.recountY } }] })}</>,
  }
})
vi.mock('@/lib/queries', () => ({ usePopScore: vi.fn(), useSetPopScoreTrack: vi.fn(), useOverridePopScore: vi.fn(() => ({ mutate: vi.fn(), isPending: false, isError: false })), useEditCampaign: vi.fn() }))

describe('pass 8 chart regressions', () => {
  it('wires recount plus post rows through the rendered chart tooltip', () => {
    tooltipRow.recountY = 0
    const data = {
      ...espressoWalk,
      post_events: [{ date: '2026-09-23', count: 5 }],
      ugc_history: [
        { date: '2026-09-20', total: 10, daily: 1 },
        { date: '2026-09-21', total: 11, daily: 1 },
        { date: '2026-09-23', total: 11, daily: null },
      ],
      ugc: { ...espressoWalk.ugc, recounts: [{ date: '2026-09-23', change: 0 }] },
    } as unknown as PopScore
    vi.mocked(usePopScore).mockReturnValue({ data, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
    vi.mocked(useEditCampaign).mockReturnValue({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
    render(<PopScoreCard slug="example" />)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    fireEvent.click(screen.getByRole('button', { name: 'Daily new videos' }))
    expect(document.body.textContent).toContain('Sep 23, 2026')
    expect(document.body.textContent).toContain('recount (not counted)')
    expect(document.body.textContent).toContain('5 creator posts')
  })
  it('shows only date and post count for an inserted popularity post day', () => {
    tooltipRow.recountY = null
    const data = { ...espressoWalk, post_events: [{ date: '2026-09-23', count: 3 }] } as unknown as PopScore
    vi.mocked(usePopScore).mockReturnValue({ data, isLoading: false, isError: false } as ReturnType<typeof usePopScore>)
    vi.mocked(useSetPopScoreTrack).mockReturnValue({ mutate: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useSetPopScoreTrack>)
    vi.mocked(useEditCampaign).mockReturnValue({ mutate: vi.fn(), reset: vi.fn(), isPending: false, isError: false } as unknown as ReturnType<typeof useEditCampaign>)
    render(<PopScoreCard slug="example" />)
    fireEvent.click(screen.getByRole('button', { name: 'Show trend' }))
    expect(document.body.textContent).toContain('Sep 23, 2026')
    expect(document.body.textContent).toContain('3 creator posts')
    expect(document.body.textContent).not.toContain('— Popularity')
  })
})

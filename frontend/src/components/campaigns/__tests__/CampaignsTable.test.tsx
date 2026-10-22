import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CampaignsTable } from '@/components/campaigns/CampaignsTable'
import { api } from '@/lib/api'
import type { CampaignSummary } from '@/lib/types'

vi.mock('@/lib/api', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/lib/api')>()), api: { editCampaign: vi.fn().mockResolvedValue({}) } }))

const row: CampaignSummary = {
  slug: 'song', title: 'Campaign', artist: 'Artist', song: 'Song', start_date: '2026-09-01', end_date: '', completion_status: 'booked',
  budget: { total: 0, booked: 0, paid: 0, left: 0, pct: 0 }, stats: { total_views: 0, cpm: null, live_posts: 0, posts_expected: 0 }, creator_count: 0,
}

describe('<CampaignsTable /> completion cache refresh', () => {
  beforeEach(() => vi.clearAllMocks())
  it('invalidates the campaign and pop-score detail when completion changes', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const invalidate = vi.spyOn(client, 'invalidateQueries')
    render(<QueryClientProvider client={client}><MemoryRouter><CampaignsTable data={[row]} /></MemoryRouter></QueryClientProvider>)
    fireEvent.click(screen.getByTitle('Booking complete — click to mark campaign wrapped'))
    await waitFor(() => expect(api.editCampaign).toHaveBeenCalledWith('song', { completion_status: 'completed' }))
    expect(screen.getByText('Campaign')).toHaveClass('truncate')
    expect(document.querySelector('tbody tr td')!).toHaveClass('sticky')
    await waitFor(() => {
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['campaign', 'song'] })
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ['popScore', 'song'] })
    })
  })
})

describe('<CampaignsTable /> dashboard sent checkbox', () => {
  const renderTable = (data: CampaignSummary[]) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={client}><MemoryRouter><CampaignsTable data={data} /></MemoryRouter></QueryClientProvider>)
  }
  beforeEach(() => vi.clearAllMocks())

  it('marks an unsent campaign as sent', async () => {
    const setDashboardSent = vi.fn().mockResolvedValue({ ok: true, dashboard_sent_at: '2026-10-22T10:00:00' })
    ;(api as unknown as Record<string, unknown>).setDashboardSent = setDashboardSent
    renderTable([{ ...row, dashboard_sent_at: '' }])
    const box = screen.getByRole('checkbox', { name: 'Mark dashboard sent to point of contact' })
    expect(box).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(box)
    await waitFor(() => expect(setDashboardSent).toHaveBeenCalledWith('song', true))
    expect(api.editCampaign).not.toHaveBeenCalled()
  })

  it('shows the sent date and unchecks', async () => {
    const setDashboardSent = vi.fn().mockResolvedValue({ ok: true, dashboard_sent_at: '' })
    ;(api as unknown as Record<string, unknown>).setDashboardSent = setDashboardSent
    renderTable([{ ...row, dashboard_sent_at: '2026-10-20T15:00:00' }])
    const box = screen.getByRole('checkbox', { name: /Dashboard sent to point of contact on Oct 20, 2026/ })
    expect(box).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(box)
    await waitFor(() => expect(setDashboardSent).toHaveBeenCalledWith('song', false))
  })
})

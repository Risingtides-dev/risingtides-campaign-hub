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

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CampaignHeader } from '@/components/campaigns/CampaignHeader'
import { MemoryRouter } from 'react-router-dom'
import type { CampaignDetail } from '@/lib/types'

describe('<CampaignHeader />', () => {
  it('includes end_date with start_date in the edit submission', () => {
    const onEdit = vi.fn()
    const campaign = {
      slug: 'song', title: 'Artist - Song', artist: 'Artist', song: 'Song', sound_id: '', official_sound: '',
      tt_artist_label: '', tt_track_name: '', additional_sounds: [], cobrand_link: '', cobrand_share_url: '',
      cobrand_upload_url: '', start_date: '2026-08-01', end_date: '2026-08-20', budget: { total: 0, booked: 0, paid: 0, left: 0 },
      stats: {}, creators: [], matched_videos: [], platform: '', status: '', source: '', label: '', round: '', campaign_stage: '',
      project_lead: [], client_email: '', platform_split: {}, content_types: [],
    } as unknown as CampaignDetail
    render(<MemoryRouter><CampaignHeader campaign={campaign} onEdit={onEdit} onRefresh={vi.fn()} isEditing={false} isRefreshing={false} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    fireEvent.change(screen.getAllByDisplayValue(/2026-/)[1], { target: { value: '2026-08-24' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ start_date: '2026-08-01', end_date: '2026-08-24' }))
  })
})

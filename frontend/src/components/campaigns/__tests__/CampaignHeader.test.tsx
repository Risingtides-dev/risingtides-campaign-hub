import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CampaignHeader } from '@/components/campaigns/CampaignHeader'
import { MemoryRouter } from 'react-router-dom'
import type { CampaignDetail } from '@/lib/types'

describe('<CampaignHeader />', () => {
  it('disables Cancel while a save is pending', () => {
    const campaign = { slug: 'song', title: 'Song', start_date: '2026-08-01', budget: { total: 0, booked: 0, paid: 0, left: 0 }, creators: [], matched_videos: [] } as unknown as CampaignDetail
    render(<MemoryRouter><CampaignHeader campaign={campaign} onEdit={vi.fn()} onRefresh={vi.fn()} isEditing isRefreshing={false} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })
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
    expect(onEdit).not.toHaveBeenCalled()
    fireEvent.change(screen.getAllByDisplayValue(/2026-/)[1], { target: { value: '2026-08-24' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onEdit).toHaveBeenCalledWith(expect.objectContaining({ start_date: '2026-08-01', end_date: '2026-08-24' }))
  })

  it('seeds the current end date on open and omits unchanged end_date', () => {
    const onEdit = vi.fn()
    const campaign = { slug: 'song', title: 'Artist - Song', artist: 'Artist', song: 'Song', sound_id: '', official_sound: '', tt_artist_label: '', tt_track_name: '', additional_sounds: [], cobrand_link: '', start_date: '2026-08-01', end_date: '', budget: { total: 0, booked: 0, paid: 0, left: 0 }, stats: {}, creators: [], matched_videos: [], platform: '', status: '', source: '', label: '', round: '', campaign_stage: '', project_lead: [], client_email: '', platform_split: {}, content_types: [] } as unknown as CampaignDetail
    const { rerender } = render(<MemoryRouter><CampaignHeader campaign={campaign} onEdit={onEdit} onRefresh={vi.fn()} isEditing={false} isRefreshing={false} /></MemoryRouter>)
    const updated = { ...campaign, end_date: '2026-08-20' }
    rerender(<MemoryRouter><CampaignHeader campaign={updated} onEdit={onEdit} onRefresh={vi.fn()} isEditing={false} isRefreshing={false} /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    expect(screen.getAllByDisplayValue('2026-08-20')[0]).toHaveValue('2026-08-20')
    fireEvent.change(document.querySelector('input[type=number]')!, { target: { value: '20' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(onEdit).toHaveBeenCalledWith(expect.not.objectContaining({ end_date: expect.anything() }))
  })

  it('keeps the form open and announces a rejected save', async () => {
    const onEdit = vi.fn().mockRejectedValue(new Error('save failed'))
    const campaign = { slug: 'song', title: 'Artist - Song', artist: 'Artist', song: 'Song', sound_id: '', official_sound: '', start_date: '2026-08-01', end_date: '', budget: { total: 0, booked: 0, paid: 0, left: 0 }, stats: {}, creators: [], matched_videos: [] } as unknown as CampaignDetail
    render(<MemoryRouter><CampaignHeader campaign={campaign} onEdit={onEdit} onRefresh={vi.fn()} isEditing={false} isRefreshing={false} editError="save failed" /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('save failed')
    expect(document.querySelector('input[type=number]')!).toBeInTheDocument()
  })

  it('resets the edit mutation when opening and cancelling the form', () => {
    const reset = vi.fn()
    const campaign = { slug: 'song', title: 'Artist - Song', start_date: '2026-08-01', end_date: '', budget: { total: 0, booked: 0, paid: 0, left: 0 }, creators: [], matched_videos: [] } as unknown as CampaignDetail
    render(<MemoryRouter><CampaignHeader campaign={campaign} onEdit={vi.fn()} onResetEdit={reset} onRefresh={vi.fn()} isEditing={false} isRefreshing={false} editError="stale" /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    expect(reset).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).toHaveTextContent('stale')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(reset).toHaveBeenCalledTimes(2)
  })
})

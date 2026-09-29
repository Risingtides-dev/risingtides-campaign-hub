import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { CampaignHeader } from '@/components/campaigns/CampaignHeader'
import type { CampaignDetail } from '@/lib/types'

const campaign = {
  slug: 'artist-song',
  title: 'Artist - Song',
  artist: 'Artist',
  song: 'Song',
  official_sound: 'https://old.example/sound',
  sound_id: '1234567890123456789',
  additional_sounds: [],
  start_date: '2026-01-01',
  budget: { total: 1000, booked: 0, paid: 0, left: 1000, pct: 0 },
  tt_artist_label: '',
  tt_track_name: '',
  cobrand_link: '',
  cobrand_share_url: '',
} as unknown as CampaignDetail

function renderHeader(onDropLink: (url: string, expected: string) => Promise<unknown>, pending = false) {
  return render(
    <MemoryRouter>
      <CampaignHeader
        campaign={campaign}
        onEdit={() => undefined}
        onRefresh={() => undefined}
        isEditing={false}
        isRefreshing={false}
        onDropLink={onDropLink}
        isDroppingLink={pending}
      />
    </MemoryRouter>,
  )
}

describe('<CampaignHeader /> link drop-in', () => {
  it('sends an explicit URL mutation with the displayed value as its CAS guard', async () => {
    const user = userEvent.setup()
    const save = vi.fn().mockResolvedValue({ ok: true })
    renderHeader(save)

    await user.type(screen.getByLabelText('Drop a campaign link'), 'https://example.com/new')
    await user.click(screen.getByRole('button', { name: 'Save link' }))

    expect(save).toHaveBeenCalledWith(
      'https://example.com/new',
      'https://old.example/sound',
    )
    expect(await screen.findByText('Link saved to this campaign.')).toBeInTheDocument()
    expect(screen.getByLabelText('Drop a campaign link')).toHaveValue('')
  })

  it('keeps a failed URL for retry and exposes the server conflict', async () => {
    const user = userEvent.setup()
    renderHeader(vi.fn().mockRejectedValue(new Error('That link already belongs to another campaign.')))

    const input = screen.getByLabelText('Drop a campaign link')
    await user.type(input, 'https://example.com/duplicate')
    await user.click(screen.getByRole('button', { name: 'Save link' }))

    expect(await screen.findByText('That link already belongs to another campaign.')).toBeInTheDocument()
    expect(input).toHaveValue('https://example.com/duplicate')
  })

  it('shows the pending state and blocks duplicate submits', () => {
    renderHeader(vi.fn(), true)
    const button = screen.getByRole('button', { name: 'Saving...' })
    expect(button).toBeDisabled()
  })
})

import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import CampaignDetail from './CampaignDetail'

const mocks = vi.hoisted(() => ({
  editMutation: { mutateAsync: vi.fn().mockResolvedValue(undefined), mutate: vi.fn(), isPending: false, isError: false, reset: vi.fn() },
  popProps: null as null | { slug: string; tracker_url?: string },
  headerProps: null as null | { onEdit: (data: Record<string, unknown>) => unknown },
}))
vi.mock('@/lib/queries', () => {
  const mutation = () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, isError: false, data: null, error: null })
  return {
    useCampaign: () => ({ data: { slug: 'song', title: 'Campaign', tracker_url: 'https://tracker.test', budget: {}, stats: {}, creators: [], matched_videos: [] }, isLoading: false, isError: false }),
    useCobrandStats: () => ({ data: null, isLoading: false, isError: false }),
    useEditCampaign: () => mocks.editMutation,
    useRefreshStats: mutation, useAddCreator: mutation, useEditCreator: mutation, useTogglePaid: mutation,
    useRemoveCreator: mutation, useCreateTracker: mutation, useSetCobrandLinks: mutation,
  }
})
vi.mock('@/components/campaigns/CampaignHeader', () => ({ CampaignHeader: (props: typeof mocks.headerProps) => { mocks.headerProps = props; return null } }))
vi.mock('@/components/campaigns/PopScoreCard', () => ({ PopScoreCard: (props: typeof mocks.popProps) => { mocks.popProps = props; return <div data-testid="song-attribution" /> } }))
vi.mock('@/components/campaigns/StatCards', () => ({ StatCards: () => null }))
vi.mock('@/components/campaigns/CobrandSection', () => ({ CobrandStatsCard: () => null, CobrandLinkInput: () => null, CobrandUploadSection: () => null }))
vi.mock('@/components/campaigns/ShareTokenSection', () => ({ ShareTokenSection: () => null }))
vi.mock('@/components/campaigns/AddCreatorForm', () => ({ AddCreatorForm: () => null }))
vi.mock('@/components/campaigns/CreatorsTable', () => ({ CreatorsTable: () => null }))

describe('<CampaignDetail /> attribution wiring', () => {
  it('renders the song card with campaign context and forwards edited end_date through the shared edit mutation', async () => {
    render(<MemoryRouter initialEntries={['/campaign/song']}><Routes><Route path="/campaign/:slug" element={<CampaignDetail />} /></Routes></MemoryRouter>)
    expect(screen.getByTestId('song-attribution')).toBeInTheDocument()
    expect(mocks.popProps).toEqual({ slug: 'song', tracker_url: 'https://tracker.test' })
    const editPayload = { end_date: '2026-09-30' }
    await mocks.headerProps?.onEdit(editPayload)
    expect(mocks.editMutation.mutateAsync).toHaveBeenCalledWith(editPayload)
  })
})

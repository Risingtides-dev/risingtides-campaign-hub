/**
 * Regressions for the three booking-form bugs described in issue #292:
 *   1. Server failure vs 404 — only 404 → trial, 5xx/transport → unavailable
 *   2. Stale-response guard — a slow response for handle A must not land
 *      after the user typed handle B
 *   3. Platform switch re-triggers lookups and passes platform to last-rate
 *   4. Manual edits to price/posts are never clobbered by a lookup
 */
import React from 'react'
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AddCreatorForm } from '@/components/campaigns/AddCreatorForm'
import { api, ApiError } from '@/lib/api'

// Silence console.error from expected thrown errors inside act()
beforeEach(() => vi.spyOn(console, 'error').mockImplementation(() => {}))

vi.mock('@/lib/api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/lib/api')>()
  return {
    ...mod,
    api: {
      getCreatorIntel: vi.fn(),
      getLastRate: vi.fn(),
      getPaypal: vi.fn().mockResolvedValue({ paypal: '' }),
    },
  }
})

// Radix Select calls scrollIntoView on mount which jsdom doesn't support.
// Swap it with a native <select> so we can test platform-switching behavior
// without touching the UI library's internals.
vi.mock('@/components/ui/select', () => ({
  Select: ({
    value,
    onValueChange,
    children,
  }: {
    value: string
    onValueChange: (v: string) => void
    children: React.ReactNode
  }) => (
    <select
      data-testid="platform-select"
      value={value}
      onChange={(e) => onValueChange(e.target.value)}
    >
      {children}
    </select>
  ),
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: React.ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))

vi.mock('@/components/CreatorAutocomplete', () => ({
  CreatorAutocomplete: ({
    value,
    onChange,
    onBlur,
    className,
  }: {
    value: string
    onChange: (v: string) => void
    onBlur: () => void
    className?: string
  }) => (
    <input
      data-testid="username-input"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      onBlur={onBlur}
      className={className}
    />
  ),
}))

const INTEL_TRIAL = new ApiError('not found', 404, { error: 'not found' })
const INTEL_SERVER_ERROR = new ApiError('server error', 500, { error: 'server error' })
const INTEL_NETWORK = new Error('Network request failed')

const INTEL_DATA = {
  posts: 20,
  avg_views: 5000,
  viral_rate: 0,
  score_balanced: 30,
}

function renderForm() {
  const onAdd = vi.fn()
  render(<AddCreatorForm onAdd={onAdd} isPending={false} />)
  return { onAdd }
}

function typeHandle(value: string) {
  const input = screen.getByTestId('username-input')
  fireEvent.change(input, { target: { value } })
  fireEvent.blur(input)
}

describe('AddCreatorForm — server failure vs 404', () => {
  it('shows trial verdict on 404', async () => {
    vi.mocked(api.getCreatorIntel).mockRejectedValue(INTEL_TRIAL)
    vi.mocked(api.getLastRate).mockResolvedValue({ last_rate: null })
    renderForm()
    typeHandle('newcreator')
    await waitFor(() =>
      expect(screen.getByText(/No tracked history/)).toBeInTheDocument()
    )
  })

  it('shows unavailable verdict on 500', async () => {
    vi.mocked(api.getCreatorIntel).mockRejectedValue(INTEL_SERVER_ERROR)
    vi.mocked(api.getLastRate).mockResolvedValue({ last_rate: null })
    renderForm()
    typeHandle('problemcreator')
    await waitFor(() =>
      expect(screen.getByText(/unavailable right now/)).toBeInTheDocument()
    )
  })

  it('shows unavailable verdict on transport error', async () => {
    vi.mocked(api.getCreatorIntel).mockRejectedValue(INTEL_NETWORK)
    vi.mocked(api.getLastRate).mockResolvedValue({ last_rate: null })
    renderForm()
    typeHandle('problemcreator')
    await waitFor(() =>
      expect(screen.getByText(/unavailable right now/)).toBeInTheDocument()
    )
  })

  it('does NOT block submission on unavailable (not cold)', async () => {
    vi.mocked(api.getCreatorIntel).mockRejectedValue(INTEL_SERVER_ERROR)
    vi.mocked(api.getLastRate).mockResolvedValue({ last_rate: null })
    const { onAdd } = renderForm()
    typeHandle('problemcreator')
    await waitFor(() =>
      expect(screen.getByText(/unavailable right now/)).toBeInTheDocument()
    )
    const btn = screen.getByRole('button', { name: /Add/ })
    expect(btn).not.toBeDisabled()
  })
})

describe('AddCreatorForm — stale-response guard', () => {
  it('discards a slow intel response for a previous handle', async () => {
    let resolveFirst!: (v: unknown) => void
    const slowIntel = new Promise((res) => { resolveFirst = res })

    vi.mocked(api.getCreatorIntel)
      .mockReturnValueOnce(slowIntel as ReturnType<typeof api.getCreatorIntel>)
      .mockRejectedValue(INTEL_TRIAL)
    vi.mocked(api.getLastRate).mockResolvedValue({ last_rate: null })

    renderForm()

    // Type first handle — slow in-flight request
    typeHandle('slowhandle')

    // Type second handle before the first resolves
    typeHandle('newhandle')
    await waitFor(() =>
      expect(screen.getByText(/No tracked history/)).toBeInTheDocument()
    )

    // Now resolve the first request with cold intel
    await act(async () => {
      resolveFirst(INTEL_DATA)
      await Promise.resolve()
    })

    // The cold verdict from the first handle must NOT overwrite the trial verdict
    expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
    expect(screen.getByText(/No tracked history/)).toBeInTheDocument()
  })
})

describe('AddCreatorForm — platform switch', () => {
  it('re-triggers last-rate lookup with new platform on switch', async () => {
    vi.mocked(api.getCreatorIntel).mockRejectedValue(INTEL_TRIAL)
    vi.mocked(api.getLastRate).mockResolvedValue({ last_rate: null })

    renderForm()
    typeHandle('dualplatform')
    await waitFor(() => expect(vi.mocked(api.getLastRate)).toHaveBeenCalled())

    const firstCallPlatform = (vi.mocked(api.getLastRate).mock.calls[0] ?? [])[1]
    expect(firstCallPlatform).toBe('tiktok')

    // Switch to Instagram via the mocked native <select>
    const platformSelect = screen.getByTestId('platform-select')
    fireEvent.change(platformSelect, { target: { value: 'instagram' } })

    await waitFor(() => {
      const calls = vi.mocked(api.getLastRate).mock.calls
      const lastCall = calls[calls.length - 1] ?? []
      expect(lastCall[1]).toBe('instagram')
    })
  })

  it('intel verdict updates to neutral for Instagram (no cold/breaker)', async () => {
    vi.mocked(api.getCreatorIntel).mockResolvedValue(INTEL_DATA as ReturnType<typeof api.getCreatorIntel> extends Promise<infer T> ? T : never)
    vi.mocked(api.getLastRate).mockResolvedValue({ last_rate: null })

    renderForm()

    // On TikTok: INTEL_DATA (20 posts, 0 viral, 5K avg) → cold
    typeHandle('coldoncreator')
    await waitFor(() =>
      expect(screen.getByText(/Cold history/)).toBeInTheDocument()
    )

    // Switch to Instagram via the mocked native <select>: same intel data must NOT yield cold
    const platformSelect = screen.getByTestId('platform-select')
    fireEvent.change(platformSelect, { target: { value: 'instagram' } })

    await waitFor(() =>
      expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
    )
    // Should show neutral (tracked posts line) not cold
    expect(screen.getByText(/tracked posts/)).toBeInTheDocument()
    expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
  })
})

describe('AddCreatorForm — manual edit protection', () => {
  it('does not overwrite manually typed price when last-rate resolves', async () => {
    vi.mocked(api.getCreatorIntel).mockRejectedValue(INTEL_TRIAL)
    let resolveLate!: (v: { last_rate: { total_rate: number; posts_owed: number; campaign: string; added_date: string } }) => void
    const lateRate = new Promise<{ last_rate: { total_rate: number; posts_owed: number; campaign: string; added_date: string } }>(
      (res) => { resolveLate = res }
    )
    vi.mocked(api.getLastRate).mockReturnValue(lateRate)

    renderForm()
    typeHandle('metacreator')

    // User manually changes the price before the lookup resolves
    const priceInput = screen.getByDisplayValue('100')
    fireEvent.change(priceInput, { target: { value: '999' } })

    // Now late rate resolves
    await act(async () => {
      resolveLate({ last_rate: { total_rate: 777, posts_owed: 4, campaign: 'Old Camp', added_date: '2026-01-01' } })
      await Promise.resolve()
    })

    // Manual price must survive
    expect(screen.getByDisplayValue('999')).toBeInTheDocument()
  })

  it('does not overwrite manually typed posts when last-rate resolves', async () => {
    vi.mocked(api.getCreatorIntel).mockRejectedValue(INTEL_TRIAL)
    let resolveLate!: (v: { last_rate: { total_rate: number; posts_owed: number; campaign: string; added_date: string } }) => void
    const lateRate = new Promise<{ last_rate: { total_rate: number; posts_owed: number; campaign: string; added_date: string } }>(
      (res) => { resolveLate = res }
    )
    vi.mocked(api.getLastRate).mockReturnValue(lateRate)

    renderForm()
    typeHandle('metacreator')

    const postsInput = screen.getByDisplayValue('5')
    fireEvent.change(postsInput, { target: { value: '12' } })

    await act(async () => {
      resolveLate({ last_rate: { total_rate: 777, posts_owed: 4, campaign: 'Old Camp', added_date: '2026-01-01' } })
      await Promise.resolve()
    })

    expect(screen.getByDisplayValue('12')).toBeInTheDocument()
  })
})

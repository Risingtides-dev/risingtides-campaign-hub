import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import CreatorIntelligence from "./CreatorIntelligence"

const hooks = vi.hoisted(() => ({
  breakers: vi.fn(), sounds: vi.fn(), fit: vi.fn(), rebook: vi.fn(),
  creator: vi.fn(), outcomes: vi.fn(), retry: vi.fn(),
}))

vi.mock("@/lib/queries", () => ({
  useBreakers: hooks.breakers, useSounds: hooks.sounds, useSoundFit: hooks.fit,
  useRebookSuggestions: hooks.rebook, useCreatorIntel: hooks.creator,
  useCreatorOutcomes: hooks.outcomes,
}))

function result(data: unknown, isError = false) {
  return { data, isError, isLoading: false, refetch: hooks.retry }
}

describe("CreatorIntelligence query states", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    hooks.breakers.mockReturnValue(result({ breakers: [], count: 0, min_posts: 5 }))
    hooks.sounds.mockReturnValue(result({ sounds: [] }))
    hooks.fit.mockReturnValue(result(undefined))
    hooks.rebook.mockReturnValue(result({ suggestions: [] }))
    hooks.creator.mockReturnValue(result(undefined))
    hooks.outcomes.mockReturnValue(result(undefined))
  })

  it("reports ranking failures and retries instead of claiming no matches", async () => {
    hooks.breakers.mockReturnValue(result(undefined, true))
    render(<CreatorIntelligence />)
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load creator rankings.")
    expect(screen.queryByText("No creators match.")).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Retry" }))
    expect(hooks.retry).toHaveBeenCalledOnce()
  })

  it("reports rebooking failures separately from an empty result", async () => {
    hooks.rebook.mockReturnValue(result(undefined, true))
    render(<CreatorIntelligence />)
    await userEvent.click(screen.getByRole("button", { name: "Re-book" }))
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load re-book suggestions.")
    expect(screen.queryByText("No suggestions right now.")).not.toBeInTheDocument()
  })

  it("reports sound picker failures separately from no matching sounds", async () => {
    hooks.sounds.mockReturnValue(result(undefined, true))
    render(<CreatorIntelligence />)
    await userEvent.click(screen.getByRole("button", { name: "By Sound" }))
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load sounds.")
    expect(screen.queryByText("No sounds match.")).not.toBeInTheDocument()
  })

  it("keeps shared-sound rounds separately selected and reports fit errors", async () => {
    const sound = { sound_id: "same-sound", artist: "Artist", song: "Same Song", round: "1", start_date: "2026-10-01", campaign_slug: "round-1", post_count: 0, freshness: "fresh" }
    hooks.sounds.mockReturnValue(result({ sounds: [sound, { ...sound, round: "2", start_date: "2026-11-01", campaign_slug: "round-2" }] }))
    hooks.fit.mockReturnValue(result(undefined, true))
    render(<CreatorIntelligence />)
    await userEvent.click(screen.getByRole("button", { name: "By Sound" }))
    const first = screen.getByRole("button", { name: /Round 1/ })
    const second = screen.getByRole("button", { name: /Round 2/ })
    expect(first).toHaveTextContent("2026-10-01")
    expect(second).toHaveTextContent("2026-11-01")
    await userEvent.click(first)
    expect(hooks.fit).toHaveBeenLastCalledWith("same-sound", "round-1")
    expect(first).toHaveAttribute("aria-pressed", "true")
    expect(second).toHaveAttribute("aria-pressed", "false")
    await userEvent.click(second)
    expect(hooks.fit).toHaveBeenLastCalledWith("same-sound", "round-2")
    expect(first).toHaveAttribute("aria-pressed", "false")
    expect(second).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load sound fit.")
    expect(screen.queryByText("No qualifying creators for this sound.")).not.toBeInTheDocument()
  })

  it("renders a successful empty fit explicitly", async () => {
    hooks.sounds.mockReturnValue(result({ sounds: [{ sound_id: "sound", artist: "Artist", song: "Song", campaign_slug: "campaign", post_count: 0, freshness: "fresh" }] }))
    hooks.fit.mockReturnValue(result({ creators: [] }))
    render(<CreatorIntelligence />)
    await userEvent.click(screen.getByRole("button", { name: "By Sound" }))
    await userEvent.click(screen.getByRole("button", { name: /Song/ }))
    expect(screen.getByText("No qualifying creators for this sound.")).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })
})

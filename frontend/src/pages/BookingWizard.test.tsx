import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import BookingWizard from "./BookingWizard"
import type { LibraryCreator, NetworkCreator, SoundFitCreator, SoundFitResponse, TargetSound } from "@/lib/types"

const mocks = vi.hoisted(() => ({
  sounds: vi.fn(), network: vi.fn(), library: vi.fn(), fit: vi.fn(),
  add: vi.fn(), navigate: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn(),
}))
vi.mock("@/lib/queries", () => ({
  keys: { outreach: (slug: string) => ["outreach", slug] },
  useSounds: mocks.sounds, useNetwork: mocks.network, useLibrary: mocks.library, useSoundFit: mocks.fit,
}))
vi.mock("@/lib/api", () => ({ api: { addToOutreach: mocks.add } }))
vi.mock("react-router-dom", () => ({ useNavigate: () => mocks.navigate }))
vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error, info: mocks.info } }))

const sound: TargetSound = { sound_id: "123", artist: "Artist", song: "Song", campaign_slug: "round-one", post_count: 0, freshness: "fresh" }
const secondSound: TargetSound = { ...sound, song: "Song Round 2", campaign_slug: "round-two" }
function result<T>(data: T, overrides = {}) {
  return { data, isLoading: false, isError: false, refetch: vi.fn(), ...overrides }
}
function creator(account = "@Alice", score = 10): SoundFitCreator {
  return { account, fit_score: score, breaker_score: score, viral_rate: 10, avg_views: 100, millionaires: 0, distinct_sounds: 1, on_sound_avg: null, posted_this_sound: false, posted_this_artist: false, reasons: [] }
}
function rate(overrides: Partial<LibraryCreator> = {}): LibraryCreator {
  return { username: "Alice", key: "alice", rate: 25, rate_source: "booking", platform: "tiktok", ...overrides } as LibraryCreator
}
function network(overrides: Partial<NetworkCreator> = {}): NetworkCreator {
  return { username: "alice", platform: "tiktok", default_rate: 10, default_posts: 3, ...overrides } as NetworkCreator
}
function fit(creators = [creator()], campaign = sound): SoundFitResponse {
  return { sound_id: campaign.sound_id, artist: campaign.artist, song: campaign.song, campaign_slug: campaign.campaign_slug, creators }
}
function renderWizard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const rendered = render(<QueryClientProvider client={client}><BookingWizard /></QueryClientProvider>)
  return { ...rendered, invalidate, client }
}
async function pick() { await userEvent.click(screen.getByRole("button", { name: "Song fresh Artist" })) }
async function selectAlice() { await userEvent.click(screen.getByRole("button", { name: /@Alice/ })) }

beforeEach(() => {
  vi.clearAllMocks()
  mocks.sounds.mockReturnValue(result({ sounds: [sound] }))
  mocks.network.mockReturnValue(result([]))
  mocks.library.mockReturnValue(result({ creators: [rate()] }))
  mocks.fit.mockImplementation((_soundId, slug) => result(fit([creator()], slug === secondSound.campaign_slug ? secondSound : sound)))
  mocks.add.mockResolvedValue({ ok: true, added: 1 })
})

describe("Booking Wizard", () => {
  it("books from library rates with an empty network and reaches paid creators beyond the first40", async () => {
    const candidates = Array.from({ length: 45 }, (_, i) => creator(`@unrated${i}`, 100 - i))
    candidates.push(creator(" @ALIce/ ", 1))
    mocks.fit.mockReturnValue(result(fit(candidates)))
    const { invalidate } = renderWizard()
    await pick()
    expect(mocks.fit).toHaveBeenLastCalledWith("123", "round-one", 1000)
    expect(mocks.library).toHaveBeenLastCalledWith("w60", "tiktok")
    await userEvent.click(screen.getByRole("button", { name: /@ALIce/ }))
    expect(screen.getByText(/1 selected · 1 posts/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-one", [{ username: "alice", rate: 25, posts: 1 }])
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["outreach", "round-one"] })
    expect(mocks.success).toHaveBeenCalledWith("Added 1 creator to Song outreach")
    expect(mocks.navigate).toHaveBeenCalledWith("/campaign/round-one/outreach")
  }, 15_000)
  it("prefers the effective library rate while preserving network post defaults", async () => {
    mocks.network.mockReturnValue(result([network({ username: " @ALICE/ " })]))
    renderWizard()
    await pick()
    await selectAlice()
    expect(screen.getByText("$75")).toBeInTheDocument()
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-one", [{ username: "alice", rate: 75, posts: 3 }])
  })
  it("uses a genuine network rate when no library rate exists", async () => {
    mocks.library.mockReturnValue(result({ creators: [rate({ rate: null, rate_source: "none" })] }))
    mocks.network.mockReturnValue(result([network()]))
    renderWizard()
    await pick()
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-one", [{ username: "alice", rate: 10, posts: 3 }])
  })
  it("preserves a network total quote instead of multiplying it by the post count", async () => {
    mocks.library.mockReturnValue(result({ creators: [] }))
    mocks.network.mockReturnValue(result([network({ default_rate: 75, default_posts: 3 })]))
    renderWizard()
    await pick()
    await selectAlice()
    expect(screen.getByText("$75")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /@Alice/ })).toHaveTextContent("$25")
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-one", [{ username: "alice", rate: 75, posts: 3 }])
  })
  it("can deselect a creator whose rate disappears and still book the valid selection", async () => {
    mocks.library.mockReturnValue(result({ creators: [rate(), rate({ key: "bob", username: "Bob" })] }))
    mocks.fit.mockReturnValue(result(fit([creator(), creator("@Bob")])))
    const rendered = renderWizard()
    await pick()
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: /@Bob/ }))
    mocks.library.mockReturnValue(result({ creators: [rate({ rate: 0, rate_source: "override" }), rate({ key: "bob", username: "Bob" })] }))
    rendered.rerender(<QueryClientProvider client={rendered.client}><BookingWizard /></QueryClientProvider>)
    const invalid = screen.getByRole("button", { name: /@Alice/ })
    expect(invalid).toBeEnabled()
    expect(invalid).toHaveAttribute("aria-pressed", "true")
    await userEvent.click(invalid)
    expect(invalid).toBeDisabled()
    expect(invalid).toHaveAttribute("aria-pressed", "false")
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-one", [{ username: "bob", rate: 25, posts: 1 }])
  })
  it("prunes a vanished recommendation on review instead of permanently blocking the remaining selection", async () => {
    mocks.library.mockReturnValue(result({ creators: [rate(), rate({ key: "bob", username: "Bob" })] }))
    mocks.fit.mockReturnValue(result(fit([creator(), creator("@Bob")])))
    const rendered = renderWizard()
    await pick()
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: /@Bob/ }))
    mocks.fit.mockReturnValue(result(fit([creator("@Bob")])))
    rendered.rerender(<QueryClientProvider client={rendered.client}><BookingWizard /></QueryClientProvider>)
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).not.toHaveBeenCalled()
    expect(mocks.error).toHaveBeenCalledWith(expect.stringContaining("Check your selection"))
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-one", [{ username: "bob", rate: 25, posts: 1 }])
  })
  it.each([0, -10, Number.NaN, Number.POSITIVE_INFINITY, null])("blocks invalid explicit library rate %s rather than reviving a network rate", async (value) => {
    mocks.library.mockReturnValue(result({ creators: [rate({ rate: value, rate_source: "override" })] }))
    mocks.network.mockReturnValue(result([network()]))
    renderWizard()
    await pick()
    expect(screen.getByRole("button", { name: /@Alice/ })).toBeDisabled()
    expect(screen.getByRole("button", { name: "Book to outreach" })).toBeDisabled()
    expect(mocks.add).not.toHaveBeenCalled()
  })
  it.each([0, -1, 1.5, Number.NaN])("blocks invalid network post count %s", async (posts) => {
    mocks.network.mockReturnValue(result([network({ default_posts: posts })]))
    renderWizard()
    await pick()
    expect(screen.getByRole("button", { name: /@Alice/ })).toBeDisabled()
  })
  it("does not use an Instagram library rate for a TikTok handle", async () => {
    mocks.library.mockReturnValue(result({ creators: [rate({ platform: "instagram" })] }))
    renderWizard()
    await pick()
    expect(screen.getByRole("button", { name: /@Alice/ })).toBeDisabled()
  })
  it("keeps shared-sound campaign rounds independently selectable and resets selection", async () => {
    mocks.sounds.mockReturnValue(result({ sounds: [sound, secondSound] }))
    renderWizard()
    await pick()
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: "Song Round 2 fresh Artist" }))
    expect(mocks.fit).toHaveBeenLastCalledWith("123", "round-two", 1000)
    expect(screen.getByRole("button", { name: "Song Round 2 fresh Artist" })).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByRole("button", { name: "Song fresh Artist" })).toHaveAttribute("aria-pressed", "false")
    expect(screen.getByRole("button", { name: "Book to outreach" })).toBeDisabled()
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-two", [{ username: "alice", rate: 25, posts: 1 }])
  })
  it("labels identically named rounds and keeps their identity after filtering", async () => {
    const first = { ...sound, round: "1", start_date: "2026-10-01" }
    const second = { ...sound, campaign_slug: "round-two", round: "2", start_date: "2026-11-01" }
    mocks.sounds.mockReturnValue(result({ sounds: [first, second] }))
    renderWizard()
    const firstButton = screen.getByRole("button", { name: /Song fresh Artist Round 1 · 2026-10-01/ })
    const secondButton = screen.getByRole("button", { name: /Song fresh Artist Round 2 · 2026-11-01/ })
    await userEvent.click(firstButton)
    await selectAlice()
    await userEvent.click(secondButton)
    expect(firstButton).toHaveAttribute("aria-pressed", "false")
    expect(secondButton).toHaveAttribute("aria-pressed", "true")
    expect(screen.getByRole("button", { name: "Book to outreach" })).toBeDisabled()
    expect(mocks.fit).toHaveBeenLastCalledWith("123", "round-two", 1000)
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    expect(mocks.add).toHaveBeenCalledWith("round-two", [{ username: "alice", rate: 25, posts: 1 }])
  })
  it("reports zero additions as already present without claiming a new booking", async () => {
    mocks.add.mockResolvedValue({ ok: true, added: 0 })
    renderWizard()
    await pick()
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    await waitFor(() => expect(mocks.info).toHaveBeenCalledWith("Selected creators are already in outreach."))
    expect(mocks.success).not.toHaveBeenCalled()
  })
  it.each([{ ok: true }, { ok: true, added: 2 }, { ok: false, added: 1 }])("does not invent success for unconfirmed result %j", async (response) => {
    mocks.add.mockResolvedValue(response)
    renderWizard()
    await pick()
    await selectAlice()
    await userEvent.click(screen.getByRole("button", { name: "Book 1 to outreach" }))
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(expect.stringContaining("couldn't be confirmed")))
    expect(mocks.success).not.toHaveBeenCalled()
    expect(mocks.navigate).not.toHaveBeenCalled()
    expect(mocks.add).toHaveBeenCalledTimes(1)
  })
  it("shows query failures despite cached data rather than presenting empty or bookable data", async () => {
    mocks.sounds.mockReturnValue(result({ sounds: [sound] }, { isError: true }))
    const rendered = renderWizard()
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load sounds.")
    expect(screen.queryByText("No campaign sounds available.")).not.toBeInTheDocument()
    mocks.sounds.mockReturnValue(result({ sounds: [sound] }))
    mocks.fit.mockReturnValue(result(fit(), { isError: true }))
    mocks.library.mockReturnValue(result({ creators: [rate()] }, { isError: true }))
    rendered.rerender(<QueryClientProvider client={rendered.client}><BookingWizard /></QueryClientProvider>)
    await pick()
    expect(screen.getByText("Couldn't rank creators for this sound.")).toBeInTheDocument()
    expect(screen.getByText("Couldn't load creator rates.")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Book to outreach" })).toBeDisabled()
    expect(screen.queryByRole("button", { name: /@Alice/ })).not.toBeInTheDocument()
  })
  it("distinguishes a real empty result from an unmatched sound search", async () => {
    mocks.fit.mockReturnValue(result(fit([])))
    renderWizard()
    await pick()
    expect(screen.getByText("No tracked creators qualify for this sound.")).toBeInTheDocument()
    await userEvent.type(screen.getByRole("textbox", { name: "Search sounds" }), "missing")
    expect(screen.getByText("No sounds match your search.")).toBeInTheDocument()
  })
  it("refuses cached fit data for a different selected campaign", async () => {
    mocks.sounds.mockReturnValue(result({ sounds: [secondSound] }))
    mocks.fit.mockReturnValue(result(fit()))
    renderWizard()
    await userEvent.click(screen.getByRole("button", { name: "Song Round 2 fresh Artist" }))
    expect(screen.queryByRole("button", { name: /@Alice/ })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Book to outreach" })).toBeDisabled()
  })
})

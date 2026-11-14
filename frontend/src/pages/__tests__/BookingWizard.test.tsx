/**
 * BookingWizard regressions — issue #284
 *
 * Coverage:
 *  - empty network + existing library-rated creators → rows are bookable
 *  - creator with no library/network rate → "no rate" label, row disabled
 *  - invalid rate (0) → treated as missing, row disabled
 *  - selection toggle and reset on sound change
 *  - correct outreach payload (username, rate, posts)
 *  - both rate sources failing → error banner appears
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import BookingWizard from "@/pages/BookingWizard"
import { api } from "@/lib/api"
import type { SoundFitCreator, TargetSound, LibraryCreator } from "@/lib/types"

// ── helpers ────────────────────────────────────────────────────────────

function makeQC() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
}

function renderWizard(qc = makeQC()) {
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <BookingWizard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// Mock navigate so the test doesn't blow up after a successful booking.
vi.mock("react-router-dom", async (importOriginal) => {
  const orig = await importOriginal<typeof import("react-router-dom")>()
  return { ...orig, useNavigate: () => vi.fn() }
})

// ── fixtures ───────────────────────────────────────────────────────────

const SOUND_ID = "7291004856"

const sound: TargetSound = {
  sound_id: SOUND_ID,
  artist: "Test Artist",
  song: "Test Song",
  campaign_slug: "test-campaign-r1",
  campaign_title: "Test Campaign R1",
  post_count: 2,
  freshness: "fresh",
}

function makeFitCreator(account: string, fit_score = 80): SoundFitCreator {
  return {
    account,
    fit_score,
    breaker_score: 0.6,
    viral_rate: 0.1,
    avg_views: 50_000,
    millionaires: 1,
    distinct_sounds: 10,
    on_sound_avg: null,
    posted_this_sound: false,
    posted_this_artist: false,
    reasons: ["general breaker"],
  }
}

function makeLibraryCreator(username: string, rate: number | null): Partial<LibraryCreator> {
  return {
    username,
    key: username.toLowerCase(),
    rate,
    rate_source: rate !== null ? "booking" : "none",
    rate_override: null,
    niches: [],
    slow: false,
    note: "",
    paypal_email: "",
    platform: "tiktok",
    followers: 0,
    avatar_url: "",
    campaigns: 1,
    posts_owed: 1,
    posts_done: 1,
    spend: rate ?? 0,
    last_booked_at: "2026-01-01T00:00:00Z",
    scouted: false,
    stats: {},
    stats_updated_at: "",
  }
}

// ── mock setup ─────────────────────────────────────────────────────────

function mockApis({
  sounds = [sound],
  network = [] as unknown[],
  libraryCreators = [] as Partial<LibraryCreator>[],
  fitCreators = [] as SoundFitCreator[],
  networkFails = false,
  libraryFails = false,
}: {
  sounds?: TargetSound[]
  network?: unknown[]
  libraryCreators?: Partial<LibraryCreator>[]
  fitCreators?: SoundFitCreator[]
  networkFails?: boolean
  libraryFails?: boolean
} = {}) {
  const fetchMock = vi.fn().mockImplementation((url: string) => {
    if (url.includes("/api/intelligence/sounds")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ sounds }),
      })
    }
    if (url.includes("/api/network")) {
      if (networkFails) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ error: "network down" }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(network) })
    }
    if (url.includes("/api/library/creators") && !url.includes("/rate") && !url.includes("/niches")) {
      if (libraryFails) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ error: "library down" }) })
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            window: "wall",
            windows: ["wall"],
            count: libraryCreators.length,
            creators: libraryCreators,
          }),
      })
    }
    if (url.includes(`/api/intelligence/sound-fit/${SOUND_ID}`)) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            sound_id: SOUND_ID,
            artist: sound.artist,
            song: sound.song,
            campaign_slug: sound.campaign_slug,
            creators: fitCreators,
          }),
      })
    }
    return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
  })
  globalThis.fetch = fetchMock as unknown as typeof fetch
  return fetchMock
}

const originalFetch = globalThis.fetch
beforeEach(() => {
  vi.clearAllMocks()
  globalThis.fetch = originalFetch
})

// ── tests ──────────────────────────────────────────────────────────────

describe("BookingWizard rate sourcing", () => {
  it("enables a creator row when their rate comes from the library even with an empty network", async () => {
    const alice = makeLibraryCreator("alice", 150)
    mockApis({
      network: [],
      libraryCreators: [alice],
      fitCreators: [makeFitCreator("alice")],
    })
    renderWizard()
    await waitFor(() => expect(screen.getByText("Test Song")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Test Song"))
    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument())
    // Rate cell should show the library rate, not "no rate".
    expect(screen.getByText("$150")).toBeInTheDocument()
    // Row must NOT be disabled.
    const row = screen.getByText("alice").closest("button")
    expect(row).not.toBeDisabled()
  })

  it("shows 'no rate' and disables the row when neither library nor network has a rate", async () => {
    const bob = makeLibraryCreator("bob", null)
    mockApis({
      network: [],
      libraryCreators: [bob],
      fitCreators: [makeFitCreator("bob")],
    })
    renderWizard()
    await waitFor(() => expect(screen.getByText("Test Song")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Test Song"))
    await waitFor(() => expect(screen.getByText("bob")).toBeInTheDocument())
    expect(screen.getByText("no rate")).toBeInTheDocument()
    const row = screen.getByText("bob").closest("button")
    expect(row).toBeDisabled()
  })

  it("treats a zero-rate library entry as missing (row disabled)", async () => {
    const carol = makeLibraryCreator("carol", 0)
    mockApis({
      network: [],
      libraryCreators: [carol],
      fitCreators: [makeFitCreator("carol")],
    })
    renderWizard()
    await waitFor(() => expect(screen.getByText("Test Song")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Test Song"))
    await waitFor(() => expect(screen.getByText("carol")).toBeInTheDocument())
    expect(screen.getByText("no rate")).toBeInTheDocument()
    const row = screen.getByText("carol").closest("button")
    expect(row).toBeDisabled()
  })

  it("network rate overrides the library rate when both are present", async () => {
    const dave = makeLibraryCreator("dave", 100)
    mockApis({
      network: [{ username: "dave", default_rate: 200, default_posts: 2, platform: "tiktok", paypal_email: "", manychat_subscriber_id: "", niches: [], notes: "", added_at: "" }],
      libraryCreators: [dave],
      fitCreators: [makeFitCreator("dave")],
    })
    renderWizard()
    await waitFor(() => expect(screen.getByText("Test Song")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Test Song"))
    await waitFor(() => expect(screen.getByText("dave")).toBeInTheDocument())
    // Network rate ($200) should win over library rate ($100).
    expect(screen.getByText("$200")).toBeInTheDocument()
  })
})

describe("BookingWizard selection", () => {
  it("toggles a creator in and out of the selection", async () => {
    const alice = makeLibraryCreator("alice", 150)
    mockApis({ libraryCreators: [alice], fitCreators: [makeFitCreator("alice")] })
    renderWizard()
    await waitFor(() => expect(screen.getByText("Test Song")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Test Song"))
    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument())

    const row = screen.getByText("alice").closest("button")!
    // Select.
    fireEvent.click(row)
    expect(screen.getByText(/Book 1 to outreach/i)).toBeInTheDocument()
    // Deselect.
    fireEvent.click(row)
    expect(screen.queryByText(/Book 1 to outreach/i)).not.toBeInTheDocument()
  })

  it("resets selection when a different sound is picked", async () => {
    const sound2: TargetSound = { ...sound, sound_id: "other-sound", campaign_slug: "test-r2", campaign_title: "Test R2" }
    const alice = makeLibraryCreator("alice", 150)
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/intelligence/sounds")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ sounds: [sound, sound2] }) })
      }
      if (url.includes("/api/network")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
      }
      if (url.includes("/api/library/creators")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ window: "wall", windows: ["wall"], count: 1, creators: [alice] }) })
      }
      if (url.includes(`/api/intelligence/sound-fit/${SOUND_ID}`)) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ sound_id: SOUND_ID, campaign_slug: sound.campaign_slug, creators: [makeFitCreator("alice")] }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ sound_id: "other-sound", campaign_slug: "test-r2", creators: [] }) })
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch
    renderWizard()
    await waitFor(() => expect(screen.getAllByText("Test Song").length).toBeGreaterThan(0))
    fireEvent.click(screen.getAllByText("Test Song")[0].closest("button")!)
    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument())
    fireEvent.click(screen.getByText("alice").closest("button")!)

    // Now pick sound2 — selection should reset.
    const r2button = screen.getByText("Test R2").closest("button")!
    fireEvent.click(r2button)
    expect(screen.queryByText(/Book 1 to outreach/i)).not.toBeInTheDocument()
  })
})

describe("BookingWizard outreach payload", () => {
  it("calls addToOutreach with the correct username, rate and posts", async () => {
    const alice = makeLibraryCreator("alice", 150)
    mockApis({ libraryCreators: [alice], fitCreators: [makeFitCreator("alice")] })
    const addToOutreach = vi.fn().mockResolvedValue({ ok: true, added: 1 })
    ;(api as unknown as Record<string, unknown>).addToOutreach = addToOutreach
    renderWizard()
    await waitFor(() => expect(screen.getByText("Test Song")).toBeInTheDocument())
    fireEvent.click(screen.getByText("Test Song"))
    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument())
    fireEvent.click(screen.getByText("alice").closest("button")!)
    fireEvent.click(screen.getByText(/Book 1 to outreach/i))
    await waitFor(() => expect(addToOutreach).toHaveBeenCalled())
    const [slug, payload] = addToOutreach.mock.calls[0]
    expect(slug).toBe("test-campaign-r1")
    expect(payload).toEqual([{ username: "alice", rate: 150, posts: 1 }])
  })

  it("books into the correct campaign slug when multiple sounds share a sound_id", async () => {
    // The user picks the Round 2 entry — booking must go to that slug, not Round 1.
    const r1: TargetSound = { ...sound, campaign_slug: "song-r1", campaign_title: "Song R1" }
    const r2: TargetSound = { ...sound, campaign_slug: "song-r2", campaign_title: "Song R2" }
    const alice = makeLibraryCreator("alice", 100)
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/intelligence/sounds")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ sounds: [r1, r2] }) })
      }
      if (url.includes("/api/network")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve([]) })
      }
      if (url.includes("/api/library/creators")) {
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ window: "wall", windows: ["wall"], count: 1, creators: [alice] }) })
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({ sound_id: SOUND_ID, campaign_slug: "song-r1", creators: [makeFitCreator("alice")] }) })
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch
    const addToOutreach = vi.fn().mockResolvedValue({ ok: true, added: 1 })
    ;(api as unknown as Record<string, unknown>).addToOutreach = addToOutreach

    renderWizard()
    await waitFor(() => expect(screen.getByText("Song R2")).toBeInTheDocument())
    // Click the R2 entry.
    fireEvent.click(screen.getByText("Song R2"))
    await waitFor(() => expect(screen.getByText("alice")).toBeInTheDocument())
    fireEvent.click(screen.getByText("alice").closest("button")!)
    fireEvent.click(screen.getByText(/Book 1 to outreach/i))
    await waitFor(() => expect(addToOutreach).toHaveBeenCalled())
    expect(addToOutreach.mock.calls[0][0]).toBe("song-r2")
  })
})

describe("BookingWizard error states", () => {
  it("shows an error banner when both network and library fail to load", async () => {
    mockApis({ networkFails: true, libraryFails: true })
    renderWizard()
    await waitFor(() =>
      expect(screen.getByText(/Could not load creator rates/i)).toBeInTheDocument(),
    )
  })
})

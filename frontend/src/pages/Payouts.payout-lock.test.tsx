// Regression tests for the payout lock session security fixes (issue #299):
// - revoked-key reentry must not serve cached credentials
// - deferred responses arriving after Lock must not restore the unlocked view
// - admin key must not appear in React Query cache keys
// - clipboard failure on rotate must expose the new link inline (no silent swallow)
// - clipboard failure must not trigger a second rotation
//
// Tests run against a QueryClient configured with the app's production defaults
// (staleTime: 5 min, refetchOnMount: false) so the bugs reproduce as described.
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { Mock } from "vitest"
import Payouts from "./Payouts"

// Match the app's production QueryClient defaults from main.tsx exactly.
function makeQC() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 5 * 60 * 1000, refetchOnMount: false },
    },
  })
}

const KEY = "testkey".padEnd(32, "x")

const overview = {
  creators: [
    {
      username: "alice",
      handle: "alice",
      method: "paypal",
      destination: "alice@example.com",
      confirmed: true,
      flagged: true,
      has_link: true,
      updated_at: "2026-11-01T00:00:00Z",
    },
  ],
  summary: { total: 1, confirmed: 1, unconfirmed_on_file: 0, missing: 0, flagged: 1, links_issued: 1 },
}

const emptyQueue = { ready: [], awaiting_confirmation: [], not_ready: [], in_batch: [], totals: { ready_count: 0, ready_amount: 0, payable_now: 0, by_method: {} }, trusted_min_campaigns: 6 }
const emptyBatches = { batches: [], paypal: { connected: false, env: "sandbox" } }

function okJson(body: unknown) {
  return { ok: true, status: 200, json: async () => body }
}

function err401() {
  return { ok: false, status: 401, json: async () => ({ error: "Invalid key" }) }
}

function stubFetch(handler: (url: string) => unknown): Mock {
  const fn = vi.fn((url: string) => Promise.resolve(handler(url)))
  vi.stubGlobal("fetch", fn)
  return fn
}

// Handles all payout admin endpoints with sensible defaults; pass overrides for specific ones.
function defaultFetch(overrides: Record<string, unknown> = {}) {
  return stubFetch((url) => {
    for (const [pattern, body] of Object.entries(overrides)) {
      if (url.includes(pattern)) return body
    }
    if (url.includes("/api/payouts/admin/creators")) return okJson(overview)
    if (url.includes("/api/payouts/admin/queue")) return okJson(emptyQueue)
    if (url.includes("/api/payouts/admin/batches")) return okJson(emptyBatches)
    return okJson({})
  })
}

function setup(qc: QueryClient) {
  return render(
    <QueryClientProvider client={qc}>
      <Payouts />
    </QueryClientProvider>,
  )
}

async function unlock({ container }: ReturnType<typeof setup>, key = KEY) {
  const input = container.querySelector('input[type="password"]') as HTMLInputElement
  await userEvent.type(input, key)
  await userEvent.click(screen.getByRole("button", { name: "Unlock" }))
}

beforeEach(() => {
  sessionStorage.clear()
  vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
})

describe("revoked-key reentry", () => {
  it("makes a fresh server request when the same key is re-entered after Lock", async () => {
    let overviewCallCount = 0
    const fn = stubFetch((url) => {
      if (url.includes("/api/payouts/admin/creators")) {
        overviewCallCount++
        // first unlock: succeed; second unlock (same key, now revoked): fail
        return overviewCallCount === 1 ? okJson(overview) : err401()
      }
      if (url.includes("/api/payouts/admin/queue")) return okJson(emptyQueue)
      if (url.includes("/api/payouts/admin/batches")) return okJson(emptyBatches)
      return okJson({})
    })

    const qc = makeQC()
    const rendered = setup(qc)

    // First unlock — data loads
    await unlock(rendered)
    await screen.findByText("Payouts")

    // Lock
    await userEvent.click(screen.getByRole("button", { name: "Lock" }))
    await screen.findByRole("button", { name: "Unlock" })

    // Re-enter the same key; server now returns 401
    await unlock(rendered)

    // Should show the auth error, not the cached admin view
    await waitFor(() => expect(screen.getByText("Invalid key")).toBeInTheDocument())
    expect(screen.queryByText("Payouts")).not.toBeInTheDocument()

    // The overview endpoint was hit twice (once per unlock, never cached)
    expect(overviewCallCount).toBe(2)
  })
})

describe("deferred responses after Lock", () => {
  it("does not restore the unlocked view when a response arrives after Lock", async () => {
    let resolveOverview!: (v: unknown) => void
    const overviewPromise = new Promise((res) => { resolveOverview = res })

    stubFetch((url) => {
      if (url.includes("/api/payouts/admin/creators")) return overviewPromise
      if (url.includes("/api/payouts/admin/queue")) return okJson(emptyQueue)
      if (url.includes("/api/payouts/admin/batches")) return okJson(emptyBatches)
      return okJson({})
    })

    const qc = makeQC()
    const rendered = setup(qc)

    // Unlock — query fires but stays in-flight
    await unlock(rendered)
    // After unlock the page is in loading state (Lock button shows, Unlock button gone)
    await waitFor(() => expect(screen.getByRole("button", { name: "Lock" })).toBeInTheDocument())
    expect(screen.queryByRole("button", { name: "Unlock" })).not.toBeInTheDocument()

    // Lock before the response resolves
    await userEvent.click(screen.getByRole("button", { name: "Lock" }))

    // Page is now locked — KeyGate shows the Unlock button
    await screen.findByRole("button", { name: "Unlock" })

    // The deferred response arrives after Lock
    resolveOverview(okJson(overview))
    await new Promise((r) => setTimeout(r, 50))

    // Still locked — the late response must not restore the admin view
    expect(screen.getByRole("button", { name: "Unlock" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Lock" })).not.toBeInTheDocument()
  })
})

describe("cache does not contain the admin key", () => {
  it("stores no query cache entries whose key includes the plaintext admin key", async () => {
    defaultFetch()
    const qc = makeQC()
    const rendered = setup(qc)

    await unlock(rendered)
    await screen.findByText("Payouts")

    const cacheKeys = qc.getQueryCache().getAll().map((q) => JSON.stringify(q.queryKey))
    for (const k of cacheKeys) {
      expect(k).not.toContain(KEY)
    }
  })
})

describe("rotate clipboard handling", () => {
  it("does not show the inline link when clipboard write succeeds", async () => {
    vi.mocked(navigator.clipboard.writeText).mockResolvedValue(undefined)
    const LINK = "https://hub.example/payout#abc"
    defaultFetch({ "/rotate-link": okJson({ username: "alice", link: LINK }) })

    const qc = makeQC()
    const rendered = setup(qc)
    await unlock(rendered)
    await screen.findByText("Payouts")
    // Use an anchored regex: the tab button name starts with "Payment info", the
    // flagged-creator alert also contains "Payment info" but mid-sentence.
    await userEvent.click(screen.getByRole("button", { name: /^Payment info/i }))

    await userEvent.click(screen.getByRole("button", { name: "New link (kill old)" }))

    await waitFor(() => expect(vi.mocked(navigator.clipboard.writeText)).toHaveBeenCalledWith(LINK))
    // No inline manual-copy input after a successful clipboard write
    expect(screen.queryByRole("textbox", { name: /New payout link for @alice/i })).not.toBeInTheDocument()
  })

  it("exposes the new link for manual copy when clipboard is denied", async () => {
    vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new DOMException("NotAllowedError"))
    const NEW_LINK = "https://hub.example/payout#xyz789"
    defaultFetch({ "/rotate-link": okJson({ username: "alice", link: NEW_LINK }) })

    const qc = makeQC()
    const rendered = setup(qc)
    await unlock(rendered)
    await screen.findByText("Payouts")
    await userEvent.click(screen.getByRole("button", { name: /^Payment info/i }))

    await userEvent.click(screen.getByRole("button", { name: "New link (kill old)" }))

    // The new link URL must appear as a selectable input so the admin can copy it
    await waitFor(() => {
      const input = screen.getByRole("textbox", { name: /New payout link for @alice/i })
      expect(input).toHaveValue(NEW_LINK)
    })
  })

  it("does not issue a second rotation on clipboard failure", async () => {
    vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new DOMException("NotAllowedError"))
    const fetchFn = defaultFetch({ "/rotate-link": okJson({ username: "alice", link: "https://hub.example/payout#xyz" }) })

    const qc = makeQC()
    const rendered = setup(qc)
    await unlock(rendered)
    await screen.findByText("Payouts")
    await userEvent.click(screen.getByRole("button", { name: /^Payment info/i }))

    await userEvent.click(screen.getByRole("button", { name: "New link (kill old)" }))

    // Wait for the inline link to appear (proves the first rotation completed)
    await waitFor(() => screen.getByRole("textbox", { name: /New payout link for @alice/i }))

    const rotateCalls = fetchFn.mock.calls.filter(([u]: [string]) => u.includes("/rotate-link"))
    expect(rotateCalls.length).toBe(1)
  })

  it("clears rotated links on Lock", async () => {
    vi.mocked(navigator.clipboard.writeText).mockRejectedValue(new DOMException("NotAllowedError"))
    defaultFetch({ "/rotate-link": okJson({ username: "alice", link: "https://hub.example/payout#xyz" }) })

    const qc = makeQC()
    const rendered = setup(qc)
    await unlock(rendered)
    await screen.findByText("Payouts")
    await userEvent.click(screen.getByRole("button", { name: /^Payment info/i }))
    await userEvent.click(screen.getByRole("button", { name: "New link (kill old)" }))
    await waitFor(() => screen.getByRole("textbox", { name: /New payout link for @alice/i }))

    // Lock — inline links must be cleared with the session
    await userEvent.click(screen.getByRole("button", { name: "Lock" }))
    await screen.findByRole("button", { name: "Unlock" })

    // Inline link no longer in the DOM
    expect(screen.queryByRole("textbox", { name: /New payout link for @alice/i })).not.toBeInTheDocument()
  })
})

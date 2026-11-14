import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { PayoutBatches } from "../PayoutBatches"
import { PayoutSessionProvider } from "@/lib/payoutSession"
import type { BatchItem, BatchesResponse, PayoutBatch } from "@/lib/payouts"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))
const ADMIN_KEY = "synthetic-payout-key"
const SESSION = "opaque-test-session"
const PREFIX = ["payouts", SESSION]
const item = (overrides: Partial<BatchItem> = {}): BatchItem => ({
  id: 1, campaign: "Campaign", campaign_id: 1, username: "alice", platform: "tiktok", amount: 100,
  method: "paypal", destination: "test@example.invalid", lane: "api", status: "queued", provider_status: "", error: "", paid_at: "", ...overrides,
})
function batch(overrides: Partial<PayoutBatch> = {}): PayoutBatch {
  const items = overrides.items ?? [item()]
  const api = items.filter((row) => row.lane === "api").reduce((sum, row) => sum + row.amount, 0)
  const manual = items.filter((row) => row.lane === "manual").reduce((sum, row) => sum + row.amount, 0)
  return { id: 1, status: "draft", paypal_env: "live", sender_batch_id: "original-request", paypal_batch_id: "", created_at: "2026-11-13T21:00:00", approved_at: "", last_synced_at: "", error: "", items, totals: { api, manual, all: api + manual }, ...overrides }
}
function show(initial: PayoutBatch, connected = true, extra?: (url: string, init?: RequestInit) => Promise<unknown>, onMutate?: () => Promise<void>) {
  let active = true
  let current: BatchesResponse = { batches: [initial], paypal: { connected, env: "live" } }
  let read: ((init?: RequestInit) => Promise<unknown>) | undefined
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/api/payouts/admin/batches") && (!init?.method || init.method === "GET")) {
      return read ? await read(init) : { ok: true, status: 200, json: async () => current }
    }
    const response = extra ? await extra(url, init) : current.batches[0]
    if (response && typeof response === "object" && "ok" in response && "json" in response) return response
    return { ok: true, status: 200, json: async () => response }
  })
  vi.stubGlobal("fetch", fetch)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false, onMutate } } })
  const invalidate = vi.spyOn(client, "invalidateQueries")
  const rendered = render(<QueryClientProvider client={client}><PayoutSessionProvider sessionId={SESSION} isActive={() => active}><PayoutBatches adminKey={ADMIN_KEY} /></PayoutSessionProvider></QueryClientProvider>)
  return { ...rendered, client, fetch, invalidate, stop: () => { active = false }, setRead: (handler: typeof read) => { read = handler }, setData: (next: PayoutBatch) => { current = { ...current, batches: [next] }; client.setQueryData([...PREFIX, "batches"], current) } }
}
async function card() { return within(await screen.findByRole("article", { name: "Batch 1" })) }
async function openHistory() { await userEvent.click(await screen.findByRole("button", { name: "Past batches (1)" })) }
const requests = (fetch: ReturnType<typeof vi.fn>, suffix: string) => fetch.mock.calls.filter(([url]) => String(url).endsWith(suffix))

beforeEach(() => vi.clearAllMocks())

describe("payment batch outcomes", () => {
  it.each([
    { status: "failed" as const, env: "live", heading: "Failed batch", amount: "Failed $100" },
    { status: "sandbox_ok" as const, env: "sandbox", heading: "Sandbox results", amount: "Test $100" },
    { status: "review" as const, env: "live", heading: "Needs review", amount: "Review $100" },
  ])("does not report $status money as paid", async ({ status, env, heading, amount }) => {
    show(batch({ status: "closed", paypal_env: env, items: [item({ status })] }))
    await openHistory()
    const view = await card()
    expect(view.getByRole("heading", { name: heading })).toBeInTheDocument()
    expect(view.queryByRole("heading", { name: "Paid" })).not.toBeInTheDocument()
    expect(view.getByText(amount)).toBeInTheDocument()
  })

  it("separates actually paid and failed amounts in a mixed closed batch", async () => {
    show(batch({ status: "closed", items: [item({ amount: 60, status: "succeeded" }), item({ id: 2, username: "bob", amount: 40, status: "failed" })] }))
    await openHistory()
    const view = await card()
    expect(view.getByRole("heading", { name: "Partially paid" })).toBeInTheDocument()
    expect(view.getByText("Paid $60 · Failed $40")).toBeInTheDocument()
    expect(view.queryByText("Paid $100")).not.toBeInTheDocument()
  })

  it("counts real manual payments separately from a sandbox API payment", async () => {
    show(batch({ status: "closed", paypal_env: "sandbox", items: [item({ status: "sandbox_ok" }), item({ id: 2, username: "bob", amount: 75, status: "succeeded", lane: "manual", method: "cashapp" })] }))
    await openHistory()
    const view = await card()
    expect(view.getByRole("heading", { name: "Partially paid" })).toBeInTheDocument()
    expect(view.getByText("Paid $75 · Test $100")).toBeInTheDocument()
  })

  it("does not label legacy sandbox API succeeded plus real manual settlement as wholly paid", async () => {
    show(batch({ status: "closed", paypal_env: "sandbox", items: [item({ status: "succeeded" }), item({ id: 2, username: "bob", amount: 75, status: "succeeded", lane: "manual", method: "cashapp" })] }))
    await openHistory()
    const view = await card()
    expect(view.getByRole("heading", { name: "Partially paid" })).toBeInTheDocument()
    expect(view.getByText("Paid $75 · Test $100")).toBeInTheDocument()
  })

  it("shows Paid only for a wholly successful live batch", async () => {
    show(batch({ status: "closed", items: [item({ status: "succeeded" })] }))
    await openHistory()
    expect((await card()).getByRole("heading", { name: "Paid" })).toBeInTheDocument()
  })

  it("keeps cancelled batches identifiable if returned by the server", async () => {
    show(batch({ status: "cancelled", items: [], totals: { api: 0, manual: 0, all: 0 } }))
    await openHistory()
    expect((await card()).getByRole("heading", { name: "Cancelled batch" })).toBeInTheDocument()
  })
})

describe("batch approval and reconciliation", () => {
  it("requires the exact total and sends one deliberate approval with session-scoped cache identities", async () => {
    const state = show(batch())
    const view = await card()
    expect(screen.getByText("PayPal: configured (LIVE)")).toBeInTheDocument()
    const input = view.getByRole("textbox", { name: /Confirm PayPal total/ })
    const send = view.getByRole("button", { name: "Send $100" })
    await userEvent.type(input, "1")
    expect(send).toBeDisabled()
    await userEvent.clear(input)
    await userEvent.type(input, "100.001")
    expect(send).toBeDisabled()
    await userEvent.clear(input)
    await userEvent.type(input, "100.00")
    expect(send).toBeEnabled()
    await userEvent.click(send)
    expect(requests(state.fetch, "/approve")).toHaveLength(1)
    const [, init] = requests(state.fetch, "/approve")[0]
    expect(JSON.parse(init.body)).toEqual({ confirm_total: "100.00" })
    expect(init.headers["X-Payout-Admin-Key"]).toBe(ADMIN_KEY)
    await waitFor(() => expect(state.invalidate).toHaveBeenCalledWith({ queryKey: PREFIX }))
    expect(state.client.getQueryCache().findAll().every((query) => !query.queryKey.includes(ADMIN_KEY))).toBe(true)
    expect(state.client.getMutationCache().getAll().every((mutation) => !mutation.options.mutationKey?.includes(ADMIN_KEY))).toBe(true)
  })

  it("disables approval when PayPal is not configured", async () => {
    const state = show(batch(), false)
    const view = await card()
    expect(view.getByRole("textbox", { name: /Confirm PayPal total/ })).toBeDisabled()
    await userEvent.click(view.getByRole("button", { name: "Send $100" }))
    expect(requests(state.fetch, "/approve")).toHaveLength(0)
    expect(screen.getByText("PayPal: not configured")).toBeInTheDocument()
  })

  it("invalidates typed approval when the draft total changes", async () => {
    const state = show(batch())
    const view = await card()
    await userEvent.type(view.getByRole("textbox", { name: /Confirm PayPal total/ }), "100")
    expect(view.getByRole("button", { name: "Send $100" })).toBeEnabled()
    act(() => state.setData(batch({ items: [item({ amount: 150 })] })))
    await waitFor(() => expect(view.getByRole("button", { name: "Send $150" })).toBeDisabled())
    expect(requests(state.fetch, "/approve")).toHaveLength(0)
  })

  it("never retries Send for an unknown attempt and reconciles only the original receipt", async () => {
    const state = show(batch({ status: "sending" }))
    const view = await card()
    expect(view.queryByRole("button", { name: /^Send/ })).not.toBeInTheDocument()
    expect(view.getByRole("heading", { name: "Awaiting reconciliation" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Queue all ready" })).toBeDisabled()
    await userEvent.type(view.getByRole("textbox", { name: "Original PayPal batch ID for batch 1" }), "PROVIDER-123")
    await userEvent.click(view.getByRole("button", { name: "Reconcile receipt" }))
    expect(requests(state.fetch, "/approve")).toHaveLength(0)
    expect(requests(state.fetch, "/reconcile")).toHaveLength(1)
    expect(JSON.parse(requests(state.fetch, "/reconcile")[0][1].body)).toEqual({ paypal_batch_id: "PROVIDER-123" })
  })

  it("holds a 400 unknown-send outcome until the fresh post-error read returns sending", async () => {
    let finish!: (response: unknown) => void
    const fresh = new Promise((resolve) => { finish = resolve })
    const state = show(batch(), true, async () => {
      state.setRead(async () => fresh)
      return { ok: false, status: 400, json: async () => ({ error: "Original outcome unknown" }) }
    })
    const view = await card()
    await userEvent.type(view.getByRole("textbox", { name: /Confirm PayPal total/ }), "100")
    await userEvent.click(view.getByRole("button", { name: "Send $100" }))
    await waitFor(() => expect(view.getByRole("heading", { name: "Awaiting reconciliation" })).toBeInTheDocument())
    expect(view.queryByRole("button", { name: /^Send/ })).not.toBeInTheDocument()
    await act(async () => { finish({ ok: true, status: 200, json: async () => ({ batches: [batch({ status: "sending" })], paypal: { connected: true, env: "live" } }) }); await fresh })
    expect(view.queryByRole("button", { name: /^Send/ })).not.toBeInTheDocument()
    expect(requests(state.fetch, "/approve")).toHaveLength(1)
  })

  it("recovers a refused OAuth preflight only after a fresh successful read proves draft", async () => {
    const state = show(batch(), true, async () => ({ ok: false, status: 502, json: async () => ({ error: "OAuth preflight unavailable" }) }))
    const view = await card()
    await userEvent.type(view.getByRole("textbox", { name: /Confirm PayPal total/ }), "100")
    await userEvent.click(view.getByRole("button", { name: "Send $100" }))
    await waitFor(() => expect(requests(state.fetch, "/api/payouts/admin/batches")).toHaveLength(2))
    await waitFor(() => expect(view.getByRole("button", { name: "Send $100" })).toBeEnabled())
    expect(view.queryByRole("button", { name: "Reconcile receipt" })).not.toBeInTheDocument()
    expect(requests(state.fetch, "/approve")).toHaveLength(1)
  })

  it("keeps approval held when its proof read fails and offers only a GET retry", async () => {
    const state = show(batch(), true, async () => {
      state.setRead(async () => ({ ok: false, status: 503, json: async () => ({ error: "Proof read unavailable" }) }))
      throw new Error("Lost approval response")
    })
    const view = await card()
    await userEvent.type(view.getByRole("textbox", { name: /Confirm PayPal total/ }), "100")
    await userEvent.click(view.getByRole("button", { name: "Send $100" }))
    expect(await screen.findByRole("alert")).toHaveTextContent("Proof read unavailable")
    expect(screen.queryByRole("button", { name: /^Send/ })).not.toBeInTheDocument()
    state.setRead(async () => ({ ok: true, status: 200, json: async () => ({ batches: [batch({ status: "sending" })], paypal: { connected: true, env: "live" } }) }))
    await userEvent.click(screen.getByRole("button", { name: "Refresh batches" }))
    expect(await screen.findByRole("heading", { name: "Awaiting reconciliation" })).toBeInTheDocument()
    expect(requests(state.fetch, "/approve")).toHaveLength(1)
  })

  it("cancels an earlier in-flight read so it cannot provide stale draft proof after a send error", async () => {
    let finishOld!: (response: unknown) => void
    const oldRead = new Promise((resolve) => { finishOld = resolve })
    let oldSignal: AbortSignal | undefined
    const state = show(batch(), true, async () => {
      state.setRead(async () => ({ ok: true, status: 200, json: async () => ({ batches: [batch({ status: "sending" })], paypal: { connected: true, env: "live" } }) }))
      return { ok: false, status: 400, json: async () => ({ error: "Original outcome unknown" }) }
    })
    const view = await card()
    state.setRead(async (init) => { oldSignal = init?.signal as AbortSignal; return oldRead })
    void state.client.refetchQueries({ queryKey: [...PREFIX, "batches"], exact: true })
    await waitFor(() => expect(oldSignal).toBeDefined())
    await userEvent.type(view.getByRole("textbox", { name: /Confirm PayPal total/ }), "100")
    await userEvent.click(view.getByRole("button", { name: "Send $100" }))
    await waitFor(() => expect(oldSignal?.aborted).toBe(true))
    await act(async () => { finishOld({ ok: true, status: 200, json: async () => ({ batches: [batch()], paypal: { connected: true, env: "live" } }) }); await oldRead })
    await waitFor(() => expect(state.client.getQueryData<BatchesResponse>([...PREFIX, "batches"])?.batches[0].status).toBe("sending"))
    expect(screen.queryByRole("button", { name: /^Send/ })).not.toBeInTheDocument()
    expect(requests(state.fetch, "/approve")).toHaveLength(1)
  })

  it("allows receipt refresh for a closed settled batch without automatically contacting the provider", async () => {
    const state = show(batch({ status: "closed", paypal_batch_id: "PROVIDER-OLD", items: [item({ status: "succeeded" })] }))
    await openHistory()
    const view = await card()
    expect(requests(state.fetch, "/sync")).toHaveLength(0)
    await userEvent.click(view.getByRole("button", { name: "Refresh status" }))
    expect(requests(state.fetch, "/sync")).toHaveLength(1)
    expect(requests(state.fetch, "/approve")).toHaveLength(0)
  })

  it("can clear a draft after its last item was removed", async () => {
    const state = show(batch({ items: [], totals: { api: 0, manual: 0, all: 0 } }))
    const view = await card()
    expect(view.queryByRole("button", { name: /^Send/ })).not.toBeInTheDocument()
    await userEvent.click(view.getByRole("button", { name: "Clear batch" }))
    expect(requests(state.fetch, "/cancel")).toHaveLength(1)
  })

  it("does not refresh or announce late mutation results after the payout session ends", async () => {
    let finish!: (value: unknown) => void
    const pending = new Promise((resolve) => { finish = resolve })
    const state = show(batch(), true, async () => pending)
    const view = await card()
    await userEvent.type(view.getByRole("textbox", { name: /Confirm PayPal total/ }), "100")
    await userEvent.click(view.getByRole("button", { name: "Send $100" }))
    state.stop()
    await act(async () => { finish(batch({ status: "sent" })); await pending })
    expect(state.invalidate).not.toHaveBeenCalled()
    expect(state.fetch.mock.calls.filter(([url]) => url.endsWith("/api/payouts/admin/batches"))).toHaveLength(1)
    expect(toast.success).not.toHaveBeenCalled()
  })

  it("blocks a queued mutation after Lock even if its cache entry was removed", async () => {
    let release!: () => void
    const gate = new Promise<void>((resolve) => { release = resolve })
    const state = show(batch(), true, undefined, async () => gate)
    const view = await card()
    await userEvent.type(view.getByRole("textbox", { name: /Confirm PayPal total/ }), "100")
    await userEvent.click(view.getByRole("button", { name: "Send $100" }))
    await waitFor(() => expect(state.client.getMutationCache().getAll()).toHaveLength(1))
    const mutation = state.client.getMutationCache().getAll()[0]
    state.stop()
    state.client.getMutationCache().remove(mutation)
    state.unmount()
    await act(async () => { release(); await gate })
    await waitFor(() => expect(mutation.state.status).toBe("error"))
    expect(requests(state.fetch, "/approve")).toHaveLength(0)
    expect(state.client.getMutationCache().getAll()).toHaveLength(0)
    expect(toast.success).not.toHaveBeenCalled()
  })

  it("hides approval controls when a cached batch read fails", async () => {
    const state = show(batch())
    await card()
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ error: "Batch read unavailable" }) }))
    await act(async () => { await state.client.invalidateQueries({ queryKey: PREFIX }) })
    expect(await screen.findByRole("alert")).toHaveTextContent("Batch read unavailable")
    expect(screen.queryByRole("button", { name: /^Send/ })).not.toBeInTheDocument()
  })
})

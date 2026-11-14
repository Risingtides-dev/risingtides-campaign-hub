import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import Payouts from "./Payouts"
import { PayoutLinkGenerator } from "@/components/payouts/PayoutLinkGenerator"
import { PayoutSessionProvider } from "@/lib/payoutSession"
import type { PayoutAdminOverview } from "@/lib/payouts"
import { StrictMode } from "react"

const mocks = vi.hoisted(() => ({
  overview: vi.fn(), events: vi.fn(), links: vi.fn(), rotate: vi.fn(), clearFlag: vi.fn(),
  success: vi.fn(), error: vi.fn(), clipboard: vi.fn(),
}))
vi.mock("sonner", () => ({ toast: { success: mocks.success, error: mocks.error } }))
vi.mock("@/lib/payouts", async (importOriginal) => ({
  ...await importOriginal<typeof import("@/lib/payouts")>(),
  payoutAdmin: { overview: mocks.overview, events: mocks.events, links: mocks.links, rotate: mocks.rotate, clearFlag: mocks.clearFlag },
}))
vi.mock("@/components/payouts/PayoutBatches", () => ({ PayoutBatches: () => <p>Batch controls</p> }))
vi.mock("@/components/payouts/CampaignPayouts", () => ({ CampaignPayouts: () => <p>Campaign controls</p> }))

const KEY = "test-only-payout-key"
const LINK = "https://example.test/payout#synthetic-test-link"
const overview: PayoutAdminOverview = {
  creators: [{ username: "alice", handle: "alice", method: "paypal", destination: "alice@example.test", confirmed: true, flagged: true, has_link: true, updated_at: "2026-11-01T00:00:00" }],
  summary: { total: 1, confirmed: 1, unconfirmed_on_file: 0, missing: 0, flagged: 1, links_issued: 1 },
}
const linkResult = { links: [{ username: "alice", handle: "alice", link: LINK, newly_issued: true, has_destination: true }], skipped: [] }

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((yes) => { resolve = yes })
  return { promise, resolve }
}

let clients: QueryClient[] = []
function client() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 5 * 60_000, refetchOnMount: false, refetchOnWindowFocus: false } } })
  clients.push(queryClient)
  return queryClient
}
function renderPayouts(queryClient = client()) {
  render(<QueryClientProvider client={queryClient}><Payouts /></QueryClientProvider>)
  return queryClient
}
function unlock() {
  fireEvent.change(screen.getByLabelText("Payout admin key"), { target: { value: KEY } })
  fireEvent.click(screen.getByRole("button", { name: "Unlock" }))
}
async function paymentInfo() {
  await screen.findByText("Batch controls")
  fireEvent.click(screen.getByRole("button", { name: /^Payment info/ }))
  await screen.findByText("alice@example.test")
}

describe("Payout admin session ownership", () => {
  beforeEach(() => {
    onlineManager.setOnline(true)
    vi.clearAllMocks()
    sessionStorage.clear()
    mocks.overview.mockResolvedValue(overview)
    mocks.events.mockResolvedValue({ events: [] })
    mocks.links.mockResolvedValue(linkResult)
    mocks.rotate.mockResolvedValue({ username: "alice", link: LINK })
    mocks.clearFlag.mockResolvedValue({ ok: true })
    mocks.clipboard.mockRejectedValue(new Error("Clipboard denied"))
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: mocks.clipboard } })
  })
  afterEach(() => {
    for (const queryClient of clients) queryClient.clear()
    clients = []
    onlineManager.setOnline(true)
    sessionStorage.clear()
  })

  it("reauthenticates the same key after lock and never exposes warm financial data on rejection", async () => {
    mocks.overview.mockResolvedValueOnce(overview).mockRejectedValue(new Error("Key revoked"))
    const queryClient = renderPayouts()
    unlock()
    await paymentInfo()
    const keys = queryClient.getQueryCache().getAll().map((query) => query.queryKey)
    expect(JSON.stringify(keys)).not.toContain(KEY)
    expect(keys.some((key) => key.includes("events"))).toBe(true)
    fireEvent.click(screen.getByRole("button", { name: "Lock" }))
    expect(screen.queryByText("alice@example.test")).not.toBeInTheDocument()
    unlock()
    expect(await screen.findByRole("alert")).toHaveTextContent("Key revoked")
    expect(mocks.overview).toHaveBeenCalledTimes(2)
    expect(screen.queryByText("Batch controls")).not.toBeInTheDocument()
    expect(screen.queryByText("alice@example.test")).not.toBeInTheDocument()
    expect(queryClient.getQueryCache().findAll({ queryKey: ["payouts"] }).every((query) => query.state.data === undefined)).toBe(true)
  })

  it("verifies remembered credentials through a fresh opaque session before mounting finance controls", async () => {
    const pending = deferred<PayoutAdminOverview>()
    mocks.overview.mockReturnValue(pending.promise)
    sessionStorage.setItem("rt.payoutAdminKey", KEY)
    renderPayouts()
    expect(screen.getByText("Checking access…")).toBeInTheDocument()
    expect(screen.queryByText("Batch controls")).not.toBeInTheDocument()
    await act(async () => pending.resolve(overview))
    expect(await screen.findByText("Batch controls")).toBeInTheDocument()
    expect(mocks.overview).toHaveBeenCalledWith(KEY)
  })

  it("finishes access verification under the app's StrictMode lifecycle", async () => {
    sessionStorage.setItem("rt.payoutAdminKey", KEY)
    const queryClient = client()
    render(<StrictMode><QueryClientProvider client={queryClient}><Payouts /></QueryClientProvider></StrictMode>)
    expect(await screen.findByText("Batch controls")).toBeInTheDocument()
    expect(screen.queryByText("Checking access…")).not.toBeInTheDocument()
  })

  it("cancels and removes a locked session's query without allowing a late reply to resurrect it", async () => {
    const pending = deferred<PayoutAdminOverview>()
    mocks.overview.mockReturnValue(pending.promise)
    const queryClient = renderPayouts()
    unlock()
    await waitFor(() => expect(mocks.overview).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole("button", { name: "Lock" }))
    await act(async () => pending.resolve(overview))
    expect(screen.getByLabelText("Payout admin key")).toBeInTheDocument()
    expect(screen.queryByText("Batch controls")).not.toBeInTheDocument()
    expect(queryClient.getQueryCache().findAll({ queryKey: ["payouts"] }).every((query) => query.state.data === undefined)).toBe(true)
  })

  it("retains a rotated link for manual copying when clipboard access fails without rotating twice", async () => {
    renderPayouts()
    unlock()
    await paymentInfo()
    fireEvent.click(screen.getByRole("button", { name: "New link (kill old)" }))
    expect(await screen.findByLabelText("New payment-info link for @alice")).toHaveValue(LINK)
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(expect.stringContaining("Clipboard unavailable")))
    expect(mocks.success).not.toHaveBeenCalledWith(expect.stringContaining("copied"))
    expect(mocks.rotate).toHaveBeenCalledTimes(1)
    fireEvent.focus(screen.getByLabelText("New payment-info link for @alice"))
    expect(mocks.rotate).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole("button", { name: "Lock" }))
    expect(screen.queryByDisplayValue(LINK)).not.toBeInTheDocument()
  })

  it("discards a rotation response arriving after lock, including its mutation-cache result", async () => {
    const pending = deferred<{ username: string; link: string }>()
    mocks.rotate.mockReturnValue(pending.promise)
    const queryClient = renderPayouts()
    unlock()
    await paymentInfo()
    fireEvent.click(screen.getByRole("button", { name: "New link (kill old)" }))
    await waitFor(() => expect(mocks.rotate).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole("button", { name: "Lock" }))
    await act(async () => pending.resolve({ username: "alice", link: LINK }))
    expect(screen.queryByDisplayValue(LINK)).not.toBeInTheDocument()
    expect(mocks.clipboard).not.toHaveBeenCalled()
    expect(mocks.success).not.toHaveBeenCalled()
    expect(JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.state.data))).not.toContain(LINK)
  })

  it("removes issued links and suppresses late issuance results after lock", async () => {
    const pending = deferred<typeof linkResult>()
    mocks.links.mockReturnValue(pending.promise)
    const queryClient = renderPayouts()
    unlock()
    await paymentInfo()
    fireEvent.change(screen.getByLabelText("Creator handles"), { target: { value: "@alice" } })
    fireEvent.click(screen.getByRole("button", { name: "Get 1 link" }))
    await waitFor(() => expect(mocks.links).toHaveBeenCalledTimes(1))
    fireEvent.click(screen.getByRole("button", { name: "Lock" }))
    await act(async () => pending.resolve(linkResult))
    expect(screen.queryByRole("button", { name: "Copy link" })).not.toBeInTheDocument()
    expect(JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.state.data))).not.toContain(LINK)
  })

  it("never dispatches offline-paused link issuance after locking", async () => {
    const queryClient = renderPayouts()
    unlock()
    await paymentInfo()
    onlineManager.setOnline(false)
    fireEvent.change(screen.getByLabelText("Creator handles"), { target: { value: "@alice" } })
    fireEvent.click(screen.getByRole("button", { name: "Get 1 link" }))
    await waitFor(() => expect(queryClient.getMutationCache().getAll().some((mutation) => mutation.state.isPaused)).toBe(true))
    fireEvent.click(screen.getByRole("button", { name: "Lock" }))
    await act(async () => { onlineManager.setOnline(true); await queryClient.resumePausedMutations() })
    expect(mocks.links).not.toHaveBeenCalled()
    expect(screen.getByLabelText("Payout admin key")).toBeInTheDocument()
  })

  it("checks session ownership at dispatch when an offline-paused generator was unmounted", async () => {
    const queryClient = renderPayouts()
    unlock()
    await paymentInfo()
    onlineManager.setOnline(false)
    fireEvent.change(screen.getByLabelText("Creator handles"), { target: { value: "@alice" } })
    fireEvent.click(screen.getByRole("button", { name: "Get 1 link" }))
    await waitFor(() => expect(queryClient.getMutationCache().getAll().some((mutation) => mutation.state.isPaused)).toBe(true))
    const paused = queryClient.getMutationCache().getAll().find((mutation) => mutation.state.isPaused)!
    fireEvent.click(screen.getByRole("button", { name: "Pay creators" }))
    await act(async () => { onlineManager.setOnline(true); await queryClient.resumePausedMutations() })
    await waitFor(() => expect(paused.state.status).toBe("error"))
    expect(mocks.links).not.toHaveBeenCalled()
  })

  it("blocks dispatch after lock even when deferred mutation setup resumes after cache removal", async () => {
    const gate = deferred<void>()
    const onMutate = vi.fn(() => gate.promise)
    const queryClient = client()
    queryClient.setMutationDefaults(["payouts"], { onMutate })
    renderPayouts(queryClient)
    unlock()
    await paymentInfo()
    fireEvent.change(screen.getByLabelText("Creator handles"), { target: { value: "@alice" } })
    fireEvent.click(screen.getByRole("button", { name: "Get 1 link" }))
    await waitFor(() => expect(onMutate).toHaveBeenCalledTimes(1))
    const mutation = queryClient.getMutationCache().getAll().find((item) => item.state.status === "pending")!
    expect(mocks.links).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole("button", { name: "Lock" }))
    expect(queryClient.getMutationCache().getAll()).toHaveLength(0)
    await act(async () => gate.resolve(undefined))
    await waitFor(() => expect(mutation.state.status).toBe("error"))
    expect(mocks.links).not.toHaveBeenCalled()
    expect(screen.getByLabelText("Payout admin key")).toBeInTheDocument()
  })

  it("offers the actual link and DM text for manual copy without issuing another link", async () => {
    const queryClient = client()
    render(<QueryClientProvider client={queryClient}><PayoutSessionProvider sessionId="synthetic-session">
      <PayoutLinkGenerator adminKey={KEY} onIssued={vi.fn()} />
    </PayoutSessionProvider></QueryClientProvider>)
    fireEvent.change(screen.getByLabelText("Creator handles"), { target: { value: "@alice" } })
    fireEvent.click(screen.getByRole("button", { name: "Get 1 link" }))
    fireEvent.click(await screen.findByRole("button", { name: "Copy link" }))
    expect(await screen.findByLabelText("Link to copy manually")).toHaveValue(LINK)
    fireEvent.click(screen.getByRole("button", { name: "Copy DM" }))
    await waitFor(() => expect((screen.getByLabelText("DM to copy manually") as HTMLTextAreaElement).value).toContain(LINK))
    expect(mocks.links).toHaveBeenCalledTimes(1)
    expect(mocks.success).not.toHaveBeenCalled()
    expect(JSON.stringify(queryClient.getMutationCache().getAll().map((mutation) => mutation.options.mutationKey))).not.toContain(KEY)
  })
})

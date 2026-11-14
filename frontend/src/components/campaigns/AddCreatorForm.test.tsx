import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"
import { AddCreatorForm } from "./AddCreatorForm"

const api = vi.hoisted(() => ({ getCreatorIntel: vi.fn(), getLastRate: vi.fn(), getPaypal: vi.fn() }))
vi.mock("@/lib/api", () => ({ api }))
vi.mock("@/components/CreatorAutocomplete", () => ({
  CreatorAutocomplete: ({ value, onChange, onBlur, onSelect }: {
    value: string; onChange: (value: string) => void; onBlur: () => void; onSelect: (value: string) => void
  }) => <>
    <input aria-label="Username" value={value} onChange={(event) => onChange(event.target.value)} onBlur={onBlur} />
    <button type="button" onClick={() => { onChange("@Bob"); onSelect("@Bob") }}>Select Bob</button>
  </>,
}))
vi.mock("@/components/ui/select", () => ({
  Select: ({ value, onValueChange, children }: { value: string; onValueChange: (value: string) => void; children: ReactNode }) =>
    <select aria-label="Platform" value={value} onChange={(event) => onValueChange(event.target.value)}>{children}</select>,
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => <option value={value}>{children}</option>,
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const breaker = { posts: 30, avg_views: 100_000, viral_rate: 10, score_balanced: 60 }
const cold = { posts: 30, avg_views: 100, viral_rate: 0, score_balanced: 2 }
const quote = (total_rate = 250, posts_owed = 2, platform: string | undefined = "tiktok") => ({
  last_rate: { total_rate, posts_owed, platform, campaign: "Previous campaign", added_date: "2026-11-01" },
})

function typeName(value: string, blur = true) {
  const input = screen.getByRole("textbox", { name: "Username" })
  fireEvent.change(input, { target: { value } })
  if (blur) fireEvent.blur(input)
}

describe("AddCreatorForm analysis and lookup ownership", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getCreatorIntel.mockResolvedValue(breaker)
    api.getLastRate.mockResolvedValue({ last_rate: null })
    api.getPaypal.mockResolvedValue({ paypal: "" })
  })

  it.each([
    [404, "No tracked TikTok history."],
    [503, "Creator analysis unavailable."],
    [undefined, "Creator analysis unavailable."],
  ])("distinguishes a %s lookup outcome without blocking manual booking", async (status, message) => {
    api.getCreatorIntel.mockRejectedValue(Object.assign(new Error("Lookup failed"), { status }))
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName("@Alice")
    expect(await screen.findByText(message)).toBeInTheDocument()
    if (status !== 404) expect(screen.queryByText("No tracked TikTok history.")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled()
  })

  it("invalidates all pending evidence as soon as the typed identity changes", async () => {
    const intel = deferred<typeof cold>()
    const rate = deferred<ReturnType<typeof quote>>()
    const paypal = deferred<{ paypal: string }>()
    api.getCreatorIntel.mockReturnValue(intel.promise)
    api.getLastRate.mockReturnValue(rate.promise)
    api.getPaypal.mockReturnValue(paypal.promise)
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName("Alice")
    typeName("Bob", false) // no blur and no second lookup yet
    await act(async () => { intel.resolve(cold); rate.resolve(quote(900)); paypal.resolve({ paypal: "alice@example.test" }) })
    expect(api.getCreatorIntel).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Last booked/)).not.toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Price ($)" })).toHaveValue(100)
    expect(screen.getByRole("textbox", { name: "PayPal" })).toHaveValue("")
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled()
  })

  it("preserves the existing cold-history override and clears it when identity changes", async () => {
    api.getCreatorIntel.mockResolvedValue(cold)
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName("Alice")
    expect(await screen.findByText("Cold history:")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled()
    fireEvent.click(screen.getByRole("checkbox", { name: "Book anyway" }))
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled()
    typeName("Bob", false)
    expect(screen.queryByRole("checkbox", { name: "Book anyway" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled()
  })

  it("autocomplete selection owns the new responses and suppresses the earlier handle", async () => {
    const old = deferred<typeof cold>()
    api.getCreatorIntel.mockImplementation((name: string) => name === "alice" ? old.promise : Promise.resolve(breaker))
    api.getLastRate.mockImplementation((name: string) => Promise.resolve(name === "bob" ? quote() : { last_rate: null }))
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName("Alice")
    fireEvent.click(screen.getByRole("button", { name: "Select Bob" }))
    expect(await screen.findByText(/Proven breaker/)).toBeInTheDocument()
    await act(async () => old.resolve(cold))
    expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Price ($)" })).toHaveValue(250)
    expect(api.getLastRate).toHaveBeenLastCalledWith("bob", "tiktok")
  })

  it("does not revive an earlier request after editing away and back to the same handle", async () => {
    const old = deferred<typeof cold>()
    const fresh = deferred<typeof breaker>()
    api.getCreatorIntel.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise)
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName("Alice")
    typeName("Bob", false)
    typeName("ALICE")
    await act(async () => old.resolve(cold))
    expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
    await act(async () => fresh.resolve(breaker))
    expect(screen.getByText(/Proven breaker/)).toBeInTheDocument()
  })

  it("skips TikTok analysis for Instagram and ignores old platform responses", async () => {
    const intel = deferred<typeof cold>()
    const rate = deferred<ReturnType<typeof quote>>()
    api.getCreatorIntel.mockReturnValue(intel.promise)
    api.getLastRate.mockImplementation((_name: string, platform: string) => platform === "tiktok" ? rate.promise : Promise.resolve(quote(900, 3, "instagram")))
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName(" @ALICE/ ")
    fireEvent.change(screen.getByRole("combobox", { name: "Platform" }), { target: { value: "instagram" } })
    await waitFor(() => expect(screen.getByRole("spinbutton", { name: "Price ($)" })).toHaveValue(900))
    await act(async () => { intel.resolve(cold); rate.resolve(quote(50)) })
    expect(api.getCreatorIntel).toHaveBeenCalledTimes(1)
    expect(api.getLastRate).toHaveBeenLastCalledWith("alice", "instagram")
    expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Proven breaker/)).not.toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Price ($)" })).toHaveValue(900)
    expect(screen.getByRole("spinbutton", { name: "Posts Owed" })).toHaveValue(3)
  })

  it("preserves manually typed rate, posts and PayPal when matching responses arrive", async () => {
    const rate = deferred<ReturnType<typeof quote>>()
    const paypal = deferred<{ paypal: string }>()
    api.getLastRate.mockReturnValue(rate.promise)
    api.getPaypal.mockReturnValue(paypal.promise)
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName("Alice")
    fireEvent.change(screen.getByRole("spinbutton", { name: "Price ($)" }), { target: { value: "777" } })
    fireEvent.change(screen.getByRole("spinbutton", { name: "Posts Owed" }), { target: { value: "9" } })
    fireEvent.change(screen.getByRole("textbox", { name: "PayPal" }), { target: { value: "manual@example.test" } })
    await act(async () => { rate.resolve(quote()); paypal.resolve({ paypal: "lookup@example.test" }) })
    expect(screen.getByRole("spinbutton", { name: "Price ($)" })).toHaveValue(777)
    expect(screen.getByRole("spinbutton", { name: "Posts Owed" })).toHaveValue(9)
    expect(screen.getByRole("textbox", { name: "PayPal" })).toHaveValue("manual@example.test")
  })

  it("invalidates pending lookups on submission and reset", async () => {
    const intel = deferred<typeof cold>()
    const rate = deferred<ReturnType<typeof quote>>()
    const paypal = deferred<{ paypal: string }>()
    api.getCreatorIntel.mockReturnValue(intel.promise)
    api.getLastRate.mockReturnValue(rate.promise)
    api.getPaypal.mockReturnValue(paypal.promise)
    const onAdd = vi.fn()
    render(<AddCreatorForm onAdd={onAdd} isPending={false} />)
    typeName("Alice")
    fireEvent.click(screen.getByRole("button", { name: "Add" }))
    expect(onAdd).toHaveBeenCalledWith({ username: "alice", posts_owed: 5, total_rate: 100, paypal_email: "", platform: "tiktok" })
    await act(async () => { intel.resolve(cold); rate.resolve(quote()); paypal.resolve({ paypal: "lookup@example.test" }) })
    expect(screen.getByRole("textbox", { name: "Username" })).toHaveValue("")
    expect(screen.getByRole("spinbutton", { name: "Price ($)" })).toHaveValue(100)
    expect(screen.getByRole("textbox", { name: "PayPal" })).toHaveValue("")
    expect(screen.queryByText(/Cold history/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Last booked/)).not.toBeInTheDocument()
  })

  it.each(["instagram", ""])("refuses rate evidence from the wrong or unknown platform (%s)", async (platform) => {
    api.getLastRate.mockResolvedValue(quote(900, 3, platform))
    render(<AddCreatorForm onAdd={vi.fn()} isPending={false} />)
    typeName("Alice")
    expect(await screen.findByText("Rate history unavailable.")).toBeInTheDocument()
    expect(screen.getByRole("spinbutton", { name: "Price ($)" })).toHaveValue(100)
    expect(screen.getByRole("button", { name: "Add" })).toBeEnabled()
  })
})

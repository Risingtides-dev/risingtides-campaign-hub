import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import CreatorDashboard from "./CreatorDashboard"
import { parseHandles } from "@/lib/payouts"
import type { CreatorDashboardData } from "@/lib/payouts"

const TOKEN = "A".repeat(43)

function dashboard(overrides: Partial<CreatorDashboardData> = {}): CreatorDashboardData {
  return {
    creator: { handle: "alice", method: "", destination_masked: "", confirmed: false },
    current: [
      {
        campaign: "Mattilo - Beautiful Life",
        artist: "Mattilo",
        song: "Beautiful Life",
        start_date: "2026-10-20",
        platforms: ["tiktok"],
        sounds: [
          { platform: "tiktok", url: "https://www.tiktok.com/music/x-1" },
          { platform: "tiktok", url: "javascript:alert(1)" },
        ],
        brief: "Open creative",
        open_creative: true,
        captions: ["pov: you found the song"],
        posts_owed: 3,
        posts_done: 1,
        rate: 150,
        status: "in_progress",
        active: true,
      },
    ],
    payments: [{ campaign: "Old - Song", amount: 80, date: "2026-08-20", platform: "tiktok" }],
    totals: { paid: 80, campaigns: 2 },
    ...overrides,
  }
}

function mockFetch(responses: Array<{ status: number; body: unknown }>) {
  const fn = vi.fn()
  for (const r of responses) {
    fn.mockResolvedValueOnce({ ok: r.status < 400, status: r.status, json: async () => r.body })
  }
  vi.stubGlobal("fetch", fn)
  return fn
}

describe("CreatorDashboard", () => {
  beforeEach(() => {
    window.location.hash = ""
  })

  it("shows an invalid-link message and calls nothing without a token", () => {
    const fetchFn = mockFetch([])
    render(<CreatorDashboard />)
    expect(screen.getByRole("alert")).toHaveTextContent(/isn't valid/)
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it("renders bookings, brief, captions, progress and payment history", async () => {
    window.location.hash = `#${TOKEN}`
    mockFetch([{ status: 200, body: dashboard() }])
    render(<CreatorDashboard />)
    expect(await screen.findByText(/Hey @alice/)).toBeInTheDocument()
    expect(screen.getByText("Mattilo - Beautiful Life")).toBeInTheDocument()
    expect(screen.getByText("Open creative")).toBeInTheDocument()
    expect(screen.getByText("pov: you found the song")).toBeInTheDocument()
    expect(screen.getByText("1 / 3 posted")).toBeInTheDocument()
    expect(screen.getByText("$80 paid")).toBeInTheDocument()
    expect(screen.getByText(/Add your payment details/)).toBeInTheDocument()

    const soundLinks = screen.getAllByRole("link", { name: /Use this sound/ })
    expect(soundLinks).toHaveLength(1) // the javascript: URL is never rendered
    expect(soundLinks[0]).toHaveAttribute("href", "https://www.tiktok.com/music/x-1")
    expect(soundLinks[0]).toHaveAttribute("rel", "noopener noreferrer")
  })

  it("saves payment details with the token in the body, never the URL", async () => {
    window.location.hash = `#${TOKEN}`
    const fetchFn = mockFetch([
      { status: 200, body: dashboard() },
      {
        status: 200,
        body: { ok: true, result: "created", handle: "alice", method: "paypal",
                destination_masked: "al•••@gmail.com", confirmed: true },
      },
    ])
    render(<CreatorDashboard />)
    await screen.findByText(/Hey @alice/)
    await userEvent.type(screen.getByPlaceholderText("you@email.com"), "alice@gmail.com")
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }))

    expect(await screen.findByText("al•••@gmail.com")).toBeInTheDocument()
    expect(screen.queryByText(/Add your payment details/)).not.toBeInTheDocument()
    for (const [url, init] of fetchFn.mock.calls) {
      expect(url).not.toContain(TOKEN)
      expect(JSON.parse(init.body).token).toBe(TOKEN)
    }
    expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({
      token: TOKEN, method: "paypal", destination: "alice@gmail.com",
    })
  })

  it("shows the server's validation error and keeps the form open", async () => {
    window.location.hash = `#${TOKEN}`
    mockFetch([
      { status: 200, body: dashboard() },
      { status: 400, body: { error: "Cash App tags are 1–20 letters or numbers, like $yourname." } },
    ])
    render(<CreatorDashboard />)
    await screen.findByText(/Hey @alice/)
    await userEvent.click(screen.getByText("Cash App"))
    await userEvent.type(screen.getByPlaceholderText("$yourcashtag"), "$$$")
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }))
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Cash App tags/))
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument()
  })

  it("shows the server's message when the token is unknown", async () => {
    window.location.hash = `#${TOKEN}`
    mockFetch([{ status: 404, body: { error: "This link isn't valid anymore." } }])
    render(<CreatorDashboard />)
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/isn't valid anymore/))
  })
})

describe("parseHandles", () => {
  it("splits, strips @ and de-duplicates case-insensitively", () => {
    expect(parseHandles("@Alice, bob\n@alice  carol,")).toEqual(["Alice", "bob", "carol"])
  })
})

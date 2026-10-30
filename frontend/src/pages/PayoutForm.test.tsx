import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import PayoutForm from "./PayoutForm"
import { parseHandles } from "@/lib/payouts"

const TOKEN = "A".repeat(43)

function mockFetch(responses: Array<{ status: number; body: unknown }>) {
  const fn = vi.fn()
  for (const r of responses) {
    fn.mockResolvedValueOnce({
      ok: r.status < 400,
      status: r.status,
      json: async () => r.body,
    })
  }
  vi.stubGlobal("fetch", fn)
  return fn
}

describe("PayoutForm (public creator page)", () => {
  beforeEach(() => {
    window.location.hash = ""
  })

  it("shows an invalid-link message and calls nothing without a token", () => {
    const fetchFn = mockFetch([])
    render(<PayoutForm />)
    expect(screen.getByRole("alert")).toHaveTextContent(/isn't valid/)
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it("sends the token in the body, never the URL, and saves details", async () => {
    window.location.hash = `#${TOKEN}`
    const fetchFn = mockFetch([
      { status: 200, body: { handle: "alice", method: "", destination_masked: "", confirmed: false } },
      {
        status: 200,
        body: { ok: true, result: "created", handle: "alice", method: "paypal",
                destination_masked: "al•••@gmail.com", confirmed: true },
      },
    ])
    render(<PayoutForm />)
    expect(await screen.findByText(/Hey @alice/)).toBeInTheDocument()

    await userEvent.type(screen.getByPlaceholderText("you@email.com"), "alice@gmail.com")
    await userEvent.click(screen.getByRole("button", { name: "Confirm" }))

    expect(await screen.findByText(/You're all set/)).toBeInTheDocument()
    for (const [url, init] of fetchFn.mock.calls) {
      expect(url).not.toContain(TOKEN)
      expect(JSON.parse(init.body).token).toBe(TOKEN)
    }
    expect(JSON.parse(fetchFn.mock.calls[1][1].body)).toEqual({
      token: TOKEN, method: "paypal", destination: "alice@gmail.com",
    })
  })

  it("shows the server's validation error and stays on the form", async () => {
    window.location.hash = `#${TOKEN}`
    mockFetch([
      { status: 200, body: { handle: "alice", method: "", destination_masked: "", confirmed: false } },
      { status: 400, body: { error: "Cash App tags are 1–20 letters or numbers, like $yourname." } },
    ])
    render(<PayoutForm />)
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
    render(<PayoutForm />)
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/isn't valid anymore/))
  })
})

describe("parseHandles", () => {
  it("splits, strips @ and de-duplicates case-insensitively", () => {
    expect(parseHandles("@Alice, bob\n@alice  carol,")).toEqual(["Alice", "bob", "carol"])
  })
})

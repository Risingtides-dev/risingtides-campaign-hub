import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import { PaymentQueue } from "../PaymentQueue"
import type { PaymentQueue as Queue, QueueRow } from "@/lib/payouts"

const base: QueueRow = {
  slug: "live", campaign: "Live", username: "newbie", handle: "newbie", platform: "tiktok",
  amount: 150, posts_owed: 3, posts_done: 3, reason: "posts_complete", trusted: false,
  trust_override: "", delivered_campaigns: 1, method: "paypal", destination: "n@gmail.com", destination_issue: "",
}
const queue: Queue = {
  ready: [base],
  awaiting_confirmation: [{ ...base, username: "vet", handle: "vet", trusted: true, delivered_campaigns: 6,
                            reason: "trusted_unconfirmed", destination_issue: "changed", amount: 300 }],
  not_ready: [],
  totals: { ready_count: 1, ready_amount: 150, payable_now: 150, by_method: { paypal: 150 } },
  trusted_min_campaigns: 6,
}

describe("PaymentQueue", () => {
  it("lists ready and trusted bookings and confirms acceptance with the admin key", async () => {
    const fetchFn = vi.fn(async (url: string) => ({
      ok: true,
      status: 200,
      json: async () => (url.endsWith("/api/payouts/admin/queue") ? queue : { ok: true }),
    }))
    vi.stubGlobal("fetch", fetchFn)
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PaymentQueue adminKey={"k".repeat(32)} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText("@newbie")).toBeInTheDocument()
    expect(screen.getByText("Details changed — review first")).toBeInTheDocument()
    expect(screen.getByText(/1 bookings · \$150 payable now/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole("button", { name: /Accepted booking/ }))
    const markCall = fetchFn.mock.calls.find(([u]) => String(u).includes("/bookings/mark"))
    expect(markCall).toBeDefined()
    const [url, init] = markCall as unknown as [string, { headers: Record<string, string>; body: string }]
    expect(url).toContain("/api/payouts/admin/bookings/mark")
    expect(init.headers["X-Payout-Admin-Key"]).toBe("k".repeat(32))
    expect(JSON.parse(init.body)).toMatchObject({ slug: "live", username: "vet", platform: "tiktok", action: "confirm" })
  })
})

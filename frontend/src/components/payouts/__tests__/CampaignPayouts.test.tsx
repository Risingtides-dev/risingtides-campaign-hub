import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import type { Mock } from "vitest"
import { CampaignPayouts } from "../CampaignPayouts"
import type { PaymentQueue, QueueRow } from "@/lib/payouts"

const row = (o: Partial<QueueRow>): QueueRow => ({
  slug: "live", campaign: "Live Song", start_date: "2026-10-20", username: "u", handle: "u", platform: "tiktok",
  amount: 100, posts_owed: 2, posts_done: 2, reason: "posts_complete", trusted: false, trust_override: "",
  delivered_campaigns: 1, method: "paypal", destination: "u@gmail.com", destination_issue: "",
  booking_destination: "", payment: null, ...o,
})

const queue: PaymentQueue = {
  ready: [row({ username: "owed", handle: "owed" })],
  awaiting_confirmation: [
    row({ username: "vet", handle: "vet", trusted: true, reason: "trusted_unconfirmed", posts_done: 0 }),
  ],
  not_ready: [
    row({
      username: "posting", handle: "posting", reason: "posts_incomplete", posts_done: 1,
      method: "", destination: "", destination_issue: "missing", booking_destination: "old@gmail.com",
    }),
  ],
  in_batch: [
    row({
      username: "queued", handle: "queued",
      payment: { item_id: 9, item_status: "queued", batch_id: 1, batch_status: "draft" },
    }),
  ],
  totals: { ready_count: 1, ready_amount: 100, payable_now: 100, by_method: { paypal: 100 } },
  trusted_min_campaigns: 6,
}

function setup(): Mock {
  const fetchFn = vi.fn(async (url: string) => ({
    ok: true,
    status: 200,
    json: async () => (url.endsWith("/api/payouts/admin/queue") ? queue : { ok: true, items: [], totals: {} }),
  }))
  vi.stubGlobal("fetch", fetchFn)
  render(
    <QueryClientProvider client={new QueryClient()}>
      <CampaignPayouts adminKey={"k".repeat(32)} />
    </QueryClientProvider>,
  )
  return fetchFn
}

const bodies = (fn: Mock, part: string) =>
  fn.mock.calls
    .filter(([u]) => String(u).includes(part))
    .map(([, init]) => JSON.parse((init as { body: string }).body))

describe("CampaignPayouts", () => {
  it("groups creators under their campaign with clear status", async () => {
    setup()
    expect(await screen.findByText("Live Song")).toBeInTheDocument()
    expect(screen.getByText("All posts in — owed")).toBeInTheDocument()
    expect(screen.getByText("Not confirmed yet")).toBeInTheDocument()
    expect(screen.getByText("In today's payments")).toBeInTheDocument()
    expect(screen.queryByText("@posting")).not.toBeInTheDocument() // "Needs action" hides still-posting

    await userEvent.click(screen.getByRole("button", { name: "Still posting" }))
    expect(screen.getByText("@posting")).toBeInTheDocument()
    expect(screen.getByText("old@gmail.com")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Use this" })).toBeInTheDocument()
  })

  it("Pay adds one booking; Confirm & pay confirms then adds", async () => {
    const fetchFn = setup()
    await screen.findByText("Live Song")
    await userEvent.click(screen.getByRole("button", { name: "Pay $100" }))
    expect(bodies(fetchFn, "/batches/add-booking")[0]).toEqual({ slug: "live", username: "owed", platform: "tiktok" })

    const vetRow = screen.getByText("@vet").closest("tr")!
    await userEvent.click(within(vetRow).getByRole("button", { name: "Confirm & pay" }))
    expect(bodies(fetchFn, "/bookings/mark").at(-1)).toMatchObject({ username: "vet", action: "confirm" })
    expect(bodies(fetchFn, "/batches/add-booking").at(-1)).toMatchObject({ username: "vet" })
  })
})

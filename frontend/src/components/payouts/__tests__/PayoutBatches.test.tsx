import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { describe, expect, it, vi } from "vitest"
import { PayoutBatches } from "../PayoutBatches"
import type { BatchItem, BatchesResponse, PayoutBatch } from "@/lib/payouts"

const BASE_ITEM: BatchItem = {
  id: 1, campaign: "Live Song", campaign_id: 1, username: "u", platform: "tiktok",
  amount: 100, method: "paypal", destination: "u@g.com", lane: "api",
  status: "queued", provider_status: "", error: "", paid_at: "",
}

const BASE_BATCH: PayoutBatch = {
  id: 1, status: "closed", paypal_env: "live",
  created_at: "2026-10-01T10:00:00", approved_at: "2026-10-01T10:00:00",
  last_synced_at: "", error: "",
  items: [], totals: { api: 0, manual: 0, all: 0 },
}

const LIVE_PAYPAL = { connected: true, env: "live" }
const SANDBOX_PAYPAL = { connected: true, env: "sandbox" }
const NO_PAYPAL = { connected: false, env: "" }

async function setup(resp: BatchesResponse) {
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok: true, status: 200, json: async () => resp,
  })))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <PayoutBatches adminKey={"k".repeat(32)} />
    </QueryClientProvider>,
  )
  // Expand "Past payments" if present so closed-batch cards are visible.
  const toggle = await screen.findByRole("button", { name: /Past payments/ }).catch(() => null)
  if (toggle) await userEvent.click(toggle)
}

function item(overrides: Partial<BatchItem>): BatchItem {
  return { ...BASE_ITEM, ...overrides }
}

describe("PayoutBatches — batch headline and amount", () => {
  it("fully paid closed batch shows Paid headline with paid amount", async () => {
    await setup({
      batches: [{ ...BASE_BATCH, items: [item({ status: "succeeded" })], totals: { api: 100, manual: 0, all: 100 } }],
      paypal: LIVE_PAYPAL,
    })
    // Headline must start with "Paid " and not be the item-status "Paid ✓"
    expect(screen.getByText((t) => t.startsWith("Paid ") && !t.includes("✓"))).toBeInTheDocument()
    // Amount in header: getAllByText because the item table also shows it
    expect(screen.getAllByText("$100").length).toBeGreaterThan(0)
  })

  it("closed batch where all items failed shows Failed headline and $0", async () => {
    await setup({
      batches: [{ ...BASE_BATCH, items: [item({ status: "failed", error: "Receiver ineligible" })], totals: { api: 100, manual: 0, all: 100 } }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.getByText(/Failed.*nothing paid/)).toBeInTheDocument()
    expect(screen.getByText("$0")).toBeInTheDocument()
    expect(screen.queryByText(/^Paid /)).not.toBeInTheDocument()
  })

  it("closed mixed batch shows Partial headline with paid amount only", async () => {
    await setup({
      batches: [{
        ...BASE_BATCH,
        items: [item({ id: 1, username: "a", status: "succeeded", amount: 100 }), item({ id: 2, username: "b", status: "failed", amount: 50, error: "Failed" })],
        totals: { api: 150, manual: 0, all: 150 },
      }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.getByText(/Partial.*1 failed/)).toBeInTheDocument()
    // The header shows $100 (paid amount), not $150 (batch total)
    expect(screen.getAllByText("$100").length).toBeGreaterThan(0)
    expect(screen.queryByText("$150")).not.toBeInTheDocument()
  })

  it("sandbox closed batch shows Sandbox test headline and $0", async () => {
    await setup({
      batches: [{
        ...BASE_BATCH, paypal_env: "sandbox",
        items: [item({ status: "sandbox_ok" })],
        totals: { api: 100, manual: 0, all: 100 },
      }],
      paypal: SANDBOX_PAYPAL,
    })
    expect(screen.getByText(/Sandbox test.*no real money/)).toBeInTheDocument()
    expect(screen.queryByText(/^Paid /)).not.toBeInTheDocument()
    expect(screen.getByText("$0")).toBeInTheDocument()
  })

  it("sending batch shows reconcile headline not Paid", async () => {
    await setup({
      batches: [{
        ...BASE_BATCH, status: "sending",
        items: [item({ status: "queued" })],
        totals: { api: 100, manual: 0, all: 100 },
      }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.getByText(/Sending.*reconcile/)).toBeInTheDocument()
    expect(screen.queryByText(/^Paid /)).not.toBeInTheDocument()
  })
})

describe("PayoutBatches — Send gate", () => {
  const draftBatch: PayoutBatch = {
    ...BASE_BATCH, status: "draft",
    items: [item({ status: "queued" })],
    totals: { api: 100, manual: 0, all: 100 },
  }

  it("Send disabled when PayPal not connected even with correct total typed", async () => {
    await setup({ batches: [draftBatch], paypal: NO_PAYPAL })
    await userEvent.type(screen.getByPlaceholderText("0.00"), "100.00")
    expect(screen.getByRole("button", { name: /Send/ })).toBeDisabled()
    expect(screen.getByText(/PayPal isn't connected/)).toBeInTheDocument()
  })

  it("Send disabled with wrong total even with connected PayPal", async () => {
    await setup({ batches: [draftBatch], paypal: LIVE_PAYPAL })
    await userEvent.type(screen.getByPlaceholderText("0.00"), "50.00")
    expect(screen.getByRole("button", { name: /Send/ })).toBeDisabled()
  })

  it("Send disabled with empty total field", async () => {
    await setup({ batches: [draftBatch], paypal: LIVE_PAYPAL })
    expect(screen.getByRole("button", { name: /Send/ })).toBeDisabled()
  })

  it("Send enabled only when connected PayPal and exact total typed", async () => {
    await setup({ batches: [draftBatch], paypal: LIVE_PAYPAL })
    await userEvent.type(screen.getByPlaceholderText("0.00"), "100.00")
    expect(screen.getByRole("button", { name: /Send/ })).toBeEnabled()
  })
})

describe("PayoutBatches — sending batch reconcile", () => {
  it("sending batch shows Refresh PayPal status not Send form", async () => {
    await setup({
      batches: [{
        ...BASE_BATCH, status: "sending",
        items: [item({ status: "queued" })],
        totals: { api: 100, manual: 0, all: 100 },
      }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.getByText(/Sending.*reconcile/)).toBeInTheDocument()
    expect(screen.queryByPlaceholderText("0.00")).not.toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Send/ })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Refresh PayPal status" })).toBeInTheDocument()
  })
})

describe("PayoutBatches — manual-only batch", () => {
  it("manual-only draft shows Start paying button, no Send form", async () => {
    await setup({
      batches: [{
        ...BASE_BATCH, status: "draft",
        items: [item({ lane: "manual", method: "cashapp", destination: "$ca", status: "queued" })],
        totals: { api: 0, manual: 50, all: 50 },
      }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.queryByPlaceholderText("0.00")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Start paying these by hand" })).toBeInTheDocument()
  })
})

describe("PayoutBatches — Refresh PayPal status visibility", () => {
  it("sent batch with api items shows Refresh button", async () => {
    await setup({
      batches: [{ ...BASE_BATCH, status: "sent", items: [item({ status: "pending" })], totals: { api: 100, manual: 0, all: 100 } }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.getByRole("button", { name: "Refresh PayPal status" })).toBeInTheDocument()
  })

  it("closed batch with api items shows Refresh button for reversals", async () => {
    await setup({
      batches: [{ ...BASE_BATCH, status: "closed", items: [item({ status: "succeeded" })], totals: { api: 100, manual: 0, all: 100 } }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.getByRole("button", { name: "Refresh PayPal status" })).toBeInTheDocument()
  })

  it("manual-only closed batch does not show Refresh button", async () => {
    await setup({
      batches: [{ ...BASE_BATCH, status: "closed", items: [item({ lane: "manual", method: "cashapp", status: "succeeded" })], totals: { api: 0, manual: 100, all: 100 } }],
      paypal: LIVE_PAYPAL,
    })
    expect(screen.getByText((t) => t.startsWith("Paid ") && !t.includes("✓"))).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "Refresh PayPal status" })).not.toBeInTheDocument()
  })
})

describe("PayoutBatches — destination cancel reset", () => {
  it("Cancel in destination edit resets typed input", async () => {
    // DestinationCell is in CampaignPayouts, not PayoutBatches. Test the
    // reset behaviour directly by importing and rendering DestinationCell.
    const { DestinationCell } = await import("../DestinationCell")
    const row = {
      slug: "s", campaign: "C", start_date: "2026-01-01", username: "u", handle: "u",
      platform: "tiktok" as const, amount: 100, posts_owed: 2, posts_done: 2,
      reason: "posts_complete" as const, trusted: false, trust_override: "" as const,
      delivered_campaigns: 1, method: "paypal" as const, destination: "orig@g.com",
      destination_issue: "" as const, booking_destination: "", payment: null,
    }
    render(<DestinationCell row={row} adminKey={"k".repeat(32)} onSaved={() => {}} />)
    // Open the edit form
    await userEvent.click(screen.getByRole("button", { name: /✎ Edit/ }))
    // Modify the input
    const input = screen.getByDisplayValue("orig@g.com")
    await userEvent.clear(input)
    await userEvent.type(input, "changed@g.com")
    expect(screen.getByDisplayValue("changed@g.com")).toBeInTheDocument()
    // Cancel should restore the original value
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
    // Edit form should be gone; original destination still shows in the cell
    expect(screen.queryByDisplayValue("changed@g.com")).not.toBeInTheDocument()
    expect(screen.getByText("orig@g.com")).toBeInTheDocument()
  })
})

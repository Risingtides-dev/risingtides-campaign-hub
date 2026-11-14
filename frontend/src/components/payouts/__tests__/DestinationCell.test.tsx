import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { DestinationCell } from "../DestinationCell"
import { PayoutSessionProvider } from "@/lib/payoutSession"
import type { QueueRow } from "@/lib/payouts"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))
const row = { username: "alice", handle: "alice", method: "paypal", destination: "original@example.invalid", booking_destination: "", destination_issue: "" } as QueueRow
beforeEach(() => vi.clearAllMocks())

describe("DestinationCell", () => {
  it("discards cancelled payment method and destination edits", async () => {
    render(<DestinationCell row={row} adminKey="synthetic-key" onSaved={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: "Edit" }))
    await userEvent.selectOptions(screen.getByRole("combobox"), "cashapp")
    const input = screen.getByRole("textbox", { name: "Payment destination for @alice" })
    await userEvent.clear(input)
    await userEvent.type(input, "$cancelled")
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
    await userEvent.click(screen.getByRole("button", { name: "Edit" }))
    expect(screen.getByRole("combobox")).toHaveValue("paypal")
    expect(screen.getByRole("textbox")).toHaveValue("original@example.invalid")
  })

  it("locks the editor while saving and ignores results after the session ends", async () => {
    let active = true
    let finish!: (value: unknown) => void
    const pending = new Promise((resolve) => { finish = resolve })
    vi.stubGlobal("fetch", vi.fn(async () => pending))
    const saved = vi.fn()
    render(<PayoutSessionProvider sessionId="opaque" isActive={() => active}><DestinationCell row={row} adminKey="synthetic-key" onSaved={saved} /></PayoutSessionProvider>)
    await userEvent.click(screen.getByRole("button", { name: "Edit" }))
    await userEvent.click(screen.getByRole("button", { name: "Save" }))
    expect(screen.getByRole("textbox")).toBeDisabled()
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled()
    active = false
    await act(async () => { finish({ ok: true, status: 200, json: async () => ({ ok: true }) }); await pending })
    expect(saved).not.toHaveBeenCalled()
    expect(toast.success).not.toHaveBeenCalled()
  })
})

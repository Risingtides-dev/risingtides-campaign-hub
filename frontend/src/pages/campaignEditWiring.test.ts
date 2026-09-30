import { describe, expect, it, vi } from "vitest"
import { campaignEditWiring } from "./campaignEditWiring"

describe("campaignEditWiring", () => {
  it("wires reset, error fallback, async save, pending state, and payload identity", async () => {
    const payload = { title: "Changed", end_date: "2026-09-30" }
    const mutateAsync = vi.fn().mockResolvedValue("saved")
    const reset = vi.fn()
    const wiring = campaignEditWiring({ mutateAsync, reset, isError: false, isPending: true })
    expect(wiring.isEditing).toBe(true)
    expect(wiring.editError).toBeUndefined()
    expect(await wiring.onEdit(payload)).toBe("saved")
    expect(mutateAsync).toHaveBeenCalledWith(payload)
    wiring.onResetEdit()
    expect(reset).toHaveBeenCalledOnce()
    expect(campaignEditWiring({ mutateAsync, reset, isError: true, isPending: false }).editError).toBe("Failed to save campaign")
    expect(campaignEditWiring({ mutateAsync, reset, isError: true, error: { message: "Network" }, isPending: false }).editError).toBe("Network")
  })
})

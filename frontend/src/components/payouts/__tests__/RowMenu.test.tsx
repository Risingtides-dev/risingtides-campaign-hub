import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, it, vi } from "vitest"
import { RowMenu } from "../RowMenu"
import type { QueueRow } from "@/lib/payouts"

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }))
vi.mock("sonner", () => ({ toast }))

it("retains the issued dashboard message for manual copying without generating a second link", async () => {
  const user = userEvent.setup()
  vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new Error("Clipboard blocked"))
  const link = "https://example.invalid/creator#synthetic-token"
  const fetchFn = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({
    links: [{ username: "alice", handle: "alice", link, newly_issued: true, has_destination: false }], skipped: [],
  }) })
  vi.stubGlobal("fetch", fetchFn)
  const changed = vi.fn()
  render(<RowMenu row={{ username: "alice", handle: "alice", reason: "posts_incomplete", payment: null, trust_override: "", delivered_campaigns: 0 } as QueueRow} adminKey="synthetic-key" onChanged={changed} />)
  await user.click(screen.getByRole("button", { name: "More for @alice" }))
  await user.click(screen.getByRole("menuitem", { name: "Copy DM with their dashboard link" }))
  const manual = await screen.findByRole("textbox", { name: "Dashboard message for @alice" })
  expect(manual).toHaveAttribute("readonly")
  expect((manual as HTMLTextAreaElement).value).toContain(link)
  expect((manual as HTMLTextAreaElement).value).not.toContain("🙂")
  expect(fetchFn).toHaveBeenCalledTimes(1)
  expect(changed).toHaveBeenCalledTimes(1)
  expect(toast.success).not.toHaveBeenCalled()
})

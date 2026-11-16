import { describe, it, expect, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { CopyButton } from "../CopyButton"

describe("CopyButton", () => {
  it("copies the PayPal email in one click", async () => {
    const user = userEvent.setup()
    const spy = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue()
    render(<CopyButton value="creator@paypal.com" label="Copy @creator's PayPal" />)
    await user.click(screen.getByRole("button", { name: "Copy @creator's PayPal" }))
    expect(spy).toHaveBeenCalledWith("creator@paypal.com")
  })
})

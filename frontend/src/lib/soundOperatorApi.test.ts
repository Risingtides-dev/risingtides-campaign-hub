import { beforeEach, describe, expect, it, vi } from "vitest"
import { api, operatorLogin, operatorSession } from "./soundOperatorApi"

describe("Sound Assignments browser auth", () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it("loads the existing session before the roster and sends CSRF only on mutation", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch")
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true, csrf_token: "synthetic-csrf" }), { status: 200 }))
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ pages: [] }), { status: 200 }))
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))

    expect(await operatorSession()).toBe(true)
    await api("/pages")
    await api("/sync", { method: "POST" })

    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([
      "/api/sound-assignments/session", "/api/sound-assignments/pages", "/api/sound-assignments/sync",
    ])
    const read = fetcher.mock.calls[1][1] as RequestInit
    const write = fetcher.mock.calls[2][1] as RequestInit
    expect(read.credentials).toBe("same-origin")
    expect(new Headers(read.headers).has("X-CSRF-Token")).toBe(false)
    expect(new Headers(write.headers).get("X-CSRF-Token")).toBe("synthetic-csrf")
    expect(new Headers(write.headers).has("X-Hub-Write-Key")).toBe(false)
  })

  it("keeps the operator session on an upstream 401 but expires on Hub's gate", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch")
    const expired = vi.fn()
    window.addEventListener("sound-operator-expired", expired)
    try {
      fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true, csrf_token: "retained-csrf" }), { status: 200 }))
      fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ error: "Content Lab credentials rejected." }), { status: 401 }))
      fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ error: "Operator login required." }), { status: 401 }))
      expect(await operatorSession()).toBe(true)
      await expect(api("/sync", { method: "POST" })).rejects.toThrow("Content Lab credentials rejected.")
      expect(expired).not.toHaveBeenCalled()
      await expect(api("/sync", { method: "POST" })).rejects.toThrow("Operator login required.")
      expect(expired).toHaveBeenCalledTimes(1)
      const retainedWrite = fetcher.mock.calls[2][1] as RequestInit
      expect(new Headers(retainedWrite.headers).get("X-CSRF-Token")).toBe("retained-csrf")
    } finally {
      window.removeEventListener("sound-operator-expired", expired)
    }
  })

  it("logs in with an entered password without retaining it as an API key", async () => {
    const fetcher = vi.spyOn(globalThis, "fetch")
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ authenticated: true, csrf_token: "next-csrf" }), { status: 200 }))
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    await operatorLogin("synthetic-password")
    await api("/sync", { method: "POST" })
    const login = fetcher.mock.calls[0][1] as RequestInit
    expect(login.body).toBe(JSON.stringify({ password: "synthetic-password" }))
    const write = fetcher.mock.calls[1][1] as RequestInit
    expect(new Headers(write.headers).get("X-CSRF-Token")).toBe("next-csrf")
    expect(JSON.stringify(write)).not.toContain("synthetic-password")
  })
})

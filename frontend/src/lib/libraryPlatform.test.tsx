import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "./api"
import { libraryKeys, useLibrary, useLibraryRate } from "./queries"
import type { LibraryPlatform, LibraryResponse } from "./types"

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ creators: [] }) }))
})

describe("platform-scoped library rates", () => {
  it("keeps legacy URLs while requesting explicit platform authority when selected", async () => {
    await api.getLibrary("w60", "tiktok")
    expect(fetch).toHaveBeenLastCalledWith(expect.stringMatching(/\/api\/library\/creators\?window=w60&platform=tiktok$/), expect.anything())
    await api.getLibraryRate("name/with/slash", "instagram")
    expect(fetch).toHaveBeenLastCalledWith(expect.stringMatching(/\/api\/library\/creators\/name%2Fwith%2Fslash\/rate\?platform=instagram$/), expect.anything())
    await api.getLastRate("name/with/slash", "tiktok")
    expect(fetch).toHaveBeenLastCalledWith(expect.stringMatching(/\/api\/last-rate\/name%2Fwith%2Fslash\?platform=tiktok$/), expect.anything())
    await api.getLibrary("w60")
    expect(fetch).toHaveBeenLastCalledWith(expect.stringMatching(/\/api\/library\/creators\?window=w60$/), expect.anything())
    await api.getLibraryRate("alice")
    expect(fetch).toHaveBeenLastCalledWith(expect.stringMatching(/\/api\/library\/creators\/alice\/rate$/), expect.anything())
    expect(libraryKeys.creators("w60", "tiktok")).not.toEqual(libraryKeys.creators("w60", "instagram"))
    expect(libraryKeys.rate("alice", "tiktok")).not.toEqual(libraryKeys.rate("alice", "instagram"))
  })

  it("never exposes previous unscoped or another platform's rates while the next scope loads", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    let releaseTikTok!: (value: LibraryResponse) => void
    const tikTok = new Promise<LibraryResponse>((resolve) => { releaseTikTok = resolve })
    const legacy = { creators: [{ key: "alice", platform: "instagram", rate: 900 }] } as LibraryResponse
    const scoped = { creators: [{ key: "alice", platform: "tiktok", rate: 25 }] } as LibraryResponse
    const getLibrary = vi.spyOn(api, "getLibrary").mockImplementation(async (_window, platform) => platform === "tiktok" ? tikTok : legacy)
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result, rerender } = renderHook(
      ({ platform }: { platform?: LibraryPlatform }) => useLibrary("w60", platform),
      { wrapper, initialProps: {} },
    )
    await waitFor(() => expect(result.current.data?.creators[0].rate).toBe(900))
    rerender({ platform: "tiktok" })
    await waitFor(() => expect(getLibrary).toHaveBeenLastCalledWith("w60", "tiktok"))
    expect(result.current.data).toBeUndefined()
    expect(result.current.isLoading).toBe(true)
    releaseTikTok(scoped)
    await waitFor(() => expect(result.current.data?.creators[0].rate).toBe(25))
    client.clear()
  })

  it("fetches single-creator rates separately per platform", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const getRate = vi.spyOn(api, "getLibraryRate").mockImplementation(async (_username, platform) => ({ username: "alice", rate: platform === "tiktok" ? 25 : 900, source: "booking", last_rate: null, last_booked_at: "", campaigns: 1 }))
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result, rerender } = renderHook(
      ({ platform }: { platform: LibraryPlatform }) => useLibraryRate("alice", true, platform),
      { wrapper, initialProps: { platform: "instagram" } },
    )
    await waitFor(() => expect(result.current.data?.rate).toBe(900))
    rerender({ platform: "tiktok" })
    await waitFor(() => expect(result.current.data?.rate).toBe(25))
    expect(getRate).toHaveBeenCalledTimes(2)
    client.clear()
  })
})

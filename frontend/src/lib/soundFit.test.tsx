import { renderHook, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "./api"
import { useSoundFit } from "./queries"

const response = { sound_id: "123", campaign_slug: "round-one", artist: "Artist", song: "Song", creators: [] }
beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => response }))
})

describe("sound-fit campaign selection", () => {
  it("keeps legacy calls and safely encodes campaign-specific parameters", async () => {
    await api.getSoundFit("sound/123", "round two&other=true", 1000)
    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/intelligence/sound-fit/sound%2F123?campaign_slug=round+two%26other%3Dtrue&limit=1000"),
      expect.anything(),
    )
    await api.getSoundFit("123")
    expect(fetch).toHaveBeenLastCalledWith(expect.stringMatching(/\/api\/intelligence\/sound-fit\/123$/), expect.anything())
  })

  it("does not reuse cached rankings across campaign rounds or candidate limits", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const getFit = vi.spyOn(api, "getSoundFit").mockImplementation(async (sound, campaign) => ({ ...response, sound_id: sound, campaign_slug: campaign ?? "round-one" }))
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const { result, rerender } = renderHook(
      ({ campaign, limit }) => useSoundFit("123", campaign, limit),
      { wrapper, initialProps: { campaign: "round-one", limit: 40 } },
    )
    await waitFor(() => expect(result.current.data?.campaign_slug).toBe("round-one"))
    rerender({ campaign: "round-two", limit: 40 })
    await waitFor(() => expect(result.current.data?.campaign_slug).toBe("round-two"))
    rerender({ campaign: "round-two", limit: 1000 })
    await waitFor(() => expect(getFit).toHaveBeenLastCalledWith("123", "round-two", 1000))
    expect(getFit).toHaveBeenCalledTimes(3)
    client.clear()
  })
})

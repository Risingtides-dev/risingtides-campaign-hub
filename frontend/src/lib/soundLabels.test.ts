import { describe, expect, it } from "vitest"
import { campaignRoundLabels } from "./soundLabels"
import type { TargetSound } from "./types"

function sound(campaign_slug: string, extras: Partial<TargetSound> = {}): TargetSound {
  return { campaign_slug, song: "Same Song", artist: "Artist", sound_id: "same-sound", post_count: 0, freshness: "fresh", ...extras }
}

describe("campaign round labels", () => {
  it("keeps unique song labels uncluttered", () => {
    expect(campaignRoundLabels([sound("one", { round: "1" })]).size).toBe(0)
  })

  it("uses real round and date metadata for identical song labels", () => {
    const labels = campaignRoundLabels([
      sound("one", { round: "1", start_date: "2026-10-01" }),
      sound("two", { round: "Round 2", start_date: "2026-11-01" }),
    ])
    expect(labels.get("one")).toBe("Round 1 · 2026-10-01")
    expect(labels.get("two")).toBe("Round 2 · 2026-11-01")
  })

  it("falls back to campaign identity when metadata cannot distinguish campaigns", () => {
    const labels = campaignRoundLabels([sound("one"), sound("two")])
    expect(labels.get("one")).toBe("one")
    expect(labels.get("two")).toBe("two")
    const sameRound = campaignRoundLabels([sound("one", { round: "2" }), sound("two", { round: "2" })])
    expect(sameRound.get("one")).toBe("Round 2 · one")
    expect(sameRound.get("two")).toBe("Round 2 · two")
  })
})

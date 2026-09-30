import { describe, expect, it, vi } from "vitest"
import type { PopScore } from "@/lib/types"
import { prepareTrendData, selectTrendSeries, trendEventTicks, zoomedPopularityDomain } from "../popScoreChartData"

declare const process: { env: Record<string, string | undefined> }

const payload: PopScore = {
  linked: true, phase: "live", streams: { start_total: 10, end_total: 20, followup_total: 20, now: 25, end_is_to_date: false, followup_is_to_date: false, gained_campaign: 10, gained_followup: 0, growth_pct_campaign: 100, baseline_daily: 5, campaign_daily: 4, followup_daily: 1, lift_pct_campaign: -20, lift_pct_followup: -80 },
  ugc: { start: 2, end: 5, followup: 7, start_total: 2, end_total: 5, followup_total: 7, now: 8, now_date: "2026-01-04", change_since_start: 6, change_since_end: 3, baseline_daily: 2, campaign_daily: 3, followup_daily: 1, gained_campaign: 3, gained_followup: 2, lift_pct_campaign: 50, end_is_to_date: false, followup_is_to_date: false },
  history: [{ date: "2026-01-01", value: 40 }, { date: "2026-01-02", value: 50 }, { date: "2026-01-03", value: 51 }],
  streams_history: [{ date: "2026-01-01", total: 10, daily: null }, { date: "2026-01-02", total: 14, daily: 4, smoothed: true }],
  ugc_history: [{ date: "2026-01-01", total: 2, daily: null }, { date: "2026-01-02", total: 5, daily: 3 }],
  post_events: [{ date: "2026-01-02", count: 4 }, { date: "2026-01-05", count: 9 }],
}

describe("pop score trend preparation", () => {
  it("selects each series and marks dim and smoothed daily bars", () => {
    expect(selectTrendSeries(payload, "streams")[1]).toMatchObject({ value: 4, smoothed: true, belowBaseline: true })
    expect(selectTrendSeries(payload, "ugc")[1]).toMatchObject({ value: 3, belowBaseline: false })
    expect(selectTrendSeries(payload, "popularity").map(p => p.value)).toEqual([40, 50, 51])
  })
  it("zooms popularity to three points around its range and clamps at 0–100", () => {
    expect(zoomedPopularityDomain(selectTrendSeries(payload, "popularity"))).toEqual([37, 54])
    expect(zoomedPopularityDomain([{ date: "x", time: 0, value: 99 }])).toEqual([96, 100])
    expect(zoomedPopularityDomain([])).toEqual([0, 100])
  })
  it("keeps post event ticks by date, including gap days without a reading", () => {
    expect(trendEventTicks(payload).map(event => event.date)).toEqual(["2026-01-02", "2026-01-05"])
    expect(prepareTrendData(payload, "ugc").points[1].postCount).toBe(4)
  })
  it("filters future post dates using the local calendar date", () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date("2026-09-30T23:30:00Z")) // Pacific evening; Oct 1 is still future
    try {
      const data = { ...payload, post_events: [{ date: "2026-09-30", count: 1 }, { date: "2026-10-01", count: 8 }] }
      expect(trendEventTicks(data).map(event => event.date)).toEqual(["2026-09-30"])
      expect(prepareTrendData(data, "popularity").events.map(event => event.date)).toEqual(["2026-09-30"])
    } finally {
      vi.useRealTimers()
    }
  })

  it("uses the local day when UTC has already crossed midnight", () => {
    const priorTz = process.env.TZ
    process.env.TZ = 'America/Los_Angeles'
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-30T02:00:00Z'))
    try {
      const result = trendEventTicks({ ...payload, post_events: [{ date: '2026-09-29', count: 1 }, { date: '2026-09-30', count: 1 }] })
      expect(result.map(event => event.date)).toEqual(['2026-09-29'])
    } finally {
      vi.useRealTimers()
      if (priorTz === undefined) delete process.env.TZ
      else process.env.TZ = priorTz
    }
    expect(process.env.TZ).toBe(priorTz)
  })
  it("keeps an empty popularity series on the finite default domain", () => {
    const empty = { ...payload, history: [], post_events: [{ date: "2026-01-05", count: 2 }] }
    const prepared = prepareTrendData(empty, "popularity")
    expect(prepared.domain).toEqual([0, 100])
    expect(prepared.points[0].postY).toBe(100)
    expect(prepared.domain?.every(Number.isFinite)).toBe(true)
  })
})

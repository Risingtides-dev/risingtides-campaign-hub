import type { PopScore } from "@/lib/types"

export type TrendMode = "popularity" | "streams" | "ugc"
export type TrendPoint = { date: string; time: number; value: number | null; smoothed?: boolean; belowBaseline?: boolean; postCount?: number; postY?: number | null; recountY?: number | null }

const dayTime = (date: string) => new Date(`${date}T00:00:00`).getTime()

export function selectTrendSeries(data: PopScore, mode: TrendMode): TrendPoint[] {
  if (mode === "popularity") return (data.history ?? []).map(p => ({ date: p.date, time: dayTime(p.date), value: p.value }))
  const history = mode === "streams" ? data.streams_history ?? [] : data.ugc_history ?? []
  const baseline = mode === "streams" ? data.streams?.baseline_daily : data.ugc?.baseline_daily
  return history.map(p => ({ date: p.date, time: dayTime(p.date), value: p.daily, smoothed: p.smoothed, belowBaseline: p.daily != null && baseline != null && p.daily < baseline }))
}

export function zoomedPopularityDomain(points: TrendPoint[]): [number, number] {
  const values = points.flatMap(p => p.value == null ? [] : [p.value])
  if (!values.length) return [0, 100]
  return [Math.max(0, Math.min(...values) - 3), Math.min(100, Math.max(...values) + 3)]
}

export function trendEventTicks(data: PopScore) {
  return (data.post_events ?? []).filter(event => event.count > 0).map(event => ({ date: event.date, time: dayTime(event.date), count: event.count }))
}

export function prepareTrendData(data: PopScore, mode: TrendMode) {
  const points = selectTrendSeries(data, mode)
  const events = trendEventTicks(data)
  const counts = new Map(events.map(event => [event.date, event.count]))
  const recounts = new Set((mode === "streams" ? data.streams?.recounts : mode === "ugc" ? data.ugc?.recounts : [])?.map(r => r.date) ?? [])
  const domain = mode === "popularity" ? zoomedPopularityDomain(points) : undefined
  const postY = mode === "popularity" ? domain?.[1] : Math.max(0, ...points.flatMap(p => p.value == null ? [] : [p.value]))
  return { points: points.map(point => ({ ...point, postCount: counts.get(point.date), postY: counts.has(point.date) ? postY : null, recountY: recounts.has(point.date) ? 0 : null })), events, domain }
}

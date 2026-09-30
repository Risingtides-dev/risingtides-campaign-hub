import { useEffect, useRef, useState } from "react"
import {
  Bar, Cell, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter,
  Tooltip as RTooltip, XAxis, YAxis,
} from "recharts"
import { AlertCircle, Loader2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useEditCampaign, useOverridePopScore, usePopScore, useSetPopScoreTrack } from "@/lib/queries"
import type { PopScore } from "@/lib/types"
import { chartAxisProps, chartTooltipProps } from "./chartDate"
import { prepareTrendData, type TrendMode } from "./popScoreChartData"
// eslint-disable-next-line react-refresh/only-export-components
export { chartAxisProps } from "./chartDate"

const ACCENT = "#E100C3"
const AXIS = "#909098"
const STREAMS_AXIS_WIDTH = 70

function TrackLinkForm({ initial, onSave, onUnlink, onCancel, isPending, error }: {
  initial: string; onSave: (link: string) => void; onUnlink?: () => void; onCancel?: () => void
  isPending: boolean; error?: string
}) {
  const [link, setLink] = useState(initial)
  const [confirmUnlink, setConfirmUnlink] = useState(false)
  const keepSongRef = useRef<HTMLButtonElement>(null)
  useEffect(() => { if (confirmUnlink) keepSongRef.current?.focus() }, [confirmUnlink])
  return <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); onSave(link.trim()) }}>
    <Input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Spotify track link, Chartmetric link, or ISRC" aria-label="Song link for pop score" className="w-full sm:w-[380px] h-9 text-[13px]" />
    <Button type="submit" size="sm" disabled={isPending || !link.trim()}>{isPending ? <Loader2 className="size-4 animate-spin" /> : "Save"}</Button>
    {onCancel && <Button type="button" size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>}
    {onUnlink && !confirmUnlink && <button type="button" disabled={isPending} onClick={() => setConfirmUnlink(true)} className="text-xs text-rt-fg-tertiary hover:text-rt-fg">Unlink song</button>}
    {onUnlink && confirmUnlink && <span className="flex flex-wrap items-center gap-2 text-xs">Unlink — this also clears saved choices? <button type="button" disabled={isPending} onClick={onUnlink} className="min-h-6 px-1 text-rt-magenta">Yes, unlink</button> <button ref={keepSongRef} type="button" onClick={() => setConfirmUnlink(false)} className="min-h-6 px-1 text-rt-fg-tertiary">Keep song</button></span>}
    {error && <p className="w-full text-red-500 text-[13px]">{error}</p>}
  </form>
}

const num = (v: number | null | undefined) => v == null ? "—" : v.toLocaleString()
const pct = (v: number | null | undefined) => v == null ? "N/A" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`
const headlinePct = pct
const compact = (v: number | null | undefined) => v == null ? "—" : Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v)
const rate = (v: number | null | undefined) => v == null ? "—" : Math.abs(v) < 1000 ? Math.round(v).toLocaleString("en") : compact(v)
const date = (v?: string) => v ? new Date(`${v}T00:00:00`).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" }) : "—"
const shortDate = (v: string) => date(v)
const signedCompact = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${compact(Math.abs(v))}`

function AnomalyNotes({ metric, data, pending, pendingDate, error, failedDate, onOverride }: { metric: "streams" | "ugc"; data: PopScore; pending: boolean; pendingDate?: string; error?: string; failedDate?: string; onOverride: (body: { metric: "streams" | "ugc"; date: string; action: "include" | "exclude" | "auto" }) => void }) {
  const block = data[metric]
  const unit = metric === "streams" ? "streams" : "TikTok videos"
  const recounts = block?.recounts ?? []
  const unusual = block?.unusual ?? []
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const summary = (items: typeof recounts, kind: "recount" | "unusual") => {
    // Equal absolute changes choose the later calendar date.
    const largest = items.reduce<typeof items[number] | undefined>((current, item) => !current || Math.abs(item.change) > Math.abs(current.change) || (Math.abs(item.change) === Math.abs(current.change) && item.date > current.date) ? item : current, undefined)
    const metricName = metric === "streams" ? "Streams" : "TikTok videos"
    if (!items.length) return null
    const isExpanded = !!expanded[`${metric}-${kind}`]
    const label = kind === "recount" ? `${items.length} Chartmetric recount${items.length === 1 ? "" : "s"} not counted` : `${items.length} unusual jump${items.length === 1 ? "" : "s"} counted`
    return <div key={`${metric}-${kind}`} className="text-[10px] text-rt-fg-tertiary"><button type="button" aria-expanded={isExpanded} onClick={() => setExpanded(value => ({ ...value, [`${metric}-${kind}`]: !value[`${metric}-${kind}`] }))} className="text-left hover:text-rt-fg">{metricName}: {label}{items.length > 1 && ` · largest ${signedCompact(largest!.change)} on ${shortDate(largest!.date)}`}</button>{isExpanded && <ul className="ml-3 mt-1 space-y-1">{items.map(item => {
      const counted = kind === "unusual"
      const action = item.source === "manual" ? "auto" : kind === "recount" ? "include" : "exclude"
      const actionText = item.source === "manual" ? "Reset" : kind === "recount" ? "Count it" : "Leave it out"
      const targetDate = item.source === "manual" ? (item.choice_date ?? item.date) : item.date
      return <li key={`${item.date}-${item.change}`} className="flex flex-wrap items-center gap-x-1.5"><span>{shortDate(item.date)} ({signedCompact(item.change)} {unit}) · {counted ? "counted" : "not counted"}{item.source === "manual" ? ` · ${item.with ? `counted with ${shortDate(item.with)} · set by you` : "set by you"}` : ""}</span><button type="button" aria-label={`${actionText} — ${shortDate(item.date)}, ${metric === "streams" ? "Streams" : "TikTok videos"}`} disabled={pending && pendingDate === targetDate} onClick={() => onOverride({ metric, date: targetDate, action })} className="min-h-6 px-1 text-rt-magenta disabled:opacity-40">{actionText}</button></li>
    })}</ul>}</div>
  }
  return <div data-metric={metric}>{summary(recounts, "recount")}{summary(unusual, "unusual")}{error && failedDate && [...recounts, ...unusual].some(item => item.date === failedDate) && <p role="alert" className="text-red-400">{error}</p>}</div>
}

// eslint-disable-next-line react-refresh/only-export-components
export function formatTrendTooltip(point: { date: string; value?: number | null; smoothed?: boolean; count?: number; recount?: boolean }, mode: TrendMode) {
  const label = mode === "popularity" ? "Popularity" : mode === "streams" ? "Daily streams" : "Daily new videos"
  return { date: date(point.date), value: point.recount ? "recount (not counted)" : point.value == null ? undefined : mode === "popularity" ? num(point.value) : rate(point.value), label, estimated: !!point.smoothed, posts: point.count }
}

// eslint-disable-next-line react-refresh/only-export-components
export function renderTrendTooltipContent(point: { date: string; value?: number | null; smoothed?: boolean; recount?: boolean }, mode: TrendMode, postCount?: number) {
  const formatted = formatTrendTooltip({ ...point, count: postCount }, mode)
  const isRecount = !!point.recount
  return <div className="rounded border border-white/15 bg-rt-bg-card px-2 py-1 text-xs shadow"><div>{formatted.date}</div>{(formatted.value != null || isRecount) && <div>{formatted.value ?? "—"}{!isRecount && ` ${formatted.label}${formatted.estimated ? " · estimated" : ""}`}</div>}{formatted.posts != null && <div>{formatted.posts} creator posts</div>}</div>
}

// eslint-disable-next-line react-refresh/only-export-components
export function renderTrendTooltipForRow(row: { date: string; value?: number | null; smoothed?: boolean; count?: number; recountY?: number | null }, mode: TrendMode, events: { date: string; count: number }[]) {
  const event = events.find(item => item.date === row.date)
  return renderTrendTooltipContent({ date: row.date, value: row.value, smoothed: row.smoothed, recount: row.recountY != null && row.value == null }, mode, event?.count ?? row.count)
}

function phaseText(data: PopScore) {
  if (data.phase === "followup") {
    return data.followup_day == null ? undefined : `Follow-up (day ${data.followup_day} of ${data.followup_days ?? 28})`
  }
  return ({ live: "Live", complete: "Complete", finished_no_end: "Finished · end date not set", not_started: "Not started", no_start: "Not started" } as Record<string, string>)[data.phase ?? ""]
}

function PopScoreChart({ data }: { data: PopScore }) {
  const [mode, setMode] = useState<TrendMode>("popularity")
  const [containerWidth, setContainerWidth] = useState(600)
  const [chartElement, setChartElement] = useState<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!chartElement || typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(entries => {
      const width = entries[0]?.contentRect.width
      setContainerWidth(width && width > 0 ? width : 600)
    })
    observer.observe(chartElement)
    return () => observer.disconnect()
  }, [chartElement])
  const prepared = prepareTrendData(data, mode)
  const today = new Date().setHours(0, 0, 0, 0)
  const throughToday = new Set(prepared.events.filter(event => event.time <= today).map(event => event.date))
  const chartData = prepared.points.map(point => prepared.events.some(event => event.date === point.date) && !throughToday.has(point.date) ? { ...point, postY: null } : point)
  const points = chartData.filter(p => p.value != null)
  const sameBounds = !!data.start_date && data.start_date === data.end_date
  const dates = [...points.map(point => point.time), ...prepared.events.filter(event => event.time <= today).map(event => event.time)]
  const min = dates.length ? Math.min(...dates) : 0
  const max = dates.length ? Math.max(...dates) : 0
  const lines = [data.start_date, sameBounds ? "" : data.end_date, data.followup_end].map((d, i) => ({ date: d, label: [sameBounds ? "Start/End" : "Start", "End", "+28 days"][i] })).filter((p): p is {date: string; label: string} => !!p.date).filter(p => new Date(`${p.date}T00:00:00`).getTime() >= min && new Date(`${p.date}T00:00:00`).getTime() <= max)
  const chartLabel = mode === "popularity" ? "Popularity" : mode === "streams" ? "Daily streams" : "Daily new videos"
  const recounts = mode === "streams" ? data.streams?.recounts ?? [] : mode === "ugc" ? data.ugc?.recounts ?? [] : []
  const events = prepared.events
  const tooltipContent = ({ active, payload }: { active?: boolean; payload?: ReadonlyArray<{ payload?: Record<string, unknown> }> }) => {
    if (!active || !payload?.length) return null
    const row = payload.map(item => item.payload ?? {}).find(item => typeof item.date === "string")
    if (!row) return null
    return renderTrendTooltipForRow({ date: String(row.date), value: typeof row.value === "number" ? row.value : undefined, smoothed: row.smoothed === true, recountY: typeof row.recountY === "number" ? row.recountY : null, count: typeof row.count === "number" ? row.count : undefined }, mode, events)
  }
  const labels = lines.map(({ label }) => containerWidth < 480 ? (label === "Start/End" ? "S/E" : label === "Start" ? "S" : label === "End" ? "E" : "+28") : label)
  return <div className="space-y-2">
    <div className="flex gap-1" role="group" aria-label="Chart metric">
      <button type="button" aria-pressed={mode === "popularity"} onClick={() => setMode("popularity")} className={`rounded px-2 py-1 text-xs ${mode === "popularity" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Popularity</button>
      <button type="button" aria-pressed={mode === "streams"} onClick={() => setMode("streams")} className={`rounded px-2 py-1 text-xs ${mode === "streams" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Daily streams</button>
      <button type="button" aria-pressed={mode === "ugc"} onClick={() => setMode("ugc")} className={`rounded px-2 py-1 text-xs ${mode === "ugc" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Daily new videos</button>
    </div>
    {points.filter(p => p.value != null).length < 2 ? <p className="text-rt-fg-tertiary text-[13px]">Not enough history yet to chart.</p> : <div role="img" aria-label={`${chartLabel} trend chart for ${data.track?.name ?? "linked song"}`} className="h-36 w-full" ref={setChartElement}>
      <ResponsiveContainer width="100%" height="100%">
        {mode === "popularity" ? <LineChart data={chartData} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <XAxis type="number" dataKey="time" domain={[min, max]} tick={{ fill: AXIS, fontSize: 10 }} {...chartAxisProps} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis width={STREAMS_AXIS_WIDTH} domain={prepared.domain} tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <RTooltip {...chartTooltipProps} content={(props) => tooltipContent(props as { active?: boolean; payload?: ReadonlyArray<{ payload?: Record<string, unknown> }> })} /><Line type="stepAfter" connectNulls dataKey="value" stroke={ACCENT} strokeWidth={2} dot={(props) => { const point = props.payload as { smoothed?: boolean }; return <circle cx={props.cx} cy={props.cy} r={2} fill={point.smoothed ? "#f08be0" : ACCENT} /> }} />
          {events.length > 0 && <Scatter dataKey="postY" name="creator posts" fill={AXIS} shape={(props) => props.cx == null || props.cy == null || props.payload?.postY == null ? null : <line className="creator-post-tick" x1={props.cx} x2={props.cx} y1={props.cy} y2={props.cy + 5} stroke={AXIS} />} />}
          {lines.map(({date: d, label}, i) => { const right = new Date(`${d}T00:00:00`).getTime() >= max - (max - min) * .15; return <ReferenceLine key={`${label}-${d}`} x={new Date(`${d}T00:00:00`).getTime()} stroke={AXIS} strokeDasharray="3 3" label={{ value: labels[i], fill: AXIS, fontSize: 9, position: right ? "insideTopRight" : "insideTopLeft", textAnchor: right ? "end" : "start", offset: 8 }} /> })}
        </LineChart> : <ComposedChart data={chartData} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <XAxis type="number" dataKey="time" domain={[min, max]} tick={{ fill: AXIS, fontSize: 10 }} {...chartAxisProps} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis width={STREAMS_AXIS_WIDTH} tickFormatter={(v: number) => Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v)} tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <ReferenceLine y={mode === "streams" ? data.streams?.baseline_daily ?? undefined : data.ugc?.baseline_daily ?? undefined} stroke={AXIS} strokeDasharray="4 3" label={{ value: "before", fill: AXIS, fontSize: 9, position: "insideTopLeft" }} />
          <RTooltip {...chartTooltipProps} content={(props) => tooltipContent(props as { active?: boolean; payload?: ReadonlyArray<{ payload?: Record<string, unknown> }> })} />
          <Bar dataKey="value" name={chartLabel} maxBarSize={5} isAnimationActive={false} radius={[1, 1, 0, 0]}>{chartData.map((point, index) => <Cell key={index} fill={point.belowBaseline ? (point.smoothed ? `${ACCENT}33` : `${ACCENT}55`) : (point.smoothed ? "#f08be0" : ACCENT)} />)}</Bar>
          {events.length > 0 && <Scatter dataKey="postY" name="creator posts" fill={AXIS} shape={(props) => props.cx == null || props.cy == null || props.payload?.postY == null ? null : <line className="creator-post-tick" x1={props.cx} x2={props.cx} y1={props.cy} y2={props.cy + 5} stroke={AXIS} />} />}
          {recounts.length > 0 && <Scatter dataKey="recountY" name="recount" fill="none" shape={(props) => props.cx == null || props.cy == null || props.payload?.recountY == null ? null : <circle cx={props.cx} cy={props.cy} r={3} fill="none" stroke={AXIS} />}/>}
          {lines.map(({date: d, label}, i) => { const right = new Date(`${d}T00:00:00`).getTime() >= max - (max - min) * .15; return <ReferenceLine key={`${label}-${d}`} x={new Date(`${d}T00:00:00`).getTime()} stroke={AXIS} strokeDasharray="3 3" label={{ value: labels[i], fill: AXIS, fontSize: 9, position: right ? "insideTopRight" : "insideTopLeft", textAnchor: right ? "end" : "start", offset: 8 }} /> })}
        </ComposedChart>}
      </ResponsiveContainer>
    </div>}
    {mode === "popularity" && <p className="text-[10px] text-rt-fg-tertiary">zoomed · score is 0–100</p>}
    {prepared.points.some(p => p.smoothed) && <p className="text-[10px] text-rt-fg-tertiary">light = estimated (Chartmetric skipped a day)</p>}
  </div>
}

function headline(data: PopScore) {
  const parts: string[] = []
  if (data.popularity?.start != null && data.popularity.end != null) parts.push(`Popularity ${data.popularity.start} → ${data.popularity.end}`)
  const s = data.streams
  const streamBits = [
    s?.baseline_daily != null && s.campaign_daily != null ? `${rate(s.baseline_daily)} → ${rate(s.campaign_daily)}/day (${headlinePct(s.lift_pct_campaign)})` : "",
    s?.growth_pct_campaign != null ? `${headlinePct(s.growth_pct_campaign)} growth${s.adjusted ? "*" : ""}` : "",
  ].filter(Boolean)
  if (streamBits.length) parts.push(`streams ${streamBits.join(", ")}`)
  const u = data.ugc
  const ugcBits = [
    u?.baseline_daily != null && u.campaign_daily != null ? `${rate(u.baseline_daily)} → ${rate(u.campaign_daily)}/day` : "",
    u?.growth_pct_campaign != null ? `${headlinePct(u.growth_pct_campaign)} growth${u.adjusted ? "*" : ""}` : "",
    u?.gained_campaign != null ? `${compact(u.gained_campaign)} new during the campaign` : "",
  ].filter(Boolean)
  if (ugcBits.length) parts.push(`TikTok videos ${ugcBits.join(", ")}`)
  const toDate = ["live", "finished_no_end", "followup"].includes(data.phase ?? "") ? " (to date)" : ""
  return parts.length ? `${parts.join(" · ")}${toDate}` : ""
}

export function PopScoreCard({ slug, tracker_url }: { slug: string; tracker_url?: string }) {
  const popScore = usePopScore(slug)
  const setTrack = useSetPopScoreTrack(slug)
  const override = useOverridePopScore(slug)
  const editCampaign = useEditCampaign(slug)
  const [editing, setEditing] = useState(false)
  const [endDateDraft, setEndDateDraft] = useState("")
  const [editingEndDate, setEditingEndDate] = useState(false)
  const [showTrend, setShowTrend] = useState(false)
  const save = (link: string) => setTrack.mutate(link, { onSuccess: () => setEditing(false) })
  const data = popScore.data
  const errorBody = (popScore.error as (Error & { body?: { linked?: unknown; link?: unknown } }) | undefined)?.body
  const errorLink = errorBody?.link
  const initialLink = data?.link ?? (typeof errorLink === "string" ? errorLink : "")
  const linkedOnForm = data?.linked || errorBody?.linked === true
  const header = <div className="flex items-center justify-between mb-3"><h3 className="text-[15px] font-semibold">Song attribution</h3>
    {data?.linked && !editing && <button type="button" onClick={() => setEditing(true)} className="text-rt-fg-tertiary hover:text-rt-fg transition-colors" title="Change song" aria-label="Change song"><Pencil className="size-3.5" /></button>}</div>
  if (popScore.isLoading) return <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5">{header}<div className="flex items-center gap-2 text-rt-fg-tertiary text-sm py-2"><Loader2 className="size-4 animate-spin" /> Loading Chartmetric…</div></div>
  const showForm = editing || popScore.isError || !data?.linked
  const pop = data?.popularity
  const streams = data?.streams
  return <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5 space-y-3">
    {header}
    {popScore.isError && <div className="flex items-center gap-2 text-red-500 text-sm"><AlertCircle className="size-4" />{popScore.error?.message || "Couldn't load pop score"}</div>}
    {!popScore.isError && data?.linked && !editing && <>
      {data.streams_error && <div className="text-xs text-rt-fg-tertiary" role="status">{data.streams_error}</div>}
      {data.ugc_error && <div className="text-xs text-rt-fg-tertiary" role="status">{data.ugc_error}</div>}
      <div className="flex flex-wrap items-center gap-3">
        {data.track?.image_url && <img src={data.track.image_url} alt="" className="size-12 rounded object-cover" />}
        <div className="min-w-0 flex-1"><div className="min-w-0 truncate font-medium">{data.track?.name ?? "Linked track"}</div><div className="text-[13px] text-rt-fg-tertiary">{data.track?.artists?.join(", ")}</div></div>
        {data.link_status === "linked_auto" && <span className="text-[10px] text-rt-fg-tertiary">Linked automatically</span>}
        {phaseText(data) && <span className="rounded-full bg-white/8 px-2.5 py-1 text-xs">{phaseText(data)}</span>}
        {data.data_as_of && <span className="text-xs text-rt-fg-tertiary">Data as of {date(data.data_as_of)}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[13px] text-rt-fg-tertiary">
        <span>Start {date(data.start_date)}</span><span>→</span><span>End {data.end_date ? date(data.end_date) : "not set"}</span>{data.end_date_auto && data.end_date && <span className="text-[11px] text-rt-fg-tertiary">· set when finished</span>}
        {!editingEndDate && <><button type="button" className="text-rt-magenta" onClick={() => { editCampaign.reset(); setEndDateDraft(data.end_date || ""); setEditingEndDate(true) }}>{data.end_date ? "Change" : "Set an end date"}</button>{data.end_date && <button type="button" disabled={editCampaign.isPending} className="text-rt-magenta disabled:opacity-40" onClick={() => editCampaign.mutate({ end_date: "" })}>Clear</button>}</>}
        {editingEndDate && <><Input aria-label="End date" type="date" min={data.start_date} value={endDateDraft} className="h-8 w-auto" disabled={editCampaign.isPending} onChange={(e) => setEndDateDraft(e.target.value)} /><Button size="sm" disabled={editCampaign.isPending || !endDateDraft} onClick={() => editCampaign.mutate({ end_date: endDateDraft }, { onSuccess: () => setEditingEndDate(false) })}>Save</Button><button type="button" onClick={() => { editCampaign.reset(); setEditingEndDate(false) }}>Cancel</button></>}
        <span>→</span><span>Follow-up ends {data.followup_end ? date(data.followup_end) : "—"}</span>
        {editCampaign.isPending && <span className="text-[11px] text-rt-fg-tertiary">Updating…</span>}
        {editCampaign.isError && <span role="alert" className="text-red-400">{editCampaign.error?.message}</span>}
      </div>
      {headline(data) && <p className="text-[12px] text-rt-fg-tertiary">{headline(data)}</p>}
      {popScore.isFetching && !popScore.isLoading && <p className="text-[10px] text-rt-fg-tertiary">Updating…</p>}
      <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-[12px]"><thead className="text-rt-fg-tertiary"><tr><th className="sticky left-0 bg-rt-bg-card text-left font-normal">Metric</th>{["Start", "End", "+28 days", "Now"].map(x => <th className="text-right font-normal" key={x}>{x}</th>)}</tr></thead><tbody>
        {([[
          "Popularity", pop?.start, pop?.end, pop?.followup, pop?.now, pop?.end_is_to_date, pop?.followup_is_to_date, pop?.change_campaign, pop?.change_followup, pop?.change_since_end,
        ], [
          "Streams", streams?.start_total, streams?.end_total, streams?.followup_total, streams?.now, streams?.end_is_to_date, streams?.followup_is_to_date, streams?.gained_campaign, streams?.gained_followup, streams?.change_since_end,
        ], [
          "TikTok videos", data.ugc?.start_total, data.ugc?.end_total, data.ugc?.followup_total, data.ugc?.now, data.ugc?.end_is_to_date, data.ugc?.followup_is_to_date, data.ugc?.gained_campaign, data.ugc?.gained_followup, data.ugc?.change_since_end,
        ]] as const).map(([label, a, b, c, d, endTd, followTd, changeCampaign, changeFollowup, changeNow]) => {
          const adjusted = label === "Streams" ? streams?.adjusted : label === "TikTok videos" ? data.ugc?.adjusted : false
          const star = data.phase !== "not_started" && data.phase !== "no_start" && adjusted
          return <tr key={label} className="border-t border-white/8"><th className="sticky left-0 bg-rt-bg-card py-1.5 text-left font-medium">{label}{label !== "Popularity" && star && <sup className="ml-0.5 text-[9px] text-rt-fg-tertiary">*</sup>}</th>{[a,b,c,d].map((value,i) => {
          const change = i === 1 ? changeCampaign : i === 2 ? changeFollowup : i === 3 ? changeNow : null
          const block = label === "Popularity" ? pop : label === "Streams" ? streams : data.ugc
          const readingDate = i === 3 ? block?.now_date : undefined
          const followDate = label === "Popularity" ? (pop?.followup_is_to_date ? pop?.now_date : data.followup_end) : label === "Streams" ? (streams?.followup_is_to_date ? streams?.now_date : data.followup_end) : (data.ugc?.followup_is_to_date ? data.ugc?.now_date : data.followup_end)
          const sameReading = i === 3 && !!readingDate && readingDate === followDate
          const asOf = i === 3 ? block?.now_date : i === 1 ? data.end_date : i === 0 ? data.start_date : undefined
          return <td key={i} className="py-1.5 text-right tabular-nums">{i === 3 && d != null && d === c && sameReading ? <span className="text-rt-fg-tertiary">same as +28 days</span> : value == null ? "—" : label === "Popularity" ? num(value) : compact(value)}{i === 1 && endTd && <> <span className="text-[10px] text-rt-fg-tertiary">to date</span></>}{i === 2 && followTd && <> <span className="text-[10px] text-rt-fg-tertiary">to date</span></>}{i === 3 && asOf && <span className="block text-[10px] text-rt-fg-tertiary">as of {date(asOf)}</span>}{change != null && !sameReading && i !== 3 && <span className="block text-[10px] text-rt-fg-tertiary">{change > 0 ? "+" : ""}{label === "Popularity" ? num(change) : compact(change)} {i === 1 ? "during campaign" : "since end"}</span>}{i === 3 && (block?.change_since_start != null || block?.change_since_end != null) && <span className="block text-[10px] text-rt-fg-tertiary">{[block.change_since_start != null ? `${signedCompact(block.change_since_start)} since start` : null, block.change_since_end != null ? `${signedCompact(block.change_since_end)} since end` : null].filter(Boolean).join(" · ")}</span>}</td>
        })}</tr>})}
      </tbody></table></div>
      {data.phase !== "not_started" && data.phase !== "no_start" && (streams?.adjusted || data.ugc?.adjusted) && <p className="text-[10px] text-rt-fg-tertiary">* Totals are as reported; changes leave out Chartmetric recounts.</p>}
      {!data.streams_error && <p className="text-[11px] text-rt-fg-tertiary">Daily streams {rate(streams?.baseline_daily)} → {rate(streams?.campaign_daily)} during ({pct(streams?.lift_pct_campaign)}){streams?.followup_daily != null ? ` → ${rate(streams.followup_daily)} after${streams.lift_pct_followup != null ? ` (${pct(streams.lift_pct_followup)} vs before)` : ""}` : ""}</p>}
      {!data.ugc_error && <p className="text-[11px] text-rt-fg-tertiary">New TikTok videos/day {rate(data.ugc?.baseline_daily)} → {rate(data.ugc?.campaign_daily)} during ({pct(data.ugc?.lift_pct_campaign)}){data.ugc?.followup_daily != null ? ` → ${rate(data.ugc.followup_daily)} after${data.ugc.lift_pct_followup != null ? ` (${pct(data.ugc.lift_pct_followup)} vs before)` : ""}` : ""}{data.ugc?.gained_campaign != null ? ` · ${compact(data.ugc.gained_campaign)} new during the campaign` : ""}</p>}
      {data.stale_overrides?.length ? <div className="flex flex-wrap items-center gap-2 text-[10px] text-rt-fg-tertiary"><span>{data.stale_overrides.length} saved choice{data.stale_overrides.length === 1 ? "" : "s"} no longer {data.stale_overrides.length === 1 ? "matches" : "match"} Chartmetric's data</span>{data.stale_overrides.map(item => { const pending = override.isPending && override.variables?.metric === item.metric && override.variables?.date === item.date; return <span key={`${item.metric}-${item.date}`} className="inline-flex items-center gap-1"><span>{shortDate(item.date)} · {item.metric === "streams" ? "Streams" : "TikTok videos"} · {item.action === "include" ? "counted" : "not counted"}</span><button type="button" aria-label={`Reset stale ${item.metric} choice for ${shortDate(item.date)}`} disabled={pending} className="text-rt-magenta disabled:opacity-40" onClick={() => override.mutate({ metric: item.metric, date: item.date, action: "auto" })}>Reset</button></span> })}{override.isError && data.stale_overrides.some(item => item.metric === override.variables?.metric && item.date === override.variables?.date) && <span role="alert" className="text-red-400">{override.error?.message || "Couldn't reset saved choice."}</span>}</div> : null}
      {data.phase !== "not_started" && data.phase !== "no_start" && <><AnomalyNotes metric="streams" data={data} pending={override.isPending} pendingDate={override.isPending && override.variables?.metric === "streams" ? override.variables?.date : undefined} error={override.isError ? override.error?.message : undefined} failedDate={override.isError && override.variables?.metric === "streams" ? override.variables?.date : undefined} onOverride={body => override.mutate(body)} /><AnomalyNotes metric="ugc" data={data} pending={override.isPending} pendingDate={override.isPending && override.variables?.metric === "ugc" ? override.variables?.date : undefined} error={override.isError ? override.error?.message : undefined} failedDate={override.isError && override.variables?.metric === "ugc" ? override.variables?.date : undefined} onOverride={body => override.mutate(body)} /></>}
      <div><button type="button" aria-expanded={showTrend} aria-controls={`attribution-trend-${slug}`} className="text-[12px] text-rt-fg-tertiary hover:text-rt-fg" onClick={() => setShowTrend(v => !v)}>{showTrend ? "Hide trend" : "Show trend"}</button><div id={`attribution-trend-${slug}`} hidden={!showTrend} className="mt-2">{showTrend && <PopScoreChart data={data} />}</div></div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-3 text-[12px] text-rt-fg-tertiary"><span>Shows what happened to the song around the campaign — not proof the campaign caused all of it.</span>{tracker_url && <a href={tracker_url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap text-rt-magenta hover:underline">Open Tides Tracker ↗</a>}</div>
    </>}
    {showForm && <>{!data?.linked && !popScore.isError && <><p className="text-rt-fg-tertiary text-[13px]">{data?.link_status === "pending" ? "Looking up this song on Chartmetric — check back shortly." : data?.link_status === "not_released" ? "Song not out yet — we'll link it automatically when it's released (checked daily)" : data?.link_status === "artist_not_found" ? "Artist not found on Chartmetric yet. We'll keep checking." : data?.link_status === "ambiguous" ? "Several songs match these details. Add a direct track link to choose the right one." : data?.link_status === "generic_title" ? "This title is too general to match safely. Add a direct track link to choose the right song." : data?.link_status === "no_song_info" ? "Add a song title and artist so we can look for the track." : "Song link has not been checked yet."}</p></>}<TrackLinkForm key={initialLink} initial={initialLink} onSave={save} onUnlink={linkedOnForm ? () => save("") : undefined} onCancel={editing ? () => setEditing(false) : undefined} isPending={setTrack.isPending} error={setTrack.isError ? setTrack.error?.message : undefined} /></>}
  </div>
}

import { useState } from "react"
import {
  Bar, Cell, ComposedChart, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter,
  Tooltip as RTooltip, XAxis, YAxis,
} from "recharts"
import { AlertCircle, Loader2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useEditCampaign, usePopScore, useSetPopScoreTrack } from "@/lib/queries"
import type { PopScore } from "@/lib/types"
import { chartAxisProps, chartTooltipProps } from "./chartDate"
import { prepareTrendData, type TrendMode } from "./popScoreChartData"
// eslint-disable-next-line react-refresh/only-export-components
export { chartAxisProps } from "./chartDate"

const ACCENT = "#E100C3"
const AXIS = "#909098"
const STREAMS_AXIS_WIDTH = 70

function TrackLinkForm({ initial, onSave, onCancel, isPending, error }: {
  initial: string; onSave: (link: string) => void; onCancel?: () => void
  isPending: boolean; error?: string
}) {
  const [link, setLink] = useState(initial)
  return <form className="flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); onSave(link.trim()) }}>
    <Input value={link} onChange={(e) => setLink(e.target.value)} placeholder="Spotify track link, Chartmetric link, or ISRC" aria-label="Song link for pop score" className="w-full sm:w-[380px] h-9 text-[13px]" />
    <Button type="submit" size="sm" disabled={isPending}>{isPending ? <Loader2 className="size-4 animate-spin" /> : "Save"}</Button>
    {onCancel && <Button type="button" size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>}
    {error && <p className="w-full text-red-500 text-[13px]">{error}</p>}
  </form>
}

const num = (v: number | null | undefined) => v == null ? "—" : v.toLocaleString()
const pct = (v: number | null | undefined) => v == null ? "N/A" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`
const compact = (v: number | null | undefined) => v == null ? "—" : Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v)
const date = (v?: string) => v ? new Date(`${v}T00:00:00`).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" }) : "—"

function phaseText(data: PopScore) {
  if (data.phase === "followup") {
    return data.followup_day == null ? undefined : `Follow-up (day ${data.followup_day} of ${data.followup_days ?? 28})`
  }
  return ({ live: "Live", complete: "Complete", finished_no_end: "Finished · end date not set", not_started: "Not started", no_start: "Not started" } as Record<string, string>)[data.phase ?? ""]
}

function PopScoreChart({ data }: { data: PopScore }) {
  const [mode, setMode] = useState<TrendMode>("popularity")
  const prepared = prepareTrendData(data, mode)
  const points = prepared.points.filter(p => p.value != null)
  const min = points.length ? Math.min(...points.map(p => p.time)) : 0
  const max = points.length ? Math.max(...points.map(p => p.time)) : 0
  const sameBounds = !!data.start_date && data.start_date === data.end_date
  const lines = [data.start_date, sameBounds ? "" : data.end_date, data.followup_end].map((d, i) => ({ date: d, label: [sameBounds ? "Start/End" : "Start", "End", "Follow-up"][i] })).filter((p): p is {date: string; label: string} => !!p.date).filter(p => new Date(`${p.date}T00:00:00`).getTime() >= min && new Date(`${p.date}T00:00:00`).getTime() <= max)
  const chartLabel = mode === "popularity" ? "Popularity" : mode === "streams" ? "Daily streams" : "Daily new videos"
  return <div className="space-y-2">
    <div className="flex gap-1" role="group" aria-label="Chart metric">
      <button type="button" aria-pressed={mode === "popularity"} onClick={() => setMode("popularity")} className={`rounded px-2 py-1 text-xs ${mode === "popularity" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Popularity</button>
      <button type="button" aria-pressed={mode === "streams"} onClick={() => setMode("streams")} className={`rounded px-2 py-1 text-xs ${mode === "streams" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Daily streams</button>
      <button type="button" aria-pressed={mode === "ugc"} onClick={() => setMode("ugc")} className={`rounded px-2 py-1 text-xs ${mode === "ugc" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Daily new videos</button>
    </div>
    {points.length < 2 ? <p className="text-rt-fg-tertiary text-[13px]">Not enough history yet to chart.</p> : <div className="h-36 w-full" data-testid="attribution-chart" data-plotted-values={points.map(p => p.value).join(",")} data-below-baseline={prepared.points.map(p => p.belowBaseline ? "dim" : "accent").join(",")} data-event-ticks={prepared.events.map(e => `${e.date}:${e.count}`).join(",")} data-reference-labels={lines.map(line => line.label).join(",")} aria-label={`${chartLabel} chart`}>
      <ResponsiveContainer width="100%" height="100%">
        {mode === "popularity" ? <LineChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <XAxis type="number" dataKey="time" domain={["dataMin", "dataMax"]} tick={{ fill: AXIS, fontSize: 10 }} {...chartAxisProps} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis width={STREAMS_AXIS_WIDTH} domain={prepared.domain} tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <RTooltip {...chartTooltipProps} /><Line type="stepAfter" dataKey="value" stroke={ACCENT} strokeWidth={2} dot={(props) => { const point = props.payload as { smoothed?: boolean }; return <circle cx={props.cx} cy={props.cy} r={2} fill={point.smoothed ? "#f08be0" : ACCENT} /> }} />
          <Scatter data={prepared.events.map(e => ({ time: e.time, y: prepared.domain![1], count: e.count }))} dataKey="y" name="creator posts" fill={AXIS} shape={(props) => props.cx == null || props.cy == null ? null : <g><title>{`${props.payload.count} creator posts`}</title><line x1={props.cx} x2={props.cx} y1={props.cy} y2={props.cy + 5} stroke={AXIS} /></g>} />
          {lines.map(({date: d, label}) => <ReferenceLine key={`${label}-${d}`} x={new Date(`${d}T00:00:00`).getTime()} stroke={AXIS} strokeDasharray="3 3" label={{ value: label, fill: AXIS, fontSize: 10 }} />)}
          <text x={6} y={12} fill={AXIS} fontSize={9}>zoomed · score is 0–100</text>
        </LineChart> : <ComposedChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <XAxis type="number" dataKey="time" domain={["dataMin", "dataMax"]} tick={{ fill: AXIS, fontSize: 10 }} {...chartAxisProps} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis width={STREAMS_AXIS_WIDTH} tickFormatter={(v: number) => Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v)} tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <ReferenceLine y={mode === "streams" ? data.streams?.baseline_daily ?? undefined : data.ugc?.baseline_daily ?? undefined} stroke={AXIS} strokeDasharray="4 3" label={{ value: "before", fill: AXIS, fontSize: 9, position: "insideTopLeft" }} />
          <RTooltip {...chartTooltipProps} formatter={(value, name, item) => { const p = item.payload as { count?: number }; return name === "creator posts" ? [`${p.count} creator posts`, "Posts"] : [value, chartLabel] }} />
          <Bar dataKey="value" name={chartLabel} maxBarSize={5} radius={[1, 1, 0, 0]}>{points.map((point, index) => <Cell key={index} fill={point.smoothed ? "#f08be0" : point.belowBaseline ? `${ACCENT}55` : ACCENT} />)}</Bar>
          <Scatter data={prepared.events.map(e => ({ time: e.time, y: Math.max(...points.map(p => p.value ?? 0)), count: e.count }))} dataKey="y" name="creator posts" fill={AXIS} shape={(props) => props.cx == null || props.cy == null ? null : <g><title>{`${props.payload.count} creator posts`}</title><line x1={props.cx} x2={props.cx} y1={props.cy} y2={props.cy + 5} stroke={AXIS} /></g>} />
          {lines.map(({date: d, label}) => <ReferenceLine key={`${label}-${d}`} x={new Date(`${d}T00:00:00`).getTime()} stroke={AXIS} strokeDasharray="3 3" label={{ value: label, fill: AXIS, fontSize: 10 }} />)}
        </ComposedChart>}
      </ResponsiveContainer>
    </div>}
  </div>
}

function headline(data: PopScore) {
  const parts: string[] = []
  if (data.popularity?.start != null && data.popularity.end != null) parts.push(`Popularity ${data.popularity.start} → ${data.popularity.end}`)
  const s = data.streams
  if (s?.baseline_daily != null && s.campaign_daily != null) parts.push(`streams ${compact(s.baseline_daily)} → ${compact(s.campaign_daily)}/day (${pct(s.lift_pct_campaign)})`)
  const u = data.ugc
  if (u?.baseline_daily != null && u.campaign_daily != null) parts.push(`TikTok videos ${compact(u.baseline_daily)} → ${compact(u.campaign_daily)}/day${u.gained_campaign == null ? "" : `, ${compact(u.gained_campaign)} new during the campaign`}`)
  return parts.join(" · ")
}

export function PopScoreCard({ slug, tracker_url }: { slug: string; tracker_url?: string }) {
  const popScore = usePopScore(slug)
  const setTrack = useSetPopScoreTrack(slug)
  const editCampaign = useEditCampaign(slug)
  const [editing, setEditing] = useState(false)
  const [endDateDraft, setEndDateDraft] = useState("")
  const [editingEndDate, setEditingEndDate] = useState(false)
  const [showTrend, setShowTrend] = useState(false)
  const save = (link: string) => setTrack.mutate(link, { onSuccess: () => setEditing(false) })
  const data = popScore.data
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
        <div className="min-w-0 flex-1"><div className="font-medium">{data.track?.name ?? "Linked track"}</div><div className="text-[13px] text-rt-fg-tertiary">{data.track?.artists?.join(", ")}</div></div>
        {phaseText(data) && <span className="rounded-full bg-white/8 px-2.5 py-1 text-xs">{phaseText(data)}</span>}
        {data.data_as_of && <span className="text-xs text-rt-fg-tertiary">Data as of {date(data.data_as_of)}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[13px] text-rt-fg-tertiary">
        <span>Start {date(data.start_date)}</span><span>→</span><span>End {data.end_date ? date(data.end_date) : "not set"}</span>
        {!editingEndDate && <><button type="button" className="text-rt-magenta" onClick={() => { editCampaign.reset(); setEndDateDraft(data.end_date || ""); setEditingEndDate(true) }}>{data.end_date ? "Change" : "Set an end date"}</button>{data.end_date && <button type="button" className="text-rt-magenta" onClick={() => editCampaign.mutate({ end_date: "" })}>Clear</button>}</>}
        {editingEndDate && <><Input aria-label="End date" type="date" min={data.start_date} value={endDateDraft} className="h-8 w-auto" disabled={editCampaign.isPending} onChange={(e) => setEndDateDraft(e.target.value)} /><Button size="sm" disabled={editCampaign.isPending || !endDateDraft} onClick={() => editCampaign.mutate({ end_date: endDateDraft }, { onSuccess: () => setEditingEndDate(false) })}>Save</Button><button type="button" onClick={() => { editCampaign.reset(); setEditingEndDate(false) }}>Cancel</button></>}
        <span>→</span><span>Follow-up ends {data.followup_end ? date(data.followup_end) : "—"}</span>
        {editCampaign.isError && <span role="alert" className="text-red-400">{editCampaign.error?.message}</span>}
      </div>
      {headline(data) && <p className="text-[12px] text-rt-fg-tertiary">{headline(data)}</p>}
      <div className="overflow-x-auto"><table className="w-full min-w-[520px] text-[12px]"><thead className="text-rt-fg-tertiary"><tr><th className="text-left font-normal">Metric</th>{["Start", "End", "+28 days", "Now"].map(x => <th className="text-right font-normal" key={x}>{x}</th>)}</tr></thead><tbody>
        {([[
          "Popularity", pop?.start, pop?.end, pop?.followup, pop?.now, pop?.end_is_to_date, pop?.followup_is_to_date, pop?.change_campaign, pop?.change_followup, pop?.change_since_end,
        ], [
          "Streams", streams?.start_total, streams?.end_total, streams?.followup_total, streams?.now, streams?.end_is_to_date, streams?.followup_is_to_date, streams?.gained_campaign, streams?.gained_followup, streams?.change_since_end,
        ], [
          "TikTok videos", data.ugc?.start_total, data.ugc?.end_total, data.ugc?.followup_total, data.ugc?.now, data.ugc?.end_is_to_date, data.ugc?.followup_is_to_date, data.ugc?.gained_campaign, data.ugc?.gained_followup, data.ugc?.change_since_end,
        ]] as const).map(([label, a, b, c, d, endTd, followTd, changeCampaign, changeFollowup, changeNow]) => <tr key={label} className="border-t border-white/8"><th className="py-1.5 text-left font-medium">{label}</th>{[a,b,c,d].map((value,i) => {
          const change = i === 1 ? changeCampaign : i === 2 ? changeFollowup : i === 3 ? changeNow : null
          return <td key={i} className="py-1.5 text-right tabular-nums">{value == null ? "—" : label === "Popularity" ? num(value) : compact(value)}{i === 1 && endTd && <span className="ml-1 text-[10px] text-rt-fg-tertiary">to date</span>}{i === 2 && followTd && <span className="ml-1 text-[10px] text-rt-fg-tertiary">to date</span>}{i === 3 && d != null && d === c && <span className="ml-1 text-[10px] text-rt-fg-tertiary">same</span>}{change != null && <span className="block text-[10px] text-rt-fg-tertiary">{change > 0 ? "+" : ""}{label === "Popularity" ? num(change) : compact(change)}</span>}</td>
        })}</tr>)}
      </tbody></table></div>
      {!data.streams_error && <p className="text-[11px] text-rt-fg-tertiary">Daily streams {compact(streams?.baseline_daily)} → {compact(streams?.campaign_daily)} during ({pct(streams?.lift_pct_campaign)}){streams?.followup_daily != null ? ` → ${compact(streams.followup_daily)} after` : ""}</p>}
      {!data.ugc_error && <p className="text-[11px] text-rt-fg-tertiary">New TikTok videos/day {compact(data.ugc?.baseline_daily)} → {compact(data.ugc?.campaign_daily)} during ({pct(data.ugc?.lift_pct_campaign)}){data.ugc?.followup_daily != null ? ` → ${compact(data.ugc.followup_daily)} after` : ""}{data.ugc?.gained_campaign != null ? ` · ${compact(data.ugc.gained_campaign)} new during the campaign` : ""}</p>}
      <div><button type="button" className="text-[12px] text-rt-fg-tertiary hover:text-rt-fg" onClick={() => setShowTrend(v => !v)}>{showTrend ? "Hide trend" : "Show trend"}</button>{showTrend && <div className="mt-2"><PopScoreChart data={data} /></div>}</div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-3 text-[12px] text-rt-fg-tertiary"><span>Shows what happened to the song around the campaign — not proof the campaign caused all of it.</span>{tracker_url && <a href={tracker_url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap text-rt-magenta hover:underline">Open Tides Tracker ↗</a>}</div>
    </>}
    {showForm && <>{!data?.linked && !popScore.isError && <p className="text-rt-fg-tertiary text-[13px]">Link the song to track its Spotify popularity through this campaign.</p>}<TrackLinkForm initial={data?.link ?? ""} onSave={save} onCancel={editing ? () => setEditing(false) : undefined} isPending={setTrack.isPending} error={setTrack.isError ? setTrack.error?.message : undefined} /></>}
  </div>
}

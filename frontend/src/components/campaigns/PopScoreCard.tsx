import { useState } from "react"
import {
  Area, AreaChart, Line, LineChart, ReferenceLine, ResponsiveContainer,
  Tooltip as RTooltip, XAxis, YAxis,
} from "recharts"
import { AlertCircle, Loader2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useEditCampaign, usePopScore, useSetPopScoreTrack } from "@/lib/queries"
import type { PopScore } from "@/lib/types"
import { chartAxisProps, chartTooltipProps } from "./chartDate"

const ACCENT = "#E100C3"
const AXIS = "#909098"
const POPULARITY_AXIS_WIDTH = 54
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
const signedCompact = (v: number | null | undefined) => v == null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${compact(Math.abs(v))}`
const date = (v?: string) => v ? new Date(`${v}T00:00:00`).toLocaleDateString("en", { month: "short", day: "numeric", year: "numeric" }) : "—"

function phaseText(data: PopScore) {
  if (data.phase === "followup") {
    return data.followup_day == null ? undefined : `Follow-up (day ${data.followup_day} of ${data.followup_days ?? 28})`
  }
  return ({ live: "Live", complete: "Complete", not_started: "Not started", no_start: "Not started" } as Record<string, string>)[data.phase ?? ""]
}

function PopScoreChart({ data }: { data: PopScore }) {
  const [mode, setMode] = useState<"popularity" | "streams">("popularity")
  const points = (mode === "popularity" ? (data.history ?? []).map((p) => ({ date: p.date, value: p.value })) : (data.streams_history ?? []).map((p) => ({ date: p.date, value: p.daily }))).filter(p => p.value != null).map(p => ({ ...p, time: new Date(`${p.date}T00:00:00`).getTime() }))
  const min = points.length ? Math.min(...points.map(p => p.time)) : 0
  const max = points.length ? Math.max(...points.map(p => p.time)) : 0
  const sameBounds = !!data.start_date && data.start_date === data.end_date
  const lines = [data.start_date, sameBounds ? "" : data.end_date, data.followup_end].map((d, i) => ({ date: d, label: [sameBounds ? "Start/End" : "Start", "End", "Follow-up"][i] })).filter((p): p is {date: string; label: string} => !!p.date).filter(p => new Date(`${p.date}T00:00:00`).getTime() >= min && new Date(`${p.date}T00:00:00`).getTime() <= max)
  return <div className="space-y-2">
    <div className="flex gap-1" role="group" aria-label="Chart metric">
      <button type="button" aria-pressed={mode === "popularity"} onClick={() => setMode("popularity")} className={`rounded px-2 py-1 text-xs ${mode === "popularity" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Popularity</button>
      <button type="button" aria-pressed={mode === "streams"} onClick={() => setMode("streams")} className={`rounded px-2 py-1 text-xs ${mode === "streams" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Daily streams</button>
    </div>
    {points.length < 2 ? <p className="text-rt-fg-tertiary text-[13px]">Not enough history yet to chart.</p> : <div className="h-36 w-full" data-testid="attribution-chart" data-plotted-values={points.map(p => p.value).join(",")} data-reference-labels={lines.map(line => line.label).join(",")} aria-label={mode === "popularity" ? "Popularity chart" : "Daily streams chart"}>
      <ResponsiveContainer width="100%" height="100%">
        {mode === "popularity" ? <LineChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <XAxis type="number" dataKey="time" domain={["dataMin", "dataMax"]} tick={{ fill: AXIS, fontSize: 10 }} {...chartAxisProps} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis width={POPULARITY_AXIS_WIDTH} domain={[0, 100]} tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <RTooltip {...chartTooltipProps} /><Line type="stepAfter" dataKey="value" stroke={ACCENT} strokeWidth={2} dot={false} />
          {lines.map(({date: d, label}) => <ReferenceLine key={`${label}-${d}`} x={new Date(`${d}T00:00:00`).getTime()} stroke={AXIS} strokeDasharray="3 3" label={{ value: label, fill: AXIS, fontSize: 10 }} />)}
        </LineChart> : <AreaChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
          <XAxis type="number" dataKey="time" domain={["dataMin", "dataMax"]} tick={{ fill: AXIS, fontSize: 10 }} {...chartAxisProps} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis width={STREAMS_AXIS_WIDTH} tickFormatter={(v: number) => Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 }).format(v)} tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <RTooltip {...chartTooltipProps} /><Area type="monotone" dataKey="value" stroke={ACCENT} fill={ACCENT} fillOpacity={0.18} connectNulls />
          {lines.map(({date: d, label}) => <ReferenceLine key={`${label}-${d}`} x={new Date(`${d}T00:00:00`).getTime()} stroke={AXIS} strokeDasharray="3 3" label={{ value: label, fill: AXIS, fontSize: 10 }} />)}
        </AreaChart>}
      </ResponsiveContainer>
    </div>}
  </div>
}

function MetricRow({ title, start, end, followup, change, endToDate, followupToDate, noEnd }: {
  title: string; start: string; end: string; followup: string; change: string
  endToDate?: boolean; followupToDate?: boolean; noEnd?: boolean
}) {
  const cells = [["Start", start, false], ["End", end, !!endToDate], ["Follow-up", followup, !!followupToDate]] as const
  return <section className="space-y-2"><div className="flex flex-wrap items-center gap-2"><h4 className="text-[13px] font-medium">{title}</h4><span className="text-[11px] text-rt-fg-tertiary">{change}</span></div>
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">{cells.map(([label, value, toDate]) => <div key={label} className="rounded-md bg-white/[0.03] px-3 py-2">
      <div className="text-[11px] text-rt-fg-tertiary">{label}{toDate && <span className="ml-1">to date</span>}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      {label === "Follow-up" && noEnd && <div className="text-[11px] text-rt-fg-tertiary">Set an end date</div>}
    </div>)}</div>
  </section>
}

export function PopScoreCard({ slug, tracker_url }: { slug: string; tracker_url?: string }) {
  const popScore = usePopScore(slug)
  const setTrack = useSetPopScoreTrack(slug)
  const editCampaign = useEditCampaign(slug)
  const [editing, setEditing] = useState(false)
  const [endDateDraft, setEndDateDraft] = useState("")
  const [editingEndDate, setEditingEndDate] = useState(false)
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
      <div className="flex flex-wrap items-center gap-3">
        {data.track?.image_url && <img src={data.track.image_url} alt="" className="size-12 rounded object-cover" />}
        <div className="min-w-0 flex-1"><div className="font-medium">{data.track?.name ?? "Linked track"}</div><div className="text-[13px] text-rt-fg-tertiary">{data.track?.artists?.join(", ")}</div></div>
        {phaseText(data) && <span className="rounded-full bg-white/8 px-2.5 py-1 text-xs">{phaseText(data)}</span>}
        {data.data_as_of && <span className="text-xs text-rt-fg-tertiary">Data as of {date(data.data_as_of)}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[13px] text-rt-fg-tertiary">
        <span>Start {date(data.start_date)}</span><span>→</span><span>End {data.end_date ? date(data.end_date) : "not set"}</span>
        {!editingEndDate && <><button type="button" className="text-rt-magenta" onClick={() => { setEndDateDraft(data.end_date || ""); setEditingEndDate(true) }}>{data.end_date ? "Change" : "Set an end date"}</button>{data.end_date && <button type="button" className="text-rt-magenta" onClick={() => editCampaign.mutate({ end_date: "" })}>Clear</button>}</>}
        {editingEndDate && <><Input aria-label="End date" type="date" min={data.start_date} value={endDateDraft} className="h-8 w-auto" disabled={editCampaign.isPending} onChange={(e) => setEndDateDraft(e.target.value)} /><Button size="sm" disabled={editCampaign.isPending || !endDateDraft} onClick={() => editCampaign.mutate({ end_date: endDateDraft }, { onSuccess: () => setEditingEndDate(false) })}>Save</Button><button type="button" onClick={() => setEditingEndDate(false)}>Cancel</button></>}
        <span>→</span><span>Follow-up ends {data.followup_end ? date(data.followup_end) : "—"}</span>
        {editCampaign.isError && <span role="alert" className="text-red-400">{editCampaign.error?.message}</span>}
      </div>
      <MetricRow title="Popularity" start={num(pop?.start)} end={num(pop?.end)} followup={data.end_date ? num(pop?.followup) : "—"} change={`${pop?.change_campaign == null ? "N/A" : `${pop.change_campaign > 0 ? "+" : ""}${pop.change_campaign} pts`} · follow-up ${pop?.change_followup == null ? "N/A" : `${pop.change_followup > 0 ? "+" : ""}${pop.change_followup} pts`}`} endToDate={pop?.end_is_to_date} followupToDate={pop?.followup_is_to_date} noEnd={!data.end_date} />
      {data.streams_error ? <div className="text-xs text-rt-fg-tertiary" role="status">{data.streams_error}</div> : <><MetricRow title="Streams" start={compact(streams?.start_total)} end={compact(streams?.end_total)} followup={data.end_date ? compact(streams?.followup_total) : "—"} change={`${signedCompact(streams?.gained_campaign)} during · ${signedCompact(streams?.gained_followup)} after · Growth during campaign: ${pct(streams?.growth_pct_campaign)}`} endToDate={streams?.end_is_to_date} followupToDate={streams?.followup_is_to_date} noEnd={!data.end_date} />
      <div className="rounded-md bg-white/[0.03] px-3 py-2 text-[13px]"><span className="font-medium">Impact</span><div className="mt-1 flex flex-col gap-1 text-rt-fg-tertiary sm:flex-row sm:flex-wrap sm:gap-2">
        <span>Avg daily streams — before {compact(streams?.baseline_daily)} · during {compact(streams?.campaign_daily)} ({pct(streams?.lift_pct_campaign)}) · after {data.end_date ? `${compact(streams?.followup_daily)} (${pct(streams?.lift_pct_followup)} vs before)` : "Set an end date"}</span></div></div></>}
      <PopScoreChart data={data} />
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-3 text-[12px] text-rt-fg-tertiary"><span>Shows what happened to the song around the campaign — not proof the campaign caused all of it.</span>{tracker_url && <a href={tracker_url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap text-rt-magenta hover:underline">Open Tides Tracker ↗</a>}</div>
    </>}
    {showForm && <>{!data?.linked && !popScore.isError && <p className="text-rt-fg-tertiary text-[13px]">Link the song to track its Spotify popularity through this campaign.</p>}<TrackLinkForm initial={data?.link ?? ""} onSave={save} onCancel={editing ? () => setEditing(false) : undefined} isPending={setTrack.isPending} error={setTrack.isError ? setTrack.error?.message : undefined} /></>}
  </div>
}

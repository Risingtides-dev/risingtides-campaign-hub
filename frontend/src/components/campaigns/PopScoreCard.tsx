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

const ACCENT = "#E100C3"
const AXIS = "#909098"

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
    const start = data.end_date ? new Date(`${data.end_date}T00:00:00`) : null
    const now = new Date(`${(data.data_as_of || new Date().toISOString().slice(0, 10))}T00:00:00`)
    const day = start ? Math.max(1, Math.floor((now.getTime() - start.getTime()) / 86400000) + 1) : 1
    return `Follow-up (day ${Math.min(day, data.followup_days ?? 28)} of ${data.followup_days ?? 28})`
  }
  return ({ live: "Live", complete: "Complete", not_started: "Not started", no_start: "Not started" } as Record<string, string>)[data.phase ?? "live"]
}

function PopScoreChart({ data }: { data: PopScore }) {
  const [mode, setMode] = useState<"popularity" | "streams">("popularity")
  const points: { date: string; value: number | null }[] = mode === "popularity"
    ? (data.history ?? []).map((p) => ({ date: p.date, value: p.value }))
    : (data.streams_history ?? []).map((p) => ({ date: p.date, value: p.daily }))
  const lines = [data.start_date, data.end_date, data.followup_end].filter((d): d is string => !!d)
  return <div className="space-y-2">
    <div className="flex gap-1" role="group" aria-label="Chart metric">
      <button type="button" aria-pressed={mode === "popularity"} onClick={() => setMode("popularity")} className={`rounded px-2 py-1 text-xs ${mode === "popularity" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Popularity</button>
      <button type="button" aria-pressed={mode === "streams"} onClick={() => setMode("streams")} className={`rounded px-2 py-1 text-xs ${mode === "streams" ? "bg-white/10 text-rt-fg" : "text-rt-fg-tertiary"}`}>Daily streams</button>
    </div>
    {points.length < 2 ? <p className="text-rt-fg-tertiary text-[13px]">Not enough history yet to chart.</p> : <div className="h-36 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {mode === "popularity" ? <LineChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: -24 }}>
          <XAxis dataKey="date" tick={{ fill: AXIS, fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis domain={[0, 100]} tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <RTooltip /><Line type="stepAfter" dataKey="value" stroke={ACCENT} strokeWidth={2} dot={false} />
          {lines.map((d, i) => <ReferenceLine key={d} x={d} stroke={AXIS} strokeDasharray="3 3" label={{ value: ["Start", "End", "Follow-up"][i], fill: AXIS, fontSize: 10 }} />)}
        </LineChart> : <AreaChart data={points} margin={{ top: 6, right: 8, bottom: 0, left: -24 }}>
          <XAxis dataKey="date" tick={{ fill: AXIS, fontSize: 10 }} tickFormatter={(d: string) => d.slice(5)} axisLine={false} tickLine={false} minTickGap={24} />
          <YAxis tick={{ fill: AXIS, fontSize: 10 }} axisLine={false} tickLine={false} />
          <RTooltip /><Area type="monotone" dataKey="value" stroke={ACCENT} fill={ACCENT} fillOpacity={0.18} connectNulls />
          {lines.map((d, i) => <ReferenceLine key={d} x={d} stroke={AXIS} strokeDasharray="3 3" label={{ value: ["Start", "End", "Follow-up"][i], fill: AXIS, fontSize: 10 }} />)}
        </AreaChart>}
      </ResponsiveContainer>
    </div>}
  </div>
}

function MetricRow({ title, start, end, followup, change, compactValues = false, endToDate, followupToDate, noEnd }: {
  title: string; start: string; end: string; followup: string; change: string
  compactValues?: boolean; endToDate?: boolean; followupToDate?: boolean; noEnd?: boolean
}) {
  const cells = [["Start", start, false], ["End", end, !!endToDate], ["Follow-up", followup, !!followupToDate]] as const
  return <section className="space-y-2"><div className="flex flex-wrap items-center gap-2"><h4 className="text-[13px] font-medium">{title}</h4><span className="text-[11px] text-rt-fg-tertiary">{change}</span></div>
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">{cells.map(([label, value, toDate]) => <div key={label} className="rounded-md bg-white/[0.03] px-3 py-2">
      <div className="text-[11px] text-rt-fg-tertiary">{label}{toDate && <span className="ml-1">to date</span>}</div>
      <div className={`text-lg font-semibold tabular-nums ${compactValues ? "" : ""}`}>{value}</div>
      {label === "Follow-up" && noEnd && <div className="text-[11px] text-rt-fg-tertiary">Set an end date</div>}
    </div>)}</div>
  </section>
}

export function PopScoreCard({ slug, tracker_url }: { slug: string; tracker_url?: string }) {
  const popScore = usePopScore(slug)
  const setTrack = useSetPopScoreTrack(slug)
  const editCampaign = useEditCampaign(slug)
  const [editing, setEditing] = useState(false)
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
        <span className="rounded-full bg-white/8 px-2.5 py-1 text-xs">{phaseText(data)}</span>
        {data.data_as_of && <span className="text-xs text-rt-fg-tertiary">Data as of {date(data.data_as_of)}</span>}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-[13px] text-rt-fg-tertiary">
        <span>Start {date(data.start_date)}</span><span>→</span><span>End {data.end_date ? date(data.end_date) : "not set"}</span>
        {!data.end_date && <label className="inline-flex items-center gap-1 text-rt-magenta">Set an end date<Input aria-label="Set an end date" type="date" className="h-8 w-auto" disabled={editCampaign.isPending} onChange={(e) => e.target.value && editCampaign.mutate({ end_date: e.target.value })} /></label>}
        <span>→</span><span>Follow-up ends {data.followup_end ? date(data.followup_end) : "—"}</span>
        {editCampaign.isError && <span className="text-red-400">{editCampaign.error?.message}</span>}
      </div>
      <MetricRow title="Popularity" start={num(pop?.start)} end={num(pop?.end)} followup={data.end_date ? num(pop?.followup) : "—"} change={`${pop?.change_campaign == null ? "N/A" : `${pop.change_campaign > 0 ? "+" : ""}${pop.change_campaign} pts`} · follow-up ${pop?.change_followup == null ? "N/A" : `${pop.change_followup > 0 ? "+" : ""}${pop.change_followup} pts`}`} endToDate={pop?.end_is_to_date} followupToDate={pop?.followup_is_to_date} noEnd={!data.end_date} />
      <MetricRow title="Streams" start={compact(streams?.start_total)} end={compact(streams?.end_total)} followup={data.end_date ? compact(streams?.followup_total) : "—"} change={`Growth during campaign: ${pct(streams?.growth_pct_campaign)}`} compactValues endToDate={streams?.end_is_to_date} followupToDate={streams?.followup_is_to_date} noEnd={!data.end_date} />
      <div className="rounded-md bg-white/[0.03] px-3 py-2 text-[13px]"><span className="font-medium">Impact</span><div className="mt-1 flex flex-col gap-1 text-rt-fg-tertiary sm:flex-row sm:flex-wrap sm:gap-2">
        <span>Avg daily streams — before {compact(streams?.baseline_daily)} · during {compact(streams?.campaign_daily)} ({pct(streams?.lift_pct_campaign)}) · after {data.end_date ? `${compact(streams?.followup_daily)} (${pct(streams?.lift_pct_followup)} vs before)` : "Set an end date"}</span></div></div>
      <PopScoreChart data={data} />
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-3 text-[12px] text-rt-fg-tertiary"><span>Shows what happened to the song around the campaign — not proof the campaign caused all of it.</span>{tracker_url && <a href={tracker_url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap text-rt-magenta hover:underline">Open Tides Tracker ↗</a>}</div>
    </>}
    {showForm && <>{!data?.linked && !popScore.isError && <p className="text-rt-fg-tertiary text-[13px]">Link the song to track its Spotify popularity through this campaign.</p>}<TrackLinkForm initial={data?.link ?? ""} onSave={save} onCancel={editing ? () => setEditing(false) : undefined} isPending={setTrack.isPending} error={setTrack.isError ? setTrack.error?.message : undefined} /></>}
  </div>
}

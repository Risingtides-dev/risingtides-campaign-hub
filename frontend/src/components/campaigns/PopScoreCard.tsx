import { useState } from "react"
import {
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip as RTooltip,
  XAxis,
  YAxis,
} from "recharts"
import { AlertCircle, Loader2, Pencil } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { usePopScore, useSetPopScoreTrack } from "@/lib/queries"
import type { PopScore } from "@/lib/types"

const ACCENT = "#E100C3"
const AXIS = "#909098"

function formatDelta(delta: number | null | undefined) {
  if (delta === null || delta === undefined) return null
  if (delta === 0) return { text: "±0 since start", cls: "text-rt-fg-tertiary" }
  return delta > 0
    ? { text: `+${delta} since start`, cls: "text-emerald-400" }
    : { text: `${delta} since start`, cls: "text-red-400" }
}

function TrackLinkForm({
  initial,
  onSave,
  onCancel,
  isPending,
  error,
}: {
  initial: string
  onSave: (link: string) => void
  onCancel?: () => void
  isPending: boolean
  error?: string
}) {
  const [link, setLink] = useState(initial)
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault()
        onSave(link.trim())
      }}
    >
      <Input
        value={link}
        onChange={(e) => setLink(e.target.value)}
        placeholder="Spotify track link, Chartmetric link, or ISRC"
        aria-label="Song link for pop score"
        className="w-full sm:w-[380px] h-9 text-[13px]"
      />
      <Button type="submit" size="sm" disabled={isPending}>
        {isPending ? <Loader2 className="size-4 animate-spin" /> : "Save"}
      </Button>
      {onCancel && (
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      )}
      {error && <p className="w-full text-red-500 text-[13px]">{error}</p>}
    </form>
  )
}

function PopScoreChart({ data }: { data: PopScore }) {
  const history = data.history ?? []
  if (history.length < 2) {
    return <p className="text-rt-fg-tertiary text-[13px]">Not enough history yet to chart.</p>
  }
  const startInRange = data.start_date && history.some((p) => p.date <= data.start_date!)
  return (
    <div className="h-36 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={history} margin={{ top: 6, right: 8, bottom: 0, left: -24 }}>
          <XAxis
            dataKey="date"
            tick={{ fill: AXIS, fontSize: 10 }}
            tickFormatter={(d: string) => d.slice(5)}
            axisLine={false}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis
            domain={["dataMin - 3", "dataMax + 3"]}
            allowDecimals={false}
            tick={{ fill: AXIS, fontSize: 10 }}
            axisLine={false}
            tickLine={false}
          />
          <RTooltip
            contentStyle={{
              background: "#0A0A0A",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 12,
              fontSize: 12,
            }}
            labelStyle={{ color: "#FAFCFF" }}
            formatter={(v) => [v, "Pop score"]}
          />
          {startInRange && (
            <ReferenceLine
              x={data.start_date}
              stroke={AXIS}
              strokeDasharray="3 3"
              label={{ value: "Start", fill: AXIS, fontSize: 10, position: "insideTopLeft" }}
            />
          )}
          <Line type="stepAfter" dataKey="value" stroke={ACCENT} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

export function PopScoreCard({ slug }: { slug: string }) {
  const popScore = usePopScore(slug)
  const setTrack = useSetPopScoreTrack(slug)
  const [editing, setEditing] = useState(false)

  const save = (link: string) =>
    setTrack.mutate(link, { onSuccess: () => setEditing(false) })
  const saveError = setTrack.isError ? setTrack.error?.message : undefined

  const header = (
    <div className="flex items-center justify-between mb-3">
      <h3 className="text-[15px] font-semibold">Pop Score</h3>
      {popScore.data?.linked && !editing && (
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-rt-fg-tertiary hover:text-rt-fg transition-colors"
          title="Change song"
          aria-label="Change song"
        >
          <Pencil className="size-3.5" />
        </button>
      )}
    </div>
  )

  if (popScore.isLoading) {
    return (
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5">
        {header}
        <div className="flex items-center gap-2 text-rt-fg-tertiary text-sm py-2">
          <Loader2 className="size-4 animate-spin" /> Loading Chartmetric…
        </div>
      </div>
    )
  }

  const data = popScore.data
  const showForm = editing || popScore.isError || !data?.linked

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5 space-y-3">
      {header}
      {popScore.isError && (
        <div className="flex items-center gap-2 text-red-500 text-sm">
          <AlertCircle className="size-4" />
          {popScore.error?.message || "Couldn't load pop score"}
        </div>
      )}
      {!popScore.isError && data?.linked && !editing && (
        <>
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <span className="text-3xl font-semibold tabular-nums">
              {data.spotify_popularity ?? "—"}
            </span>
            {(() => {
              const d = formatDelta(data.change_since_start)
              return d && <span className={`text-[13px] ${d.cls}`}>{d.text}</span>
            })()}
            <span className="text-rt-fg-tertiary text-[13px]">
              {data.track?.name}
              {data.track?.artists?.length ? ` · ${data.track.artists.join(", ")}` : ""}
            </span>
          </div>
          <p className="text-rt-fg-tertiary text-[12px]">
            Spotify popularity (0–100) via Chartmetric
            {typeof data.chartmetric_score === "number" &&
              ` · Chartmetric score ${data.chartmetric_score.toFixed(1)}`}
          </p>
          <PopScoreChart data={data} />
        </>
      )}
      {showForm && (
        <>
          {!data?.linked && !popScore.isError && (
            <p className="text-rt-fg-tertiary text-[13px]">
              Link the song to track its Spotify popularity through this campaign.
            </p>
          )}
          <TrackLinkForm
            initial={data?.link ?? ""}
            onSave={save}
            onCancel={editing ? () => setEditing(false) : undefined}
            isPending={setTrack.isPending}
            error={saveError}
          />
        </>
      )}
    </div>
  )
}

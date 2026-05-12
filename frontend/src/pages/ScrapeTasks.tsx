import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  useScrapeTaskQueue,
  useScrapeTaskHealth,
  useMarkVideosTracked,
  useUnmarkVideosTracked,
  useMarkCampaignTracked,
  useDismissVideos,
  useTriggerCron,
} from "@/lib/queries"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Copy, Check, ExternalLink, RefreshCw, AlertTriangle, X, Undo2 } from "lucide-react"
import type { ScrapeTaskCampaign, ScrapeTaskVideo } from "@/lib/types"

/**
 * Scrape Tasks tab — by-campaign default organization.
 *
 * The person doing tracking work opens this tab once per day:
 * 1. Glances at the health panel — is yesterday's cron healthy?
 * 2. Picks the campaign with the most untracked links
 * 3. Copies links into Cobrand, ticks the checkbox, moves on
 * 4. Repeats per campaign until queue is empty
 */
export default function ScrapeTasks() {
  const [search, setSearch] = useState("")
  const [trackedBy, setTrackedBy] = useState("")

  const queueQ = useScrapeTaskQueue()
  const healthQ = useScrapeTaskHealth()
  const markMut = useMarkVideosTracked()
  const unmarkMut = useUnmarkVideosTracked()
  const markCampaignMut = useMarkCampaignTracked()
  const dismissMut = useDismissVideos()
  const triggerMut = useTriggerCron()

  const filtered = useMemo(() => {
    if (!queueQ.data) return [] as ScrapeTaskCampaign[]
    const q = search.trim().toLowerCase()
    if (!q) return queueQ.data.campaigns
    return queueQ.data.campaigns.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        c.artist.toLowerCase().includes(q) ||
        c.song.toLowerCase().includes(q)
    )
  }, [queueQ.data, search])

  const totalUntracked = queueQ.data?.total_untracked ?? 0

  const lastRunDegraded = healthQ.data?.history?.[0]?.degraded ?? false
  const lastRunStarted = healthQ.data?.history?.[0]?.started_at ?? ""
  const lastRunMatches = healthQ.data?.history?.[0]?.total_new_matches ?? 0
  const lastRunEmptyRate = healthQ.data?.history?.[0]?.empty_creator_rate ?? 0

  return (
    <div className="px-6 py-6 max-w-[1400px] mx-auto">
      <div className="flex items-baseline justify-between mb-4">
        <div>
          <h1 className="text-2xl font-bold text-[#1a1a2e]">Scrape Tasks</h1>
          <p className="text-sm text-[#666] mt-1">
            New matched links to copy into Cobrand. Organized by campaign.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            placeholder="Filter campaigns…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-56"
          />
          <Input
            placeholder="Your name (optional)"
            value={trackedBy}
            onChange={(e) => setTrackedBy(e.target.value)}
            className="w-44"
            title="Recorded as 'tracked_by' so you can see who handled what."
          />
        </div>
      </div>

      {/* Health panel */}
      <Card className="p-4 mb-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            {lastRunDegraded ? (
              <Badge className="bg-[#fff1c8] text-[#a16100] border-[#f4d169] gap-1">
                <AlertTriangle size={14} />
                DEGRADED
              </Badge>
            ) : (
              <Badge className="bg-[#dcf6dc] text-[#226e22] border-[#9ad59a]">
                Healthy
              </Badge>
            )}
            <span className="text-sm text-[#444]">
              Last run: {lastRunStarted ? new Date(lastRunStarted).toLocaleString() : "—"}
            </span>
            <span className="text-sm text-[#666]">
              {lastRunMatches} new matches • {Math.round(lastRunEmptyRate * 100)}% empty rate
            </span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-sm text-[#444] font-medium">
              {totalUntracked} untracked
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={triggerMut.isPending}
              onClick={() => triggerMut.mutate("campaign_refresh")}
              title="Trigger a campaign refresh now (yt-dlp profile scrape)"
            >
              <RefreshCw size={14} className={triggerMut.isPending ? "animate-spin" : ""} />
              {triggerMut.isPending ? "Running…" : "Run cron now"}
            </Button>
          </div>
        </div>
        {lastRunDegraded && (
          <div className="mt-3 px-3 py-2 bg-[#fff8e8] border border-[#f4d169] rounded text-sm text-[#7a4a00]">
            The last cron run produced no useful data — TikTok likely
            rate-limited the scraper. Today's queue may be incomplete. Re-run
            cron or wait for tomorrow's scheduled run.
          </div>
        )}
      </Card>

      {/* Queue */}
      {queueQ.isLoading && (
        <div className="text-sm text-[#666] py-12 text-center">Loading…</div>
      )}
      {queueQ.isError && (
        <div className="text-sm text-red-600 py-12 text-center">
          Failed to load queue. Try refreshing.
        </div>
      )}
      {!queueQ.isLoading && filtered.length === 0 && (
        <Card className="p-12 text-center text-[#666]">
          {search ? (
            <>No campaigns match "{search}".</>
          ) : (
            <>
              <div className="text-base font-medium text-[#444] mb-1">
                Queue is clear.
              </div>
              <div className="text-sm">
                No untracked links right now. Next cron run is at 6 AM EST.
              </div>
            </>
          )}
        </Card>
      )}

      <div className="flex flex-col gap-3">
        {filtered.map((camp) => (
          <CampaignBlock
            key={camp.slug}
            camp={camp}
            trackedBy={trackedBy}
            onMark={(ids) =>
              markMut.mutate({ ids, tracked_by: trackedBy })
            }
            onUnmark={(ids) => unmarkMut.mutate(ids)}
            onMarkAll={() =>
              markCampaignMut.mutate({ slug: camp.slug, tracked_by: trackedBy })
            }
            onDismiss={(ids, reason) =>
              dismissMut.mutate({
                ids,
                dismissed_by: trackedBy,
                reason,
              })
            }
            isMarking={markMut.isPending || markCampaignMut.isPending}
            isDismissing={dismissMut.isPending}
          />
        ))}
      </div>
    </div>
  )
}

function CampaignBlock({
  camp,
  onMark,
  onUnmark,
  onMarkAll,
  onDismiss,
  isMarking,
  isDismissing,
}: {
  camp: ScrapeTaskCampaign
  trackedBy: string
  onMark: (ids: number[]) => void
  onUnmark: (ids: number[]) => void
  onMarkAll: () => void
  onDismiss: (ids: number[], reason?: string) => void
  isMarking: boolean
  isDismissing: boolean
}) {
  const [open, setOpen] = useState(true)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  // Optimistic local "just ticked" state — keeps rows visible (greyed) so
  // he can see what he's marked and undo accidental clicks. Pruned when
  // a refetch confirms the row has left the queue server-side.
  const [locallyTicked, setLocallyTicked] = useState<Set<number>>(new Set())

  const videoIdSet = useMemo(
    () => new Set(camp.videos.map((v) => v.id)),
    [camp.videos]
  )
  useEffect(() => {
    setLocallyTicked((prev) => {
      let changed = false
      const next = new Set<number>()
      for (const id of prev) {
        if (videoIdSet.has(id)) next.add(id)
        else changed = true
      }
      return changed ? next : prev
    })
  }, [videoIdSet])

  const markIds = (ids: number[]) => {
    setLocallyTicked((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.add(id))
      return next
    })
    onMark(ids)
  }

  const undoMarkIds = (ids: number[]) => {
    setLocallyTicked((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.delete(id))
      return next
    })
    onUnmark(ids)
  }

  const markAllLocal = () => {
    setLocallyTicked((prev) => {
      const next = new Set(prev)
      camp.videos.forEach((v) => next.add(v.id))
      return next
    })
    onMarkAll()
  }

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const totalViews = camp.videos.reduce((acc, v) => acc + (v.views || 0), 0)
  const fuzzy = camp.videos.filter((v) => v.match_strategy && v.match_strategy !== "sound_id")
  const fuzzyCount = fuzzy.length

  return (
    <Card className="overflow-hidden">
      {/* Campaign header */}
      <div
        className="px-4 py-3 flex items-center justify-between cursor-pointer hover:bg-[#fafafd]"
        onClick={() => setOpen(!open)}
      >
        <div className="flex items-center gap-3 min-w-0">
          <span className="text-base font-semibold text-[#1a1a2e] truncate">
            {camp.title}
          </span>
          <Badge variant="outline" className="text-xs">
            {camp.untracked_count} untracked
          </Badge>
          {camp.match_strategy === "strict" && (
            <Badge className="bg-[#dee9ff] text-[#0b62d6] border-[#a5c0f0] text-xs">
              strict
            </Badge>
          )}
          {fuzzyCount > 0 && camp.match_strategy !== "strict" && (
            <Badge
              className="bg-[#fff1c8] text-[#a16100] border-[#f4d169] text-xs"
              title="These matches came from fuzzy fallback — verify each one"
            >
              {fuzzyCount} fuzzy
            </Badge>
          )}
          {camp.round && (
            <Badge variant="outline" className="text-xs uppercase">
              {camp.round}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className="text-sm text-[#666]">
            {totalViews.toLocaleString()} views
          </span>
          <Link
            to={`/campaign/${camp.slug}`}
            onClick={(e) => e.stopPropagation()}
            className="text-xs text-[#0b62d6] hover:underline"
          >
            open campaign
          </Link>
        </div>
      </div>

      {open && (
        <div className="border-t border-[#e8e8ef]">
          {/* Bulk action bar */}
          <div className="px-4 py-2 bg-[#fafafd] border-b border-[#e8e8ef] flex items-center justify-between">
            <div className="flex items-center gap-3 text-sm">
              <span className="text-[#666]">
                {selected.size > 0
                  ? `${selected.size} selected`
                  : `${camp.videos.length} link(s)`}
              </span>
              {selected.size > 0 && (
                <>
                  <Button
                    size="sm"
                    onClick={() => {
                      markIds(Array.from(selected))
                      setSelected(new Set())
                    }}
                    disabled={isMarking}
                  >
                    <Check size={14} />
                    Mark {selected.size} tracked
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    className="border-[#f1c8c8] text-[#a13434] hover:bg-[#fceaea]"
                    onClick={() => {
                      const reason = window.prompt(
                        `Dismiss ${selected.size} match(es) as bad? Optional reason:`,
                        ""
                      )
                      if (reason === null) return
                      onDismiss(Array.from(selected), reason.trim() || undefined)
                      setSelected(new Set())
                    }}
                    disabled={isDismissing}
                    title="Hide these as false-positive matches — they stop counting toward totals"
                  >
                    <X size={14} />
                    Dismiss {selected.size}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setSelected(new Set())}
                  >
                    Clear selection
                  </Button>
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  if (
                    confirm(
                      `Mark all ${camp.untracked_count} link(s) for "${camp.title}" as tracked?`
                    )
                  ) {
                    markAllLocal()
                  }
                }}
                disabled={isMarking}
              >
                Mark whole campaign tracked
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  // Comma-separated single line — Cobrand's bulk paste format
                  const allUrls = camp.videos.map((v) => v.url).join(" ")
                  navigator.clipboard.writeText(allUrls)
                }}
                title={`Copy all ${camp.videos.length} link(s) as one comma-separated string for Cobrand`}
              >
                <Copy size={14} />
                Copy all {camp.videos.length} as batch
              </Button>
            </div>
          </div>

          {/* Video rows */}
          <table className="w-full text-sm">
            <thead className="bg-[#fafafd] border-b border-[#e8e8ef] text-[11px] uppercase tracking-wide text-[#888]">
              <tr>
                <th className="w-8 px-2 py-2"></th>
                <th className="text-left px-2 py-2">Creator</th>
                <th className="text-left px-2 py-2">Link</th>
                <th className="text-right px-2 py-2 w-24">Views</th>
                <th className="text-left px-2 py-2 w-32">Strategy</th>
                <th className="px-2 py-2 w-20"></th>
              </tr>
            </thead>
            <tbody>
              {camp.videos.map((v) => (
                <VideoRow
                  key={v.id}
                  video={v}
                  selected={selected.has(v.id)}
                  onToggle={() => toggle(v.id)}
                  onMarkOne={() => markIds([v.id])}
                  onUndoOne={() => undoMarkIds([v.id])}
                  onDismissOne={(reason) => onDismiss([v.id], reason)}
                  isMarking={isMarking}
                  isDismissing={isDismissing}
                  isLocallyTicked={locallyTicked.has(v.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function VideoRow({
  video,
  selected,
  onToggle,
  onMarkOne,
  onUndoOne,
  onDismissOne,
  isMarking,
  isDismissing,
  isLocallyTicked,
}: {
  video: ScrapeTaskVideo
  selected: boolean
  onToggle: () => void
  onMarkOne: () => void
  onUndoOne: () => void
  onDismissOne: (reason?: string) => void
  isMarking: boolean
  isDismissing: boolean
  isLocallyTicked: boolean
}) {
  const [copied, setCopied] = useState(false)

  const copyLink = () => {
    navigator.clipboard.writeText(video.url)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  return (
    <tr
      className={
        "border-b border-[#f0f0f5] hover:bg-[#fafafd]" +
        (isLocallyTicked ? " opacity-50 line-through" : "")
      }
    >
      <td className="px-2 py-2 align-middle">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          disabled={isLocallyTicked}
          className="cursor-pointer disabled:cursor-not-allowed"
        />
      </td>
      <td className="px-2 py-2 font-medium text-[#1a1a2e]">{video.account || "—"}</td>
      <td className="px-2 py-2 max-w-0">
        <a
          href={video.url}
          target="_blank"
          rel="noreferrer"
          className="text-[#0b62d6] hover:underline truncate inline-block max-w-full align-middle"
          title={video.url}
        >
          {video.url}
        </a>
      </td>
      <td className="px-2 py-2 text-right tabular-nums">
        {video.views.toLocaleString()}
      </td>
      <td className="px-2 py-2">
        {video.match_strategy === "sound_id" && (
          <Badge variant="outline" className="text-xs">
            sound_id
          </Badge>
        )}
        {video.match_strategy === "internal_creator" && (
          <Badge className="bg-[#e7f0ff] text-[#0b62d6] border-[#bcd1f5] text-xs">
            internal
          </Badge>
        )}
        {video.match_strategy === "fuzzy_word_overlap" && (
          <Badge
            className="bg-[#fff1c8] text-[#a16100] border-[#f4d169] text-xs"
            title="Matched on fuzzy word overlap — verify before tracking"
          >
            fuzzy
          </Badge>
        )}
        {video.match_strategy === "discovered_original_sound" && (
          <Badge className="bg-[#f1e8ff] text-[#5a32b8] border-[#cdb5f4] text-xs">
            discovered
          </Badge>
        )}
        {!video.match_strategy && (
          <span className="text-xs text-[#888]">—</span>
        )}
      </td>
      <td className="px-2 py-2">
        <div className="flex items-center justify-end gap-1">
          <button
            onClick={copyLink}
            className="p-1 rounded hover:bg-[#eef2ff] text-[#666] hover:text-[#0b62d6]"
            title="Copy link"
          >
            {copied ? <Check size={14} /> : <Copy size={14} />}
          </button>
          <a
            href={video.url}
            target="_blank"
            rel="noreferrer"
            className="p-1 rounded hover:bg-[#eef2ff] text-[#666] hover:text-[#0b62d6]"
            title="Open in TikTok"
          >
            <ExternalLink size={14} />
          </a>
          {isLocallyTicked ? (
            <button
              onClick={onUndoOne}
              disabled={isMarking}
              className="p-1 rounded hover:bg-[#fff5e6] text-[#a16100] hover:text-[#7a4a00] disabled:opacity-50"
              title="Undo — restore to the queue"
            >
              <Undo2 size={14} />
            </button>
          ) : (
            <>
              <button
                onClick={onMarkOne}
                disabled={isMarking}
                className="p-1 rounded hover:bg-[#dcf6dc] text-[#666] hover:text-[#226e22] disabled:opacity-50"
                title="Mark this link as tracked"
              >
                <Check size={14} />
              </button>
              <button
                onClick={() => {
                  const reason = window.prompt(
                    "Dismiss this match as a false positive? Optional reason:",
                    ""
                  )
                  if (reason === null) return
                  onDismissOne(reason.trim() || undefined)
                }}
                disabled={isDismissing}
                className="p-1 rounded hover:bg-[#fceaea] text-[#666] hover:text-[#a13434] disabled:opacity-50"
                title="Dismiss as false-positive — excluded from totals"
              >
                <X size={14} />
              </button>
            </>
          )}
        </div>
      </td>
    </tr>
  )
}

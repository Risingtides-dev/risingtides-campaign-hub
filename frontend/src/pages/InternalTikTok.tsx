import { useState, useMemo } from "react"
import { Link } from "react-router-dom"
import {
  useInternalCreators,
  useInternalGroups,
  useInternalGroupStats,
  useInternalFreshness,
  useAddInternalCreators,
  useRemoveInternalCreator,
} from "@/lib/queries"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2, ChevronRight, X, Plus, Trash2, ExternalLink } from "lucide-react"
import type { InternalGroup } from "@/lib/types"

function formatNum(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoStr(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

function daysBetween(start: string, end: string): number {
  const s = new Date(start)
  const e = new Date(end)
  return Math.max(1, Math.round((e.getTime() - s.getTime()) / (1000 * 60 * 60 * 24)))
}

// A cluster card: stats from the internal scrape, linking to the cluster's
// detail/scrape page, plus a deep-link to its TidesTracker when one is pinned.
function GroupStatsCard({ group, days }: { group: InternalGroup; days: number }) {
  const { data: stats, isLoading } = useInternalGroupStats(group.slug, days)

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5 hover:border-rt-magenta/40 hover:shadow-sm transition-all">
      <div className="flex items-start justify-between mb-3">
        <div>
          <Link
            to={`/internal/group/${group.slug}`}
            className="text-[16px] font-semibold text-rt-fg hover:text-rt-magenta"
          >
            {group.title}
          </Link>
          <p className="text-[12px] text-rt-fg-tertiary">{group.member_count} accounts</p>
        </div>
        {group.tracker_id ? (
          <a
            href={`https://risingtides-tracker.com/${group.tracker_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 text-[12px] text-rt-magenta font-medium hover:underline"
            title="Open Tides Tracker"
          >
            Tracker <ExternalLink className="size-3" />
          </a>
        ) : (
          <Link to={`/internal/group/${group.slug}`}>
            <ChevronRight className="size-4 text-rt-fg-tertiary" />
          </Link>
        )}
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2 text-rt-fg-tertiary text-xs">
          <Loader2 className="size-3 animate-spin" /> Loading...
        </div>
      ) : stats ? (
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-[11px] text-rt-fg-tertiary uppercase tracking-wide">Views</div>
            <div className="text-[18px] font-bold text-rt-fg">{formatNum(stats.total_views)}</div>
          </div>
          <div>
            <div className="text-[11px] text-rt-fg-tertiary uppercase tracking-wide">Posts</div>
            <div className="text-[18px] font-bold text-rt-fg">{stats.total_posts}</div>
          </div>
          <div>
            <div className="text-[11px] text-rt-fg-tertiary uppercase tracking-wide">Likes</div>
            <div className="text-[18px] font-bold text-rt-fg">{formatNum(stats.total_likes)}</div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

export default function InternalTikTok() {
  const [tab, setTab] = useState<"stats" | "accounts" | "groups">("stats")
  const [addInput, setAddInput] = useState("")
  const [newGroupSlug, setNewGroupSlug] = useState("")
  const [newGroupTitle, setNewGroupTitle] = useState("")
  const [newGroupKind, setNewGroupKind] = useState("custom")

  // Stats date range (controls what GroupStatsCards show)
  const [statsStartDate, setStatsStartDate] = useState(daysAgoStr(30))
  const [statsEndDate, setStatsEndDate] = useState(todayStr())
  const statsDays = useMemo(() => daysBetween(statsStartDate, statsEndDate), [statsStartDate, statsEndDate])

  const { data: groups, isLoading: groupsLoading } = useInternalGroups()
  const { data: creators, isLoading: creatorsLoading } = useInternalCreators()
  const { data: freshness } = useInternalFreshness()

  // Staleness guard (post June-3 silent-zero incident): if the newest scraped
  // video predates the selected window, the zeros below are a data-freshness
  // problem, not a performance signal — say so loudly.
  const staleForWindow = useMemo(() => {
    if (!freshness?.newest_upload_date) return false
    const newest = freshness.newest_upload_date // YYYYMMDD
    const windowStart = statsStartDate.replaceAll("-", "")
    return newest < windowStart
  }, [freshness, statsStartDate])
  const addCreators = useAddInternalCreators()
  const removeCreator = useRemoveInternalCreator()

  // Clusters are the single grouping axis — one bucket of pages per Notion
  // `Group` value (kind="cluster"), each 1:1 with a Tides Tracker.
  const clusterGroups = (groups || [])
    .filter((g) => g.kind === "cluster" && g.member_count > 0)
    .sort((a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99) || a.title.localeCompare(b.title))

  const allGroups = (groups || [])
    .filter((g) => g.member_count > 0 || g.slug === "general")
    .sort((a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99))

  const sortedCreators = [...(creators || [])].sort(
    (a, b) => (b.total_views ?? 0) - (a.total_views ?? 0)
  )

  function handleAddCreators(e: React.FormEvent) {
    e.preventDefault()
    const value = addInput.trim()
    if (!value) return
    addCreators.mutate(value, { onSuccess: () => setAddInput("") })
  }

  function handleRemoveCreator(username: string) {
    if (!confirm(`Remove @${username} from internal creators?`)) return
    removeCreator.mutate(username)
  }

  async function handleCreateGroup(e: React.FormEvent) {
    e.preventDefault()
    const slug = newGroupSlug.trim().toLowerCase().replace(/\s+/g, "_")
    const title = newGroupTitle.trim()
    if (!slug || !title) return
    try {
      await fetch("/api/internal/groups", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug, title, kind: newGroupKind }),
      })
      setNewGroupSlug("")
      setNewGroupTitle("")
      window.location.reload()
    } catch {
      // Silently handle — user can retry
    }
  }

  async function handleDeleteGroup(id: number, title: string) {
    if (!confirm(`Delete group "${title}"? Members won't be deleted.`)) return
    try {
      await fetch(`/api/internal/groups/${id}`, { method: "DELETE" })
      window.location.reload()
    } catch {
      // Silently handle — user can retry
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h1 className="text-[22px] font-semibold">Internal TikTok</h1>
          <p className="text-rt-fg-tertiary text-sm">{creators?.length ?? 0} total accounts</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 border-b border-white/8">
        {[
          { key: "stats" as const, label: "Stats" },
          { key: "accounts" as const, label: `All Accounts (${creators?.length ?? 0})` },
          { key: "groups" as const, label: `Groups (${(groups || []).length})` },
        ].map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t.key
                ? "border-rt-magenta text-rt-magenta"
                : "border-transparent text-rt-fg-tertiary hover:text-rt-fg"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Stats tab */}
      {tab === "stats" && (
        <div>
          {/* Stats date range picker */}
          <div className="flex flex-wrap items-center gap-2 mb-4 p-3 bg-white/[0.03] rounded-[10px] border border-white/8">
            <span className="text-[13px] text-rt-fg-tertiary font-medium">Stats period:</span>
            <Input
              type="date"
              value={statsStartDate}
              onChange={(e) => setStatsStartDate(e.target.value)}
              className="w-[145px] h-8 text-sm"
            />
            <span className="text-rt-fg-tertiary text-sm">to</span>
            <Input
              type="date"
              value={statsEndDate}
              onChange={(e) => setStatsEndDate(e.target.value)}
              className="w-[145px] h-8 text-sm"
            />
            <span className="text-[12px] text-rt-fg-tertiary">({statsDays} days)</span>
          </div>

          {staleForWindow && freshness && (
            <div className="mb-4 rounded-[10px] border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
              <span className="font-semibold">Scrape data is stale.</span>{" "}
              The newest scraped video is from{" "}
              {freshness.newest_upload_date
                ? `${freshness.newest_upload_date.slice(0, 4)}-${freshness.newest_upload_date.slice(4, 6)}-${freshness.newest_upload_date.slice(6, 8)}`
                : "unknown"}
              {typeof freshness.days_since_newest_upload === "number" &&
                ` (${freshness.days_since_newest_upload}d ago)`}
              {" "}— every stat in this window will read zero until a scrape runs. The daily
              6 AM scheduler should cover this; if this banner persists, check the scrape logs.
            </div>
          )}

          {groupsLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-5 animate-spin text-rt-fg-tertiary" />
            </div>
          ) : clusterGroups.length > 0 ? (
            <>
              {/* Clusters — one card per Notion `Group`, each 1:1 with a tracker */}
              <h2 className="text-[15px] font-semibold text-rt-fg mb-3">Clusters</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {clusterGroups.map((g) => (
                  <GroupStatsCard key={g.slug} group={g} days={statsDays} />
                ))}
              </div>
            </>
          ) : (
            <div className="text-center py-12 text-rt-fg-tertiary text-sm">
              No clusters yet. Clusters populate from the Notion <code>Group</code> field
              on the next sync — add a <code>Group</code> value to pages in Master Pages.
            </div>
          )}
        </div>
      )}

      {/* All Accounts tab */}
      {tab === "accounts" && (
        <div>
          {/* Add form */}
          <form onSubmit={handleAddCreators} className="mb-4 flex gap-2">
            <Input
              type="text"
              value={addInput}
              onChange={(e) => setAddInput(e.target.value)}
              placeholder="Add creators (@username, comma separated)"
              className="flex-1 text-sm h-9"
            />
            <Button
              type="submit"
              size="sm"
              className="bg-rt-magenta hover:bg-rt-purple text-white h-9 px-4"
              disabled={addCreators.isPending || !addInput.trim()}
            >
              {addCreators.isPending ? <Loader2 className="size-3 animate-spin" /> : <><Plus className="size-3.5" /> Add</>}
            </Button>
          </form>
          {addCreators.isError && (
            <p className="text-rt-red text-xs mb-2">{addCreators.error?.message || "Failed to add"}</p>
          )}

          <div className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden">
            {creatorsLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="size-5 animate-spin text-rt-fg-tertiary" />
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/8 bg-white/[0.03]">
                    <th className="text-left px-4 py-2.5 text-[12px] text-rt-fg-tertiary font-semibold uppercase tracking-wide">Creator</th>
                    <th className="text-right px-4 py-2.5 text-[12px] text-rt-fg-tertiary font-semibold uppercase tracking-wide">Videos</th>
                    <th className="text-right px-4 py-2.5 text-[12px] text-rt-fg-tertiary font-semibold uppercase tracking-wide">Views</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedCreators.map((c) => (
                    <tr key={c.username} className="border-b border-white/5 last:border-b-0 hover:bg-white/[0.03]">
                      <td className="px-4 py-2">
                        <Link to={`/internal/${c.username}`} className="text-rt-magenta hover:underline">
                          @{c.username}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-right text-rt-fg-tertiary">{c.total_videos}</td>
                      <td className="px-4 py-2 text-right text-rt-fg-tertiary">{c.total_views.toLocaleString()}</td>
                      <td className="px-2 py-2">
                        <button
                          type="button"
                          onClick={() => handleRemoveCreator(c.username)}
                          className="text-rt-red hover:text-rt-red p-1"
                          title="Remove"
                          disabled={removeCreator.isPending}
                        >
                          <X className="size-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* Groups tab */}
      {tab === "groups" && (
        <div>
          {/* Create group form */}
          <form onSubmit={handleCreateGroup} className="mb-4 flex flex-wrap gap-2">
            <Input
              type="text"
              value={newGroupTitle}
              onChange={(e) => setNewGroupTitle(e.target.value)}
              placeholder="Group title (e.g. Jake's Pages)"
              className="w-[200px] text-sm h-9"
            />
            <Input
              type="text"
              value={newGroupSlug}
              onChange={(e) => setNewGroupSlug(e.target.value)}
              placeholder="slug (e.g. jake_balik)"
              className="w-[160px] text-sm h-9"
            />
            <select
              value={newGroupKind}
              onChange={(e) => setNewGroupKind(e.target.value)}
              className="h-9 px-2 text-sm border border-white/8 rounded-md bg-rt-bg-card text-rt-fg"
            >
              <option value="cluster">cluster</option>
              <option value="custom">custom</option>
            </select>
            <Button type="submit" size="sm" className="bg-rt-magenta hover:bg-rt-purple text-white h-9 px-4">
              <Plus className="size-3.5" /> Create Group
            </Button>
          </form>

          <div className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden">
            {groupsLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="size-5 animate-spin text-rt-fg-tertiary" />
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/8 bg-white/[0.03]">
                    <th className="text-left px-4 py-2.5 text-[12px] text-rt-fg-tertiary font-semibold uppercase tracking-wide">Title</th>
                    <th className="text-left px-4 py-2.5 text-[12px] text-rt-fg-tertiary font-semibold uppercase tracking-wide">Slug</th>
                    <th className="text-left px-4 py-2.5 text-[12px] text-rt-fg-tertiary font-semibold uppercase tracking-wide">Kind</th>
                    <th className="text-right px-4 py-2.5 text-[12px] text-rt-fg-tertiary font-semibold uppercase tracking-wide">Members</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {allGroups.map((g) => (
                    <tr key={g.id} className="border-b border-white/5 last:border-b-0 hover:bg-white/[0.03]">
                      <td className="px-4 py-2.5">
                        <Link to={`/internal/group/${g.slug}`} className="text-rt-magenta hover:underline font-medium">
                          {g.title}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-rt-fg-tertiary text-xs font-mono">{g.slug}</td>
                      <td className="px-4 py-2.5 text-rt-fg-tertiary">{g.kind}</td>
                      <td className="px-4 py-2.5 text-right text-rt-fg-tertiary">{g.member_count}</td>
                      <td className="px-2 py-2.5">
                        <button
                          type="button"
                          onClick={() => handleDeleteGroup(g.id, g.title)}
                          className="text-rt-red hover:text-rt-red p-1"
                          title="Delete group"
                        >
                          <Trash2 className="size-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

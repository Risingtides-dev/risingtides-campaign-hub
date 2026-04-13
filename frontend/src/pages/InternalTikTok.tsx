import { useState, useCallback, useMemo } from "react"
import { Link } from "react-router-dom"
import {
  useInternalCreators,
  useInternalGroups,
  useInternalGroupStats,
  useTriggerInternalScrape,
  useTriggerGroupScrape,
  useInternalScrapeStatus,
  useAddInternalCreators,
  useRemoveInternalCreator,
} from "@/lib/queries"
import { ScrapeProgress } from "@/components/internal/ScrapeProgress"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2, ChevronRight, X, Plus, Trash2 } from "lucide-react"
import type { InternalGroup } from "@/lib/types"

const PERSON_GROUPS = ["jake_balik", "john_smathers", "sam_hudgens", "eric_cromartie", "johnny_balik", "seeno_pages"]
const LABEL_GROUPS = ["warner_pages", "atlantic_pages"]

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

function GroupStatsCard({ group, days }: { group: InternalGroup; days: number }) {
  const { data: stats, isLoading } = useInternalGroupStats(group.slug, days)

  return (
    <Link
      to={`/internal/group/${group.slug}`}
      className="block bg-white border border-[#e8e8ef] rounded-[10px] p-5 hover:border-[#0b62d6]/40 hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="text-[16px] font-semibold text-[#1a1a2e]">{group.title}</h3>
          <p className="text-[12px] text-[#888]">{group.member_count} accounts</p>
        </div>
        <ChevronRight className="size-4 text-[#888]" />
      </div>
      {isLoading ? (
        <div className="flex items-center gap-2 text-[#888] text-xs">
          <Loader2 className="size-3 animate-spin" /> Loading...
        </div>
      ) : stats ? (
        <div className="grid grid-cols-3 gap-3">
          <div>
            <div className="text-[11px] text-[#888] uppercase tracking-wide">Views</div>
            <div className="text-[18px] font-bold text-[#1a1a2e]">{formatNum(stats.total_views)}</div>
          </div>
          <div>
            <div className="text-[11px] text-[#888] uppercase tracking-wide">Posts</div>
            <div className="text-[18px] font-bold text-[#1a1a2e]">{stats.total_posts}</div>
          </div>
          <div>
            <div className="text-[11px] text-[#888] uppercase tracking-wide">Likes</div>
            <div className="text-[18px] font-bold text-[#1a1a2e]">{formatNum(stats.total_likes)}</div>
          </div>
        </div>
      ) : null}
    </Link>
  )
}

function ScrapeCard({
  title,
  count,
  onScrape,
  isPending,
  isRunning,
}: {
  title: string
  count: number
  onScrape: (startDate: string, endDate: string) => void
  isPending: boolean
  isRunning: boolean
}) {
  const [startDate, setStartDate] = useState(daysAgoStr(30))
  const [endDate, setEndDate] = useState(todayStr())

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-4">
      <div className="text-[14px] font-semibold text-[#1a1a2e] mb-1">{title}</div>
      <div className="text-[12px] text-[#888] mb-2">{count} accounts</div>
      <div className="flex items-center gap-1.5 mb-2">
        <Input
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          className="flex-1 h-7 text-xs px-1.5"
        />
        <span className="text-[#888] text-xs">to</span>
        <Input
          type="date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          className="flex-1 h-7 text-xs px-1.5"
        />
      </div>
      <Button
        onClick={() => onScrape(startDate, endDate)}
        disabled={isPending || isRunning}
        className="w-full bg-[#0b62d6] hover:bg-[#0951b5] text-white text-sm"
        size="sm"
      >
        {isPending ? <Loader2 className="size-3.5 animate-spin" /> : `Scrape ${title}`}
      </Button>
    </div>
  )
}

export default function InternalTikTok() {
  const [tab, setTab] = useState<"stats" | "accounts" | "groups">("stats")
  const [scraping, setScraping] = useState(false)
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
  const triggerScrape = useTriggerInternalScrape()
  const triggerGroupScrape = useTriggerGroupScrape()
  const addCreators = useAddInternalCreators()
  const removeCreator = useRemoveInternalCreator()
  const { data: scrapeStatus } = useInternalScrapeStatus(true)
  const isRunning = scraping || !!scrapeStatus?.running

  const handleScrapeComplete = useCallback(() => setScraping(false), [])

  const personGroups = (groups || [])
    .filter((g) => PERSON_GROUPS.includes(g.slug))
    .sort((a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99))

  const labelGroups = (groups || [])
    .filter((g) => LABEL_GROUPS.includes(g.slug))
    .sort((a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99))

  const allGroups = (groups || [])
    .filter((g) => g.member_count > 0 || g.slug === "general")
    .sort((a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99))

  const internalCount = personGroups.reduce((sum, g) => sum + g.member_count, 0)
  const warnerGroup = (groups || []).find((g) => g.slug === "warner_pages")
  const atlanticGroup = (groups || []).find((g) => g.slug === "atlantic_pages")

  const sortedCreators = [...(creators || [])].sort(
    (a, b) => (b.total_views ?? 0) - (a.total_views ?? 0)
  )

  function handleScrapeAll(startDate: string, endDate: string) {
    setScraping(true)
    triggerGroupScrape.mutate({ start_date: startDate, end_date: endDate })
  }

  function handleScrapeGroup(slug: string, startDate: string, endDate: string) {
    setScraping(true)
    triggerGroupScrape.mutate({ group: slug, start_date: startDate, end_date: endDate })
  }

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
          <p className="text-[#888] text-sm">{creators?.length ?? 0} total accounts</p>
        </div>
      </div>

      {/* Scrape progress */}
      <ScrapeProgress enabled={isRunning} onComplete={handleScrapeComplete} />

      {/* Three scrape cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <ScrapeCard
          title="Internal Pages"
          count={internalCount}
          onScrape={(s, e) => handleScrapeAll(s, e)}
          isPending={triggerGroupScrape.isPending}
          isRunning={isRunning}
        />
        <ScrapeCard
          title="Warner Pages"
          count={warnerGroup?.member_count ?? 0}
          onScrape={(s, e) => handleScrapeGroup("warner_pages", s, e)}
          isPending={triggerGroupScrape.isPending}
          isRunning={isRunning}
        />
        <ScrapeCard
          title="Atlantic Pages"
          count={atlanticGroup?.member_count ?? 0}
          onScrape={(s, e) => handleScrapeGroup("atlantic_pages", s, e)}
          isPending={triggerGroupScrape.isPending}
          isRunning={isRunning}
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 border-b border-[#e8e8ef]">
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
                ? "border-[#0b62d6] text-[#0b62d6]"
                : "border-transparent text-[#888] hover:text-[#1a1a2e]"
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
          <div className="flex flex-wrap items-center gap-2 mb-4 p-3 bg-[#f8f8fc] rounded-[10px] border border-[#e8e8ef]">
            <span className="text-[13px] text-[#666] font-medium">Stats period:</span>
            <Input
              type="date"
              value={statsStartDate}
              onChange={(e) => setStatsStartDate(e.target.value)}
              className="w-[145px] h-8 text-sm"
            />
            <span className="text-[#888] text-sm">to</span>
            <Input
              type="date"
              value={statsEndDate}
              onChange={(e) => setStatsEndDate(e.target.value)}
              className="w-[145px] h-8 text-sm"
            />
            <span className="text-[12px] text-[#888]">({statsDays} days)</span>
          </div>

          {groupsLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="size-5 animate-spin text-[#888]" />
            </div>
          ) : (
            <>
              {/* Person groups */}
              <h2 className="text-[15px] font-semibold text-[#1a1a2e] mb-3">Internal Pages</h2>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
                {personGroups.map((g) => (
                  <GroupStatsCard key={g.slug} group={g} days={statsDays} />
                ))}
              </div>

              {/* Label groups */}
              {labelGroups.length > 0 && (
                <>
                  <h2 className="text-[15px] font-semibold text-[#1a1a2e] mb-3">Label Pages</h2>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {labelGroups.map((g) => (
                      <GroupStatsCard key={g.slug} group={g} days={statsDays} />
                    ))}
                  </div>
                </>
              )}
            </>
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
              className="bg-[#0b62d6] hover:bg-[#0951b5] text-white h-9 px-4"
              disabled={addCreators.isPending || !addInput.trim()}
            >
              {addCreators.isPending ? <Loader2 className="size-3 animate-spin" /> : <><Plus className="size-3.5" /> Add</>}
            </Button>
          </form>
          {addCreators.isError && (
            <p className="text-red-600 text-xs mb-2">{addCreators.error?.message || "Failed to add"}</p>
          )}

          <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
            {creatorsLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="size-5 animate-spin text-[#888]" />
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#e8e8ef] bg-[#f8f8fc]">
                    <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Creator</th>
                    <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Videos</th>
                    <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Views</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedCreators.map((c) => (
                    <tr key={c.username} className="border-b border-[#f0f0f5] last:border-b-0 hover:bg-[#f8f8fc]">
                      <td className="px-4 py-2">
                        <Link to={`/internal/${c.username}`} className="text-[#0b62d6] hover:underline">
                          @{c.username}
                        </Link>
                      </td>
                      <td className="px-4 py-2 text-right text-[#666]">{c.total_videos}</td>
                      <td className="px-4 py-2 text-right text-[#666]">{c.total_views.toLocaleString()}</td>
                      <td className="px-2 py-2">
                        <button
                          type="button"
                          onClick={() => handleRemoveCreator(c.username)}
                          className="text-red-400 hover:text-red-600 p-1"
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
              className="h-9 px-2 text-sm border border-[#e8e8ef] rounded-md bg-white text-[#1a1a2e]"
            >
              <option value="booked_by">booked_by</option>
              <option value="label">label</option>
              <option value="niche">niche</option>
              <option value="custom">custom</option>
            </select>
            <Button type="submit" size="sm" className="bg-[#0b62d6] hover:bg-[#0951b5] text-white h-9 px-4">
              <Plus className="size-3.5" /> Create Group
            </Button>
          </form>

          <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
            {groupsLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="size-5 animate-spin text-[#888]" />
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[#e8e8ef] bg-[#f8f8fc]">
                    <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Title</th>
                    <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Slug</th>
                    <th className="text-left px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Kind</th>
                    <th className="text-right px-4 py-2.5 text-[12px] text-[#888] font-semibold uppercase tracking-wide">Members</th>
                    <th className="w-10"></th>
                  </tr>
                </thead>
                <tbody>
                  {allGroups.map((g) => (
                    <tr key={g.id} className="border-b border-[#f0f0f5] last:border-b-0 hover:bg-[#f8f8fc]">
                      <td className="px-4 py-2.5">
                        <Link to={`/internal/group/${g.slug}`} className="text-[#0b62d6] hover:underline font-medium">
                          {g.title}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 text-[#888] text-xs font-mono">{g.slug}</td>
                      <td className="px-4 py-2.5 text-[#888]">{g.kind}</td>
                      <td className="px-4 py-2.5 text-right text-[#666]">{g.member_count}</td>
                      <td className="px-2 py-2.5">
                        <button
                          type="button"
                          onClick={() => handleDeleteGroup(g.id, g.title)}
                          className="text-red-400 hover:text-red-600 p-1"
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

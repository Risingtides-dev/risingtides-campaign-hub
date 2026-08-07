import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import {
  ExternalLink,
  Plus,
  Loader2,
  Activity,
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Copy,
  Check,
  Pencil,
  Search,
  Trash2,
  Undo2,
  Radar,
  X,
} from "lucide-react"
import {
  useTrackers,
  useTrackerGroups,
  useCreateStandaloneTracker,
  useSetTrackerGroup,
  useSetTrackerName,
  useSetTrackerCampaign,
  useCreateTrackerGroup,
  useCampaigns,
  useArchiveTracker,
  useRestoreTracker,
} from "@/lib/queries"
import type { Tracker, TrackerCampaignSuggestion } from "@/lib/types"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const ALL_GROUP = "__all__"
const NO_GROUP = "__none__"
const NO_CAMPAIGN = "__no_campaign__"
const ARCHIVED_GROUP = "__archived__"

type SortField = "name" | "campaign" | "group" | "created"
type SortDir = "asc" | "desc"

function formatDate(iso: string): string {
  if (!iso) return "-"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "-"
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

function shortenUrl(url: string, max = 38): string {
  if (!url) return ""
  try {
    const u = new URL(url)
    const display = u.host + u.pathname
    return display.length > max ? display.slice(0, max - 1) + "…" : display
  } catch {
    return url.length > max ? url.slice(0, max - 1) + "…" : url
  }
}

export default function TidesTrackers() {
  const [activeGroup, setActiveGroup] = useState<string>(ALL_GROUP)
  // Always fetch archived rows too so the Archived pill's count is accurate
  // on first paint (without it, the pill is undiscoverable after refresh).
  // All non-archived views filter them out client-side below.
  const viewingArchived = activeGroup === ARCHIVED_GROUP
  const { data: trackers = [], isLoading, isError, error } = useTrackers(true)
  const { data: groups = [] } = useTrackerGroups()
  const [cobrandUrl, setCobrandUrl] = useState("")
  const [name, setName] = useState("")
  const [createGroupId, setCreateGroupId] = useState<string>(NO_GROUP)
  const [newGroupTitle, setNewGroupTitle] = useState("")
  const [showNewGroup, setShowNewGroup] = useState(false)

  const createTracker = useCreateStandaloneTracker()
  const setTrackerGroup = useSetTrackerGroup()
  const setTrackerName = useSetTrackerName()
  const setTrackerCampaign = useSetTrackerCampaign()
  const createGroup = useCreateTrackerGroup()
  const archiveTracker = useArchiveTracker()
  const restoreTracker = useRestoreTracker()
  const { data: campaigns = [] } = useCampaigns()
  const activeCampaigns = useMemo(
    () =>
      [...campaigns]
        .filter((c) => c.completion_status !== "completed")
        .sort((a, b) => a.title.localeCompare(b.title)),
    [campaigns]
  )

  const [search, setSearch] = useState("")
  const [sortField, setSortField] = useState<SortField>("created")
  const [sortDir, setSortDir] = useState<SortDir>("desc")

  function toggleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"))
    } else {
      setSortField(field)
      // Text columns start ascending, dates start newest-first.
      setSortDir(field === "created" ? "desc" : "asc")
    }
  }

  const groupTitleById = useMemo(() => {
    const m = new Map<number, string>()
    for (const g of groups) m.set(g.id, g.title)
    return m
  }, [groups])

  const filteredTrackers = useMemo(() => {
    let rows: Tracker[]
    if (activeGroup === ARCHIVED_GROUP) {
      rows = trackers.filter((t) => !!t.archived_at)
    } else {
      const active = trackers.filter((t) => !t.archived_at)
      if (activeGroup === ALL_GROUP) rows = active
      else if (activeGroup === NO_GROUP) rows = active.filter((t) => t.group_id == null)
      else {
        const gid = Number(activeGroup)
        rows = active.filter((t) => t.group_id === gid)
      }
    }

    const q = search.trim().toLowerCase()
    if (q) {
      const tokens = q.split(/\s+/)
      rows = rows.filter((t) => {
        const blob = [
          t.name,
          t.original_name,
          t.campaign_slug ?? "",
          t.campaign?.title ?? "",
          t.group_id != null ? groupTitleById.get(t.group_id) ?? "" : "",
          t.cobrand_share_url,
          t.tracker_url,
        ]
          .join(" ")
          .toLowerCase()
        return tokens.every((tok) => blob.includes(tok))
      })
    }

    const dir = sortDir === "asc" ? 1 : -1
    const key = (t: Tracker): string => {
      switch (sortField) {
        case "name":
          return (t.name || t.original_name).toLowerCase()
        case "campaign":
          return (t.campaign?.title ?? t.campaign_slug ?? "").toLowerCase()
        case "group":
          return (t.group_id != null ? groupTitleById.get(t.group_id) ?? "" : "").toLowerCase()
        case "created":
          return t.created_at || ""
      }
    }
    return [...rows].sort((a, b) => {
      const ka = key(a)
      const kb = key(b)
      // Blank values sink to the bottom in either direction.
      if (!ka && kb) return 1
      if (ka && !kb) return -1
      return ka < kb ? -dir : ka > kb ? dir : 0
    })
  }, [trackers, activeGroup, search, sortField, sortDir, groupTitleById])

  const ungroupedCount = useMemo(
    () =>
      trackers.filter((t) => !t.archived_at && t.group_id == null).length,
    [trackers]
  )
  const archivedCount = useMemo(
    () => trackers.filter((t) => !!t.archived_at).length,
    [trackers]
  )

  function handleCreate() {
    const url = cobrandUrl.trim()
    if (!url) return
    const groupId =
      createGroupId === NO_GROUP ? null : Number(createGroupId) || null
    createTracker.mutate(
      {
        cobrand_share_url: url,
        name: name.trim() || undefined,
        group_id: groupId,
      },
      {
        onSuccess: () => {
          setCobrandUrl("")
          setName("")
        },
      }
    )
  }

  function handleCreateGroup() {
    const title = newGroupTitle.trim()
    if (!title) return
    createGroup.mutate(
      { title },
      {
        onSuccess: (g) => {
          setNewGroupTitle("")
          setShowNewGroup(false)
          if (g?.id) setActiveGroup(String(g.id))
        },
      }
    )
  }

  function handleSetGroup(tracker: Tracker, value: string) {
    const gid = value === NO_GROUP ? null : Number(value)
    if (gid === tracker.group_id) return
    setTrackerGroup.mutate({ trackerId: tracker.id, groupId: gid })
  }

  function handleSetCampaign(tracker: Tracker, value: string) {
    const slug = value === NO_CAMPAIGN ? null : value
    if (slug === (tracker.campaign_slug ?? null)) return
    setTrackerCampaign.mutate({ trackerId: tracker.id, campaignSlug: slug })
  }

  const [copiedId, setCopiedId] = useState<string | null>(null)
  function handleCopy(tracker: Tracker) {
    if (!tracker.tracker_url) return
    navigator.clipboard.writeText(tracker.tracker_url).then(() => {
      setCopiedId(tracker.id)
      window.setTimeout(() => {
        setCopiedId((current) => (current === tracker.id ? null : current))
      }, 1500)
    })
  }

  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")
  function startEdit(tracker: Tracker) {
    setEditingId(tracker.id)
    setEditValue(tracker.name || "")
  }
  function commitEdit(tracker: Tracker) {
    const next = editValue.trim()
    setEditingId(null)
    if (next === (tracker.name || "")) return
    // Empty string clears the override and reverts to TidesTracker's original name.
    setTrackerName.mutate({ trackerId: tracker.id, name: next || null })
  }
  function cancelEdit() {
    setEditingId(null)
    setEditValue("")
  }

  function handleArchive(tracker: Tracker) {
    const label = tracker.name || tracker.original_name || "this tracker"
    if (
      !window.confirm(
        `Archive "${label}"? It will be hidden from the list and from campaign dropdowns. You can restore it later from the Archived view.`
      )
    ) {
      return
    }
    archiveTracker.mutate(tracker.id)
  }

  function handleRestore(tracker: Tracker) {
    restoreTracker.mutate(tracker.id)
  }

  return (
    <div>
      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold flex items-center gap-2">
            <Activity className="size-5 text-purple-600" />
            TidesTrackers
          </h1>
          <p className="text-[13px] text-rt-fg-tertiary mt-1">
            Manage all your Cobrand trackers in one place. Group them by label or however you like.
          </p>
        </div>
        <Button asChild size="sm" variant="outline" className="shrink-0">
          <Link to="/tracker-overview">
            <Radar className="size-3.5" />
            Overview
          </Link>
        </Button>
      </div>

      {/* Create form */}
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5 mb-4">
        <div className="text-[12px] font-semibold uppercase tracking-wide text-rt-fg-tertiary mb-3">
          New tracker
        </div>
        <div className="flex flex-col sm:flex-row gap-2">
          <Input
            type="url"
            value={cobrandUrl}
            onChange={(e) => setCobrandUrl(e.target.value)}
            placeholder="Paste Cobrand share link..."
            className="flex-1 min-w-0"
          />
          <Input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Name (optional)"
            className="sm:w-[200px]"
          />
          <Select value={createGroupId} onValueChange={setCreateGroupId}>
            <SelectTrigger className="sm:w-[160px] h-9 text-[13px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_GROUP}>No group</SelectItem>
              {groups.map((g) => (
                <SelectItem key={g.id} value={String(g.id)}>
                  {g.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            onClick={handleCreate}
            disabled={!cobrandUrl.trim() || createTracker.isPending}
            className="bg-purple-600 hover:bg-purple-700 text-white"
          >
            {createTracker.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Plus className="size-3.5" />
            )}
            Create Tracker
          </Button>
        </div>
        {createTracker.isError && (
          <div className="text-[12px] text-rt-red mt-2">
            {(createTracker.error as Error)?.message || "Failed to create tracker"}
          </div>
        )}
      </div>

      {/* Group pills */}
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] px-4 py-3 mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <GroupPill
            active={activeGroup === ALL_GROUP}
            onClick={() => setActiveGroup(ALL_GROUP)}
            label="All"
            count={trackers.filter((t) => !t.archived_at).length}
          />
          {groups.map((g) => (
            <GroupPill
              key={g.id}
              active={activeGroup === String(g.id)}
              onClick={() => setActiveGroup(String(g.id))}
              label={g.title}
              count={g.tracker_count}
            />
          ))}
          {ungroupedCount > 0 && (
            <GroupPill
              active={activeGroup === NO_GROUP}
              onClick={() => setActiveGroup(NO_GROUP)}
              label="Ungrouped"
              count={ungroupedCount}
            />
          )}
          {archivedCount > 0 && (
            <GroupPill
              active={viewingArchived}
              onClick={() => setActiveGroup(ARCHIVED_GROUP)}
              label="Archived"
              count={archivedCount}
            />
          )}

          <div className="flex-1" />

          {/* Search */}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-rt-fg-tertiary" />
            <Input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search trackers..."
              className="h-8 w-[220px] pl-8 text-[13px]"
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch("")}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-rt-fg-tertiary hover:text-rt-fg"
                aria-label="Clear search"
              >
                <X className="size-3.5" />
              </button>
            )}
          </div>

          {showNewGroup ? (
            <div className="flex items-center gap-2">
              <Input
                autoFocus
                value={newGroupTitle}
                onChange={(e) => setNewGroupTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreateGroup()
                  if (e.key === "Escape") {
                    setShowNewGroup(false)
                    setNewGroupTitle("")
                  }
                }}
                placeholder="Group name..."
                className="h-8 w-[160px] text-[13px]"
              />
              <Button
                size="sm"
                onClick={handleCreateGroup}
                disabled={!newGroupTitle.trim() || createGroup.isPending}
              >
                Add
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setShowNewGroup(false)
                  setNewGroupTitle("")
                }}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowNewGroup(true)}
            >
              <Plus className="size-3" />
              New Group
            </Button>
          )}
        </div>
      </div>

      {/* Table */}
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <SortableHead
                label="Name"
                field="name"
                sortField={sortField}
                sortDir={sortDir}
                onSort={toggleSort}
              />
              <TableHead>Cobrand link</TableHead>
              <TableHead>Tracker</TableHead>
              <SortableHead
                label="Campaign"
                field="campaign"
                sortField={sortField}
                sortDir={sortDir}
                onSort={toggleSort}
                className="w-[200px]"
              />
              <SortableHead
                label="Group"
                field="group"
                sortField={sortField}
                sortDir={sortDir}
                onSort={toggleSort}
                className="w-[180px]"
              />
              <SortableHead
                label="Created"
                field="created"
                sortField={sortField}
                sortDir={sortDir}
                onSort={toggleSort}
                className="w-[120px]"
              />
              <TableHead className="w-[90px] text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-rt-fg-tertiary text-[13px]">
                  Loading…
                </TableCell>
              </TableRow>
            ) : isError ? (
              // CAMP-80: a failed /api/trackers fetch must NOT render as the
              // "No trackers" empty state — that masked the real error and
              // made it look like the trackers were gone when they weren't.
              <TableRow>
                <TableCell colSpan={7} className="py-10 text-center">
                  <div className="mx-auto max-w-md rounded-xl border border-rt-red/30 bg-rt-red/10 px-4 py-4">
                    <div className="text-[13px] font-medium text-rt-red">
                      Couldn't load trackers
                    </div>
                    <div className="mt-1 text-[12px] text-rt-fg-tertiary">
                      {error?.message || "The trackers API request failed — they're not gone, the request errored. Check the backend is running and TidesTracker is configured."}
                    </div>
                  </div>
                </TableCell>
              </TableRow>
            ) : filteredTrackers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="text-center py-10 text-rt-fg-tertiary text-[13px]">
                  {search.trim()
                    ? "No trackers match your search."
                    : viewingArchived
                      ? "No archived trackers."
                      : "No trackers in this group yet. Paste a Cobrand link above to create one."}
                </TableCell>
              </TableRow>
            ) : (
              filteredTrackers.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-medium text-[14px]">
                    {editingId === t.id ? (
                      <Input
                        autoFocus
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        onBlur={() => commitEdit(t)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault()
                            commitEdit(t)
                          } else if (e.key === "Escape") {
                            e.preventDefault()
                            cancelEdit()
                          }
                        }}
                        placeholder={t.original_name || "Tracker name"}
                        className="h-8 text-[14px]"
                      />
                    ) : (
                      <button
                        type="button"
                        onClick={() => startEdit(t)}
                        title="Click to rename"
                        className="text-left hover:text-purple-600 transition-colors"
                      >
                        {t.name || (
                          <span className="text-rt-fg-tertiary">Untitled</span>
                        )}
                        {t.client?.name && (
                          <span className="ml-2 inline-block px-1.5 py-0.5 rounded bg-rt-magenta/10 text-rt-magenta text-[10px] uppercase tracking-wide">
                            {t.client.name}
                          </span>
                        )}
                      </button>
                    )}
                  </TableCell>
                  <TableCell>
                    {t.cobrand_share_url ? (
                      <a
                        href={t.cobrand_share_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[13px] text-rt-magenta hover:underline inline-flex items-center gap-1"
                      >
                        {shortenUrl(t.cobrand_share_url)}
                        <ExternalLink className="size-3" />
                      </a>
                    ) : (
                      <span className="text-rt-fg-tertiary text-[13px]">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {t.tracker_url ? (
                      <div className="flex items-center gap-2">
                        <a
                          href={t.tracker_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-[13px] text-purple-600 hover:underline inline-flex items-center gap-1"
                        >
                          Open
                          <ExternalLink className="size-3" />
                        </a>
                        <button
                          type="button"
                          onClick={() => handleCopy(t)}
                          title={copiedId === t.id ? "Copied!" : "Copy tracker link"}
                          className="text-rt-fg-tertiary hover:text-purple-600 transition-colors"
                        >
                          {copiedId === t.id ? (
                            <Check className="size-3.5 text-rt-green" />
                          ) : (
                            <Copy className="size-3.5" />
                          )}
                        </button>
                      </div>
                    ) : (
                      <span className="text-rt-fg-tertiary text-[13px]">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      <Select
                        value={t.campaign_slug ?? NO_CAMPAIGN}
                        onValueChange={(v) => handleSetCampaign(t, v)}
                      >
                        <SelectTrigger className="h-8 text-[13px]">
                          <SelectValue placeholder="—" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value={NO_CAMPAIGN}>—</SelectItem>
                          {t.campaign_slug &&
                            !activeCampaigns.some((c) => c.slug === t.campaign_slug) && (
                              <SelectItem value={t.campaign_slug}>
                                {t.campaign?.title || t.campaign_slug}
                              </SelectItem>
                            )}
                          {activeCampaigns.map((c) => (
                            <SelectItem key={c.slug} value={c.slug}>
                              {c.title}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {/* Auto-suggestion: shown when sound IDs overlap and the tracker
                          isn't already linked to that campaign. One click adopts it. */}
                      {(t.auto_suggested_campaigns ?? [])
                        .filter((s: TrackerCampaignSuggestion) => s.slug !== t.campaign_slug)
                        .slice(0, 1)
                        .map((s: TrackerCampaignSuggestion) => (
                          <button
                            key={s.slug}
                            type="button"
                            onClick={() => handleSetCampaign(t, s.slug)}
                            title={`Sound IDs match: ${s.matched_sound_ids.join(", ") || "—"}`}
                            className="text-left text-[11px] text-purple-600 hover:underline truncate"
                          >
                            ✦ matches {s.title}
                          </button>
                        ))}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Select
                      value={t.group_id == null ? NO_GROUP : String(t.group_id)}
                      onValueChange={(v) => handleSetGroup(t, v)}
                    >
                      <SelectTrigger className="h-8 text-[13px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_GROUP}>—</SelectItem>
                        {groups.map((g) => (
                          <SelectItem key={g.id} value={String(g.id)}>
                            {g.title}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-[13px] text-rt-fg-tertiary">
                    {formatDate(t.created_at)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1">
                      {t.archived_at ? (
                        <button
                          type="button"
                          onClick={() => handleRestore(t)}
                          disabled={restoreTracker.isPending}
                          title="Restore tracker"
                          className="p-1.5 rounded text-rt-fg-tertiary hover:text-purple-600 bg-rt-bg-card transition-colors disabled:opacity-50"
                        >
                          <Undo2 className="size-3.5" />
                        </button>
                      ) : (
                        <>
                          <button
                            type="button"
                            onClick={() => startEdit(t)}
                            title="Rename tracker"
                            className="p-1.5 rounded text-rt-fg-tertiary hover:text-purple-600 bg-rt-bg-card transition-colors"
                          >
                            <Pencil className="size-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleArchive(t)}
                            disabled={archiveTracker.isPending}
                            title="Archive tracker"
                            className="p-1.5 rounded text-rt-fg-tertiary hover:text-rt-red hover:bg-rt-red/10 transition-colors disabled:opacity-50"
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

function SortableHead({
  label,
  field,
  sortField,
  sortDir,
  onSort,
  className,
}: {
  label: string
  field: SortField
  sortField: SortField
  sortDir: SortDir
  onSort: (field: SortField) => void
  className?: string
}) {
  const active = sortField === field
  const Icon = active ? (sortDir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown
  return (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => onSort(field)}
        className={`inline-flex items-center gap-1 hover:text-rt-fg transition-colors ${
          active ? "text-rt-fg" : ""
        }`}
      >
        {label}
        <Icon className={`size-3 ${active ? "" : "opacity-40"}`} />
      </button>
    </TableHead>
  )
}

function GroupPill({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean
  onClick: () => void
  label: string
  count: number
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-[12px] font-medium transition-colors ${
        active
          ? "bg-purple-600 text-white"
          : "bg-white/5 text-rt-fg hover:bg-white/8"
      }`}
    >
      {label}
      <span
        className={`inline-block min-w-[18px] text-center px-1 rounded-full text-[10px] ${
          active ? "bg-white/20" : "bg-rt-bg-card text-rt-fg-tertiary"
        }`}
      >
        {count}
      </span>
    </button>
  )
}

import { useMemo, useState } from "react"
import { ExternalLink, Plus, Loader2, Activity } from "lucide-react"
import {
  useTrackers,
  useTrackerGroups,
  useCreateStandaloneTracker,
  useSetTrackerGroup,
  useCreateTrackerGroup,
} from "@/lib/queries"
import type { Tracker } from "@/lib/types"
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
  const { data: trackers = [], isLoading } = useTrackers()
  const { data: groups = [] } = useTrackerGroups()

  const [activeGroup, setActiveGroup] = useState<string>(ALL_GROUP)
  const [cobrandUrl, setCobrandUrl] = useState("")
  const [name, setName] = useState("")
  const [createGroupId, setCreateGroupId] = useState<string>(NO_GROUP)
  const [newGroupTitle, setNewGroupTitle] = useState("")
  const [showNewGroup, setShowNewGroup] = useState(false)

  const createTracker = useCreateStandaloneTracker()
  const setTrackerGroup = useSetTrackerGroup()
  const createGroup = useCreateTrackerGroup()

  const filteredTrackers = useMemo(() => {
    if (activeGroup === ALL_GROUP) return trackers
    if (activeGroup === NO_GROUP) return trackers.filter((t) => t.group_id == null)
    const gid = Number(activeGroup)
    return trackers.filter((t) => t.group_id === gid)
  }, [trackers, activeGroup])

  const ungroupedCount = useMemo(
    () => trackers.filter((t) => t.group_id == null).length,
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

  return (
    <div>
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-[22px] font-semibold flex items-center gap-2">
          <Activity className="size-5 text-purple-600" />
          TidesTrackers
        </h1>
        <p className="text-[13px] text-[#888] mt-1">
          Manage all your Cobrand trackers in one place. Group them by label or however you like.
        </p>
      </div>

      {/* Create form */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-5 mb-4">
        <div className="text-[12px] font-semibold uppercase tracking-wide text-[#888] mb-3">
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
          <div className="text-[12px] text-red-600 mt-2">
            {(createTracker.error as Error)?.message || "Failed to create tracker"}
          </div>
        )}
      </div>

      {/* Group pills */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-4 py-3 mb-4">
        <div className="flex items-center gap-2 flex-wrap">
          <GroupPill
            active={activeGroup === ALL_GROUP}
            onClick={() => setActiveGroup(ALL_GROUP)}
            label="All"
            count={trackers.length}
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

          <div className="flex-1" />

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
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Cobrand link</TableHead>
              <TableHead>Tracker</TableHead>
              <TableHead className="w-[180px]">Group</TableHead>
              <TableHead className="w-[120px]">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-10 text-[#999] text-[13px]">
                  Loading…
                </TableCell>
              </TableRow>
            ) : filteredTrackers.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-center py-10 text-[#999] text-[13px]">
                  No trackers in this group yet. Paste a Cobrand link above to create one.
                </TableCell>
              </TableRow>
            ) : (
              filteredTrackers.map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="font-medium text-[14px]">
                    {t.name || <span className="text-[#999]">Untitled</span>}
                    {t.client?.name && (
                      <span className="ml-2 inline-block px-1.5 py-0.5 rounded bg-[#eef2ff] text-[#0b62d6] text-[10px] uppercase tracking-wide">
                        {t.client.name}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    {t.cobrand_share_url ? (
                      <a
                        href={t.cobrand_share_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[13px] text-[#0b62d6] hover:underline inline-flex items-center gap-1"
                      >
                        {shortenUrl(t.cobrand_share_url)}
                        <ExternalLink className="size-3" />
                      </a>
                    ) : (
                      <span className="text-[#999] text-[13px]">-</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {t.tracker_url ? (
                      <a
                        href={t.tracker_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-[13px] text-purple-600 hover:underline inline-flex items-center gap-1"
                      >
                        Open
                        <ExternalLink className="size-3" />
                      </a>
                    ) : (
                      <span className="text-[#999] text-[13px]">-</span>
                    )}
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
                  <TableCell className="text-[13px] text-[#666]">
                    {formatDate(t.created_at)}
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
          : "bg-[#f0f0f5] text-[#555] hover:bg-[#e4e4ed]"
      }`}
    >
      {label}
      <span
        className={`inline-block min-w-[18px] text-center px-1 rounded-full text-[10px] ${
          active ? "bg-white/20" : "bg-white text-[#888]"
        }`}
      >
        {count}
      </span>
    </button>
  )
}

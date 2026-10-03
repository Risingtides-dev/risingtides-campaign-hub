import { useState } from "react"
import { Link } from "react-router-dom"
import {
  useInternalCreators,
  useInternalGroups,
  useInternalGroup,
  useAddInternalCreators,
  useRemoveInternalCreator,
} from "@/lib/queries"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Loader2, X, ChevronDown, ChevronRight } from "lucide-react"
import type { InternalGroup, InternalCreator } from "@/lib/types"

export function CreatorSidebar() {
  const { data: creators, isLoading: creatorsLoading } = useInternalCreators()
  const { data: groups, isLoading: groupsLoading } = useInternalGroups()
  const addCreators = useAddInternalCreators()
  const removeCreator = useRemoveInternalCreator()
  const [input, setInput] = useState("")
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  const isLoading = creatorsLoading || groupsLoading

  // Build a lookup: username -> creator data
  const creatorMap = new Map<string, InternalCreator>()
  for (const c of creators || []) {
    creatorMap.set(c.username.toLowerCase(), c)
  }

  // Sort groups by sort_order
  const sortedGroups = [...(groups || [])].sort(
    (a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99)
  )

  function toggleGroup(slug: string) {
    setCollapsed((prev) => ({ ...prev, [slug]: !prev[slug] }))
  }

  function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    const value = input.trim()
    if (!value) return
    addCreators.mutate(value, {
      onSuccess: () => setInput(""),
    })
  }

  function handleRemove(username: string) {
    if (!confirm(`Remove @${username} from internal creators?`)) return
    removeCreator.mutate(username)
  }

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-4 lg:sticky lg:top-6">
      <h3 className="text-[15px] font-semibold mb-3">
        Internal Creators ({creators?.length ?? 0})
      </h3>

      {/* Add form */}
      <form onSubmit={handleAdd} className="mb-3">
        <div className="flex gap-1.5">
          <Input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="@username"
            className="flex-1 text-[13px] h-8"
          />
          <Button
            type="submit"
            size="sm"
            className="bg-rt-magenta hover:bg-rt-purple text-white text-xs"
            disabled={addCreators.isPending || !input.trim()}
          >
            {addCreators.isPending ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              "Add"
            )}
          </Button>
        </div>
        <p className="text-[11px] text-rt-fg-tertiary mt-1">
          Comma or newline separated for bulk add
        </p>
      </form>

      {addCreators.isError && (
        <p className="text-rt-red text-xs mb-2">
          {addCreators.error?.message || "Failed to add creators"}
        </p>
      )}

      {/* Grouped creator list */}
      <div className="max-h-[600px] overflow-y-auto">
        {isLoading && (
          <div className="flex items-center justify-center py-6">
            <Loader2 className="size-4 animate-spin text-rt-fg-tertiary" />
          </div>
        )}

        {!isLoading && sortedGroups.length === 0 && (
          <p className="text-rt-fg-tertiary text-xs text-center py-4">
            No groups found.
          </p>
        )}

        {!isLoading &&
          sortedGroups
            .filter((g) => g.member_count > 0 || g.slug !== "general")
            .map((group) => (
              <GroupSection
                key={group.slug}
                group={group}
                creatorMap={creatorMap}
                isCollapsed={!!collapsed[group.slug]}
                onToggle={() => toggleGroup(group.slug)}
                onRemove={handleRemove}
                removeDisabled={removeCreator.isPending}
              />
            ))}
      </div>
    </div>
  )
}

function GroupSection({
  group,
  creatorMap,
  isCollapsed,
  onToggle,
  onRemove,
  removeDisabled,
}: {
  group: InternalGroup
  creatorMap: Map<string, InternalCreator>
  isCollapsed: boolean
  onToggle: () => void
  onRemove: (username: string) => void
  removeDisabled: boolean
}) {
  // Fetch group detail to get member usernames.
  // Small number of groups so per-group queries are fine.
  const { data: detail } = useInternalGroup(group.slug)
  const members = detail?.members || []

  return (
    <div className="mb-2">
      <button
        type="button"
        onClick={onToggle}
        className="flex items-center gap-1.5 w-full text-left py-1.5 hover:bg-white/[0.03] rounded px-1 -mx-1"
      >
        {isCollapsed ? (
          <ChevronRight className="size-3.5 text-rt-fg-tertiary flex-shrink-0" />
        ) : (
          <ChevronDown className="size-3.5 text-rt-fg-tertiary flex-shrink-0" />
        )}
        <span className="text-[13px] font-semibold text-rt-fg">
          {group.title}
        </span>
        <span className="text-[11px] text-rt-fg-tertiary ml-auto">
          {group.member_count}
        </span>
      </button>

      {!isCollapsed && (
        <div className="ml-5">
          {members.length === 0 && (
            <p className="text-white/15 text-[11px] py-1">Loading...</p>
          )}
          {members
            .sort((a, b) => {
              const aData = creatorMap.get(a.toLowerCase())
              const bData = creatorMap.get(b.toLowerCase())
              return (bData?.total_views ?? 0) - (aData?.total_views ?? 0)
            })
            .map((username) => {
              const creator = creatorMap.get(username.toLowerCase())
              return (
                <div
                  key={username}
                  className="flex items-center justify-between py-1 border-b border-white/5 last:border-b-0"
                >
                  <Link
                    to={`/internal/${username}`}
                    className="text-rt-magenta text-[13px] hover:underline flex-1 min-w-0"
                  >
                    @{username}
                    {creator && creator.total_videos > 0 && (
                      <span className="text-rt-fg-tertiary text-[11px] ml-1">
                        {creator.total_videos} posts &middot;{" "}
                        {creator.total_views.toLocaleString()}v
                      </span>
                    )}
                  </Link>
                  <button
                    type="button"
                    onClick={() => onRemove(username)}
                    className="text-rt-red hover:text-rt-red text-[16px] px-1.5 py-0.5 leading-none flex-shrink-0"
                    title="Remove"
                    disabled={removeDisabled}
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              )
            })}
        </div>
      )}
    </div>
  )
}

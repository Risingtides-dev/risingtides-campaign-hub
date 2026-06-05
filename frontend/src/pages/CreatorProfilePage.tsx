import { useState, useMemo } from "react"
import { useParams, Link } from "react-router-dom"
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table"
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  ChevronRight,
  ExternalLink,
  Loader2,
} from "lucide-react"
import { useCreatorProfile, useUpdateCreatorNiches } from "@/lib/queries"
import type { CreatorCampaignEntry, CreatorVideo } from "@/lib/types"
import { NICHE_VOCAB } from "@/lib/types"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Button } from "@/components/ui/button"

// ---- Helpers ----

function formatCurrency(value: number): string {
  return `$${value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

function formatViews(value: number): string {
  if (!value) return "-"
  return value.toLocaleString("en-US")
}

function formatCpm(value: number | null): string {
  if (value === null || value === undefined) return "-"
  return `$${value.toFixed(2)}`
}

// ---- Niche Colors ----

const NICHE_COLORS: Record<string, string> = {}
const COLOR_PALETTE = [
  "bg-blue-100 text-blue-700",
  "bg-purple-100 text-purple-700",
  "bg-green-100 text-green-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-cyan-100 text-cyan-700",
  "bg-indigo-100 text-indigo-700",
  "bg-orange-100 text-orange-700",
  "bg-teal-100 text-teal-700",
  "bg-pink-100 text-pink-700",
]
function getNicheColor(niche: string): string {
  if (!NICHE_COLORS[niche]) {
    NICHE_COLORS[niche] = COLOR_PALETTE[Object.keys(NICHE_COLORS).length % COLOR_PALETTE.length]
  }
  return NICHE_COLORS[niche]
}

// ---- TikTok Icon ----

function TikTokIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="currentColor"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1v-3.5a6.37 6.37 0 00-.79-.05A6.34 6.34 0 003.15 15.2a6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.34-6.34V8.73a8.19 8.19 0 004.76 1.52V6.8a4.84 4.84 0 01-1-.11z" />
    </svg>
  )
}

// ---- Sortable Header ----

function SortableHeader({
  column,
  label,
}: {
  column: {
    getIsSorted: () => false | "asc" | "desc"
    toggleSorting: (desc?: boolean) => void
  }
  label: string
}) {
  const sorted = column.getIsSorted()
  return (
    <button
      type="button"
      className="flex items-center gap-1 hover:text-[#555] transition-colors"
      onClick={() => column.toggleSorting(sorted === "asc")}
    >
      {label}
      {sorted === "asc" ? (
        <ArrowUp className="size-3" />
      ) : sorted === "desc" ? (
        <ArrowDown className="size-3" />
      ) : (
        <ArrowUpDown className="size-3 opacity-40" />
      )}
    </button>
  )
}

// ---- Main Component ----

export default function CreatorProfilePage() {
  const { username } = useParams<{ username: string }>()
  const { data: profile, isLoading, isError, error } = useCreatorProfile(
    username!
  )
  const updateNiches = useUpdateCreatorNiches(username!)
  const [editingNiches, setEditingNiches] = useState(false)
  const [pendingNiches, setPendingNiches] = useState<string[]>([])

  const [campaignSorting, setCampaignSorting] = useState<SortingState>([])
  const [videoSorting, setVideoSorting] = useState<SortingState>([
    { id: "views", desc: true },
  ])

  // Campaign history columns
  const campaignColumns: ColumnDef<CreatorCampaignEntry>[] = useMemo(
    () => [
      {
        accessorKey: "title",
        header: ({ column }) => (
          <SortableHeader column={column} label="Campaign" />
        ),
        cell: ({ row }) => {
          const c = row.original
          return (
            <Link
              to={`/campaign/${c.slug}`}
              className="font-semibold text-rt-magenta hover:underline"
            >
              {c.title}
            </Link>
          )
        },
      },
      {
        accessorKey: "posts_done",
        id: "posts",
        header: ({ column }) => (
          <SortableHeader column={column} label="Posts" />
        ),
        cell: ({ row }) => (
          <span className="font-semibold">
            {row.original.posts_done} / {row.original.posts_owed}
          </span>
        ),
        sortingFn: (rowA, rowB) =>
          rowA.original.posts_done - rowB.original.posts_done,
      },
      {
        accessorKey: "total_rate",
        header: ({ column }) => (
          <SortableHeader column={column} label="Rate" />
        ),
        cell: ({ row }) => (
          <span>{formatCurrency(row.original.total_rate)}</span>
        ),
      },
      {
        accessorKey: "paid",
        header: ({ column }) => (
          <SortableHeader column={column} label="Paid" />
        ),
        cell: ({ row }) => {
          const isPaid = row.original.paid?.toLowerCase() === "yes"
          return (
            <span
              className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                isPaid
                  ? "bg-rt-green/10 text-rt-green"
                  : "bg-rt-red/10 text-rt-red"
              }`}
            >
              {isPaid ? "Paid" : "Unpaid"}
            </span>
          )
        },
      },
      {
        accessorKey: "status",
        header: ({ column }) => (
          <SortableHeader column={column} label="Status" />
        ),
        cell: ({ row }) => {
          const status = row.original.status || "active"
          return (
            <span
              className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                status === "active"
                  ? "bg-rt-magenta/10 text-rt-magenta"
                  : "bg-white/5 text-rt-fg-tertiary"
              }`}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
            </span>
          )
        },
      },
      {
        accessorKey: "notes",
        header: "Notes",
        cell: ({ row }) => (
          <span className="text-[12px] text-[#666]">
            {row.original.notes || ""}
          </span>
        ),
      },
    ],
    []
  )

  // Video columns
  const videoColumns: ColumnDef<CreatorVideo>[] = useMemo(
    () => [
      {
        accessorKey: "campaign_title",
        header: ({ column }) => (
          <SortableHeader column={column} label="Campaign" />
        ),
        cell: ({ row }) => (
          <Link
            to={`/campaign/${row.original.campaign_slug}`}
            className="text-rt-magenta hover:underline text-[13px]"
          >
            {row.original.campaign_title}
          </Link>
        ),
      },
      {
        accessorKey: "url",
        header: "Post",
        cell: ({ row }) => (
          <a
            href={row.original.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-rt-magenta hover:underline inline-flex items-center gap-1 text-[13px]"
          >
            View Post
            <ExternalLink className="size-3" />
          </a>
        ),
      },
      {
        accessorKey: "views",
        header: ({ column }) => (
          <SortableHeader column={column} label="Views" />
        ),
        cell: ({ row }) => (
          <span className="text-[14px]">
            {formatViews(row.original.views)}
          </span>
        ),
      },
      {
        accessorKey: "likes",
        header: ({ column }) => (
          <SortableHeader column={column} label="Likes" />
        ),
        cell: ({ row }) => (
          <span className="text-[14px]">
            {formatViews(row.original.likes)}
          </span>
        ),
      },
      {
        accessorKey: "upload_date",
        header: ({ column }) => (
          <SortableHeader column={column} label="Date" />
        ),
        cell: ({ row }) => (
          <span className="text-[13px] text-[#666]">
            {row.original.upload_date || "-"}
          </span>
        ),
      },
    ],
    []
  )

  const campaignTable = useReactTable({
    data: profile?.campaigns ?? [],
    columns: campaignColumns,
    state: { sorting: campaignSorting },
    onSortingChange: setCampaignSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  const videoTable = useReactTable({
    data: profile?.videos ?? [],
    columns: videoColumns,
    state: { sorting: videoSorting },
    onSortingChange: setVideoSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  // Loading
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="size-6 animate-spin text-rt-fg-tertiary" />
        <span className="ml-2 text-rt-fg-tertiary text-sm">Loading creator...</span>
      </div>
    )
  }

  // Error
  if (isError || !profile) {
    return (
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-10 text-center">
        <p className="text-red-600 text-sm">
          {error?.message || "Failed to load creator profile"}
        </p>
        <Link
          to="/creators"
          className="text-rt-magenta text-sm mt-2 inline-block hover:underline"
        >
          Back to Creator Database
        </Link>
      </div>
    )
  }

  const { stats } = profile

  const statCards = [
    {
      label: "Campaigns",
      value: stats.campaigns_count.toString(),
    },
    {
      label: "Total Spend",
      value: formatCurrency(stats.total_spend),
    },
    {
      label: "Total Payout",
      value: formatCurrency(stats.total_payout),
      sub:
        stats.total_spend > 0
          ? `${Math.round((stats.total_payout / stats.total_spend) * 100)}% paid`
          : undefined,
    },
    {
      label: "Posts",
      value: `${stats.total_posts_done} / ${stats.total_posts_owed}`,
    },
    {
      label: "Total Views",
      value: formatViews(stats.total_views),
    },
    {
      label: "Avg CPM",
      value: formatCpm(stats.avg_cpm),
    },
  ]

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-[13px] text-rt-fg-tertiary">
        <Link
          to="/creators"
          className="hover:text-[#555] transition-colors"
        >
          Creator Database
        </Link>
        <ChevronRight className="size-3.5" />
        <span className="text-[#333] font-medium">@{profile.username}</span>
      </div>

      {/* Header */}
      <div className="bg-rt-bg-card border border-white/8 rounded-[10px] px-6 py-5">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <h1 className="text-[22px] font-semibold text-rt-fg">
              @{profile.username}
            </h1>
            {profile.paypal_email && (
              <p className="text-[13px] text-rt-fg-tertiary mt-0.5">
                PayPal: {profile.paypal_email}
              </p>
            )}

            {/* Niche tags */}
            <div className="mt-3">
              {editingNiches ? (
                <div className="space-y-2">
                  <div className="flex flex-wrap gap-1.5">
                    {NICHE_VOCAB.map((n) => {
                      const active = pendingNiches.includes(n)
                      return (
                        <button
                          key={n}
                          type="button"
                          onClick={() =>
                            setPendingNiches((prev) =>
                              active ? prev.filter((x) => x !== n) : [...prev, n]
                            )
                          }
                          className={`inline-flex items-center px-2.5 py-1 rounded-full text-[12px] font-medium border transition-all ${
                            active
                              ? getNicheColor(n) + " border-transparent"
                              : "bg-rt-bg-card text-rt-fg-tertiary border-white/10 hover:border-white/20"
                          }`}
                        >
                          {n}
                        </button>
                      )
                    })}
                  </div>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      className="bg-rt-magenta hover:bg-rt-purple text-white"
                      disabled={updateNiches.isPending}
                      onClick={() => {
                        updateNiches.mutate(pendingNiches, {
                          onSuccess: () => setEditingNiches(false),
                        })
                      }}
                    >
                      {updateNiches.isPending ? (
                        <Loader2 className="size-3 animate-spin mr-1" />
                      ) : null}
                      Save
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setEditingNiches(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-2 flex-wrap">
                  {(profile.niches || []).length === 0 ? (
                    <span className="text-[12px] text-[#bbb]">No niches tagged</span>
                  ) : (
                    (profile.niches || []).map((n) => (
                      <span
                        key={n}
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${getNicheColor(n)}`}
                      >
                        {n}
                      </span>
                    ))
                  )}
                  <button
                    type="button"
                    className="text-[11px] text-rt-magenta hover:underline ml-1"
                    onClick={() => {
                      setPendingNiches(profile.niches || [])
                      setEditingNiches(true)
                    }}
                  >
                    {(profile.niches || []).length === 0 ? "Add niches" : "Edit"}
                  </button>
                </div>
              )}
            </div>
          </div>

          <a
            href={`https://www.tiktok.com/@${profile.username}`}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0"
          >
            <Button
              variant="outline"
              className="gap-2"
            >
              <TikTokIcon className="size-4" />
              View on TikTok
            </Button>
          </a>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="bg-rt-bg-card border border-white/8 rounded-[10px] p-4"
          >
            <div className="text-rt-fg-tertiary text-xs font-semibold uppercase tracking-wide mb-1">
              {card.label}
            </div>
            <div className="text-[22px] font-bold text-rt-fg">
              {card.value}
            </div>
            {card.sub && (
              <div className="text-rt-fg-tertiary text-[13px] mt-0.5">{card.sub}</div>
            )}
          </div>
        ))}
      </div>

      {/* Campaign History */}
      <div>
        <h2 className="text-[16px] font-semibold text-rt-fg mb-3">
          Campaign History
        </h2>
        <div className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                {campaignTable.getHeaderGroups().map((headerGroup) => (
                  <TableRow
                    key={headerGroup.id}
                    className="border-b-2 border-white/8 hover:bg-transparent"
                  >
                    {headerGroup.headers.map((header) => (
                      <TableHead
                        key={header.id}
                        className="text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3 border-b-2 border-white/8"
                      >
                        {header.isPlaceholder
                          ? null
                          : flexRender(
                              header.column.columnDef.header,
                              header.getContext()
                            )}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {campaignTable.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={campaignColumns.length}
                      className="text-center text-rt-fg-tertiary py-10 text-sm"
                    >
                      No campaign history.
                    </TableCell>
                  </TableRow>
                ) : (
                  campaignTable.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="hover:bg-white/[0.03] border-b border-white/5"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          className="px-4 py-2 text-[14px] border-b border-white/5 align-middle"
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </div>
      </div>

      {/* Live Posts */}
      {profile.videos.length > 0 && (
        <div>
          <h2 className="text-[16px] font-semibold text-rt-fg mb-3">
            Live Posts ({profile.videos.length})
          </h2>
          <div className="bg-rt-bg-card border border-white/8 rounded-[10px] overflow-hidden">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  {videoTable.getHeaderGroups().map((headerGroup) => (
                    <TableRow
                      key={headerGroup.id}
                      className="border-b-2 border-white/8 hover:bg-transparent"
                    >
                      {headerGroup.headers.map((header) => (
                        <TableHead
                          key={header.id}
                          className="text-rt-fg-tertiary text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3 border-b-2 border-white/8"
                        >
                          {header.isPlaceholder
                            ? null
                            : flexRender(
                                header.column.columnDef.header,
                                header.getContext()
                              )}
                        </TableHead>
                      ))}
                    </TableRow>
                  ))}
                </TableHeader>
                <TableBody>
                  {videoTable.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="hover:bg-white/[0.03] border-b border-white/5"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          className="px-4 py-2 text-[14px] border-b border-white/5 align-middle"
                        >
                          {flexRender(
                            cell.column.columnDef.cell,
                            cell.getContext()
                          )}
                        </TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

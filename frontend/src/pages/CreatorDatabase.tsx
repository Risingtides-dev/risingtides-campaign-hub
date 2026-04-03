import { useState, useMemo } from "react"
import { useNavigate } from "react-router-dom"
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table"
import { ArrowUpDown, ArrowUp, ArrowDown, Search, X } from "lucide-react"
import { useCreators } from "@/lib/queries"
import type { CreatorSummary } from "@/lib/types"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

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

// ---- Main Component ----

export default function CreatorDatabase() {
  const { data: creators, isLoading, isError, error } = useCreators()
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const [selectedNiche, setSelectedNiche] = useState<string | null>(null)
  const [sorting, setSorting] = useState<SortingState>([
    { id: "total_spend", desc: true },
  ])

  // Collect all unique niches across creators
  const allNiches = useMemo(() => {
    if (!creators) return []
    const set = new Set<string>()
    creators.forEach((c) => (c.niches || []).forEach((n) => set.add(n)))
    return Array.from(set).sort()
  }, [creators])

  const filtered = useMemo(() => {
    if (!creators) return []
    let result = creators
    if (search.trim()) {
      const q = search.toLowerCase()
      result = result.filter((c) => c.username.toLowerCase().includes(q))
    }
    if (selectedNiche) {
      result = result.filter((c) => (c.niches || []).includes(selectedNiche))
    }
    return result
  }, [creators, search, selectedNiche])

  const columns: ColumnDef<CreatorSummary>[] = useMemo(
    () => [
      {
        accessorKey: "username",
        header: ({ column }) => (
          <SortableHeader column={column} label="Creator" />
        ),
        cell: ({ row }) => {
          const c = row.original
          return (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  navigate(`/creators/${c.username}`)
                }}
                className="font-semibold text-[#0b62d6] hover:underline"
              >
                @{c.username}
              </button>
              <a
                href={`https://www.tiktok.com/@${c.username}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#999] hover:text-[#333] transition-colors"
                onClick={(e) => e.stopPropagation()}
                title="View on TikTok"
              >
                <TikTokIcon className="size-3.5" />
              </a>
            </div>
          )
        },
      },
      {
        id: "niches",
        header: "Niches",
        cell: ({ row }) => {
          const niches = row.original.niches || []
          if (niches.length === 0) return <span className="text-[#ccc] text-xs">{"\u2014"}</span>
          return (
            <div className="flex flex-wrap gap-1">
              {niches.map((n) => (
                <span key={n} className={`inline-flex items-center px-1.5 py-0.5 rounded-full text-[10px] font-medium ${getNicheColor(n)}`}>
                  {n}
                </span>
              ))}
            </div>
          )
        },
      },
      {
        accessorKey: "campaigns_count",
        header: ({ column }) => (
          <SortableHeader column={column} label="Campaigns" />
        ),
        cell: ({ row }) => (
          <span className="text-[14px] font-semibold">
            {row.original.campaigns_count}
          </span>
        ),
      },
      {
        accessorKey: "total_posts_done",
        id: "posts",
        header: ({ column }) => (
          <SortableHeader column={column} label="Posts" />
        ),
        cell: ({ row }) => (
          <span className="text-[14px] font-semibold">
            {row.original.total_posts_done} / {row.original.total_posts_owed}
          </span>
        ),
        sortingFn: (rowA, rowB) =>
          rowA.original.total_posts_done - rowB.original.total_posts_done,
      },
      {
        accessorKey: "total_spend",
        header: ({ column }) => (
          <SortableHeader column={column} label="Total Spend" />
        ),
        cell: ({ row }) => (
          <span className="text-[14px]">
            {formatCurrency(row.original.total_spend)}
          </span>
        ),
      },
      {
        accessorKey: "total_payout",
        header: ({ column }) => (
          <SortableHeader column={column} label="Total Payout" />
        ),
        cell: ({ row }) => {
          const c = row.original
          const fullyPaid = c.total_payout >= c.total_spend && c.total_spend > 0
          return (
            <span
              className="text-[14px]"
              style={{ color: fullyPaid ? "#22c55e" : undefined }}
            >
              {formatCurrency(c.total_payout)}
            </span>
          )
        },
      },
      {
        accessorKey: "total_views",
        header: ({ column }) => (
          <SortableHeader column={column} label="Total Views" />
        ),
        cell: ({ row }) => (
          <span className="text-[14px]">
            {formatViews(row.original.total_views)}
          </span>
        ),
      },
      {
        accessorKey: "avg_cpm",
        header: ({ column }) => (
          <SortableHeader column={column} label="Avg CPM" />
        ),
        cell: ({ row }) => (
          <span className="text-[14px]">
            {formatCpm(row.original.avg_cpm)}
          </span>
        ),
        sortingFn: (rowA, rowB) =>
          (rowA.original.avg_cpm ?? 0) - (rowB.original.avg_cpm ?? 0),
      },
    ],
    [navigate]
  )

  const table = useReactTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div>
      {/* Top bar */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-[22px] font-semibold">Creator Database</h1>
      </div>

      {/* Search bar */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-5 py-3.5 mb-4">
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-[300px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#888]" />
            <Input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search creators..."
              className="pl-9"
            />
          </div>
          {search && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSearch("")}
            >
              <X className="size-3" />
              Clear
            </Button>
          )}
          {/* Niche filter chips */}
          {allNiches.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] text-[#999] uppercase tracking-wide">Niche:</span>
              {allNiches.map((niche) => (
                <button
                  key={niche}
                  type="button"
                  onClick={() => setSelectedNiche(selectedNiche === niche ? null : niche)}
                  className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-medium transition-all ${
                    selectedNiche === niche
                      ? getNicheColor(niche) + " ring-2 ring-offset-1 ring-current"
                      : "bg-[#f0f0f5] text-[#666] hover:bg-[#e4e4ed]"
                  }`}
                >
                  {niche}
                </button>
              ))}
              {selectedNiche && (
                <button
                  type="button"
                  onClick={() => setSelectedNiche(null)}
                  className="text-[11px] text-[#999] hover:text-[#555] underline"
                >
                  clear
                </button>
              )}
            </div>
          )}
          <span className="ml-auto text-[#888] text-[13px]">
            {filtered.length} creator{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Loading state */}
      {isLoading && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
          <p className="text-[#888] text-sm">Loading creators...</p>
        </div>
      )}

      {/* Error state */}
      {isError && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
          <p className="text-red-600 text-sm">
            {error?.message || "Failed to load creators"}
          </p>
        </div>
      )}

      {/* Creator table */}
      {!isLoading && !isError && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow
                    key={headerGroup.id}
                    className="border-b-2 border-[#e8e8ef] hover:bg-transparent"
                  >
                    {headerGroup.headers.map((header) => (
                      <TableHead
                        key={header.id}
                        className="text-[#888] text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3 border-b-2 border-[#e8e8ef]"
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
                {table.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCell
                      colSpan={columns.length}
                      className="text-center text-[#888] py-10 text-sm"
                    >
                      No creators found.
                    </TableCell>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <TableRow
                      key={row.id}
                      className="cursor-pointer hover:bg-[#fafaff] border-b border-[#f0f0f5]"
                      onClick={() =>
                        navigate(`/creators/${row.original.username}`)
                      }
                    >
                      {row.getVisibleCells().map((cell) => (
                        <TableCell
                          key={cell.id}
                          className="px-4 py-2 text-[14px] border-b border-[#f0f0f5] align-middle"
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
      )}
    </div>
  )
}

import { useNavigate } from "react-router-dom"
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table"
import { useState, useMemo, useCallback } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { ArrowUpDown, ArrowUp, ArrowDown, Check } from "lucide-react"
import type { CampaignSummary } from "@/lib/types"
import { api } from "@/lib/api"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

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

const COMPLETION_CYCLE: Record<string, CampaignSummary["completion_status"]> = {
  none: "booked",
  booked: "completed",
  completed: "none",
}

function CompletionCell({
  status,
  onClick,
}: {
  status: CampaignSummary["completion_status"]
  onClick: (e: React.MouseEvent) => void
}) {
  if (status === "none") {
    return (
      <button
        type="button"
        onClick={onClick}
        className="size-5 rounded border border-[#d0d0d8] bg-white hover:border-[#999] transition-colors"
        title="Mark booking complete"
      />
    )
  }
  if (status === "booked") {
    return (
      <button
        type="button"
        onClick={onClick}
        className="size-5 rounded border border-[#999] bg-[#f0f0f5] flex items-center justify-center hover:border-[#666] transition-colors"
        title="Booking complete — click to mark campaign wrapped"
      >
        <Check className="size-3.5 text-[#888]" />
      </button>
    )
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className="size-5 rounded border border-[#16a34a] bg-[#f0fdf4] flex items-center justify-center hover:border-[#15803d] transition-colors"
      title="Campaign wrapped — click to reset"
    >
      <Check className="size-3.5 text-[#16a34a]" />
    </button>
  )
}

function buildColumns(
  onToggleCompletion: (slug: string, current: CampaignSummary["completion_status"]) => void
): ColumnDef<CampaignSummary>[] {
  return [
  {
    id: "completion",
    header: () => <span className="sr-only">Done</span>,
    cell: ({ row }) => {
      const status = row.original.completion_status || "none"
      return (
        <CompletionCell
          status={status}
          onClick={(e) => {
            e.stopPropagation()
            onToggleCompletion(row.original.slug, status)
          }}
        />
      )
    },
    size: 40,
    enableSorting: false,
  },
  {
    accessorKey: "title",
    header: ({ column }) => (
      <SortableHeader column={column} label="Promotions" />
    ),
    cell: ({ row }) => (
      <div>
        <div className="font-semibold text-[14px]">{row.original.title}</div>
        <div className="text-[#888] text-[13px]">{row.original.song || ""}</div>
      </div>
    ),
  },
  {
    accessorKey: "artist",
    header: ({ column }) => (
      <SortableHeader column={column} label="Artist" />
    ),
    cell: ({ row }) => (
      <span className="text-[14px]">{row.original.artist || "-"}</span>
    ),
  },
  {
    accessorKey: "start_date",
    header: ({ column }) => (
      <SortableHeader column={column} label="Start Date" />
    ),
    cell: ({ row }) => {
      const raw = row.original.start_date
      if (!raw) return <span className="text-[#888] text-[14px]">-</span>
      const d = new Date(raw + "T00:00:00")
      const formatted = d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      })
      return <span className="text-[14px] whitespace-nowrap">{formatted}</span>
    },
  },
  {
    accessorKey: "status",
    header: ({ column }) => (
      <SortableHeader column={column} label="Status" />
    ),
    cell: ({ row }) => {
      const status = row.original.status || "active"
      const isActive = status.toLowerCase() === "active"
      return (
        <span
          className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${
            isActive
              ? "bg-[#eef2ff] text-[#0b62d6]"
              : "bg-[#f0fdf4] text-[#16a34a]"
          }`}
        >
          {status.charAt(0).toUpperCase() + status.slice(1)}
        </span>
      )
    },
  },
  {
    accessorKey: "budget.total",
    id: "budget",
    header: ({ column }) => (
      <SortableHeader column={column} label="Budget" />
    ),
    cell: ({ row }) => {
      const budget = row.original.budget
      const pct = Math.min(budget.pct, 100)
      return (
        <div className="min-w-[200px]">
          <div className="font-semibold text-[14px]">
            USD {formatCurrency(budget.total)}
          </div>
          <div className="w-full bg-[#e8e8ef] rounded-full h-2 mt-1.5 overflow-hidden">
            <div
              className="h-2 rounded-full bg-[#0b62d6] transition-[width] duration-300"
              style={{ width: `${pct}%` }}
            />
          </div>
          <div className="text-[#888] text-[13px] mt-1.5">
            Booked: {formatCurrency(budget.booked)} ({budget.pct}%) &middot;{" "}
            Paid: {formatCurrency(budget.paid)} &middot; Left:{" "}
            {formatCurrency(budget.left)}
          </div>
        </div>
      )
    },
    sortingFn: (rowA, rowB) =>
      rowA.original.budget.total - rowB.original.budget.total,
  },
  {
    accessorKey: "stats.total_views",
    id: "total_views",
    header: ({ column }) => (
      <SortableHeader column={column} label="Total Views" />
    ),
    cell: ({ row }) => (
      <span className="text-[14px]">
        {formatViews(row.original.stats.total_views)}
      </span>
    ),
    sortingFn: (rowA, rowB) =>
      rowA.original.stats.total_views - rowB.original.stats.total_views,
  },
  {
    accessorKey: "stats.live_posts",
    id: "live_posts",
    header: ({ column }) => (
      <SortableHeader column={column} label="Live Posts" />
    ),
    cell: ({ row }) => (
      <span className="text-[14px]">{row.original.stats.live_posts}</span>
    ),
    sortingFn: (rowA, rowB) =>
      rowA.original.stats.live_posts - rowB.original.stats.live_posts,
  },
  {
    accessorKey: "stats.cpm",
    id: "cpm",
    header: ({ column }) => <SortableHeader column={column} label="CPM" />,
    cell: ({ row }) => (
      <span className="text-[14px]">
        {formatCpm(row.original.stats.cpm)}
      </span>
    ),
    sortingFn: (rowA, rowB) =>
      (rowA.original.stats.cpm ?? 0) - (rowB.original.stats.cpm ?? 0),
  },
]
}

function SortableHeader({
  column,
  label,
}: {
  column: { getIsSorted: () => false | "asc" | "desc"; toggleSorting: (desc?: boolean) => void }
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

type SortOption = "start_date" | "a-z" | "cost" | "spend_pct" | "remaining"

const sortOptions: { value: SortOption; label: string }[] = [
  { value: "start_date", label: "Start Date" },
  { value: "a-z", label: "A–Z" },
  { value: "cost", label: "Overall Cost" },
  { value: "spend_pct", label: "Spend %" },
  { value: "remaining", label: "Remaining" },
]

function sortCampaigns(data: CampaignSummary[], by: SortOption): CampaignSummary[] {
  const sorted = [...data]
  switch (by) {
    case "start_date":
      return sorted.sort((a, b) => (b.start_date || "").localeCompare(a.start_date || ""))
    case "a-z":
      return sorted.sort((a, b) => a.title.localeCompare(b.title))
    case "cost":
      return sorted.sort((a, b) => b.budget.total - a.budget.total)
    case "spend_pct":
      return sorted.sort((a, b) => b.budget.pct - a.budget.pct)
    case "remaining":
      return sorted.sort((a, b) => a.budget.left - b.budget.left)
  }
}

interface CampaignsTableProps {
  data: CampaignSummary[]
}

export function CampaignsTable({ data }: CampaignsTableProps) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [sortBy, setSortBy] = useState<SortOption>("start_date")
  const [sorting, setSorting] = useState<SortingState>([])

  const handleToggleCompletion = useCallback(
    (slug: string, current: CampaignSummary["completion_status"]) => {
      const next = COMPLETION_CYCLE[current] || "none"
      api.editCampaign(slug, { completion_status: next }).then(() => {
        qc.invalidateQueries({ queryKey: ["campaigns"] })
      })
    },
    [qc]
  )

  const columns = useMemo(
    () => buildColumns(handleToggleCompletion),
    [handleToggleCompletion]
  )


  const sortedData = useMemo(() => sortCampaigns(data, sortBy), [data, sortBy])

  const table = useReactTable({
    data: sortedData,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[#e8e8ef]">
        <span className="text-[#888] text-xs font-semibold uppercase tracking-[0.3px]">Sort by</span>
        {sortOptions.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => { setSortBy(opt.value); setSorting([]) }}
            className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
              sortBy === opt.value
                ? "bg-[#0b62d6] text-white"
                : "bg-[#f4f4f8] text-[#555] hover:bg-[#e8e8ef]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
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
                  style={header.column.id === "completion" ? { width: 40, minWidth: 40, maxWidth: 40 } : undefined}
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
                No campaigns found. Create one above.
              </TableCell>
            </TableRow>
          ) : (
            table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                className="cursor-pointer hover:bg-[#fafaff] border-b border-[#f0f0f5]"
                onClick={() => navigate(`/campaign/${row.original.slug}`)}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell
                    key={cell.id}
                    className="px-4 py-1.5 text-[14px] border-b border-[#f0f0f5] align-middle"
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      </div>
    </div>
  )
}

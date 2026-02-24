import { useNavigate } from "react-router-dom"
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table"
import { useState } from "react"
import { ArrowUpDown, ArrowUp, ArrowDown } from "lucide-react"
import type { CampaignSummary } from "@/lib/types"
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

const columns: ColumnDef<CampaignSummary>[] = [
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
  {
    accessorKey: "start_date",
    id: "start_date",
    header: () => null,
    cell: () => null,
  },
]

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

interface CampaignsTableProps {
  data: CampaignSummary[]
}

export function CampaignsTable({ data }: CampaignsTableProps) {
  const navigate = useNavigate()
  const [sorting, setSorting] = useState<SortingState>([
    { id: "start_date", desc: true },
  ])

  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
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

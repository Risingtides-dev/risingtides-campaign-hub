import { useState, useMemo, useRef, useCallback } from "react"
import { Link } from "react-router-dom"
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table"
import { ArrowUpDown, ArrowUp, ArrowDown, Pencil, Trash2, Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import type { Creator } from "@/lib/types"

// ---- Types ----

interface CreatorsTableProps {
  creators: Creator[]
  onTogglePaid: (username: string) => void
  onEditCreator: (username: string, data: Record<string, unknown>) => void
  onRemoveCreator: (username: string) => void
  isToggling: boolean
  isEditing: boolean
  isRemoving: boolean
}

interface EditState {
  postsOwed: string
  totalRate: string
  paypalEmail: string
  notes: string
  niches: string[]
  nicheInput: string
}

// Niche color palette
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

// ---- Paid Toggle ----

function PaidToggle({
  creator,
  onToggle,
}: {
  creator: Creator
  onToggle: (username: string) => void
}) {
  const isPaid = creator.paid?.toLowerCase() === "yes"

  return (
    <label className="cursor-pointer flex items-center gap-1 whitespace-nowrap text-[12px] select-none">
      <input
        type="checkbox"
        checked={isPaid}
        onChange={() => onToggle(creator.username)}
        className="w-4 h-4 accent-green-500 cursor-pointer"
      />
      <span
        className="font-medium"
        style={{
          color: isPaid ? "#22c55e" : "#999",
          fontWeight: isPaid ? 600 : 400,
        }}
      >
        {isPaid ? "Paid" : "Unpaid"}
      </span>
    </label>
  )
}

// ---- Main Component ----

export function CreatorsTable({
  creators,
  onTogglePaid,
  onEditCreator,
  onRemoveCreator,
  isToggling,
  isEditing,
  isRemoving,
}: CreatorsTableProps) {
  const [editingUsername, setEditingUsername] = useState<string | null>(null)
  const [editState, setEditState] = useState<EditState>({
    postsOwed: "",
    totalRate: "",
    paypalEmail: "",
    notes: "",
    niches: [],
    nicheInput: "",
  })
  const editStateRef = useRef(editState)
  editStateRef.current = editState

  const updateField = useCallback(
    (field: keyof EditState, value: string) => {
      setEditState((s) => ({ ...s, [field]: value }))
    },
    []
  )
  const [removeConfirm, setRemoveConfirm] = useState<string | null>(null)
  const [sorting, setSorting] = useState<SortingState>([])

  function startEdit(creator: Creator) {
    setEditingUsername(creator.username)
    setEditState({
      postsOwed: creator.posts_owed.toString(),
      totalRate: creator.total_rate.toFixed(2),
      paypalEmail: creator.paypal_email || "",
      notes: creator.notes || "",
      niches: creator.niches || [],
      nicheInput: "",
    })
  }

  function cancelEdit() {
    setEditingUsername(null)
  }

  function saveEdit(username: string) {
    const current = editStateRef.current
    onEditCreator(username, {
      posts_owed: parseInt(current.postsOwed, 10),
      total_rate: parseFloat(current.totalRate),
      paypal_email: current.paypalEmail,
      notes: current.notes,
      niches: current.niches,
    })
    setEditingUsername(null)
  }

  function confirmRemove(username: string) {
    onRemoveCreator(username)
    setRemoveConfirm(null)
  }

  // Filter to active creators (status !== "removed")
  const activeCreators = useMemo(
    () => creators.filter((c) => c.status !== "removed"),
    [creators]
  )

  const columns: ColumnDef<Creator>[] = useMemo(
    () => [
      {
        accessorKey: "username",
        header: ({ column }) => (
          <SortableHeader column={column} label="Creator" />
        ),
        cell: ({ row }) => {
          const c = row.original
          if (editingUsername === c.username) {
            return (
              <span className="font-semibold text-[#0b62d6]">
                @{c.username}
              </span>
            )
          }
          return (
            <div className="flex items-center gap-2">
              <Link
                to={`/creators/${c.username}`}
                className="font-semibold text-[#0b62d6] hover:underline"
              >
                @{c.username}
              </Link>
              <a
                href={`https://www.tiktok.com/@${c.username}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#999] hover:text-[#333] transition-colors"
                title="View on TikTok"
              >
                <svg
                  className="size-3.5"
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1v-3.5a6.37 6.37 0 00-.79-.05A6.34 6.34 0 003.15 15.2a6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.34-6.34V8.73a8.19 8.19 0 004.76 1.52V6.8a4.84 4.84 0 01-1-.11z" />
                </svg>
              </a>
            </div>
          )
        },
      },
      {
        id: "niches",
        header: "Niches",
        cell: ({ row }) => {
          const c = row.original
          if (editingUsername === c.username) {
            return (
              <div className="flex flex-wrap gap-1 items-center max-w-[180px]">
                {editStateRef.current.niches.map((n) => (
                  <span key={n} className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[10px] font-medium ${getNicheColor(n)}`}>
                    {n}
                    <button type="button" onClick={() => setEditState((s) => ({ ...s, niches: s.niches.filter((x) => x !== n) }))}>
                      <X className="size-2.5" />
                    </button>
                  </span>
                ))}
                <Input
                  value={editStateRef.current.nicheInput}
                  onChange={(e) => setEditState((s) => ({ ...s, nicheInput: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault()
                      const val = editStateRef.current.nicheInput.trim().toLowerCase()
                      if (val && !editStateRef.current.niches.includes(val)) {
                        setEditState((s) => ({ ...s, niches: [...s.niches, val], nicheInput: "" }))
                      }
                    }
                  }}
                  placeholder="+ niche"
                  className="w-[70px] h-6 text-[10px] px-1"
                />
              </div>
            )
          }
          const niches = c.niches || []
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
        accessorKey: "posts_done",
        id: "posts",
        header: ({ column }) => (
          <SortableHeader column={column} label="Posts" />
        ),
        cell: ({ row }) => {
          const c = row.original
          if (editingUsername === c.username) {
            return (
              <div className="flex items-center gap-1">
                <span className="font-semibold">{c.posts_done}/</span>
                <Input
                  type="number"
                  min="0"
                  defaultValue={editStateRef.current.postsOwed}
                  onChange={(e) => updateField("postsOwed", e.target.value)}
                  className="w-[65px] h-8 text-sm"
                />
              </div>
            )
          }
          return (
            <span className="font-semibold">
              {c.posts_done} / {c.posts_owed}
            </span>
          )
        },
        sortingFn: (rowA, rowB) =>
          rowA.original.posts_done - rowB.original.posts_done,
      },
      {
        accessorKey: "total_rate",
        id: "price",
        header: ({ column }) => (
          <SortableHeader column={column} label="Price" />
        ),
        cell: ({ row }) => {
          const c = row.original
          if (editingUsername === c.username) {
            return (
              <Input
                type="number"
                step="0.01"
                min="0"
                defaultValue={editStateRef.current.totalRate}
                onChange={(e) => updateField("totalRate", e.target.value)}
                className="w-[90px] h-8 text-sm"
              />
            )
          }
          return (
            <span>
              ${c.total_rate.toLocaleString("en-US", {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
          )
        },
        sortingFn: (rowA, rowB) =>
          rowA.original.total_rate - rowB.original.total_rate,
      },
      {
        accessorKey: "paypal_email",
        id: "paypal",
        header: "PayPal",
        cell: ({ row }) => {
          const c = row.original
          if (editingUsername === c.username) {
            return (
              <div className="flex items-center gap-2">
                <Input
                  type="email"
                  defaultValue={editStateRef.current.paypalEmail}
                  onChange={(e) => updateField("paypalEmail", e.target.value)}
                  placeholder="paypal"
                  className="w-[180px] h-8 text-sm"
                />
                <PaidToggle creator={c} onToggle={onTogglePaid} />
              </div>
            )
          }
          return (
            <div className="flex items-center gap-2">
              <span className="text-[13px]">{c.paypal_email || "\u2014"}</span>
              <PaidToggle creator={c} onToggle={onTogglePaid} />
            </div>
          )
        },
      },
      {
        accessorKey: "notes",
        header: "Notes",
        cell: ({ row }) => {
          const c = row.original
          if (editingUsername === c.username) {
            return (
              <Input
                defaultValue={editStateRef.current.notes}
                onChange={(e) => updateField("notes", e.target.value)}
                placeholder="add note..."
                className="w-[150px] h-8 text-sm"
              />
            )
          }
          return (
            <span className="text-[12px] text-[#666]">{c.notes || ""}</span>
          )
        },
      },
      {
        id: "actions",
        header: "Actions",
        cell: ({ row }) => {
          const c = row.original
          if (editingUsername === c.username) {
            return (
              <div className="flex items-center gap-1.5">
                <Button
                  size="xs"
                  onClick={() => saveEdit(c.username)}
                  disabled={isEditing}
                  className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
                >
                  {isEditing ? (
                    <Loader2 className="size-3 animate-spin" />
                  ) : null}
                  Save
                </Button>
                <Button size="xs" variant="outline" onClick={cancelEdit}>
                  Cancel
                </Button>
              </div>
            )
          }
          return (
            <div className="flex items-center gap-1.5">
              <Button
                size="xs"
                variant="outline"
                onClick={() => startEdit(c)}
              >
                <Pencil className="size-3" />
                Edit
              </Button>
              <Button
                size="xs"
                variant="destructive"
                onClick={() => setRemoveConfirm(c.username)}
                disabled={isRemoving}
              >
                <Trash2 className="size-3" />
                Remove
              </Button>
            </div>
          )
        },
      },
    ],
    [editingUsername, isEditing, isRemoving, isToggling, onTogglePaid, updateField]
  )

  const table = useReactTable({
    data: activeCreators,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  })

  return (
    <>
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
                  No creators yet. Add one above.
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  className="hover:bg-[#fafaff] border-b border-[#f0f0f5]"
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

      {/* Remove Confirmation Dialog */}
      <Dialog
        open={removeConfirm !== null}
        onOpenChange={(open) => {
          if (!open) setRemoveConfirm(null)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Remove Creator</DialogTitle>
            <DialogDescription>
              Are you sure you want to remove @{removeConfirm} from this
              campaign? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRemoveConfirm(null)}
            >
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => removeConfirm && confirmRemove(removeConfirm)}
              disabled={isRemoving}
            >
              {isRemoving ? (
                <Loader2 className="size-3.5 animate-spin" />
              ) : (
                <Trash2 className="size-3.5" />
              )}
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

import { useState, useMemo } from "react"
import { Link } from "react-router-dom"
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  type SortingState,
  useReactTable,
} from "@tanstack/react-table"
import { ArrowUpDown, ArrowUp, ArrowDown, Search, X, Plus, Pencil, Trash2, Send, Music } from "lucide-react"
import { useNetwork, useAddNetworkCreator, useEditNetworkCreator, useRemoveNetworkCreator, useCampaigns } from "@/lib/queries"
import type { NetworkCreator } from "@/lib/types"
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
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"

function formatCurrency(value: number): string {
  return `$${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

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

function TikTokIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg">
      <path d="M19.59 6.69a4.83 4.83 0 01-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 01-2.88 2.5 2.89 2.89 0 01-2.89-2.89 2.89 2.89 0 012.89-2.89c.28 0 .54.04.79.1v-3.5a6.37 6.37 0 00-.79-.05A6.34 6.34 0 003.15 15.2a6.34 6.34 0 006.34 6.34 6.34 6.34 0 006.34-6.34V8.73a8.19 8.19 0 004.76 1.52V6.8a4.84 4.84 0 01-1-.11z" />
    </svg>
  )
}

// Niche color palette for consistent tag colors
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

interface CreatorFormData {
  username: string
  default_rate: string
  default_posts: string
  paypal_email: string
  manychat_subscriber_id: string
  platform: string
  niches: string[]
  notes: string
}

const emptyForm: CreatorFormData = {
  username: "",
  default_rate: "",
  default_posts: "1",
  paypal_email: "",
  manychat_subscriber_id: "",
  platform: "tiktok",
  niches: [],
  notes: "",
}

export default function NetworkCreators() {
  const { data: creators, isLoading, isError, error } = useNetwork()
  const { data: campaigns } = useCampaigns()
  const addCreator = useAddNetworkCreator()
  const editCreator = useEditNetworkCreator()
  const removeCreator = useRemoveNetworkCreator()

  const [search, setSearch] = useState("")
  const [sorting, setSorting] = useState<SortingState>([{ id: "username", desc: false }])
  const [showForm, setShowForm] = useState(false)
  const [editingCreator, setEditingCreator] = useState<NetworkCreator | null>(null)
  const [form, setForm] = useState<CreatorFormData>(emptyForm)
  const [nicheInput, setNicheInput] = useState("")
  const [selectedNiche, setSelectedNiche] = useState<string | null>(null)

  // Collect all unique niches across creators
  const allNiches = useMemo(() => {
    if (!creators) return []
    const set = new Set<string>()
    creators.forEach((c) => (c.niches || []).forEach((n) => set.add(n)))
    return Array.from(set).sort()
  }, [creators])

  // Filter creators by search + niche
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

  // Active campaigns only
  const activeCampaigns = useMemo(() => {
    if (!campaigns) return []
    return campaigns.filter((c) => c.status === "active")
  }, [campaigns])

  const handleAddNiche = (value: string) => {
    const niche = value.trim().toLowerCase()
    if (niche && !form.niches.includes(niche)) {
      setForm({ ...form, niches: [...form.niches, niche] })
    }
    setNicheInput("")
  }

  const handleRemoveNiche = (niche: string) => {
    setForm({ ...form, niches: form.niches.filter((n) => n !== niche) })
  }

  const handleSubmit = async () => {
    const data = {
      username: form.username.trim().replace(/^@/, ""),
      default_rate: parseFloat(form.default_rate) || 0,
      default_posts: parseInt(form.default_posts) || 1,
      paypal_email: form.paypal_email.trim(),
      manychat_subscriber_id: form.manychat_subscriber_id.trim(),
      platform: form.platform,
      niches: form.niches,
      notes: form.notes.trim(),
    }

    if (!data.username) return

    if (editingCreator) {
      await editCreator.mutateAsync({ username: editingCreator.username, data })
    } else {
      await addCreator.mutateAsync(data)
    }

    setForm(emptyForm)
    setNicheInput("")
    setShowForm(false)
    setEditingCreator(null)
  }

  const handleEdit = (creator: NetworkCreator) => {
    setEditingCreator(creator)
    setForm({
      username: creator.username,
      default_rate: creator.default_rate.toString(),
      default_posts: creator.default_posts.toString(),
      paypal_email: creator.paypal_email,
      manychat_subscriber_id: creator.manychat_subscriber_id,
      platform: creator.platform,
      niches: creator.niches || [],
      notes: creator.notes,
    })
    setNicheInput("")
    setShowForm(true)
  }

  const handleRemove = async (username: string) => {
    if (confirm(`Remove @${username} from network?`)) {
      await removeCreator.mutateAsync(username)
    }
  }

  const columns: ColumnDef<NetworkCreator>[] = useMemo(
    () => [
      {
        accessorKey: "username",
        header: ({ column }) => <SortableHeader column={column} label="Creator" />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <span className="font-semibold text-[#1a1a2e]">@{row.original.username}</span>
            <a
              href={`https://www.tiktok.com/@${row.original.username}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[#999] hover:text-[#333] transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              <TikTokIcon className="size-3.5" />
            </a>
          </div>
        ),
      },
      {
        id: "niches",
        header: "Niches",
        cell: ({ row }) => {
          const niches = row.original.niches || []
          if (niches.length === 0) return <span className="text-[#ccc] text-xs">—</span>
          return (
            <div className="flex flex-wrap gap-1">
              {niches.map((n) => (
                <span key={n} className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${getNicheColor(n)}`}>
                  {n}
                </span>
              ))}
            </div>
          )
        },
      },
      {
        accessorKey: "default_rate",
        header: ({ column }) => <SortableHeader column={column} label="Rate" />,
        cell: ({ row }) => <span className="text-[14px]">{formatCurrency(row.original.default_rate)}</span>,
      },
      {
        accessorKey: "default_posts",
        header: ({ column }) => <SortableHeader column={column} label="Posts" />,
        cell: ({ row }) => <span className="text-[14px] font-semibold">{row.original.default_posts}</span>,
      },
      {
        accessorKey: "manychat_subscriber_id",
        header: "ManyChat",
        cell: ({ row }) =>
          row.original.manychat_subscriber_id ? (
            <Badge variant="outline" className="text-xs font-mono bg-green-50 text-green-700 border-green-200">
              Linked
            </Badge>
          ) : (
            <span className="text-[#ccc] text-xs">Not linked</span>
          ),
      },
      {
        accessorKey: "paypal_email",
        header: "PayPal",
        cell: ({ row }) =>
          row.original.paypal_email ? (
            <span className="text-[13px] text-[#555]">{row.original.paypal_email}</span>
          ) : (
            <span className="text-[#ccc] text-xs">—</span>
          ),
      },
      {
        id: "actions",
        header: "",
        cell: ({ row }) => (
          <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
            <Button variant="ghost" size="sm" onClick={() => handleEdit(row.original)}>
              <Pencil className="size-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="text-red-500 hover:text-red-700"
              onClick={() => handleRemove(row.original.username)}
            >
              <Trash2 className="size-3.5" />
            </Button>
          </div>
        ),
      },
    ],
    []
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
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-[22px] font-semibold">Outreach Hub</h1>
        <Button onClick={() => { setForm(emptyForm); setNicheInput(""); setEditingCreator(null); setShowForm(true) }}>
          <Plus className="size-4 mr-1" />
          Add Creator
        </Button>
      </div>

      {/* Active Campaigns Section */}
      <div className="mb-6">
        <h2 className="text-[15px] font-semibold text-[#555] mb-3">Active Campaigns</h2>
        {!activeCampaigns.length ? (
          <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-6 text-center text-[#888] text-sm">
            No active campaigns
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {activeCampaigns.map((campaign) => (
              <div
                key={campaign.slug}
                className="bg-white border border-[#e8e8ef] rounded-[10px] p-4 hover:border-[#c8c8d8] transition-colors"
              >
                <div className="flex items-start justify-between mb-2">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-[14px] font-semibold text-[#1a1a2e] truncate">{campaign.title}</h3>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <Music className="size-3 text-[#888]" />
                      <span className="text-[12px] text-[#888]">{campaign.artist} — {campaign.song}</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-[12px] text-[#666] mb-3">
                  <span>Budget: {formatCurrency(campaign.budget.left)} left</span>
                  <span className="text-[#ccc]">·</span>
                  <span>{campaign.creator_count} creator{campaign.creator_count !== 1 ? "s" : ""}</span>
                </div>
                <Link to={`/campaign/${campaign.slug}/outreach`}>
                  <Button variant="outline" size="sm" className="w-full">
                    <Send className="size-3.5 mr-1.5" />
                    Build Campaign
                  </Button>
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Creator Network Section */}
      <h2 className="text-[15px] font-semibold text-[#555] mb-3">Creator Network</h2>

      {/* Search + Niche filter */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-5 py-3.5 mb-4">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 min-w-[200px] max-w-[300px]">
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
            <Button variant="outline" size="sm" onClick={() => setSearch("")}>
              <X className="size-3" /> Clear
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

      {isLoading && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
          <p className="text-[#888] text-sm">Loading network...</p>
        </div>
      )}

      {isError && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
          <p className="text-red-600 text-sm">{error?.message || "Failed to load network"}</p>
        </div>
      )}

      {!isLoading && !isError && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] overflow-hidden">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                {table.getHeaderGroups().map((headerGroup) => (
                  <TableRow key={headerGroup.id} className="border-b-2 border-[#e8e8ef] hover:bg-transparent">
                    {headerGroup.headers.map((header) => (
                      <TableHead
                        key={header.id}
                        className="text-[#888] text-xs font-semibold uppercase tracking-[0.3px] px-4 py-3 border-b-2 border-[#e8e8ef]"
                      >
                        {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                      </TableHead>
                    ))}
                  </TableRow>
                ))}
              </TableHeader>
              <TableBody>
                {table.getRowModel().rows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={columns.length} className="text-center text-[#888] py-10 text-sm">
                      {creators?.length ? "No creators match your filters." : 'No creators in network. Click "Add Creator" to get started.'}
                    </TableCell>
                  </TableRow>
                ) : (
                  table.getRowModel().rows.map((row) => (
                    <TableRow key={row.id} className="hover:bg-[#fafaff] border-b border-[#f0f0f5]">
                      {row.getVisibleCells().map((cell) => (
                        <TableCell key={cell.id} className="px-4 py-2 text-[14px] border-b border-[#f0f0f5] align-middle">
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
      )}

      {/* Add/Edit Dialog */}
      <Dialog open={showForm} onOpenChange={(open) => { if (!open) { setShowForm(false); setEditingCreator(null) } }}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>{editingCreator ? `Edit @${editingCreator.username}` : "Add Creator to Network"}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 py-2">
            {!editingCreator && (
              <div>
                <label className="text-sm font-medium text-[#555] mb-1 block">Username</label>
                <Input
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  placeholder="@creator_handle"
                />
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-sm font-medium text-[#555] mb-1 block">Default Rate ($)</label>
                <Input
                  type="number"
                  value={form.default_rate}
                  onChange={(e) => setForm({ ...form, default_rate: e.target.value })}
                  placeholder="100"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-[#555] mb-1 block">Default Posts</label>
                <Input
                  type="number"
                  value={form.default_posts}
                  onChange={(e) => setForm({ ...form, default_posts: e.target.value })}
                  placeholder="1"
                />
              </div>
            </div>
            {/* Niche tags input */}
            <div>
              <label className="text-sm font-medium text-[#555] mb-1 block">Niches</label>
              <div className="flex flex-wrap gap-1.5 mb-2">
                {form.niches.map((niche) => (
                  <span
                    key={niche}
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium ${getNicheColor(niche)}`}
                  >
                    {niche}
                    <button type="button" onClick={() => handleRemoveNiche(niche)} className="hover:opacity-70">
                      <X className="size-3" />
                    </button>
                  </span>
                ))}
              </div>
              <Input
                value={nicheInput}
                onChange={(e) => setNicheInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    handleAddNiche(nicheInput)
                  }
                }}
                placeholder="Type a niche and press Enter (e.g. indie, comedy)"
              />
              {allNiches.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {allNiches.filter((n) => !form.niches.includes(n)).map((niche) => (
                    <button
                      key={niche}
                      type="button"
                      onClick={() => handleAddNiche(niche)}
                      className="text-[10px] px-1.5 py-0.5 rounded bg-[#f0f0f5] text-[#666] hover:bg-[#e4e4ed] transition-colors"
                    >
                      + {niche}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div>
              <label className="text-sm font-medium text-[#555] mb-1 block">ManyChat Subscriber ID</label>
              <Input
                value={form.manychat_subscriber_id}
                onChange={(e) => setForm({ ...form, manychat_subscriber_id: e.target.value })}
                placeholder="Find in ManyChat > Audience > Contact"
              />
              <p className="text-xs text-[#999] mt-1">Required for automated DM outreach</p>
            </div>
            <div>
              <label className="text-sm font-medium text-[#555] mb-1 block">PayPal Email</label>
              <Input
                type="email"
                value={form.paypal_email}
                onChange={(e) => setForm({ ...form, paypal_email: e.target.value })}
                placeholder="creator@email.com"
              />
            </div>
            <div>
              <label className="text-sm font-medium text-[#555] mb-1 block">Notes</label>
              <Input
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                placeholder="Optional notes..."
              />
            </div>
            <Button onClick={handleSubmit} disabled={addCreator.isPending || editCreator.isPending}>
              {editingCreator ? "Save Changes" : "Add to Network"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

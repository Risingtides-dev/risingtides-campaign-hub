import { useState, useMemo } from "react"
import { useCampaigns } from "@/lib/queries"
import { CampaignsTable } from "@/components/campaigns/CampaignsTable"
import { CreateCampaignForm } from "@/components/campaigns/CreateCampaignForm"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Plus, Search, X } from "lucide-react"

type Tab = "active" | "finished"

export default function CampaignsList() {
  const { data: campaigns, isLoading, isError, error } = useCampaigns()
  const [showCreate, setShowCreate] = useState(false)
  const [search, setSearch] = useState("")
  const [tab, setTab] = useState<Tab>("active")

  const { active, finished } = useMemo(() => {
    if (!campaigns) return { active: [], finished: [] }
    return {
      active: campaigns.filter((c) => c.completion_status !== "completed"),
      finished: campaigns.filter((c) => c.completion_status === "completed"),
    }
  }, [campaigns])

  const tabData = tab === "active" ? active : finished

  const filtered = useMemo(() => {
    if (!search.trim()) return tabData
    const q = search.toLowerCase()
    return tabData.filter(
      (c) =>
        c.title.toLowerCase().includes(q) ||
        c.artist.toLowerCase().includes(q) ||
        c.song.toLowerCase().includes(q) ||
        c.slug.toLowerCase().includes(q)
    )
  }, [tabData, search])

  return (
    <div>
      {/* Top bar */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-[22px] font-semibold">Promotions</h1>
        <Button
          onClick={() => setShowCreate((prev) => !prev)}
          className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
        >
          <Plus className="size-4" />
          New Campaign
        </Button>
      </div>

      {/* Create campaign form */}
      <CreateCampaignForm open={showCreate} />

      {/* Tabs + Search bar */}
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] px-5 py-3.5 mb-4">
        <div className="flex items-center gap-3">
          {/* Tabs */}
          <div className="flex items-center gap-1 mr-3">
            <button
              type="button"
              onClick={() => setTab("active")}
              className={`px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors ${
                tab === "active"
                  ? "bg-[#0b62d6] text-white"
                  : "bg-[#f4f4f8] text-[#555] hover:bg-[#e8e8ef]"
              }`}
            >
              Active{active.length > 0 && ` (${active.length})`}
            </button>
            <button
              type="button"
              onClick={() => setTab("finished")}
              className={`px-3 py-1.5 rounded-md text-[13px] font-medium transition-colors ${
                tab === "finished"
                  ? "bg-[#0b62d6] text-white"
                  : "bg-[#f4f4f8] text-[#555] hover:bg-[#e8e8ef]"
              }`}
            >
              Finished{finished.length > 0 && ` (${finished.length})`}
            </button>
          </div>

          {/* Search */}
          <div className="relative flex-1 max-w-[300px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#888]" />
            <Input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search campaigns..."
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
          <span className="ml-auto text-[#888] text-[13px]">
            {filtered.length} campaign{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Loading / error states */}
      {isLoading && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
          <p className="text-[#888] text-sm">Loading campaigns...</p>
        </div>
      )}

      {isError && (
        <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
          <p className="text-red-600 text-sm">
            {error?.message || "Failed to load campaigns"}
          </p>
        </div>
      )}

      {/* Campaign table */}
      {!isLoading && !isError && <CampaignsTable data={filtered} />}
    </div>
  )
}

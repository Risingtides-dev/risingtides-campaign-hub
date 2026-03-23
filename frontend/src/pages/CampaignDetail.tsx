import { useState } from "react"
import { useParams, Link } from "react-router-dom"
import {
  useCampaign,
  useEditCampaign,
  useRefreshStats,
  useAddCreator,
  useEditCreator,
  useTogglePaid,
  useRemoveCreator,
  useCobrandStats,
  useCreateTracker,
  useSetCobrandLinks,
} from "@/lib/queries"
import { CampaignHeader } from "@/components/campaigns/CampaignHeader"
import { StatCards } from "@/components/campaigns/StatCards"
import { CobrandStatsCard, CobrandLinkInput, CobrandUploadSection } from "@/components/campaigns/CobrandSection"
import { AddCreatorForm } from "@/components/campaigns/AddCreatorForm"
import { CreatorsTable } from "@/components/campaigns/CreatorsTable"
import { ChevronRight, Loader2 } from "lucide-react"

export default function CampaignDetail() {
  const { slug } = useParams<{ slug: string }>()
  const [cobrandVisible, setCobrandVisible] = useState(false)

  // Data fetching
  const { data: campaign, isLoading, isError, error } = useCampaign(slug!)
  const hasCobrandShare = !!campaign?.cobrand_share_url
  const cobrandStats = useCobrandStats(slug!, hasCobrandShare)

  // Mutations
  const editCampaign = useEditCampaign(slug!)
  const refreshStats = useRefreshStats(slug!)
  const addCreator = useAddCreator(slug!)
  const editCreator = useEditCreator(slug!)
  const togglePaid = useTogglePaid(slug!)
  const removeCreator = useRemoveCreator(slug!)
  const createTracker = useCreateTracker(slug!)
  const setCobrandLinks = useSetCobrandLinks(slug!)

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="size-6 animate-spin text-[#888]" />
        <span className="ml-2 text-[#888] text-sm">Loading campaign...</span>
      </div>
    )
  }

  // Error state
  if (isError || !campaign) {
    return (
      <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-10 text-center">
        <p className="text-red-600 text-sm">
          {error?.message || "Failed to load campaign"}
        </p>
        <Link to="/" className="text-[#0b62d6] text-sm mt-2 inline-block hover:underline">
          Back to campaigns
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-[13px] text-[#888]">
        <Link to="/" className="hover:text-[#555] transition-colors">
          Promotions
        </Link>
        <ChevronRight className="size-3.5" />
        <span className="text-[#333] font-medium">{campaign.title}</span>
      </div>

      {/* Campaign Header */}
      <CampaignHeader
        campaign={campaign}
        onEdit={(data) => editCampaign.mutate(data)}
        onRefresh={() => refreshStats.mutate()}
        isEditing={editCampaign.isPending}
        isRefreshing={refreshStats.isPending}
        onToggleCobrand={() => {
          setCobrandVisible((v) => !v)
        }}
        onCreateTracker={() => createTracker.mutate()}
        isCreatingTracker={createTracker.isPending}
      />

      {/* Refresh stats feedback */}
      {refreshStats.isSuccess && (
        <div className="bg-green-50 border border-green-200 rounded-[10px] px-4 py-2 text-green-700 text-sm">
          Stats refresh triggered. Data will update shortly.
        </div>
      )}
      {refreshStats.isError && (
        <div className="bg-red-50 border border-red-200 rounded-[10px] px-4 py-2 text-red-600 text-sm">
          {refreshStats.error?.message || "Failed to refresh stats"}
        </div>
      )}

      {/* Tracker feedback */}
      {createTracker.isSuccess && (
        <div className="bg-purple-50 border border-purple-200 rounded-[10px] px-4 py-2 text-purple-700 text-sm">
          Tracker created successfully.{" "}
          {createTracker.data?.tracker_url && (
            <a
              href={createTracker.data.tracker_url}
              target="_blank"
              rel="noopener noreferrer"
              className="underline font-medium"
            >
              Open Tracker
            </a>
          )}
        </div>
      )}
      {createTracker.isError && (
        <div className="bg-red-50 border border-red-200 rounded-[10px] px-4 py-2 text-red-600 text-sm">
          {createTracker.error?.message || "Failed to create tracker"}
        </div>
      )}

      {/* Stat Cards */}
      <StatCards budget={campaign.budget} stats={campaign.stats} />

      {/* Cobrand Tracking Link + Stats */}
      <CobrandLinkInput
        currentShareUrl={campaign.cobrand_share_url}
        onSave={(data) => setCobrandLinks.mutate(data)}
        isPending={setCobrandLinks.isPending}
      />
      {hasCobrandShare && (
        <CobrandStatsCard
          stats={cobrandStats.data}
          isLoading={cobrandStats.isLoading}
          isError={cobrandStats.isError}
          error={cobrandStats.error as Error | null}
        />
      )}

      {/* Add Creator Form */}
      <AddCreatorForm
        onAdd={(data) => addCreator.mutate(data)}
        isPending={addCreator.isPending}
      />

      {/* Add creator feedback */}
      {addCreator.isError && (
        <div className="bg-red-50 border border-red-200 rounded-[10px] px-4 py-2 text-red-600 text-sm">
          {addCreator.error?.message || "Failed to add creator"}
        </div>
      )}

      {/* Creators Table */}
      <CreatorsTable
        creators={campaign.creators}
        onTogglePaid={(username) => togglePaid.mutate(username)}
        onEditCreator={(username, data) =>
          editCreator.mutate({ username, data })
        }
        onRemoveCreator={(username) => removeCreator.mutate(username)}
        isToggling={togglePaid.isPending}
        isEditing={editCreator.isPending}
        isRemoving={removeCreator.isPending}
      />

      {/* Cobrand Upload Section (toggle via Cobrand button in header) */}
      {campaign.cobrand_link && (
        <CobrandUploadSection
          cobrandLink={campaign.cobrand_link}
          matchedVideos={campaign.matched_videos || []}
          visible={cobrandVisible}
        />
      )}
    </div>
  )
}

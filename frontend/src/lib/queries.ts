import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "./api"
import type { ScrapeStatus } from "./types"

// Query keys
export const keys = {
  campaigns: ["campaigns"] as const,
  campaign: (slug: string) => ["campaign", slug] as const,
  campaignLinks: (slug: string) => ["campaign", slug, "links"] as const,
  cobrandStats: (slug: string) => ["campaign", slug, "cobrand"] as const,
  search: (q: string) => ["search", q] as const,
  creators: ["creators"] as const,
  creatorProfile: (username: string) => ["creators", username] as const,
  internalCreators: ["internal", "creators"] as const,
  internalResults: ["internal", "results"] as const,
  internalScrapeStatus: ["internal", "scrape-status"] as const,
  internalCreator: (username: string) =>
    ["internal", "creator", username] as const,
  internalGroups: ["internal", "groups"] as const,
  internalGroup: (slug: string) => ["internal", "groups", slug] as const,
  internalGroupStats: (slug: string) => ["internal", "groups", slug, "stats"] as const,
  inbox: (status?: string) => ["inbox", status ?? "all"] as const,
  paypal: (username: string) => ["paypal", username] as const,
  network: ["network"] as const,
  outreach: (slug: string) => ["outreach", slug] as const,
  outreachStatus: (slug: string) => ["outreach", slug, "status"] as const,
  trackers: ["trackers"] as const,
  trackerGroups: ["tracker-groups"] as const,
  shareTokens: ["share-tokens"] as const,
}

// --- Campaigns ---

export function useCampaigns() {
  return useQuery({ queryKey: keys.campaigns, queryFn: api.getCampaigns })
}

export function useCampaign(slug: string) {
  return useQuery({
    queryKey: keys.campaign(slug),
    queryFn: () => api.getCampaign(slug),
    enabled: !!slug,
  })
}

export function useCampaignLinks(slug: string) {
  return useQuery({
    queryKey: keys.campaignLinks(slug),
    queryFn: () => api.getCampaignLinks(slug),
    enabled: !!slug,
  })
}

export function useSearch(q: string) {
  return useQuery({
    queryKey: keys.search(q),
    queryFn: () => api.searchCampaigns(q),
    enabled: q.length > 0,
  })
}

export function useCreateCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.createCampaign,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.campaigns }),
  })
}

export function useEditCampaign(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      api.editCampaign(slug, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.campaigns })
    },
  })
}

export function useRefreshStats(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.refreshStats(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.campaignLinks(slug) })
      qc.invalidateQueries({ queryKey: keys.campaigns })
    },
  })
}

// --- Creators ---

export function useAddCreator(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Parameters<typeof api.addCreator>[1]) =>
      api.addCreator(slug, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.campaigns })
    },
  })
}

export function useEditCreator(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      username,
      data,
    }: {
      username: string
      data: Record<string, unknown>
    }) => api.editCreator(slug, username, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.campaigns })
    },
  })
}

export function useTogglePaid(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.togglePaid(slug, username),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.campaigns })
    },
  })
}

export function useRemoveCreator(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.removeCreator(slug, username),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.campaigns })
    },
  })
}

export function usePaypal(username: string) {
  return useQuery({
    queryKey: keys.paypal(username),
    queryFn: () => api.getPaypal(username),
    enabled: !!username,
  })
}

// --- Creator Database ---

export function useCreators() {
  return useQuery({ queryKey: keys.creators, queryFn: api.getCreators })
}

export function useCreatorProfile(username: string) {
  return useQuery({
    queryKey: keys.creatorProfile(username),
    queryFn: () => api.getCreatorProfile(username),
    enabled: !!username,
  })
}

// --- TidesTracker ---

export function useCreateTracker(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => api.createTracker(slug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.trackers })
    },
  })
}

export function useTrackers() {
  return useQuery({ queryKey: keys.trackers, queryFn: api.listTrackers })
}

export function useTrackerGroups() {
  return useQuery({ queryKey: keys.trackerGroups, queryFn: api.listTrackerGroups })
}

export function useCreateStandaloneTracker() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.createStandaloneTracker,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.trackers })
      qc.invalidateQueries({ queryKey: keys.trackerGroups })
    },
  })
}

export function useSetTrackerGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ trackerId, groupId }: { trackerId: string; groupId: number | null }) =>
      api.setTrackerGroup(trackerId, groupId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.trackers })
      qc.invalidateQueries({ queryKey: keys.trackerGroups })
    },
  })
}

export function useSetTrackerName() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ trackerId, name }: { trackerId: string; name: string | null }) =>
      api.setTrackerName(trackerId, name),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.trackers })
    },
  })
}

export function useSetTrackerCampaign() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      trackerId,
      campaignSlug,
    }: {
      trackerId: string
      campaignSlug: string | null
    }) => api.setTrackerCampaign(trackerId, campaignSlug),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.trackers })
    },
  })
}

export function useCreateTrackerGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.createTrackerGroup,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.trackerGroups }),
  })
}

export function useDeleteTrackerGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.deleteTrackerGroup(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.trackerGroups })
      qc.invalidateQueries({ queryKey: keys.trackers })
    },
  })
}

// --- Cobrand ---

export function useCobrandStats(slug: string, enabled = true) {
  return useQuery({
    queryKey: keys.cobrandStats(slug),
    queryFn: () => api.getCobrandStats(slug),
    enabled: enabled && !!slug,
    staleTime: 5 * 60 * 1000, // Cache for 5 minutes
    retry: false, // Don't retry if Cobrand link not set
  })
}

export function useSetCobrandLinks(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { share_url?: string; upload_url?: string }) =>
      api.setCobrandLinks(slug, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.cobrandStats(slug) })
    },
  })
}

// --- Internal ---

export function useInternalCreators() {
  return useQuery({
    queryKey: keys.internalCreators,
    queryFn: api.getInternalCreators,
  })
}

export function useAddInternalCreators() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.addInternalCreators(username),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: keys.internalCreators }),
  })
}

export function useRemoveInternalCreator() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.removeInternalCreator(username),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: keys.internalCreators }),
  })
}

export function useTriggerInternalScrape() {
  return useMutation({
    mutationFn: (hours: number) => api.triggerInternalScrape(hours),
  })
}

export function useInternalScrapeStatus(enabled = false) {
  return useQuery({
    queryKey: keys.internalScrapeStatus,
    queryFn: api.getInternalScrapeStatus,
    enabled,
    refetchInterval: (query) => {
      const data = query.state.data
      // Keep polling while running OR while we haven't seen the done signal yet
      if (data?.running) return 2000
      if (enabled && !data?.done) return 2000
      return false
    },
  })
}

export function useInternalResults() {
  return useQuery({
    queryKey: keys.internalResults,
    queryFn: api.getInternalResults,
  })
}

export function useInternalCreator(username: string) {
  return useQuery({
    queryKey: keys.internalCreator(username),
    queryFn: () => api.getInternalCreator(username),
    enabled: !!username,
  })
}

export function useInternalGroups() {
  return useQuery({
    queryKey: keys.internalGroups,
    queryFn: api.getInternalGroups,
  })
}

export function useInternalGroup(slug: string) {
  return useQuery({
    queryKey: keys.internalGroup(slug),
    queryFn: () => api.getInternalGroup(slug),
    enabled: !!slug,
  })
}

export function useInternalGroupStats(slug: string, days = 30) {
  return useQuery({
    queryKey: keys.internalGroupStats(slug),
    queryFn: () => api.getInternalGroupStats(slug, days),
    enabled: !!slug,
  })
}

export function useTriggerGroupScrape() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params: {
      hours?: number
      group?: string
      username?: string
      start_date?: string
      end_date?: string
    }) => api.triggerInternalScrapeAdvanced(params),
    onMutate: () => {
      // Clear any stale "done" state from a previous scrape so the
      // status query starts polling again and ScrapeProgress doesn't
      // immediately fire its completion handler against old data.
      qc.setQueryData<ScrapeStatus>(keys.internalScrapeStatus, {
        running: true,
        done: false,
        progress: "Starting...",
        accounts_total: 0,
        accounts_completed: 0,
        accounts_failed: 0,
        videos_so_far: 0,
        current_accounts: [],
        log: [],
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.internalScrapeStatus })
    },
  })
}

// --- Inbox ---

export function useInbox(status?: string) {
  return useQuery({
    queryKey: keys.inbox(status),
    queryFn: () => api.getInbox(status),
  })
}

export function useApproveInbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string
      data: Parameters<typeof api.approveInbox>[1]
    }) => api.approveInbox(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["inbox"] })
      qc.invalidateQueries({ queryKey: ["campaigns"] })
      qc.invalidateQueries({ queryKey: ["campaign"] })
    },
  })
}

export function useDismissInbox() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => api.dismissInbox(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["inbox"] }),
  })
}

// --- Notion ---

export function useSyncNotion() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: api.syncNotion,
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.campaigns }),
  })
}

// --- Network ---

export function useNetwork() {
  return useQuery({ queryKey: keys.network, queryFn: api.getNetwork })
}

export function useAddNetworkCreator() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: Record<string, unknown>) => api.addNetworkCreator(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.network }),
  })
}

export function useEditNetworkCreator() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ username, data }: { username: string; data: Record<string, unknown> }) =>
      api.editNetworkCreator(username, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.network }),
  })
}

export function useRemoveNetworkCreator() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.removeNetworkCreator(username),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.network }),
  })
}

// --- Outreach ---

export function useOutreach(slug: string) {
  return useQuery({
    queryKey: keys.outreach(slug),
    queryFn: () => api.getOutreach(slug),
    enabled: !!slug,
  })
}

export function useAddToOutreach(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (creators: Array<{ username: string; rate: number; posts: number }>) =>
      api.addToOutreach(slug, creators),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.outreach(slug) }),
  })
}

export function useRemoveFromOutreach(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.removeFromOutreach(slug, username),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.outreach(slug) }),
  })
}

export function useSendOutreach(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { message_template: string; reference_post?: string }) =>
      api.sendOutreach(slug, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.outreach(slug) })
      qc.invalidateQueries({ queryKey: keys.outreachStatus(slug) })
    },
  })
}

export function useOutreachStatus(slug: string, enabled = false) {
  return useQuery({
    queryKey: keys.outreachStatus(slug),
    queryFn: () => api.getOutreachStatus(slug),
    enabled: enabled && !!slug,
    refetchInterval: enabled ? 10000 : false,
  })
}

export function useConfirmOutreach(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (username: string) => api.confirmOutreach(slug, username),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.outreach(slug) })
      qc.invalidateQueries({ queryKey: keys.outreachStatus(slug) })
      qc.invalidateQueries({ queryKey: keys.campaign(slug) })
      qc.invalidateQueries({ queryKey: keys.campaigns })
    },
  })
}

// --- Share Tokens ---

export function useCreateShareToken(slug: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: { label?: string; expires_days?: number }) =>
      api.createShareToken(slug, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.shareTokens }),
  })
}

export function useShareTokens() {
  return useQuery({
    queryKey: keys.shareTokens,
    queryFn: api.listShareTokens,
  })
}

export function useRevokeShareToken() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (token: string) => api.revokeShareToken(token),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.shareTokens }),
  })
}

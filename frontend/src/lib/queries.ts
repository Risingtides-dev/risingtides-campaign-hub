import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "./api"

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
  inbox: (status?: string) => ["inbox", status ?? "all"] as const,
  paypal: (username: string) => ["paypal", username] as const,
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

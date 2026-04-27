import type {
  CampaignSummary,
  CampaignDetail,
  MatchedVideo,
  CobrandStats,
  CreatorSummary,
  CreatorProfile,
  InternalCreator,
  InternalGroup,
  InternalGroupDetail,
  InternalGroupStats,
  InternalScrapeResults,
  InternalSongResult,
  ScrapeStatus,
  InboxItem,
  InboxCreator,
  ApiOk,
  SearchResult,
  BudgetResponse,
  NetworkCreator,
  OutreachResponse,
  OutreachStatusResponse,
  Tracker,
  TrackerGroup,
  ShareToken,
} from "./types"

const API_BASE = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:5055" : "")

class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = "ApiError"
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({ error: res.statusText }))
    throw new ApiError(body.error || res.statusText, res.status)
  }
  return res.json()
}

export const api = {
  // Campaigns
  getCampaigns: () => request<CampaignSummary[]>("/api/campaigns"),

  getCampaign: (slug: string) =>
    request<CampaignDetail>(`/api/campaign/${slug}`),

  createCampaign: (data: {
    title: string
    official_sound: string
    start_date: string
    budget: number
  }) =>
    request<ApiOk & { slug: string }>("/api/campaign/create", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  editCampaign: (slug: string, data: Record<string, unknown>) =>
    request<ApiOk>(`/api/campaign/${slug}/edit`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  refreshStats: (slug: string) =>
    request<ApiOk>(`/api/campaign/${slug}/refresh`, {
      method: "POST",
    }),

  getCampaignLinks: (slug: string) =>
    request<{
      videos: MatchedVideo[]
      scrape_log: Record<string, unknown>
    }>(`/api/campaign/${slug}/links`),

  searchCampaigns: (q: string) =>
    request<SearchResult>(`/api/search?q=${encodeURIComponent(q)}`),

  getBudget: (slug: string) =>
    request<BudgetResponse>(`/api/campaign/${slug}/budget`),

  // Creators
  addCreator: (
    slug: string,
    data: {
      username: string
      posts_owed: number
      total_rate: number
      paypal_email?: string
      platform?: string
    }
  ) =>
    request<ApiOk>(`/api/campaign/${slug}/creator/add`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  editCreator: (
    slug: string,
    username: string,
    data: Record<string, unknown>
  ) =>
    request<ApiOk>(`/api/campaign/${slug}/creator/${username}/edit`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  togglePaid: (slug: string, username: string) =>
    request<{ ok: boolean; paid: string; username: string }>(
      `/api/campaign/${slug}/creator/${username}/toggle-paid`,
      { method: "POST" }
    ),

  removeCreator: (slug: string, username: string) =>
    request<ApiOk>(
      `/api/campaign/${slug}/creator/${username}/remove`,
      { method: "POST" }
    ),

  getPaypal: (username: string) =>
    request<{ paypal: string }>(`/api/paypal/${username}`),

  // Creator Database
  getCreators: () => request<CreatorSummary[]>("/api/creators"),
  getCreatorProfile: (username: string) =>
    request<CreatorProfile>(`/api/creators/${username}`),

  // TidesTracker
  createTracker: (slug: string) =>
    request<ApiOk & { tracker_campaign_id: string; tracker_url: string }>(
      `/api/campaign/${slug}/create-tracker`,
      { method: "POST" }
    ),

  // Cobrand
  getCobrandStats: (slug: string) =>
    request<CobrandStats>(`/api/campaign/${slug}/cobrand`),

  setCobrandLinks: (
    slug: string,
    data: { share_url?: string; upload_url?: string }
  ) =>
    request<ApiOk>(`/api/campaign/${slug}/cobrand`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  // Internal
  getInternalCreators: () =>
    request<InternalCreator[]>("/api/internal/creators"),

  addInternalCreators: (username: string) =>
    request<ApiOk & { added: string[] }>("/api/internal/creators", {
      method: "POST",
      body: JSON.stringify({ username }),
    }),

  removeInternalCreator: (username: string) =>
    request<ApiOk>(`/api/internal/creators/${username}`, {
      method: "DELETE",
    }),

  triggerInternalScrape: (hours: number) =>
    request<ApiOk>("/api/internal/scrape", {
      method: "POST",
      body: JSON.stringify({ hours }),
    }),

  getInternalScrapeStatus: () =>
    request<ScrapeStatus>("/api/internal/scrape/status"),

  getInternalResults: () =>
    request<InternalScrapeResults>("/api/internal/results"),

  getInternalCreator: (username: string) =>
    request<{
      username: string
      total_videos: number
      total_videos_raw: number
      total_views: number
      total_likes: number
      songs: InternalSongResult[]
    }>(`/api/internal/creator/${username}`),

  getInternalGroups: () =>
    request<InternalGroup[]>("/api/internal/groups"),

  getInternalGroup: (slug: string) =>
    request<InternalGroupDetail>(`/api/internal/groups/${slug}`),

  getInternalGroupStats: (slug: string, days = 30) =>
    request<InternalGroupStats>(`/api/internal/groups/${slug}/stats?days=${days}`),

  triggerInternalScrapeAdvanced: (params: {
    hours?: number
    group?: string
    username?: string
    start_date?: string
    end_date?: string
  }) =>
    request<ApiOk & { creators_count: number }>("/api/internal/scrape", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Inbox
  getInbox: (status?: string) =>
    request<InboxItem[]>(
      `/api/inbox${status ? `?status=${status}` : ""}`
    ),

  addInboxItem: (data: Record<string, unknown>) =>
    request<ApiOk & { id: string }>("/api/inbox", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  approveInbox: (
    id: string,
    data: { campaign_slug: string; creators: InboxCreator[] }
  ) =>
    request<ApiOk & { added: string[] }>(`/api/inbox/${id}/approve`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  dismissInbox: (id: string) =>
    request<ApiOk>(`/api/inbox/${id}/dismiss`, {
      method: "POST",
    }),

  // Notion sync
  syncNotion: () =>
    request<
      ApiOk & {
        created: Array<{ slug: string; title: string }>
        skipped: Array<{ slug: string; reason: string }>
      }
    >("/api/webhooks/notion/sync", { method: "POST" }),

  // Network
  getNetwork: () => request<NetworkCreator[]>("/api/network"),

  addNetworkCreator: (data: Record<string, unknown>) =>
    request<ApiOk & { creator: NetworkCreator }>("/api/network", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  editNetworkCreator: (username: string, data: Record<string, unknown>) =>
    request<ApiOk & { creator: NetworkCreator }>(`/api/network/${username}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),

  removeNetworkCreator: (username: string) =>
    request<ApiOk>(`/api/network/${username}`, { method: "DELETE" }),

  // Outreach
  getOutreach: (slug: string) =>
    request<OutreachResponse>(`/api/campaign/${slug}/outreach`),

  addToOutreach: (slug: string, creators: Array<{ username: string; rate: number; posts: number }>) =>
    request<ApiOk & { added: number }>(`/api/campaign/${slug}/outreach/add`, {
      method: "POST",
      body: JSON.stringify(creators),
    }),

  removeFromOutreach: (slug: string, username: string) =>
    request<ApiOk>(`/api/campaign/${slug}/outreach/remove`, {
      method: "POST",
      body: JSON.stringify({ username }),
    }),

  sendOutreach: (slug: string, data: { message_template: string; reference_post?: string }) =>
    request<{ ok: boolean; sent: string[]; errors: Array<{ username: string; error: string }> }>(
      `/api/campaign/${slug}/outreach/send`,
      { method: "POST", body: JSON.stringify(data) }
    ),

  getOutreachStatus: (slug: string) =>
    request<OutreachStatusResponse>(`/api/campaign/${slug}/outreach/status`),

  confirmOutreach: (slug: string, username: string) =>
    request<ApiOk>(`/api/campaign/${slug}/outreach/confirm`, {
      method: "POST",
      body: JSON.stringify({ username }),
    }),

  // TidesTrackers — list comes live from TidesTracker; groups are local
  listTrackers: () => request<Tracker[]>("/api/trackers"),

  createStandaloneTracker: (data: {
    name?: string
    cobrand_share_url: string
    group_id?: number | null
  }) =>
    request<{
      ok: boolean
      tracker: {
        id: string
        name: string
        cobrand_share_url: string
        tracker_url: string
        group_id: number | null
      }
    }>("/api/trackers", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  setTrackerGroup: (trackerId: string, groupId: number | null) =>
    request<{ ok: boolean; id: string; group_id: number | null }>(
      `/api/trackers/${trackerId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ group_id: groupId }),
      }
    ),

  setTrackerName: (trackerId: string, name: string | null) =>
    request<{ ok: boolean; id: string; name: string | null }>(
      `/api/trackers/${trackerId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ name }),
      }
    ),

  setTrackerCampaign: (trackerId: string, campaignSlug: string | null) =>
    request<{ ok: boolean; id: string; campaign_slug: string | null }>(
      `/api/trackers/${trackerId}`,
      {
        method: "PATCH",
        body: JSON.stringify({ campaign_slug: campaignSlug }),
      }
    ),

  listTrackerGroups: () => request<TrackerGroup[]>("/api/tracker-groups"),

  createTrackerGroup: (data: { title: string; slug?: string }) =>
    request<TrackerGroup>("/api/tracker-groups", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteTrackerGroup: (id: number) =>
    request<ApiOk>(`/api/tracker-groups/${id}`, { method: "DELETE" }),

  // Share Tokens
  createShareToken: (slug: string, data: { label?: string; expires_days?: number }) =>
    request<{ ok: boolean; token: ShareToken; url: string }>(`/api/campaign/${slug}/share-token`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  listShareTokens: () =>
    request<ShareToken[]>("/api/share-tokens"),

  revokeShareToken: (token: string) =>
    request<ApiOk>(`/api/share-token/${token}`, { method: "DELETE" }),
}

export { ApiError }

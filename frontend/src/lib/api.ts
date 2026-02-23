import type {
  CampaignSummary,
  CampaignDetail,
  MatchedVideo,
  CobrandStats,
  InternalCreator,
  InternalScrapeResults,
  InternalSongResult,
  ScrapeStatus,
  InboxItem,
  InboxCreator,
  ApiOk,
  SearchResult,
  BudgetResponse,
} from "./types"

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:5055"

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
}

export { ApiError }

import { useState } from "react"
import { Link, Outlet, useLocation } from "react-router-dom"
import { Menu, AlertTriangle } from "lucide-react"
import { Sidebar } from "./Sidebar"
import { Toaster } from "@/components/ui/sonner"
import {
  getShellMeta,
  type ShellRouteMeta,
  isCampaignDetailPath,
  isCampaignSubpath,
} from "@/lib/navigation"
import { useCampaigns, useInbox, useScrapeTaskHealth, useScrapeTaskQueue } from "@/lib/queries"

export function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const meta = getShellMeta(location.pathname)

  const campaignsQuery = useCampaigns()
  const inboxPendingQ = useInbox("pending")
  const scrapeHealthQ = useScrapeTaskHealth()
  const scrapeQueueQ = useScrapeTaskQueue()

  const staleSync = Boolean(scrapeHealthQ.data?.last_run?.status && scrapeHealthQ.data.last_run.status !== "success")
  const failedScrapes = Boolean(scrapeHealthQ.data?.history?.[0]?.degraded)
  const pendingInbox = inboxPendingQ.data?.length ?? 0
  const untrackedCount = scrapeQueueQ.data?.total_untracked ?? 0
  const campaignSyncErrors = campaignsQuery.isError ? 1 : 0

  const campaignDetail = isCampaignDetailPath(location.pathname)
    ? location.pathname.split("/")[2]
    : isCampaignSubpath(location.pathname)
      ? location.pathname.split("/")[2]
      : null

  const normalizedMeta: ShellRouteMeta = {
    ...meta,
    breadcrumb: campaignDetail
      ? [...meta.breadcrumb, { label: campaignDetail }]
      : meta.breadcrumb,
  }

  const mobileTitle = normalizedMeta.sectionLabel

  return (
    <div className="flex min-h-screen bg-[#f7f7f9] text-[#1a1a2e]">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex-1 md:ml-[220px] min-w-0">
        <div className="md:hidden flex items-center gap-3 p-4 bg-white border-b border-[#e8e8ef]">
          <button
            onClick={() => setSidebarOpen(true)}
            className="p-1 rounded hover:bg-[#f0f0f5]"
          >
            <Menu className="w-6 h-6 text-[#555]" />
          </button>
          <span className="text-lg font-bold text-[#1a1a2e]">{mobileTitle}</span>
        </div>

        <main className="p-6 md:px-8 md:py-6 space-y-4">
          <div className="rounded-[10px] border border-[#e8e8ef] bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h1 className="text-[22px] font-semibold text-[#1a1a2e]">
                  {normalizedMeta.pageTitle}
                </h1>
                <div className="text-sm text-[#888] mt-1 flex flex-wrap items-center gap-1.5">
                  {normalizedMeta.breadcrumb.map((crumb, idx) => (
                    <span key={`${crumb.label}-${idx}`}>
                      {crumb.to ? (
                        <Link
                          to={crumb.to}
                          className="text-[#0b62d6] hover:underline"
                        >
                          {crumb.label}
                        </Link>
                      ) : (
                        <span>{crumb.label}</span>
                      )}
                      {idx + 1 < normalizedMeta.breadcrumb.length && (
                        <span className="text-[#aaa]">/</span>
                      )}
                    </span>
                  ))}
                </div>
              </div>

              {normalizedMeta.primaryAction && (
                <Link
                  to={normalizedMeta.primaryAction.to}
                  className="px-4 py-2 rounded-md text-sm text-white bg-[#0b62d6] hover:bg-[#0951b5] transition-colors"
                >
                  {normalizedMeta.primaryAction.label}
                </Link>
              )}
            </div>

            <div className="mt-3 grid md:grid-cols-4 gap-2 text-sm text-[#666]">
              <div className="rounded-md border border-[#e8e8ef] bg-[#fafcff] px-3 py-2">
                {staleSync ? "Sync: degraded" : "Sync: healthy"}
              </div>
              <div className="rounded-md border border-[#e8e8ef] px-3 py-2">
                Failed scrapes: {failedScrapes ? "yes" : "no"}
              </div>
              <div className="rounded-md border border-[#e8e8ef] px-3 py-2">
                Pending inbox: {pendingInbox}
              </div>
              <div className="rounded-md border border-[#e8e8ef] px-3 py-2">
                Tracker health: {untrackedCount > 0 ? `${untrackedCount} untracked links` : "normal"}
              </div>
            </div>

            {campaignSyncErrors > 0 && (
              <p className="mt-3 flex items-center gap-2 text-[#a16100] text-sm bg-[#fff4d6] px-3 py-2 rounded border border-[#f3d48f]">
                <AlertTriangle className="size-4" />
                Campaign data refresh had an issue. Open a campaign for latest detail status.
              </p>
            )}
          </div>

          <Outlet />
        </main>
      </div>

      {/* Global toast notifications */}
      <Toaster />
    </div>
  )
}

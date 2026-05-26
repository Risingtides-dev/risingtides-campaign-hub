export type ShellSectionId = "campaigns" | "creators" | "operations" | "signals"

export interface ShellRouteMeta {
  section: ShellSectionId
  sectionLabel: string
  pageTitle: string
  breadcrumb: Array<{ label: string; to?: string }>
  primaryAction?: {
    label: string
    to: string
  }
}

export interface ShellNavSection {
  section: ShellSectionId
  label: string
  links: Array<{ label: string; to: string }>
}

export const SHELL_SECTIONS: ShellNavSection[] = [
  {
    section: "campaigns",
    label: "Campaigns",
    links: [
      { label: "Promotions", to: "/" },
    ],
  },
  {
    section: "creators",
    label: "Creators",
    links: [{ label: "Creator Database", to: "/creators" }],
  },
  {
    section: "operations",
    label: "Operations",
    links: [
      { label: "Slack Inbox", to: "/inbox" },
      { label: "TidesTrackers", to: "/trackers" },
      { label: "Sound Assignments", to: "/sound-assignments" },
      { label: "Internal TikTok", to: "/internal" },
      { label: "Scrape Tasks", to: "/scrape-tasks" },
    ],
  },
  {
    section: "signals",
    label: "Signals",
    links: [{ label: "Network Creators", to: "/network" }],
  },
]

export const SHELL_NAV_ROUTES = [
  {
    section: "campaigns" as ShellSectionId,
    sectionLabel: "Campaigns",
    matchers: ["/"],
    pageTitle: "Campaigns",
    breadcrumb: [{ label: "Campaigns", to: "/" }],
    primaryAction: { label: "New Campaign", to: "/?action=new" },
  },
  {
    section: "campaigns" as ShellSectionId,
    sectionLabel: "Campaigns",
    matchers: [/^\/campaign\/[^/]+\/(links|outreach)$/],
    pageTitle: "Campaign Workflow",
    breadcrumb: [
      { label: "Campaigns", to: "/" },
      { label: "Workflow", to: undefined },
    ],
    primaryAction: { label: "Back to Campaigns", to: "/" },
  },
  {
    section: "campaigns" as ShellSectionId,
    sectionLabel: "Campaigns",
    matchers: [/^\/campaign\/[^/]+$/],
    pageTitle: "Campaign Workflow",
    breadcrumb: [{ label: "Campaigns", to: "/" }, { label: "Workflow", to: undefined }],
    primaryAction: { label: "Back to Campaigns", to: "/" },
  },
  {
    section: "creators" as ShellSectionId,
    sectionLabel: "Creators",
    matchers: ["/creators"],
    pageTitle: "Creators",
    breadcrumb: [{ label: "Creators", to: "/creators" }],
    primaryAction: { label: "Creator Database", to: "/creators" },
  },
  {
    section: "operations" as ShellSectionId,
    sectionLabel: "Operations",
    matchers: ["/inbox", "/sound-assignments", "/trackers", "/scrape-tasks", "/internal"],
    pageTitle: "Operations",
    breadcrumb: [{ label: "Operations", to: "/inbox" }],
    primaryAction: { label: "Open Inbox", to: "/inbox" },
  },
  {
    section: "signals" as ShellSectionId,
    sectionLabel: "Signals",
    matchers: ["/network"],
    pageTitle: "Signals",
    breadcrumb: [{ label: "Signals", to: "/network" }],
    primaryAction: { label: "Open Network Creators", to: "/network" },
  },
  {
    section: "campaigns" as ShellSectionId,
    sectionLabel: "Campaigns",
    matchers: ["*"],
    pageTitle: "Campaign Hub",
    breadcrumb: [{ label: "Campaign Hub", to: "/" }],
    primaryAction: { label: "Back to Campaigns", to: "/" },
  },
]

export function getShellMeta(pathname: string): ShellRouteMeta {
  const isMatch = (matcher: string | RegExp): boolean => {
    if (typeof matcher === "string") {
      return matcher === "*"
        ? true
        : matcher === "/"
          ? pathname === "/"
          : pathname === matcher || pathname.startsWith(`${matcher}/`)
    }

    return matcher.test(pathname)
  }

  const match = SHELL_NAV_ROUTES.find((entry) =>
    entry.matchers.some((m) => isMatch(m))
  )

  if (!match) {
    return {
      section: "campaigns",
      sectionLabel: "Campaigns",
      pageTitle: "Campaign Hub",
      breadcrumb: [{ label: "Campaign Hub", to: "/" }],
      primaryAction: { label: "Back to Campaigns", to: "/" },
    }
  }

  return {
    section: match.section,
    sectionLabel: match.sectionLabel,
    pageTitle: match.pageTitle,
    breadcrumb: match.breadcrumb,
    primaryAction: match.primaryAction,
  }
}

export function isCreatorDetailPath(pathname: string): boolean {
  return /^\/creators\/[^/]+$/.test(pathname)
}

export function isCampaignDetailPath(pathname: string): boolean {
  return /^\/campaign\/[^/]+$/.test(pathname)
}

export function isCampaignSubpath(pathname: string): boolean {
  return /^\/campaign\/[^/]+\/.+$/.test(pathname)
}

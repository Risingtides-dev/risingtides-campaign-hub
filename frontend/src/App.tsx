import { BrowserRouter, Routes, Route } from "react-router-dom"
import { lazy, Suspense } from "react"
import { Layout } from "./components/layout/Layout"

// Lazy-load every page so the initial bundle stays small. Chart-heavy pages
// (CreatorIntelligence, BookingEfficiency — recharts) and big tables only load
// when navigated to. Layout/shell stays eager.
const CampaignsList = lazy(() => import("./pages/CampaignsList"))
const CampaignDetail = lazy(() => import("./pages/CampaignDetail"))
const CampaignReport = lazy(() => import("./pages/CampaignReport"))
const CampaignLinks = lazy(() => import("./pages/CampaignLinks"))
const CreatorDatabase = lazy(() => import("./pages/CreatorDatabase"))
const CreatorLibrary = lazy(() => import("./pages/CreatorLibrary"))
const CreatorIntelligence = lazy(() => import("./pages/CreatorIntelligence"))
const BookingWizard = lazy(() => import("./pages/BookingWizard"))
const RisingTidesTracker = lazy(() => import("./pages/RisingTidesTracker"))
const BookerDashboard = lazy(() => import("./pages/BookerDashboard"))
const CreatorProfilePage = lazy(() => import("./pages/CreatorProfilePage"))
const InternalTikTok = lazy(() => import("./pages/InternalTikTok"))
const InternalCreatorDetail = lazy(() => import("./pages/InternalCreatorDetail"))
const SlackInbox = lazy(() => import("./pages/SlackInbox"))
const NetworkCreators = lazy(() => import("./pages/NetworkCreators"))
const CampaignOutreach = lazy(() => import("./pages/CampaignOutreach"))
const TidesTrackers = lazy(() => import("./pages/TidesTrackers"))
const TrackerOverview = lazy(() => import("./pages/TrackerOverview"))
const InternalGroupDetail = lazy(() => import("./pages/InternalGroupDetail"))
const InternalScrapeView = lazy(() => import("./pages/InternalScrapeView"))
const SoundAssignments = lazy(() => import("./pages/SoundAssignments"))
const ScrapeTasks = lazy(() => import("./pages/ScrapeTasks"))
const BookingEfficiency = lazy(() => import("./pages/BookingEfficiency"))

function RouteFallback() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-sm text-rt-fg-tertiary">
      Loading…
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route
            path="/*"
            element={
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  <Route path="/" element={<CampaignsList />} />
                  <Route path="/campaign/:slug" element={<CampaignDetail />} />
                  <Route path="/campaign/:slug/report" element={<CampaignReport />} />
                  <Route path="/campaign/:slug/links" element={<CampaignLinks />} />
                  <Route path="/campaign/:slug/outreach" element={<CampaignOutreach />} />
                  <Route path="/creators" element={<CreatorDatabase />} />
                  <Route path="/library" element={<CreatorLibrary />} />
                  <Route path="/intelligence" element={<CreatorIntelligence />} />
                  <Route path="/booking-wizard" element={<BookingWizard />} />
                  <Route path="/creators/:username" element={<CreatorProfilePage />} />
                  <Route path="/rt-tracker" element={<RisingTidesTracker />} />
                  <Route path="/team/:slug" element={<BookerDashboard />} />
                  <Route path="/internal" element={<InternalTikTok />} />
                  <Route path="/internal/scrape/:category" element={<InternalScrapeView />} />
                  <Route path="/internal/group/:slug" element={<InternalGroupDetail />} />
                  <Route path="/internal/:username" element={<InternalCreatorDetail />} />
                  <Route path="/inbox" element={<SlackInbox />} />
                  <Route path="/network" element={<NetworkCreators />} />
                  <Route path="/trackers" element={<TidesTrackers />} />
                  <Route path="/tracker-overview" element={<TrackerOverview />} />
                  <Route path="/sound-assignments" element={<SoundAssignments />} />
                  <Route path="/scrape-tasks" element={<ScrapeTasks />} />
                  <Route path="/efficiency" element={<BookingEfficiency />} />
                </Routes>
              </Suspense>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

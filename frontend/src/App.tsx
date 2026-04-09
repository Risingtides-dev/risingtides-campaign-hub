import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Layout } from "./components/layout/Layout"
import CampaignsList from "./pages/CampaignsList"
import CampaignDetail from "./pages/CampaignDetail"
import CampaignLinks from "./pages/CampaignLinks"
import CreatorDatabase from "./pages/CreatorDatabase"
import CreatorProfilePage from "./pages/CreatorProfilePage"
import InternalTikTok from "./pages/InternalTikTok"
import InternalCreatorDetail from "./pages/InternalCreatorDetail"
import SlackInbox from "./pages/SlackInbox"
import NetworkCreators from "./pages/NetworkCreators"
import CampaignOutreach from "./pages/CampaignOutreach"
import TidesTrackers from "./pages/TidesTrackers"

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<CampaignsList />} />
          <Route path="/campaign/:slug" element={<CampaignDetail />} />
          <Route path="/campaign/:slug/links" element={<CampaignLinks />} />
          <Route path="/campaign/:slug/outreach" element={<CampaignOutreach />} />
          <Route path="/creators" element={<CreatorDatabase />} />
          <Route path="/creators/:username" element={<CreatorProfilePage />} />
          <Route path="/internal" element={<InternalTikTok />} />
          <Route path="/internal/:username" element={<InternalCreatorDetail />} />
          <Route path="/inbox" element={<SlackInbox />} />
          <Route path="/network" element={<NetworkCreators />} />
          <Route path="/trackers" element={<TidesTrackers />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

import { BrowserRouter, Routes, Route } from "react-router-dom"
import { Layout } from "./components/layout/Layout"
import CampaignsList from "./pages/CampaignsList"
import CampaignDetail from "./pages/CampaignDetail"
import InternalTikTok from "./pages/InternalTikTok"
import InternalCreatorDetail from "./pages/InternalCreatorDetail"
import SlackInbox from "./pages/SlackInbox"

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<CampaignsList />} />
          <Route path="/campaign/:slug" element={<CampaignDetail />} />
          <Route path="/internal" element={<InternalTikTok />} />
          <Route path="/internal/:username" element={<InternalCreatorDetail />} />
          <Route path="/inbox" element={<SlackInbox />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

export default App

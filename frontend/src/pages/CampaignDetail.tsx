import { useParams } from "react-router-dom"

export default function CampaignDetail() {
  const { slug } = useParams<{ slug: string }>()
  return (
    <div>
      <h1 className="text-[22px] font-semibold mb-6">Campaign: {slug}</h1>
      <p className="text-[#888] text-sm">Loading campaign detail...</p>
    </div>
  )
}

import { useParams } from "react-router-dom"

export default function InternalCreatorDetail() {
  const { username } = useParams<{ username: string }>()
  return (
    <div>
      <h1 className="text-[22px] font-semibold mb-6">@{username}</h1>
      <p className="text-[#888] text-sm">Loading creator detail...</p>
    </div>
  )
}

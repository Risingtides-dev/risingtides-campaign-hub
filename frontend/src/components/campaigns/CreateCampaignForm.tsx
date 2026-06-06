import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useCreateCampaign } from "@/lib/queries"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

interface CreateCampaignFormProps {
  open: boolean
}

export function CreateCampaignForm({ open }: CreateCampaignFormProps) {
  const navigate = useNavigate()
  const createCampaign = useCreateCampaign()

  const [title, setTitle] = useState("")
  const [officialSound, setOfficialSound] = useState("")
  const [startDate, setStartDate] = useState("")
  const [budget, setBudget] = useState("")

  if (!open) return null

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    createCampaign.mutate(
      {
        title,
        official_sound: officialSound,
        start_date: startDate,
        budget: parseFloat(budget),
      },
      {
        onSuccess: (data) => {
          setTitle("")
          setOfficialSound("")
          setStartDate("")
          setBudget("")
          if (data.slug) {
            navigate(`/campaign/${data.slug}`)
          }
        },
      }
    )
  }

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5 mb-4">
      <h3 className="mb-3 text-base font-semibold">Create Campaign</h3>
      <form
        onSubmit={handleSubmit}
        className="flex flex-wrap items-end gap-3"
      >
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">
            Title (Artist - Song Promo)
          </label>
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder='e.g. Fred Again "Lights Burn Dimmer" Promo'
            required
            className="w-full sm:w-[300px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">
            Sound ID or URL
          </label>
          <Input
            value={officialSound}
            onChange={(e) => setOfficialSound(e.target.value)}
            placeholder="Sound ID, sound URL, or video URL"
            required
            className="w-full sm:w-[280px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">
            Start Date
          </label>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            required
            className="w-full sm:w-[160px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">
            Budget ($)
          </label>
          <Input
            type="number"
            step="0.01"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
            placeholder="1000"
            required
            className="w-full sm:w-[130px]"
          />
        </div>
        <Button
          type="submit"
          disabled={createCampaign.isPending}
          className="bg-rt-magenta hover:bg-rt-purple text-white"
        >
          {createCampaign.isPending ? "Creating..." : "Create"}
        </Button>
      </form>
      {createCampaign.isError && (
        <p className="mt-3 text-sm text-red-600">
          {createCampaign.error?.message || "Failed to create campaign"}
        </p>
      )}
    </div>
  )
}

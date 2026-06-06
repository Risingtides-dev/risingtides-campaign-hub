import { useState, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Plus, Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import { CreatorAutocomplete } from "@/components/CreatorAutocomplete"

interface AddCreatorFormProps {
  onAdd: (data: {
    username: string
    posts_owed: number
    total_rate: number
    paypal_email: string
    platform: string
  }) => void
  isPending: boolean
}

export function AddCreatorForm({ onAdd, isPending }: AddCreatorFormProps) {
  const [username, setUsername] = useState("")
  const [postsOwed, setPostsOwed] = useState("5")
  const [totalRate, setTotalRate] = useState("100")
  const [paypalEmail, setPaypalEmail] = useState("")
  const [platform, setPlatform] = useState("tiktok")
  const [lookingUpPaypal, setLookingUpPaypal] = useState(false)

  const lookupPaypal = useCallback(async () => {
    const name = username.replace(/^@/, "").trim()
    if (!name || paypalEmail.trim()) return

    setLookingUpPaypal(true)
    try {
      const data = await api.getPaypal(name)
      if (data.paypal && !paypalEmail.trim()) {
        setPaypalEmail(data.paypal)
      }
    } catch {
      // Silently fail - paypal lookup is optional
    } finally {
      setLookingUpPaypal(false)
    }
  }, [username, paypalEmail])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const cleanUsername = username.replace(/^@/, "").trim()
    if (!cleanUsername) return

    onAdd({
      username: cleanUsername,
      posts_owed: parseInt(postsOwed, 10),
      total_rate: parseFloat(totalRate),
      paypal_email: paypalEmail,
      platform,
    })

    // Reset form
    setUsername("")
    setPostsOwed("5")
    setTotalRate("100")
    setPaypalEmail("")
    setPlatform("tiktok")
  }

  return (
    <div className="bg-rt-bg-card border border-white/8 rounded-[10px] p-5">
      <h3 className="text-[15px] font-semibold mb-3">Add Creator</h3>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2.5">
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Username</label>
          <CreatorAutocomplete
            value={username}
            onChange={setUsername}
            onSelect={lookupPaypal}
            onBlur={lookupPaypal}
            className="w-full sm:w-[160px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Platform</label>
          <Select value={platform} onValueChange={setPlatform}>
            <SelectTrigger className="w-full sm:w-[120px] h-9 text-[13px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="tiktok">TikTok</SelectItem>
              <SelectItem value="instagram">Instagram</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Posts Owed</label>
          <Input
            type="number"
            min="1"
            value={postsOwed}
            onChange={(e) => setPostsOwed(e.target.value)}
            required
            className="w-full sm:w-[90px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">Price ($)</label>
          <Input
            type="number"
            step="0.01"
            value={totalRate}
            onChange={(e) => setTotalRate(e.target.value)}
            required
            className="w-full sm:w-[110px]"
          />
        </div>
        <div className="w-full sm:w-auto">
          <label className="block text-rt-fg-tertiary text-[13px] mb-1">
            PayPal
            {lookingUpPaypal && (
              <Loader2 className="inline size-3 ml-1 animate-spin text-rt-fg-tertiary" />
            )}
          </label>
          <Input
            type="email"
            value={paypalEmail}
            onChange={(e) => setPaypalEmail(e.target.value)}
            placeholder="email@example.com"
            className="w-full sm:w-[200px]"
          />
        </div>
        <Button
          type="submit"
          disabled={isPending}
          className="bg-rt-magenta hover:bg-rt-purple text-white"
        >
          {isPending ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Plus className="size-3.5" />
          )}
          {isPending ? "Adding..." : "Add"}
        </Button>
      </form>
    </div>
  )
}

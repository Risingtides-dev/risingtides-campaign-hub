import { useState, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Plus, Loader2 } from "lucide-react"
import { api } from "@/lib/api"

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
      platform: "tiktok",
    })

    // Reset form
    setUsername("")
    setPostsOwed("5")
    setTotalRate("100")
    setPaypalEmail("")
  }

  return (
    <div className="bg-white border border-[#e8e8ef] rounded-[10px] p-5">
      <h3 className="text-[15px] font-semibold mb-3">Add Creator</h3>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-2.5">
        <div>
          <label className="block text-[#888] text-[13px] mb-1">Username</label>
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onBlur={lookupPaypal}
            placeholder="@username"
            required
            className="w-[160px]"
          />
        </div>
        <div>
          <label className="block text-[#888] text-[13px] mb-1">Posts Owed</label>
          <Input
            type="number"
            min="1"
            value={postsOwed}
            onChange={(e) => setPostsOwed(e.target.value)}
            required
            className="w-[90px]"
          />
        </div>
        <div>
          <label className="block text-[#888] text-[13px] mb-1">Price ($)</label>
          <Input
            type="number"
            step="0.01"
            value={totalRate}
            onChange={(e) => setTotalRate(e.target.value)}
            required
            className="w-[110px]"
          />
        </div>
        <div>
          <label className="block text-[#888] text-[13px] mb-1">
            PayPal
            {lookingUpPaypal && (
              <Loader2 className="inline size-3 ml-1 animate-spin text-[#888]" />
            )}
          </label>
          <Input
            type="email"
            value={paypalEmail}
            onChange={(e) => setPaypalEmail(e.target.value)}
            placeholder="email@example.com"
            className="w-[200px]"
          />
        </div>
        <Button
          type="submit"
          disabled={isPending}
          className="bg-[#0b62d6] hover:bg-[#0951b5] text-white"
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

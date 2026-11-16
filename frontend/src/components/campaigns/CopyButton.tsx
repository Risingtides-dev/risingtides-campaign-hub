// One-click copy icon for a creator's PayPal email in the campaign creators
// table, so Jake never has to highlight text to copy it.
import { useEffect, useState } from "react"
import { Check, Copy } from "lucide-react"
import { toast } from "sonner"

const COPIED_MS = 1500

interface Props {
  value: string
  label: string
}

export function CopyButton({ value, label }: Props) {
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!copied) return
    const t = setTimeout(() => setCopied(false), COPIED_MS)
    return () => clearTimeout(t)
  }, [copied])

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      toast.success(`Copied ${value}`)
    } catch {
      toast.error("Clipboard blocked — copy it by hand")
    }
  }

  const Icon = copied ? Check : Copy
  return (
    <button
      type="button"
      onClick={() => void copy()}
      aria-label={label}
      title={label}
      className="inline-flex items-center align-middle rounded p-0.5 text-rt-fg-tertiary hover:bg-white/10 hover:text-rt-fg"
    >
      <Icon className={`h-3.5 w-3.5 ${copied ? "text-rt-green" : ""}`} />
    </button>
  )
}

import { useState } from "react"
import { toast } from "sonner"
import { Check, X } from "lucide-react"
import { useDeleteNiche, useMergeNiche, useRenameNiche } from "@/lib/queries"
import type { LibraryNiche } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { nicheStyle } from "./nicheColors"

/**
 * Housekeeping for the vocabulary.
 *
 * A vocabulary anyone can extend drifts: "gym" and "gym motivation" end up
 * side by side meaning the same thing. Rename carries every tagged creator
 * along; merge folds one niche into another. Both are the cheap fix for
 * drift that would otherwise make filtering unreliable.
 */
export function NicheManager({
  niches,
  onClose,
}: {
  niches: LibraryNiche[]
  onClose: () => void
}) {
  const [renaming, setRenaming] = useState<number | null>(null)
  const [draft, setDraft] = useState("")
  const [merging, setMerging] = useState<LibraryNiche | null>(null)

  const rename = useRenameNiche()
  const remove = useDeleteNiche()
  const merge = useMergeNiche()

  const max = niches.reduce((acc, n) => Math.max(acc, n.count), 1)

  async function submitRename(niche: LibraryNiche) {
    const name = draft.trim()
    if (!name || name === niche.name) {
      setRenaming(null)
      return
    }
    try {
      await rename.mutateAsync({ id: niche.id, name })
      toast.success(`Renamed to “${name.toLowerCase()}”`)
      setRenaming(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't rename that niche")
    }
  }

  async function submitMerge(target: LibraryNiche) {
    if (!merging) return
    try {
      await merge.mutateAsync({ id: merging.id, into: target.id })
      toast.success(`Merged “${merging.name}” into “${target.name}”`)
      setMerging(null)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't merge those niches")
    }
  }

  async function submitDelete(niche: LibraryNiche) {
    try {
      await remove.mutateAsync(niche.id)
      toast.success(`Deleted “${niche.name}”`)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't delete that niche")
    }
  }

  return (
    <div className="fixed inset-0 z-[110] grid place-items-center bg-black/70 p-6">
      <div className="flex max-h-[84vh] w-full max-w-[600px] flex-col overflow-hidden rounded-2xl border border-white/15 bg-rt-bg-raised shadow-2xl">
        <header className="flex items-center gap-3 border-b border-white/10 px-5 py-4">
          <h2 className="text-[17px] font-semibold text-rt-fg">
            {merging ? `Merge “${merging.name}” into…` : "Manage niches"}
          </h2>
          <button
            type="button"
            onClick={() => (merging ? setMerging(null) : onClose())}
            aria-label="Close"
            className="ml-auto rounded-lg p-1 text-rt-fg-tertiary hover:bg-rt-bg-card hover:text-rt-fg"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="overflow-y-auto p-2">
          {niches.length === 0 ? (
            <p className="py-8 text-center text-[13px] text-rt-fg-tertiary">
              No niches yet.
            </p>
          ) : (
            niches
              .filter((n) => !merging || n.id !== merging.id)
              .map((niche) => (
                <div
                  key={niche.id}
                  className="group flex items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-rt-bg-card"
                >
                  {renaming === niche.id ? (
                    <>
                      <Input
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") submitRename(niche)
                          if (e.key === "Escape") setRenaming(null)
                        }}
                        className="h-8 flex-1"
                      />
                      <Button
                        size="sm"
                        onClick={() => submitRename(niche)}
                        disabled={rename.isPending}
                      >
                        <Check className="size-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setRenaming(null)}
                      >
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <>
                      <span
                        style={nicheStyle(niche.name)}
                        className="rounded-full px-2.5 py-0.5 text-[11px] font-semibold"
                      >
                        {niche.name}
                      </span>
                      <span className="h-1 w-[70px] overflow-hidden rounded bg-rt-bg-elevated">
                        <span
                          className="block h-full rounded bg-gradient-to-r from-rt-magenta to-rt-purple"
                          style={{ width: `${(niche.count / max) * 100}%` }}
                        />
                      </span>
                      <span className="min-w-[62px] text-right text-[12px] tabular-nums text-rt-fg-tertiary">
                        {niche.count} creator{niche.count === 1 ? "" : "s"}
                      </span>
                      <span className="flex-1" />
                      {merging ? (
                        <Button size="sm" onClick={() => submitMerge(niche)}>
                          Merge here
                        </Button>
                      ) : (
                        <span className="flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setRenaming(niche.id)
                              setDraft(niche.name)
                            }}
                          >
                            Rename
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setMerging(niche)}
                          >
                            Merge
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => submitDelete(niche)}
                          >
                            Delete
                          </Button>
                        </span>
                      )}
                    </>
                  )}
                </div>
              ))
          )}
        </div>

        <footer className="border-t border-white/10 px-5 py-3 text-[12px] text-rt-fg-tertiary">
          Rename updates every creator carrying the tag. Merge folds one niche into
          another — the fix for “gym” vs “gym motivation”.
        </footer>
      </div>
    </div>
  )
}

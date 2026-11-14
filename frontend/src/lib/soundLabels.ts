import type { TargetSound } from "./types"

/** Only repeated artist/song labels need campaign metadata in the picker. */
export function campaignRoundLabels(sounds: TargetSound[]): Map<string, string> {
  const groups = new Map<string, TargetSound[]>()
  for (const sound of sounds) {
    const label = JSON.stringify([
      (sound.song || sound.sound_id).trim().toLowerCase(),
      sound.artist.trim().toLowerCase(),
    ])
    const group = groups.get(label) ?? []
    group.push(sound)
    groups.set(label, group)
  }
  const labels = new Map<string, string>()
  for (const group of groups.values()) {
    if (group.length < 2) continue
    const metadata = group.map((sound) => {
      const round = sound.round?.trim() ?? ""
      return [/^\d+$/.test(round) ? `Round ${round}` : round, sound.start_date?.trim()]
        .filter(Boolean).join(" · ")
    })
    for (const [index, sound] of group.entries()) {
      const label = metadata[index]
      const ambiguous = !label || metadata.filter((value) => value === label).length > 1
      labels.set(sound.campaign_slug, ambiguous
        ? [label, sound.campaign_slug].filter(Boolean).join(" · ")
        : label)
    }
  }
  return labels
}

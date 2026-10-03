/**
 * Deterministic colour per niche name.
 *
 * The vocabulary is user-created and unbounded, so a fixed palette would
 * either run out or reshuffle as niches are added. Hashing the name means
 * "trucktok" is the same colour on every card, in every session, forever —
 * which is what makes a wall of tags scannable.
 *
 * Hue comes from the hash; saturation and lightness are pinned to values
 * that stay legible on the dark surface.
 */
function hash(value: string): number {
  let h = 0
  for (let i = 0; i < value.length; i++) {
    h = (h * 31 + value.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

export function nicheStyle(name: string): { background: string; color: string } {
  const hue = hash(name) % 360
  return {
    background: `hsl(${hue} 62% 20%)`,
    color: `hsl(${hue} 82% 74%)`,
  }
}

/** Avatar fallback tint, used when a creator has no picture. */
export function avatarStyle(username: string): { background: string } {
  const hue = hash(username) % 360
  return {
    background: `linear-gradient(135deg, hsl(${hue} 55% 30%), hsl(${
      (hue + 40) % 360
    } 55% 20%))`,
  }
}

export function initials(username: string): string {
  const parts = username.replace(/[^a-zA-Z0-9]/g, " ").trim().split(/\s+/)
  const first = parts[0]?.[0] ?? "?"
  const second = parts[1]?.[0] ?? parts[0]?.[1] ?? ""
  return (first + second).toUpperCase()
}

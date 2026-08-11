import { useState } from "react"
import { avatarStyle, initials } from "./nicheColors"

/**
 * Creator avatar with a coloured-initials fallback.
 *
 * The image is the cover of their most recent tracked post rather than a
 * true profile picture: TikTok's oEmbed stopped returning author
 * thumbnails and the Cobrand author payload comes back empty. These are
 * durable cobrand-public URLs, so no refresh dance is needed — but plenty
 * of creators have no tracked posts, and a broken image is worse than
 * initials, so a load failure falls back too.
 */
export function CreatorAvatar({
  username,
  src,
  size = 40,
  className = "",
}: {
  username: string
  src?: string
  size?: number
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  const showImage = Boolean(src) && !failed

  return (
    <div
      style={{
        width: size,
        height: size,
        ...(showImage ? {} : avatarStyle(username)),
      }}
      className={`grid shrink-0 place-items-center overflow-hidden rounded-full font-semibold text-white ${className}`}
    >
      {showImage ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
          className="size-full object-cover"
        />
      ) : (
        <span style={{ fontSize: Math.round(size * 0.36) }}>
          {initials(username)}
        </span>
      )}
    </div>
  )
}

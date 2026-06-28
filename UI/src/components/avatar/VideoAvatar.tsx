import type { AvatarDriverProps } from './types'

export default function VideoAvatar({ sourceUrl }: AvatarDriverProps) {
  return (
    <video
      src={sourceUrl}
      className="h-full w-full object-contain"
      autoPlay
      loop
      muted
      playsInline
    />
  )
}

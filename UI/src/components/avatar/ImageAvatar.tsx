import type { AvatarDriverProps } from './types'

export default function ImageAvatar({ sourceUrl, manifest }: AvatarDriverProps) {
  return (
    <img
      src={sourceUrl}
      alt={manifest.filename || 'Agent avatar'}
      className="h-full w-full object-contain"
    />
  )
}

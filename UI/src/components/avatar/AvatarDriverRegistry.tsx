import type { ComponentType } from 'react'
import ImageAvatar from './ImageAvatar'
import VideoAvatar from './VideoAvatar'
import type { AvatarDriverProps, AvatarKind } from './types'

const driverRegistry: Partial<Record<AvatarKind, ComponentType<AvatarDriverProps>>> = {
  image: ImageAvatar,
  video: VideoAvatar,
}

export function resolveAvatarDriver(kind: AvatarKind) {
  return driverRegistry[kind] || null
}

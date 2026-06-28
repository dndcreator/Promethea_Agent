export type AvatarRuntimeState = 'idle' | 'thinking' | 'tool_running' | 'waiting_for_user' | 'error'

export type AvatarKind = 'none' | 'image' | 'video' | 'vrm' | 'live2d'

export type AvatarManifest = {
  avatar_id: string
  enabled: boolean
  kind: AvatarKind
  driver: string
  asset_url: string
  filename?: string
  content_type?: string
  capabilities?: string[]
}

export type AvatarDriverProps = {
  sourceUrl: string
  manifest: AvatarManifest
  state: AvatarRuntimeState
}

export interface AvatarDriver {
  kind: AvatarKind
  supports(manifest: AvatarManifest): boolean
}

export const AVATAR_UPDATED_EVENT = 'promethea-avatar-updated'

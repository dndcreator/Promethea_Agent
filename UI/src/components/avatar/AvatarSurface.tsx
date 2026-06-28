import { Activity } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { getCurrentAvatar, loadAvatarAsset } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import { resolveAvatarDriver } from './AvatarDriverRegistry'
import { AVATAR_UPDATED_EVENT } from './types'
import type { AvatarManifest, AvatarRuntimeState } from './types'

const EMPTY_AVATAR: AvatarManifest = {
  avatar_id: '',
  enabled: false,
  kind: 'none',
  driver: 'none',
  asset_url: '',
  capabilities: [],
}

export default function AvatarSurface({ state = 'idle', compact = false, spacious = false, active = true, className = '' }: { state?: AvatarRuntimeState; compact?: boolean; spacious?: boolean; active?: boolean; className?: string }) {
  const { t } = useLanguage()
  const [manifest, setManifest] = useState<AvatarManifest>(EMPTY_AVATAR)
  const [sourceUrl, setSourceUrl] = useState('')
  const Driver = resolveAvatarDriver(manifest.kind)

  const refresh = useCallback(async () => {
    try {
      const response = await getCurrentAvatar()
      if (!response.ok) throw new Error(`avatar status ${response.status}`)
      const data = await response.json()
      setManifest({ ...EMPTY_AVATAR, ...(data.avatar || {}) })
    } catch {
      setManifest(EMPTY_AVATAR)
    }
  }, [])

  useEffect(() => {
    if (!active) {
      setManifest(EMPTY_AVATAR)
      return
    }
    void refresh()
    window.addEventListener(AVATAR_UPDATED_EVENT, refresh)
    return () => window.removeEventListener(AVATAR_UPDATED_EVENT, refresh)
  }, [active, refresh])

  useEffect(() => {
    let active = true
    let objectUrl = ''
    if (!manifest.enabled || !manifest.asset_url) {
      setSourceUrl('')
      return
    }
    loadAvatarAsset(manifest.asset_url)
      .then((blob) => {
        if (!active) return
        objectUrl = URL.createObjectURL(blob)
        setSourceUrl(objectUrl)
      })
      .catch(() => {
        if (active) setSourceUrl('')
      })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [manifest.avatar_id, manifest.asset_url, manifest.enabled])

  return (
    <div className={`relative overflow-hidden bg-bg-subtle ${compact ? 'h-16 w-16 rounded-[1.15rem]' : spacious ? 'min-h-[360px] flex-1 w-full rounded-xl' : 'h-[148px] w-full rounded-xl'} ${className}`}>
      <div className="neural-surface absolute inset-0" />
      <div className="absolute inset-0">
        {sourceUrl && Driver && <Driver sourceUrl={sourceUrl} manifest={manifest} state={state} />}
      </div>
      {(!sourceUrl || !manifest.enabled) && (
        <Activity size={compact ? 30 : 42} className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 text-brand-500 opacity-80" />
      )}
      {!compact && (
        <span className="absolute bottom-3 left-3 rounded-full border border-white/70 bg-white/75 px-2 py-1 text-[10px] font-semibold text-text-normal shadow-sm backdrop-blur">
          {formatAvatarState(state, t)}
        </span>
      )}
    </div>
  )
}

function formatAvatarState(state: AvatarRuntimeState, t: (zh: string, en: string) => string) {
  if (state === 'thinking') return t('思考中', 'Thinking')
  if (state === 'tool_running') return t('执行中', 'Working')
  if (state === 'waiting_for_user') return t('等待确认', 'Waiting')
  if (state === 'error') return t('需要处理', 'Needs attention')
  return t('在线', 'Awake')
}

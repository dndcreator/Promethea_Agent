import { useEffect, useState } from 'react'
import { clearCurrentAvatar, getCurrentAvatar, setAvatarEnabled, uploadAvatar } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import AvatarSurface from './AvatarSurface'
import { AVATAR_UPDATED_EVENT } from './types'
import type { AvatarManifest } from './types'

export default function AvatarSettingsPanel() {
  const { t } = useLanguage()
  const [avatar, setAvatar] = useState<AvatarManifest | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const refresh = async () => {
    const response = await getCurrentAvatar()
    const data = await response.json().catch(() => ({}))
    setAvatar(data.avatar || null)
  }

  useEffect(() => {
    void refresh()
  }, [])

  const emitUpdated = () => window.dispatchEvent(new Event(AVATAR_UPDATED_EVENT))

  const handleUpload = async (file: File | null) => {
    if (!file) return
    setBusy(true)
    setNotice('')
    try {
      const form = new FormData()
      form.set('file', file)
      const response = await uploadAvatar(form)
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(String(data.detail || `HTTP ${response.status}`))
      setAvatar(data.avatar || null)
      emitUpdated()
      setNotice(t('形象已更新。', 'Avatar updated.'))
    } catch (error) {
      setNotice(error instanceof Error ? error.message : String(error))
    } finally {
      setBusy(false)
    }
  }

  const handleEnabled = async (enabled: boolean) => {
    setBusy(true)
    try {
      const response = await setAvatarEnabled(enabled)
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(String(data.detail || `HTTP ${response.status}`))
      setAvatar(data.avatar || null)
      emitUpdated()
    } finally {
      setBusy(false)
    }
  }

  const handleClear = async () => {
    setBusy(true)
    try {
      const response = await clearCurrentAvatar()
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setAvatar(null)
      emitUpdated()
      setNotice(t('已恢复默认形象。', 'Default avatar restored.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-xl border border-black/5 bg-gray-50/70 p-4">
      <div className="grid grid-cols-[132px_1fr] gap-4">
        <AvatarSurface />
        <div className="flex min-w-0 flex-col gap-3">
          <div>
            <h4 className="text-sm font-semibold text-text-strong">{t('Agent 形象', 'Agent Avatar')}</h4>
            <p className="mt-1 text-xs leading-5 text-text-muted">
              {t('上传图片、GIF 或视频。VRM 和 Live2D 将通过独立驱动扩展。', 'Upload an image, GIF, or video. VRM and Live2D are added through separate drivers.')}
            </p>
          </div>
          <input
            type="file"
            accept=".png,.jpg,.jpeg,.webp,.gif,.webm,.mp4,image/*,video/webm,video/mp4"
            disabled={busy}
            onChange={(event) => void handleUpload(event.target.files?.[0] || null)}
            className="block w-full text-xs text-text-muted file:mr-3 file:rounded-lg file:border-0 file:bg-brand-100 file:px-3 file:py-2 file:text-xs file:font-semibold file:text-brand-700 hover:file:bg-brand-200"
          />
          <div className="flex items-center gap-3">
            <label className="inline-flex items-center gap-2 text-xs text-text-normal">
              <input type="checkbox" checked={Boolean(avatar?.enabled)} disabled={!avatar?.avatar_id || busy} onChange={(event) => void handleEnabled(event.target.checked)} />
              {t('启用形象', 'Enable avatar')}
            </label>
            {avatar?.avatar_id && (
              <button type="button" disabled={busy} onClick={() => void handleClear()} className="text-xs font-semibold text-red-600 hover:text-red-700 disabled:opacity-50">
                {t('恢复默认', 'Restore default')}
              </button>
            )}
          </div>
          {avatar?.filename && <div className="truncate text-[11px] text-text-muted">{avatar.filename}</div>}
          {notice && <div className="text-xs text-amber-700">{notice}</div>}
        </div>
      </div>
    </section>
  )
}

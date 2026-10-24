import { useEffect, useState } from 'react'
import { Copy, Link, RefreshCw, Unlink } from 'lucide-react'
import { listChannelAccounts, pairChannelAccount, unbindChannelAccount, type ChannelAccount, type ChannelPairing } from '../../../services/api'
import { useLanguage } from '../../../store/LanguageContext'

export default function ChannelAccountsPanel() {
  const { t } = useLanguage()
  const [accounts, setAccounts] = useState<ChannelAccount[]>([])
  const [pairing, setPairing] = useState<ChannelPairing | null>(null)
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    void listChannelAccounts(controller.signal).then((rows) => {
      if (!Array.isArray(rows)) throw new Error('Invalid channel account response')
      setAccounts(rows)
    }).catch(() => {
      if (!controller.signal.aborted) setError(t('平台状态暂不可用', 'Channel status unavailable'))
    })
    return () => controller.abort()
  }, [revision, t])
  useEffect(() => {
    if (!pairing) return
    const timer = window.setTimeout(() => setPairing(null), Math.max(0, pairing.expires_at * 1000 - Date.now()))
    return () => window.clearTimeout(timer)
  }, [pairing])
  const act = async (channel: string, remove: boolean) => {
    if (busy || !accounts.some((account) => account.channel === channel)) return
    setBusy(true); setError(''); setCopied(false)
    try {
      if (remove) { await unbindChannelAccount(channel); setPairing(null) }
      else setPairing(await pairChannelAccount({ channel }))
      setRevision((value) => value + 1)
    } catch { setError(t('平台绑定操作失败', 'Channel binding failed')) }
    finally { setBusy(false) }
  }
  return <details className="rounded-lg border border-black/5 p-3">
    <summary className="cursor-pointer text-sm font-semibold">{t('消息平台', 'Messaging platforms')}</summary>
    <div className="flex justify-end mt-3"><button type="button" title={t('刷新', 'Refresh')} aria-label={t('刷新平台状态', 'Refresh channel status')} onClick={() => { setError(''); setRevision((value) => value + 1) }} className="p-2 hover:bg-black/5 rounded"><RefreshCw size={15} /></button></div>
    {accounts.length === 0 && !error && <p className="text-sm text-text-muted">{t('暂无已启用的平台', 'No enabled platforms')}</p>}
    {accounts.map((account) => <div key={`${account.channel}:${account.account_id}`} className="flex flex-wrap items-center gap-3 border-t border-black/5 py-3">
      <span className="font-medium text-sm">{({ qq: 'QQ', telegram: 'Telegram', feishu: t('飞书', 'Feishu'), dingtalk: t('钉钉', 'DingTalk'), wecom: t('企业微信', 'WeCom') } as Record<string, string>)[account.channel] || account.channel}</span>
      <span className="text-xs text-text-muted">{account.running ? t('已启动', 'Running') : t('未启动', 'Stopped')} · {account.bound ? t('已绑定', 'Linked') : t('未绑定', 'Not linked')}</span>
      <button type="button" disabled={busy || !account.running} onClick={() => void act(account.channel, false)} className="ml-auto inline-flex items-center gap-1.5 text-xs disabled:opacity-40"><Link size={14} />{account.bound ? t('重新绑定', 'Relink') : t('生成绑定码', 'Create pairing code')}</button>
      {account.bound && <button type="button" title={t('解除绑定', 'Unlink')} aria-label={`${t('解除绑定', 'Unlink')} ${account.channel}`} disabled={busy} onClick={() => void act(account.channel, true)} className="p-2 hover:bg-black/5 rounded"><Unlink size={14} /></button>}
    </div>)}
    {pairing && <div className="flex flex-wrap items-center gap-2 border-t border-black/5 pt-3">
      <code className="text-xs break-all min-w-0 flex-1 select-all">{pairing.command}</code>
      <button type="button" title={t('复制绑定指令', 'Copy pairing command')} aria-label={t('复制绑定指令', 'Copy pairing command')} onClick={() => { void navigator.clipboard.writeText(pairing.command).then(() => setCopied(true)).catch(() => setError(t('复制失败', 'Copy failed'))) }} className="p-2 hover:bg-black/5 rounded"><Copy size={15} /></button>
      <time className="text-xs text-text-muted">{copied ? t('已复制', 'Copied') : `${t('有效至', 'Expires')} ${new Date(pairing.expires_at * 1000).toLocaleTimeString()}`}</time>
    </div>}
    {error && <p role="alert" className="mt-3 text-xs text-red-600">{error}</p>}
  </details>
}

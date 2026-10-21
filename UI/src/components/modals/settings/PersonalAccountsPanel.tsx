import { useId } from 'react'
import { CalendarDays, Mail } from 'lucide-react'
import { useLanguage } from '../../../store/LanguageContext'

type Props = { status: any; draft: Record<string, string>; busy: boolean; onChange: (key: string, value: string) => void; onDisconnect: (keys: string[]) => void }

export default function PersonalAccountsPanel({ status, draft, busy, onChange, onDisconnect }: Props) {
  const { t } = useLanguage()
  const id = useId()
  const groups = [
    { key: 'mail', icon: Mail, title: t('邮件', 'Email'), configured: status?.mail?.imap_configured || status?.mail?.smtp_configured,
      fields: [
        ['MAIL__IMAP_HOST', t('IMAP 服务器', 'IMAP host'), 'text', status?.mail?.imap_host],
        ['MAIL__IMAP_PORT', t('IMAP 端口', 'IMAP port'), 'number', status?.mail?.imap_port || '993'],
        ['MAIL__SMTP_HOST', t('SMTP 服务器', 'SMTP host'), 'text', status?.mail?.smtp_host],
        ['MAIL__SMTP_PORT', t('SMTP 端口', 'SMTP port'), 'number', status?.mail?.smtp_port || ((draft.MAIL__SMTP_SECURITY || status?.mail?.smtp_security) === 'starttls' ? '587' : '465')],
        ['MAIL__USERNAME', t('邮箱账号', 'Mail username'), 'text', status?.mail?.username],
        ['MAIL__PASSWORD', t('邮箱授权码 / 密码', 'Mail app password'), 'password', ''],
        ['MAIL__FROM', t('发件地址', 'From address'), 'text', status?.mail?.from],
      ] },
    { key: 'calendar', icon: CalendarDays, title: t('日历', 'Calendar'), configured: status?.calendar?.configured,
      fields: [
        ['CALENDAR__URL', t('CalDAV 地址', 'CalDAV URL'), 'url', status?.calendar?.url],
        ['CALENDAR__USERNAME', t('日历账号', 'Calendar username'), 'text', status?.calendar?.username],
        ['CALENDAR__PASSWORD', t('日历授权码 / 密码', 'Calendar app password'), 'password', ''],
      ] },
  ]
  return <details className="rounded-lg border border-black/5 p-3">
    <summary className="cursor-pointer text-sm font-semibold">{t('个人账号', 'Personal accounts')}</summary>
    {groups.map((group) => <section key={group.key} className="py-4 border-t border-black/5 mt-3">
      <header className="flex flex-wrap items-center gap-2 mb-4 text-sm"><group.icon size={15} /><h4 className="font-semibold">{group.title}</h4><span className="ml-auto text-xs text-text-muted">{group.key === 'mail' ? `${t('收件', 'Read')} ${status?.mail?.imap_configured ? '✓' : '-'} / ${t('发件', 'Send')} ${status?.mail?.smtp_configured ? '✓' : '-'}` : group.configured ? t('已配置', 'Configured') : t('未配置', 'Not configured')}</span>{group.configured && <button type="button" disabled={busy} className="text-xs text-red-600" onClick={() => onDisconnect([...group.fields.map(([key]) => key), ...(group.key === 'mail' ? ['MAIL__SMTP_SECURITY'] : [])])}>{t('移除账号', 'Remove account')}</button>}</header>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {group.fields.map(([key, label, type, current]) => <div key={key} className="flex flex-col gap-1.5">
          <label htmlFor={`${id}-${key}`} className="text-xs font-semibold">{label}</label>
          <input id={`${id}-${key}`} type={type} disabled={busy} min={type === 'number' ? 1 : undefined} max={type === 'number' ? 65535 : undefined}
            autoComplete={type === 'password' ? 'new-password' : 'off'} value={draft[key] || ''}
            placeholder={current || t('留空则不修改', 'Leave blank to keep unchanged')}
            onChange={(event) => onChange(key, event.target.value)} className="w-full border border-black/10 rounded-lg px-3 py-2 text-sm" />
        </div>)}
        {group.key === 'mail' && <label className="flex flex-col gap-1.5 text-xs font-semibold">{t('SMTP 加密', 'SMTP security')}
          <select disabled={busy} value={draft.MAIL__SMTP_SECURITY || ''} onChange={(event) => onChange('MAIL__SMTP_SECURITY', event.target.value)} className="w-full border border-black/10 rounded-lg px-3 py-2 text-sm">
            <option value="">{t('保持不变', 'Keep unchanged')} ({status?.mail?.smtp_security || 'ssl'})</option><option value="ssl">TLS</option><option value="starttls">STARTTLS</option>
          </select>
        </label>}
      </div>
    </section>)}
  </details>
}

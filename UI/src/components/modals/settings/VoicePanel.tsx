import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Download, Mic, RefreshCw, Save, Square, Volume2 } from 'lucide-react'
import type { VoiceCapabilities, VoiceEndpointStatus } from '@promethea/sdk'
import { getVoiceModels, getVoiceStatus, readApiResponse, synthesizeSpeech, transcribeSpeech, updateRuntimeSecrets } from '../../../services/api'
import { useAudioPreview } from '../../../hooks/useAudioPreview'
import { useAudioRecorder } from '../../../hooks/useAudioRecorder'
import { useLanguage } from '../../../store/LanguageContext'
import { voiceError } from '../../../utils/voice-error'

type Kind = 'stt' | 'tts'
type Draft = Pick<VoiceEndpointStatus, 'provider' | 'model' | 'base_url' | 'voice' | 'format' | 'speed'> & { api_key: string }
const empty = (): Draft => ({ provider: 'disabled', model: '', base_url: '', voice: '', format: 'mp3', speed: 1, api_key: '' })

export default function VoicePanel() {
  const { t } = useLanguage()
  const [status, setStatus] = useState<VoiceCapabilities | null>(null)
  const [draft, setDraft] = useState<Record<Kind, Draft>>({ stt: empty(), tts: empty() })
  const [kind, setKind] = useState<Kind>('tts')
  const [speak, setSpeak] = useState(false)
  const [text, setText] = useState('')
  const [transcript, setTranscript] = useState('')
  const [models, setModels] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [audioFormat, setAudioFormat] = useState('mp3')
  const request = useRef<AbortController | null>(null)
  const preview = useAudioPreview()
  const listId = useId()
  const refresh = useCallback(() => {
    const controller = new AbortController()
    request.current?.abort()
    request.current = controller
    setError('')
    void getVoiceStatus(controller.signal).then(state => {
      if (controller.signal.aborted) return
      if (!state.stt || !state.tts) throw new Error('VOICE_INVALID_RESPONSE')
      setStatus(state); setSpeak(Boolean(state.speak_replies))
      setDraft({ stt: { ...state.stt, api_key: '' }, tts: { ...state.tts, api_key: '' } })
    }).catch(() => { if (!controller.signal.aborted) setError('VOICE_STATUS_UNAVAILABLE') })
  }, [])
  useEffect(() => {
    refresh()
    return () => request.current?.abort()
  }, [refresh])

  const perform = async (action: 'save' | 'models' | 'speak' | 'transcribe', audio?: Blob, filename = 'voice.webm') => {
    if (busy || !status) return
    const controller = new AbortController()
    request.current?.abort(); request.current = controller
    setBusy(true); setError(''); setNotice('')
    try {
      const values: Record<string, string> = { VOICE__SPEAK_REPLIES: String(speak) }
      for (const role of ['stt', 'tts'] as const) {
        const fields = role === 'stt' ? ['provider', 'model', 'base_url', 'api_key'] : ['provider', 'model', 'base_url', 'api_key', 'voice', 'format', 'speed']
        for (const [field, value] of Object.entries(draft[role])) if (fields.includes(field) && String(value).trim()) {
          values[`VOICE__${role.toUpperCase()}_${field.toUpperCase()}`] = String(value).trim()
        }
      }
      await updateRuntimeSecrets(values).then(readApiResponse)
      if (controller.signal.aborted) return
      const state = await getVoiceStatus(controller.signal)
      setStatus(state)
      setDraft(current => ({ stt: { ...current.stt, api_key: '' }, tts: { ...current.tts, api_key: '' } }))
      window.dispatchEvent(new Event('voice-settings-changed'))
      if (action === 'models') setModels((await getVoiceModels(kind, controller.signal)).models)
      else if (action === 'speak') {
        const audio = await synthesizeSpeech(text, controller.signal)
        if (!controller.signal.aborted) { setAudioFormat(draft.tts.format || 'mp3'); preview.load(audio) }
      } else if (action === 'transcribe' && audio) {
        const result = await transcribeSpeech(audio, filename, controller.signal)
        setTranscript(result.stt.text)
        if (!result.stt.text) throw new Error('VOICE_EMPTY_TRANSCRIPT')
      }
      setNotice(action === 'save' ? t('已保存', 'Saved') : t('请求成功', 'Request succeeded'))
    } catch (failure) { if (!controller.signal.aborted) setError(voiceError(failure, t)) }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }
  const recorder = useAudioRecorder((audio, filename) => perform('transcribe', audio, filename))
  const value = draft[kind]
  const patch = (changes: Partial<Draft>) => setDraft(current => ({ ...current, [kind]: { ...current[kind], ...changes } }))
  const input = 'w-full min-w-0 rounded-lg border border-black/10 bg-white px-3 py-2 text-sm'
  return <section className="settings-section" aria-label={t('语音交互', 'Voice interaction')}>
    <header className="settings-section-heading"><h3>{t('语音交互', 'Voice interaction')}</h3><button type="button" className="icon-button" disabled={busy || recorder.recording} onClick={refresh} title={t('刷新语音配置', 'Refresh speech settings')} aria-label={t('刷新语音配置', 'Refresh speech settings')}><RefreshCw size={14} /></button></header>
    <div role="tablist" aria-label={t('语音模式', 'Speech mode')} className="flex gap-3 border-b border-black/5 pb-2">
      {(['tts', 'stt'] as const).map(role => <button key={role} type="button" role="tab" aria-selected={kind === role} className={`text-sm ${kind === role ? 'font-semibold text-text-strong' : 'text-text-muted'}`} disabled={busy || recorder.recording} onClick={() => { setKind(role); setModels([]); setError(''); setNotice('') }}>{role === 'tts' ? t('语音合成', 'Speech synthesis') : t('语音识别', 'Speech recognition')}</button>)}
    </div>
    <div className="mt-3 grid grid-cols-1 gap-3" role="tabpanel">
      <label className="text-xs font-semibold">{t('提供方', 'Provider')}<select aria-label={t('提供方', 'Provider')} className={`${input} mt-1.5`} value={value.provider} disabled={busy || !status} onChange={event => patch({ provider: event.target.value, ...(event.target.value === 'elevenlabs' ? { base_url: 'https://api.elevenlabs.io', voice: '' } : {}) })}>
        <option value="disabled">{t('关闭', 'Off')}</option><option value="openai">{t('OpenAI 兼容 / 本地服务', 'OpenAI compatible / local service')}</option>{kind === 'tts' && <option value="elevenlabs">ElevenLabs</option>}
      </select></label>
      {value.provider !== 'disabled' && <>
        <label className="text-xs font-semibold">{t('接口地址', 'Endpoint')}<input type="url" className={`${input} mt-1.5`} value={value.base_url} disabled={busy} onChange={event => patch({ base_url: event.target.value })} /></label>
        <label className="text-xs font-semibold">API Key<input type="password" autoComplete="off" className={`${input} mt-1.5`} value={value.api_key} disabled={busy} placeholder={status?.[kind].api_key_configured ? t('已配置，留空保留', 'Configured; leave blank to keep') : t('本地服务可留空', 'Optional for local services')} onChange={event => patch({ api_key: event.target.value })} /></label>
        <label className="text-xs font-semibold">{t('模型', 'Model')}<div className="mt-1.5 flex items-center gap-2"><input aria-label={t('模型', 'Model')} className={input} list={listId} value={value.model} disabled={busy} onChange={event => patch({ model: event.target.value })} /><button type="button" className="icon-button shrink-0" disabled={busy} title={t('读取模型列表', 'List models')} aria-label={t('读取模型列表', 'List models')} onClick={() => void perform('models')}><RefreshCw size={15} /></button></div><datalist id={listId}>{models.map(model => <option key={model} value={model} />)}</datalist></label>
        {kind === 'tts' && <>
          <label className="text-xs font-semibold">{t('音色 / Voice ID', 'Voice / Voice ID')}<input className={`${input} mt-1.5`} value={value.voice} disabled={busy} onChange={event => patch({ voice: event.target.value })} /></label>
          <label className="text-xs font-semibold">{t('音频格式', 'Audio format')}<select aria-label={t('音频格式', 'Audio format')} className={`${input} mt-1.5`} value={value.format} disabled={busy} onChange={event => patch({ format: event.target.value })}>{(value.provider === 'elevenlabs' ? ['mp3', 'wav', 'opus'] : ['mp3', 'wav', 'opus', 'aac', 'flac']).map(format => <option key={format}>{format}</option>)}</select></label>
          {value.provider === 'openai' && <label className="text-xs font-semibold">{t('语速', 'Speed')} · {value.speed}<input type="range" min="0.25" max="4" step="0.05" className="mt-2 w-full" value={value.speed} disabled={busy} onChange={event => patch({ speed: Number(event.target.value) })} /></label>}
        </>}
      </>}
      <div className="text-xs text-text-muted" role="status">{status ? status[kind].configured ? t('已配置', 'Configured') : t('未配置完成', 'Not configured') : t('正在读取配置', 'Loading configuration')}</div>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" role="switch" checked={speak} disabled={busy || !status} onChange={event => setSpeak(event.target.checked)} />{t('语音回复', 'Spoken replies')}</label>
      <button type="button" className="secondary-button justify-self-start" disabled={busy || !status} onClick={() => void perform('save')}><Save size={14} />{t('保存语音设置', 'Save voice settings')}</button>
      {kind === 'tts' ? <>
        <label className="text-xs font-semibold">{t('试听文本', 'Preview text')}<textarea className={`${input} mt-1.5`} rows={3} maxLength={4096} value={text} disabled={busy} onChange={event => setText(event.target.value)} /></label>
        <button type="button" className="secondary-button justify-self-start" disabled={busy || !text.trim() || value.provider === 'disabled'} onClick={() => void perform('speak')}><Volume2 size={15} />{busy ? t('合成中', 'Synthesizing') : t('合成试听', 'Synthesize preview')}</button>
        {preview.url && <div className="flex min-w-0 items-center gap-2"><audio className="min-w-0 flex-1" ref={preview.element} src={preview.url} controls /><a className="icon-button" href={preview.url} download={`speech.${audioFormat}`} title={t('下载音频', 'Download audio')} aria-label={t('下载音频', 'Download audio')}><Download size={16} /></a></div>}
      </> : <>
        <div className="flex flex-wrap gap-2"><button type="button" className="secondary-button" disabled={busy || recorder.pending || value.provider === 'disabled'} onClick={() => recorder.recording ? recorder.stop() : void recorder.start()}>{recorder.recording ? <Square size={15} /> : <Mic size={15} />}{recorder.recording ? t('停止录音并识别', 'Stop and transcribe') : t('录音测试', 'Record test')}</button><label className="text-xs">{t('音频文件', 'Audio file')}<input type="file" accept="audio/*" disabled={busy || recorder.recording || value.provider === 'disabled'} onChange={event => { const file = event.target.files?.[0]; if (file) void perform('transcribe', file, file.name); event.target.value = '' }} /></label></div>
        {transcript && <output className="whitespace-pre-wrap break-words text-sm">{transcript}</output>}
      </>}
      {(error || recorder.error) && <div role="alert" className="page-error">{error ? error.startsWith('VOICE_') ? voiceError(error, t) : error : voiceError(recorder.error, t)}</div>}
      {notice && <div role="status" className="operation-notice">{notice}</div>}
    </div>
  </section>
}

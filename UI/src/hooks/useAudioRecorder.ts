import { useCallback, useEffect, useRef, useState } from 'react'

export function useAudioRecorder(onAudio: (audio: Blob, filename: string) => Promise<void>) {
  const callback = useRef(onAudio)
  callback.current = onAudio
  const recorder = useRef<MediaRecorder | null>(null)
  const generation = useRef(0)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const [recording, setRecording] = useState(false)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const cancel = useCallback(() => {
    generation.current++
    clearTimeout(timer.current)
    const active = recorder.current
    recorder.current = null
    if (active) {
      active.onstop = null
      if (active.state !== 'inactive') active.stop()
      active.stream.getTracks().forEach(track => track.stop())
    }
    setRecording(false); setPending(false); setError('')
  }, [])
  useEffect(() => cancel, [cancel])
  const stop = useCallback(() => {
    clearTimeout(timer.current)
    if (recorder.current?.state === 'recording') {
      setRecording(false); setPending(true)
      recorder.current.stop()
    }
  }, [])
  const start = async () => {
    if (pending || recording) return
    const epoch = ++generation.current
    setPending(true); setError('')
    let stream: MediaStream | undefined
    try {
      if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('VOICE_RECORDING_UNAVAILABLE')
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (epoch !== generation.current) { stream.getTracks().forEach(track => track.stop()); return }
      const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(value => MediaRecorder.isTypeSupported(value))
      const active = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      const chunks: Blob[] = []
      recorder.current = active
      active.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
      active.onerror = () => { cancel(); setError('VOICE_RECORDING_FAILED') }
      active.onstop = async () => {
        clearTimeout(timer.current)
        active.stream.getTracks().forEach(track => track.stop())
        if (recorder.current === active) recorder.current = null
        if (epoch !== generation.current) return
        setRecording(false); setPending(true)
        try {
          const blob = new Blob(chunks, { type: active.mimeType || mime || 'audio/webm' })
          if (!blob.size) throw new Error('VOICE_EMPTY_AUDIO')
          await callback.current(blob, blob.type.includes('mp4') ? 'voice.m4a' : 'voice.webm')
        } catch (failure) {
          if (epoch === generation.current) setError(failure instanceof Error ? failure.message : 'VOICE_RECORDING_FAILED')
        } finally { if (epoch === generation.current) setPending(false) }
      }
      active.start(250)
      setRecording(true); setPending(false)
      timer.current = setTimeout(stop, 60000)
    } catch (failure) {
      stream?.getTracks().forEach(track => track.stop())
      if (epoch === generation.current) {
        setPending(false)
        setError(failure instanceof DOMException && failure.name === 'NotAllowedError' ? 'VOICE_MICROPHONE_DENIED' : 'VOICE_RECORDING_UNAVAILABLE')
      }
    }
  }
  return { recording, pending, error, start, stop, cancel }
}

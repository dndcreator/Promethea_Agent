import { useCallback, useEffect, useRef, useState } from 'react'

export function useAudioPreview() {
  const element = useRef<HTMLAudioElement | null>(null)
  const [url, setUrl] = useState('')
  const stop = useCallback(() => { element.current?.pause(); setUrl('') }, [])
  useEffect(() => {
    if (!url) return
    const audio = element.current
    void audio?.play().catch(() => { /* Native controls remain available after autoplay denial. */ })
    return () => { audio?.pause(); URL.revokeObjectURL(url) }
  }, [url])
  const load = (audio: Blob) => { element.current?.pause(); setUrl(URL.createObjectURL(audio)) }
  return { url, element, load, stop }
}

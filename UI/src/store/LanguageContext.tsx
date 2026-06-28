import { createContext, useContext, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

type Lang = 'zh' | 'en'

type LanguageContextValue = {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (zh: string, en: string) => string
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    const stored = localStorage.getItem('promethea_ui_lang')
    return stored === 'en' ? 'en' : 'zh'
  })

  const value = useMemo<LanguageContextValue>(() => ({
    lang,
    setLang: (next) => {
      localStorage.setItem('promethea_ui_lang', next)
      setLangState(next)
    },
    t: (zh, en) => (lang === 'en' ? en : zh),
  }), [lang])

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLanguage() {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error('useLanguage must be used within LanguageProvider')
  return ctx
}

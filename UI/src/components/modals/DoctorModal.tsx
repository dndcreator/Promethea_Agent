import { useEffect, useState } from 'react'
import { getDoctor, migrateConfig } from '../../services/api'
import { useLanguage } from '../../store/LanguageContext'
import ResultCard from './settings/ResultCard'

export default function DoctorModal({ onClose }: { onClose: () => void }) {
  const [output, setOutput] = useState<unknown>('Running diagnostics...')
  const { t } = useLanguage()

  const runDiagnostics = () => {
    setOutput(t('正在运行诊断...', 'Running diagnostics...'))
    getDoctor()
      .then((res) => res.text())
      .then((data) => {
        try {
          setOutput(JSON.parse(data))
        } catch {
          setOutput(data)
        }
      })
      .catch((err) => setOutput({ status: 'error', message: err.message }))
  }

  useEffect(() => {
    runDiagnostics()
  }, [])

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[700px] h-[60vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('系统诊断', 'System Doctor')}</h2>
          <button type="button" onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        <div className="p-4 border-b border-black/5 flex gap-2">
          <button type="button" onClick={runDiagnostics} className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-sm font-medium rounded-lg">{t('重新运行', 'Run Again')}</button>
          <button type="button" onClick={() => migrateConfig().then(() => runDiagnostics())} className="px-3 py-1.5 bg-brand-500 hover:bg-brand-600 text-white text-sm font-medium rounded-lg">{t('重载配置', 'Reload Config')}</button>
        </div>
        <div className="flex-1 overflow-y-auto bg-bg-page p-4">
          <ResultCard payload={output} />
        </div>
      </div>
    </div>
  )
}

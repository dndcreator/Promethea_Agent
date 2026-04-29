import { useState, useEffect } from 'react';
import { getDoctor, migrateConfig } from '../../lib/api';
import { useLanguage } from '../../store/LanguageContext';

export default function DoctorModal({ onClose }: { onClose: () => void }) {
  const [output, setOutput] = useState<string>('Running diagnostics...');
  const { t } = useLanguage();
  
  const runDiagnostics = () => {
    setOutput(t('正在运行诊断...', 'Running diagnostics...'));
    getDoctor().then(res => res.text()).then(data => {
      try {
        const json = JSON.parse(data);
        setOutput(JSON.stringify(json, null, 2));
      } catch (e) {
        setOutput(data);
      }
    }).catch(err => setOutput(`Error: ${err.message}`));
  };

  useEffect(() => {
    runDiagnostics();
  }, []);

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[700px] h-[60vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('系统诊断', 'System Doctor')}</h2>
          <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        <div className="p-4 border-b border-black/5 flex gap-2">
          <button onClick={runDiagnostics} className="px-3 py-1.5 bg-gray-100 hover:bg-gray-200 text-sm font-medium rounded-lg">{t('重新运行', 'Run Again')}</button>
          <button onClick={() => migrateConfig().then(() => runDiagnostics())} className="px-3 py-1.5 bg-brand-500 hover:bg-brand-600 text-white text-sm font-medium rounded-lg">{t('重载配置', 'Reload Config')}</button>
        </div>
        <div className="flex-1 p-4 bg-gray-900 text-green-400 font-mono text-xs overflow-y-auto whitespace-pre-wrap">
          {output}
        </div>
      </div>
    </div>
  );
}

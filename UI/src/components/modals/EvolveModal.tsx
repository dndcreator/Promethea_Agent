import { useState, useEffect } from 'react';
import { getSelfEvolveStatus } from '../../lib/api';
import { useLanguage } from '../../store/LanguageContext';

export default function EvolveModal({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<any>({});
  const { t } = useLanguage();
  
  useEffect(() => {
    getSelfEvolveStatus().then(res => res.json()).then(setStatus).catch(() => {});
  }, []);

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[800px] max-h-[80vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong flex items-center gap-2">{t('自我进化实验室', 'Self Evolution Lab')} <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded">{t('实验性', 'Experimental')}</span></h2>
          <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        <div className="p-4 text-xs text-orange-700 bg-orange-50 border-b border-orange-100">
          {t('实验性功能，可能引入不稳定行为。建议使用隔离账号与记忆进行测试。', 'Experimental feature. It may introduce unstable behavior. Use an isolated account and memory for trials.')}
        </div>
        <div className="flex-1 p-6 overflow-y-auto grid grid-cols-2 gap-6 bg-bg-page">
          <div className="bg-white p-4 rounded-xl border border-black/5 shadow-sm">
            <h3 className="font-semibold text-text-strong mb-4">{t('当前行动问题', 'Current Action Issues')}</h3>
            <div className="text-xs text-text-muted">
              {status.issues?.length ? status.issues.map((i: any, idx: number) => <div key={idx}>{i}</div>) : t('暂无近期问题。', 'No recent issues detected.')}
            </div>
          </div>
          <div className="bg-white p-4 rounded-xl border border-black/5 shadow-sm">
            <h3 className="font-semibold text-text-strong mb-4">{t('进化选项', 'Evolution Options')}</h3>
            <div className="text-xs text-text-muted">
              {status.options?.length ? status.options.map((o: any, idx: number) => <div key={idx}>{o}</div>) : t('暂无可用进化选项。', 'No evolutionary options available.')}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

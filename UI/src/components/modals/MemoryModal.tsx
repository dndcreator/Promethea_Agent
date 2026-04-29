import { useState, useEffect } from 'react';
import { getMemoryEntries } from '../../lib/api';
import { useLanguage } from '../../store/LanguageContext';

export default function MemoryModal({ onClose }: { onClose: () => void }) {
  const [activeTab, setActiveTab] = useState('console');
  const [entries, setEntries] = useState<any[]>([]);
  const { t } = useLanguage();

  useEffect(() => {
    if (activeTab === 'console') {
      getMemoryEntries().then(res => res.json()).then(data => setEntries(data.entries || [])).catch(() => {});
    }
  }, [activeTab]);

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-[1200px] h-[80vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('记忆工作台', 'Memory Workbench')}</h2>
          <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        
        <div className="flex border-b border-black/5 bg-white px-4 pt-2 gap-4">
          {['console', 'inspector', 'recall', 'graph'].map(tab => (
            <button 
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors capitalize ${
                activeTab === tab ? 'border-brand-500 text-brand-600' : 'border-transparent text-text-muted hover:text-text-strong'
              }`}
            >
              {tab === 'console' ? 'Console' : tab === 'inspector' ? 'Write Inspector' : tab === 'recall' ? 'Recall Viewer' : 'Graph'}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto p-6 bg-bg-page">
          {activeTab === 'console' && (
            <div className="flex gap-4 h-full">
              <div className="w-1/3 border-r pr-4 h-full overflow-y-auto">
                <input type="search" placeholder="Search memory..." className="w-full p-2 mb-4 border rounded text-sm" />
                <div className="flex flex-col gap-2">
                  {entries.map((e, i) => (
                    <div key={i} className="p-3 bg-white border rounded shadow-sm text-xs cursor-pointer hover:border-brand-300">
                      <div className="font-semibold text-brand-600 mb-1">{e.type}</div>
                      <div className="truncate text-text-normal">{e.content}</div>
                    </div>
                  ))}
                  {entries.length === 0 && <div className="text-text-muted text-sm text-center mt-10">{t('暂无记忆条目。', 'No entries found.')}</div>}
                </div>
              </div>
              <div className="flex-1 pl-4">
                <h3 className="font-semibold text-text-strong mb-4">{t('条目详情', 'Entry Detail')}</h3>
                <div className="p-4 bg-white rounded border text-sm text-text-normal">{t('选择一个条目查看详情。', 'Select an entry to view details.')}</div>
              </div>
            </div>
          )}
          {activeTab === 'inspector' && <div className="text-text-muted text-center mt-20">Loading decisions...</div>}
          {activeTab === 'recall' && <div className="text-text-muted text-center mt-20">Loading recall runs...</div>}
          {activeTab === 'graph' && <div className="text-text-muted text-center mt-20">Loading graph data...</div>}
        </div>
      </div>
    </div>
  );
}

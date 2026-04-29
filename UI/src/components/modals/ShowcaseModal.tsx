import { useLanguage } from '../../store/LanguageContext';

export default function ShowcaseModal({ onClose }: { onClose: () => void }) {
  const { t } = useLanguage();
  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[800px] overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 flex justify-between items-center bg-gray-50/50">
          <h2 className="text-lg font-bold text-text-strong">{t('开源展示', 'Open Source Showcase')}</h2>
          <button onClick={onClose} className="text-2xl leading-none text-text-muted hover:text-text-strong">&times;</button>
        </div>
        <div className="p-6">
          <p className="text-sm text-text-muted mb-6">{t('用于演示、上手和发布说明的产品场景。', 'Product release scenarios for demos, onboarding, and launch announcements.')}</p>
          <div className="grid grid-cols-3 gap-4">
            <ShowcaseCard title="Runtime Health" desc="Show gateway, memory, tools, and policy status." cmd="promethea doctor run" />
            <ShowcaseCard title="Reasoning Visual" desc="Demonstrate ToT/ReAct visibility, steer, and stop controls." cmd="promethea reasoning list" />
            <ShowcaseCard title="Memory + Trust" desc="Show recall traces, write decisions, and workflow." cmd="promethea memory recall-runs" />
          </div>
        </div>
      </div>
    </div>
  );
}

function ShowcaseCard({ title, desc, cmd }: any) {
  return (
    <div className="p-4 border border-black/5 rounded-xl bg-gray-50 flex flex-col gap-2">
      <h3 className="font-semibold text-text-strong">{title}</h3>
      <p className="text-xs text-text-muted h-10">{desc}</p>
      <pre className="text-[10px] p-2 bg-black/5 rounded font-mono text-brand-600 mt-auto">{cmd}</pre>
    </div>
  );
}

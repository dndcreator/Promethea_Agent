import { confirmToolCall } from '../../services/api';
import { useLanguage } from '../../store/LanguageContext';

interface ConfirmModalProps {
  toolName: string;
  toolArgs: string;
  sessionId: string;
  toolCallId: string;
  onClose: (approved: boolean) => void;
}

export default function ConfirmModal({ toolName, toolArgs, sessionId, toolCallId, onClose }: ConfirmModalProps) {
  const { t } = useLanguage();
  const handleAction = async (action: 'approve' | 'reject') => {
    try {
      await confirmToolCall(sessionId, toolCallId, action);
      onClose(action === 'approve');
    } catch (error) {
      console.error(error);
      onClose(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-[9999] flex items-center justify-center p-8">
      <div className="bg-white rounded-2xl shadow-xl w-[500px] overflow-hidden">
        <div className="px-6 py-4 border-b border-black/5 bg-red-50/50">
          <h2 className="text-lg font-bold text-red-600">{t('敏感操作确认', 'Sensitive Action Confirmation')}</h2>
        </div>
        <div className="p-6 flex flex-col gap-4">
          <p className="text-sm text-text-strong">{t('Agent 请求你批准此操作：', 'The agent requests approval for this action:')}</p>
          <div className="bg-gray-50 rounded-xl p-4 border border-black/5 font-mono text-xs overflow-x-auto whitespace-pre-wrap">
            <span className="font-bold text-brand-600 mb-2 block">{toolName}</span>
            <span className="text-text-normal">{toolArgs}</span>
          </div>
          <div className="flex justify-end gap-3 mt-4">
            <button onClick={() => handleAction('reject')} className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-sm font-medium rounded-lg text-text-normal">{t('拒绝', 'Reject')}</button>
            <button onClick={() => handleAction('approve')} className="px-4 py-2 bg-red-500 hover:bg-red-600 text-sm font-medium rounded-lg text-white">{t('批准', 'Approve')}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

import { confirmToolCall } from '../../services/api';
import { useRef, useState } from 'react';
import { useLanguage } from '../../store/LanguageContext';

interface ConfirmModalProps {
  toolName: string;
  toolArgs: string;
  sessionId: string;
  toolCallId: string;
  onClose: (approved: boolean, result: Record<string, any>) => void;
}

export default function ConfirmModal({ toolName, toolArgs, sessionId, toolCallId, onClose }: ConfirmModalProps) {
  const { t } = useLanguage();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submitting = useRef(false);
  const handleAction = async (action: 'approve' | 'reject') => {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError('');
    try {
      const response = await confirmToolCall(sessionId, toolCallId, action);
      const result = await response.json();
      if (!response.ok || !['success', 'ok', 'completed', 'rejected', 'needs_confirmation'].includes(result.status)) {
        throw new Error(result.error_detail?.message || result.detail || result.error || t('操作未完成', 'Operation failed'));
      }
      onClose(action === 'approve', result);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    } finally {
      submitting.current = false;
      setBusy(false);
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
            <button disabled={busy} onClick={() => handleAction('reject')} className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-sm font-medium rounded-lg text-text-normal disabled:opacity-50">{t('拒绝', 'Reject')}</button>
            <button disabled={busy} onClick={() => handleAction('approve')} className="px-4 py-2 bg-red-500 hover:bg-red-600 text-sm font-medium rounded-lg text-white disabled:opacity-50">{busy ? t('处理中', 'Processing') : t('批准', 'Approve')}</button>
          </div>
          {error && <p role="alert" className="break-words text-sm text-red-600">{error}</p>}
        </div>
      </div>
    </div>
  );
}

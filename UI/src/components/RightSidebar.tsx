import { useEffect, useState } from 'react'
import { Info, Play, Square } from 'lucide-react'
import { getActiveReasoning, getReasoningTree, steerReasoningTree, stopReasoningTree } from '../lib/api'
import { useLanguage } from '../store/LanguageContext'

interface RightSidebarProps {
  sessionId: string | null
  treeId: string | null
}

export default function RightSidebar({ sessionId, treeId }: RightSidebarProps) {
  const { t } = useLanguage()
  const [tree, setTree] = useState<any>(null)
  const [steerNote, setSteerNote] = useState('')

  useEffect(() => {
    let interval: number | undefined

    const fetchTree = async () => {
      try {
        let activeTreeId = treeId

        if (!activeTreeId && sessionId) {
          const activeRes = await getActiveReasoning(sessionId)
          if (activeRes.ok) {
            const data = await activeRes.json()
            const items = Array.isArray(data.items) ? data.items : []
            activeTreeId = items[0]?.tree_id || null
          }
        }

        if (activeTreeId) {
          const res = await getReasoningTree(activeTreeId)
          if (res.ok) setTree(await res.json())
        } else {
          setTree(null)
        }
      } catch (error) {
        console.error(error)
      }
    }

    fetchTree()
    interval = window.setInterval(fetchTree, 2000)
    return () => window.clearInterval(interval)
  }, [sessionId, treeId])

  const currentTreeId = tree?.tree_id || tree?.id

  const handleStop = async () => {
    if (currentTreeId) {
      await stopReasoningTree(currentTreeId, 'User stopped via UI')
      setTree((prev: any) => ({ ...prev, status: 'stopped' }))
    }
  }

  const handleSteer = async () => {
    if (currentTreeId && steerNote.trim()) {
      await steerReasoningTree(currentTreeId, steerNote.trim())
      setSteerNote('')
    }
  }

  const nodes = normalizeNodes(tree)
  const isActive = ['running', 'active', 'pending'].includes(String(tree?.status || '').toLowerCase())

  return (
    <aside className="w-[320px] h-full flex flex-col glass-panel rounded-2xl shrink-0 overflow-hidden relative">
      <div className="px-5 py-4 border-b border-black/5 flex items-center justify-between z-10 bg-white/50 backdrop-blur-md shrink-0">
        <h2 className="text-[15px] font-semibold text-text-strong flex items-center gap-2">
          {t('思考追踪', 'Cognitive Trace')}
          <span className="text-xs font-normal text-text-muted">Runtime Trace</span>
        </h2>
        <button type="button" className="text-xs text-brand-600 font-medium px-2 py-1 rounded bg-brand-50 flex items-center gap-1">
          <span className={`w-1.5 h-1.5 rounded-full bg-brand-500 ${isActive ? 'animate-pulse' : ''}`}></span>
          {t('实时模式', 'Live')}
        </button>
      </div>

      <div className="absolute left-0 top-20 bottom-20 w-32 opacity-20 pointer-events-none" style={{
        backgroundImage: 'radial-gradient(circle at 0 50%, #1a73e8 0%, transparent 70%)',
        filter: 'blur(20px)',
      }}></div>

      <div className="flex-1 overflow-y-auto p-5 relative z-10">
        <div className="absolute left-[25px] top-6 bottom-6 w-px bg-brand-100"></div>
        <div className="flex flex-col gap-6">
          {!tree && (
            <div className="flex flex-col items-center justify-center h-full text-center opacity-60 mt-20">
              <Info size={32} className="text-brand-300 mb-2" />
              <p className="text-sm font-medium text-brand-600">{t('暂无活跃思考树', 'No active reasoning tree')}</p>
              <p className="text-xs text-text-muted">{t('发送消息后会在这里显示运行轨迹。', 'Start a chat to view traces.')}</p>
            </div>
          )}

          {nodes.map((node, index) => (
            <TraceItem
              key={node.id}
              time={node.time}
              title={node.title}
              desc={node.desc}
              icon={<div className={`w-2 h-2 rounded-full ${index === nodes.length - 1 && isActive ? 'bg-brand-500 animate-pulse' : 'bg-brand-400'}`}></div>}
              status={index === nodes.length - 1 && isActive ? 'active' : 'done'}
            />
          ))}

          {tree && nodes.length === 0 && (
            <TraceItem
              time={new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
              title={t('初始化', 'Initializing')}
              desc={t('Agent 正在建立思考过程。', 'Agent is setting up the thought process.')}
              icon={<div className="w-2 h-2 rounded-full bg-brand-500 animate-pulse"></div>}
              status="active"
            />
          )}
        </div>
      </div>

      <div className="p-4 border-t border-black/5 bg-white/80 backdrop-blur-xl z-10 shrink-0">
        <h3 className="text-xs font-semibold text-text-strong mb-3 flex items-center justify-between">
          <span className="flex items-center gap-2">
            {t('干预控制', 'Intervention')}
            <span className="text-[10px] font-normal text-text-muted">Control</span>
          </span>
          {currentTreeId && <span className="text-[10px] font-mono text-brand-600 bg-brand-50 px-1 rounded">{String(currentTreeId).slice(0, 6)}</span>}
        </h3>

        {tree && isActive && (
          <div className="flex flex-col gap-2 mb-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={steerNote}
                onChange={(e) => setSteerNote(e.target.value)}
                placeholder={t('引导思考方向...', 'Steer reasoning direction...')}
                className="flex-1 px-3 py-1.5 bg-white border border-black/10 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-brand-500"
              />
              <button
                type="button"
                onClick={handleSteer}
                disabled={!steerNote.trim()}
                className="px-3 py-1.5 bg-brand-50 text-brand-600 rounded-lg text-xs font-medium hover:bg-brand-100 disabled:opacity-50"
              >
                {t('引导', 'Steer')}
              </button>
            </div>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2 mb-2">
          <button type="button" disabled className="flex items-center justify-center gap-1.5 py-2 px-3 bg-white border border-black/5 rounded-lg text-xs font-medium text-text-normal shadow-sm disabled:opacity-50">
            <Play size={14} className="rotate-90" />
            {t('暂停思考', 'Pause')}
          </button>
          <button
            type="button"
            onClick={handleStop}
            disabled={!tree || !isActive}
            className="flex items-center justify-center gap-1.5 py-2 px-3 bg-red-50 border border-red-100 rounded-lg text-xs font-medium text-red-600 hover:bg-red-100 transition-colors shadow-sm disabled:opacity-50 disabled:grayscale"
          >
            <Square size={14} />
            {t('停止任务', 'Stop')}
          </button>
        </div>
        <p className="text-[10px] text-text-muted mt-2 text-center">
          {t('在关键节点进行干预，影响 Agent 的后续行为。', 'Intervene at key steps to affect later agent behavior.')}
        </p>
      </div>
    </aside>
  )
}

type NormalizedTraceNode = {
  id: string
  title: string
  desc: string
  time: string
}

function normalizeNodes(tree: any): NormalizedTraceNode[] {
  const rawNodes = Array.isArray(tree?.nodes) ? tree.nodes : Object.values(tree?.nodes || {})
  return rawNodes.map((node: any, index: number): NormalizedTraceNode => {
    const title = node.title || node.kind || node.action || `Step ${index + 1}`
    const output = typeof node.output === 'string' ? node.output : node.output ? JSON.stringify(node.output) : ''
    const desc = node.observation || node.decision || node.thought || output || node.status || 'Processing...'
    const timestamp = node.created_at || node.updated_at
    return {
      id: node.node_id || node.id || `${index}`,
      title,
      desc,
      time: timestamp
        ? new Date(Number(timestamp) * (Number(timestamp) < 10000000000 ? 1000 : 1)).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
        : new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    }
  })
}

function TraceItem({ time, title, desc, icon, status }: any) {
  return (
    <div className="relative pl-10 opacity-100">
      <div className={`absolute left-0 top-1 w-6 h-6 rounded-full flex items-center justify-center bg-white border z-10 shadow-sm ${
        status === 'active' ? 'border-brand-500 shadow-[0_0_10px_rgba(26,115,232,0.3)]' : 'border-brand-100 text-brand-600 text-xs font-bold'
      }`}>
        {icon}
      </div>
      <div className="flex items-start justify-between mb-1">
        <h4 className={`text-sm font-semibold ${status === 'active' ? 'text-brand-600' : 'text-text-strong'} truncate max-w-[150px]`}>
          {title}
        </h4>
        <span className="text-[10px] text-text-muted font-mono shrink-0">{time}</span>
      </div>
      <p className="text-xs text-text-muted leading-relaxed line-clamp-3">{desc}</p>
    </div>
  )
}

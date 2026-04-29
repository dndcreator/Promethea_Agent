import ReactFlow, { Background, Edge, Handle, MarkerType, Node, Position } from 'reactflow'
import 'reactflow/dist/style.css'
import { CheckCircle, Database, Eye, MessageSquare, Target } from 'lucide-react'

const CustomNode = ({ data }: any) => (
  <div className={`px-4 py-3 shadow-lg rounded-2xl bg-white border ${data.active ? 'border-brand-300 ring-2 ring-brand-100' : 'border-gray-100'} w-[280px]`}>
    <Handle type="target" position={Position.Left} className="opacity-0" />
    <div className="flex items-center justify-between mb-2">
      <div className="flex items-center gap-2">
        <div className={`w-6 h-6 rounded-full flex items-center justify-center ${data.iconBg} ${data.iconColor}`}>
          {data.icon}
        </div>
        <span className="font-bold text-text-strong text-sm">{data.title}</span>
      </div>
      <span className="text-[10px] text-text-muted font-mono">{data.time}</span>
    </div>
    <p className="text-xs text-text-muted">{data.desc}</p>
    {data.children && <div className="mt-3">{data.children}</div>}
    <Handle type="source" position={Position.Right} className="opacity-0" />
    <Handle type="source" position={Position.Bottom} className="opacity-0" id="b" />
    <Handle type="target" position={Position.Top} className="opacity-0" id="t" />
  </div>
)

const nodeTypes = { custom: CustomNode }

const memoryCard = (text: string, source: string, score: string) => (
  <div className="bg-gray-50 p-2 rounded-lg text-[10px]">
    <div className="font-medium text-text-strong mb-1">{text}</div>
    <div className="flex justify-between text-text-muted">
      <span>{source}</span>
      <span className="text-green-600 font-mono">{score}</span>
    </div>
  </div>
)

const initialNodes: Node[] = [
  {
    id: 'plan',
    type: 'custom',
    position: { x: 50, y: 50 },
    data: {
      title: 'Plan · 制定计划',
      time: '10:21:02',
      desc: '理解需求，拆解核心目标，确定执行方向。',
      icon: <Target size={12} />,
      iconBg: 'bg-blue-50',
      iconColor: 'text-blue-600',
    },
  },
  {
    id: 'mem1',
    type: 'custom',
    position: { x: 50, y: 180 },
    data: {
      title: 'Memory 命中',
      time: '10:21:03',
      desc: '',
      icon: <Database size={12} />,
      iconBg: 'bg-green-50',
      iconColor: 'text-green-600',
      children: memoryCard('用户偏好三栏布局的界面', '来源: User Profile', '置信度 0.92'),
    },
  },
  {
    id: 'mem2',
    type: 'custom',
    position: { x: 400, y: 180 },
    data: {
      title: 'Memory 命中',
      time: '10:21:03',
      desc: '',
      icon: <Database size={12} />,
      iconBg: 'bg-green-50',
      iconColor: 'text-green-600',
      children: memoryCard('Promethea 是 protocol-first 的 Agent Console', '来源: Project Knowledge', '置信度 0.88'),
    },
  },
  {
    id: 'obs',
    type: 'custom',
    position: { x: 150, y: 320 },
    data: {
      title: 'Observation · 观察分析',
      time: '10:21:04',
      desc: '突出思考过程的可视化与可干预性。',
      icon: <Eye size={12} />,
      iconBg: 'bg-purple-50',
      iconColor: 'text-purple-600',
    },
  },
  {
    id: 'dec',
    type: 'custom',
    position: { x: 150, y: 440 },
    data: {
      title: 'Decision · 决策',
      time: '10:21:05',
      desc: '采用三栏结构：中间主对话，右侧思考追踪，支持干预。',
      icon: <MessageSquare size={12} />,
      iconBg: 'bg-orange-50',
      iconColor: 'text-orange-600',
    },
  },
  {
    id: 'res',
    type: 'custom',
    position: { x: 150, y: 560 },
    data: {
      title: 'Response · 生成响应',
      time: '10:21:06',
      desc: '生成最终回答并同步会话与记忆可见性。',
      icon: <CheckCircle size={12} />,
      iconBg: 'bg-brand-50',
      iconColor: 'text-brand-600',
      active: true,
    },
  },
]

const initialEdges: Edge[] = [
  { id: 'e1', source: 'plan', target: 'mem1', sourceHandle: 'b', targetHandle: 't', animated: true, style: { stroke: '#94a3b8', strokeWidth: 1.5 } },
  { id: 'e2', source: 'plan', target: 'mem2', sourceHandle: 'b', targetHandle: 't', animated: true, style: { stroke: '#94a3b8', strokeWidth: 1.5 } },
  { id: 'e3', source: 'mem1', target: 'obs', sourceHandle: 'b', targetHandle: 't', animated: true, style: { stroke: '#94a3b8', strokeWidth: 1.5 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8' } },
  { id: 'e4', source: 'mem2', target: 'obs', sourceHandle: 'b', targetHandle: 't', animated: true, style: { stroke: '#94a3b8', strokeWidth: 1.5 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8' } },
  { id: 'e5', source: 'obs', target: 'dec', sourceHandle: 'b', targetHandle: 't', animated: true, style: { stroke: '#1a73e8', strokeWidth: 2 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#1a73e8' } },
  { id: 'e6', source: 'dec', target: 'res', sourceHandle: 'b', targetHandle: 't', animated: true, style: { stroke: '#1a73e8', strokeWidth: 2 }, markerEnd: { type: MarkerType.ArrowClosed, color: '#1a73e8' } },
]

export default function AgentGraph() {
  return (
    <div className="w-full h-full relative">
      <ReactFlow
        nodes={initialNodes}
        edges={initialEdges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.5}
        maxZoom={1.5}
        className="bg-transparent"
        nodesDraggable={false}
        nodesConnectable={false}
        zoomOnScroll={false}
        panOnScroll
      >
        <Background color="#cbd5e1" gap={20} size={1} />
      </ReactFlow>
      <div className="absolute inset-0 pointer-events-none" style={{ background: 'radial-gradient(circle at center, transparent 0%, rgba(255,255,255,0.4) 100%)' }}></div>
    </div>
  )
}

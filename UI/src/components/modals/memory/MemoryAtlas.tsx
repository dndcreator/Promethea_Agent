import { useEffect, useMemo, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { useLanguage } from '../../../store/LanguageContext'

type AtlasNode = {
  id: string
  label: string
  content: string
  type: string
  layer: string
  color: string
  radius: number
  x: number
  y: number
  raw: any
  virtual?: boolean
}

type AtlasEdge = {
  id: string
  source: string
  target: string
  type: string
  weight: number
  color: string
}

type Viewport = {
  x: number
  y: number
  scale: number
}

type AtlasViewMode = 'curated' | 'focus' | 'full'

const NODE_COLORS: Record<string, string> = {
  preference: '#7c3aed',
  project_state: '#059669',
  identity: '#111827',
  concept: '#0891b2',
  summary: '#16a34a',
  message: '#475569',
  entity: '#2563eb',
  action: '#f97316',
  time: '#db2777',
  location: '#0f766e',
  memory: '#64748b',
}

const EDGE_COLORS: Record<string, string> = {
  from_message: '#7c3aed',
  part_of_session: '#94a3b8',
  owned_by: '#94a3b8',
  subject_of: '#2563eb',
  object_of: '#f97316',
  summarizes: '#16a34a',
  similar_to: '#0891b2',
  related: '#475569',
  contains: '#cbd5e1',
}

export default function MemoryAtlas({
  graph,
  onSearch,
}: {
  graph: any
  onSearch: (query: string) => Promise<any>
}) {
  const { t } = useLanguage()
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const wrapperRef = useRef<HTMLDivElement | null>(null)
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, scale: 1 })
  const [hoverId, setHoverId] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [viewMode, setViewMode] = useState<AtlasViewMode>('curated')
  const [dragNodeId, setDragNodeId] = useState('')
  const [panning, setPanning] = useState(false)
  const [busy, setBusy] = useState(false)
  const pointerRef = useRef({ x: 0, y: 0 })

  const atlas = useMemo(() => buildAtlas(graph), [graph])
  const visibleAtlas = useMemo(() => projectAtlas(atlas, viewMode, selectedId, activeQuery), [atlas, viewMode, selectedId, activeQuery])
  const selectedNode = atlas.nodes.find((node) => node.id === selectedId) || null
  const neighborIds = useMemo(() => {
    const center = hoverId || selectedId
    if (!center) return new Set<string>()
    const ids = new Set<string>([center])
    visibleAtlas.edges.forEach((edge) => {
      if (edge.source === center) ids.add(edge.target)
      if (edge.target === center) ids.add(edge.source)
    })
    return ids
  }, [visibleAtlas.edges, hoverId, selectedId])

  useEffect(() => {
    const wrapper = wrapperRef.current
    if (!wrapper) return
    const rect = wrapper.getBoundingClientRect()
    setViewport({ x: rect.width / 2, y: rect.height / 2, scale: 1 })
  }, [visibleAtlas.nodes.length, viewMode])

  useEffect(() => {
    drawAtlas()
  }, [visibleAtlas, viewport, hoverId, selectedId, activeQuery])

  const runSearch = async () => {
    const next = query.trim()
    setBusy(true)
    try {
      await onSearch(next)
      setActiveQuery(next)
      setSelectedId('')
      setHoverId('')
      if (next) setViewMode('focus')
    } finally {
      setBusy(false)
    }
  }

  const resetSearch = async () => {
    setQuery('')
    setActiveQuery('')
    setSelectedId('')
    setHoverId('')
    setViewMode('curated')
    setBusy(true)
    try {
      await onSearch('')
    } finally {
      setBusy(false)
    }
  }

  const canvasPointToWorld = (x: number, y: number) => ({
    x: (x - viewport.x) / viewport.scale,
    y: (y - viewport.y) / viewport.scale,
  })

  const hitNode = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const world = canvasPointToWorld(clientX - rect.left, clientY - rect.top)
    for (let i = visibleAtlas.nodes.length - 1; i >= 0; i -= 1) {
      const node = visibleAtlas.nodes[i]
      const distance = Math.hypot(world.x - node.x, world.y - node.y)
      if (distance <= node.radius + 8) return node
    }
    return null
  }

  const onPointerDown = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const node = hitNode(event.clientX, event.clientY)
    pointerRef.current = { x: event.clientX, y: event.clientY }
    if (node) {
      setSelectedId(node.id)
      if (!node.virtual && viewMode === 'curated') setViewMode('focus')
      setDragNodeId(node.id)
      return
    }
    setPanning(true)
  }

  const onPointerMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const previous = pointerRef.current
    const dx = event.clientX - previous.x
    const dy = event.clientY - previous.y
    pointerRef.current = { x: event.clientX, y: event.clientY }
    if (dragNodeId) {
      const node = visibleAtlas.nodes.find((item) => item.id === dragNodeId)
      if (node) {
        node.x += dx / viewport.scale
        node.y += dy / viewport.scale
        drawAtlas()
      }
      return
    }
    if (panning) {
      setViewport((current) => ({ ...current, x: current.x + dx, y: current.y + dy }))
      return
    }
    const node = hitNode(event.clientX, event.clientY)
    setHoverId(node?.id || '')
  }

  const onPointerUp = () => {
    setDragNodeId('')
    setPanning(false)
  }

  const onWheel = (event: React.WheelEvent<HTMLCanvasElement>) => {
    event.preventDefault()
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const px = event.clientX - rect.left
    const py = event.clientY - rect.top
    const before = canvasPointToWorld(px, py)
    const nextScale = Math.max(0.35, Math.min(2.8, viewport.scale * (event.deltaY > 0 ? 0.9 : 1.1)))
    setViewport({
      scale: nextScale,
      x: px - before.x * nextScale,
      y: py - before.y * nextScale,
    })
  }

  const drawAtlas = () => {
    const canvas = canvasRef.current
    const wrapper = wrapperRef.current
    if (!canvas || !wrapper) return
    const rect = wrapper.getBoundingClientRect()
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.max(1, Math.floor(rect.width * dpr))
    canvas.height = Math.max(1, Math.floor(rect.height * dpr))
    canvas.style.width = `${rect.width}px`
    canvas.style.height = `${rect.height}px`
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, rect.width, rect.height)
    drawBackground(ctx, rect.width, rect.height)
    ctx.save()
    ctx.translate(viewport.x, viewport.y)
    ctx.scale(viewport.scale, viewport.scale)

    const activeNeighbors = neighborIds.size > 0 ? neighborIds : null
    visibleAtlas.edges.forEach((edge) => {
      const source = visibleAtlas.byId.get(edge.source)
      const target = visibleAtlas.byId.get(edge.target)
      if (!source || !target) return
      const dim = activeNeighbors && (!activeNeighbors.has(source.id) || !activeNeighbors.has(target.id))
      const dashed = edge.type === 'contains' || edge.type.includes('from') || edge.type.includes('derived')
      ctx.beginPath()
      ctx.setLineDash(dashed ? [5 / viewport.scale, 7 / viewport.scale] : [])
      ctx.moveTo(source.x, source.y)
      ctx.lineTo(target.x, target.y)
      ctx.strokeStyle = edge.color
      ctx.globalAlpha = edge.type === 'contains' ? 0.28 : dim ? 0.08 : 0.44
      ctx.lineWidth = Math.max(0.8, Math.min(3, 0.7 + edge.weight)) / viewport.scale
      ctx.stroke()
      ctx.setLineDash([])
      if (!dim && edge.type !== 'contains' && viewport.scale > 0.78) drawEdgeLabel(ctx, edge, source, target, viewport.scale)
    })

    visibleAtlas.nodes.forEach((node) => {
      const dim = activeNeighbors && !activeNeighbors.has(node.id)
      const selected = node.id === selectedId
      const hovered = node.id === hoverId
      ctx.globalAlpha = dim ? 0.22 : 1
      ctx.beginPath()
      ctx.arc(node.x, node.y, node.radius + (selected || hovered ? 4 : 0), 0, Math.PI * 2)
      ctx.fillStyle = selected ? '#111827' : node.virtual ? '#ffffff' : node.color
      ctx.shadowColor = node.color
      ctx.shadowBlur = node.virtual ? 13 : selected || hovered ? 18 : 7
      ctx.fill()
      ctx.shadowBlur = 0
      ctx.lineWidth = (node.virtual ? 2.4 : 1.5) / viewport.scale
      ctx.strokeStyle = node.virtual ? node.color : 'rgba(255,255,255,0.86)'
      ctx.stroke()
      const showLabel = node.virtual || selected || hovered || viewport.scale > 0.72 || node.radius > 10
      if (showLabel) {
        ctx.font = `${node.virtual ? 700 : 500} ${Math.max(10, (node.virtual ? 13 : 12) / viewport.scale)}px Inter, system-ui, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = 'rgba(17,24,39,0.88)'
        ctx.globalAlpha = dim ? 0.35 : 0.94
        ctx.fillText(node.label, node.x, node.y + node.radius + 6)
      }
    })
    ctx.restore()
    ctx.globalAlpha = 1
  }

  return (
    <div className="grid h-full grid-cols-[1fr_320px] gap-4">
      <section className="flex min-h-[560px] flex-col overflow-hidden rounded-xl border border-black/5 bg-white shadow-sm">
        <div className="flex flex-wrap items-center gap-2 border-b border-black/5 px-4 py-3">
          <div className="relative min-w-[280px] flex-1">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-muted" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.key === 'Enter' && runSearch()}
              placeholder={t('搜索记忆、概念、项目、偏好...', 'Search memories, concepts, projects, preferences...')}
              className="w-full rounded-xl border border-black/10 bg-bg-page py-2 pl-9 pr-3 text-sm outline-none focus:border-brand-300"
              type="search"
            />
          </div>
          <button type="button" onClick={runSearch} disabled={busy} className="rounded-xl bg-brand-600 px-3 py-2 text-sm font-semibold text-white disabled:opacity-50">
            {busy ? t('搜索中', 'Searching') : t('聚焦', 'Focus')}
          </button>
          {activeQuery && (
            <button type="button" onClick={resetSearch} className="inline-flex items-center gap-1 rounded-xl border border-black/10 px-3 py-2 text-sm text-text-muted">
              <X size={14} />
              {t('清除', 'Clear')}
            </button>
          )}
          <div className="inline-flex rounded-xl border border-black/10 bg-bg-page p-1">
            {(['curated', 'focus', 'full'] as AtlasViewMode[]).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setViewMode(mode)}
                className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold ${viewMode === mode ? 'bg-brand-600 text-white' : 'text-text-muted hover:text-text-strong'}`}
              >
                {mode === 'curated' ? t('主题', 'Atlas') : mode === 'focus' ? t('关联', 'Focus') : t('全量', 'Full')}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => {
              const wrapper = wrapperRef.current
              const rect = wrapper?.getBoundingClientRect()
              setViewport({ x: (rect?.width || 800) / 2, y: (rect?.height || 560) / 2, scale: 1 })
            }}
            className="rounded-xl border border-black/10 px-3 py-2 text-sm text-text-muted"
          >
            {t('重置视图', 'Reset view')}
          </button>
        </div>
        <div className="grid grid-cols-4 gap-2 border-b border-black/5 px-4 py-3 text-xs">
          <AtlasStat label={t('可见节点', 'Visible nodes')} value={visibleAtlas.nodes.length} />
          <AtlasStat label={t('可见关系', 'Visible edges')} value={visibleAtlas.edges.length} />
          <AtlasStat label={t('来源节点', 'Source nodes')} value={graph?.stats?.source_total_nodes || graph?.stats?.total_nodes || graph?.nodes?.length || 0} />
          <AtlasStat label={t('总关系', 'Total edges')} value={graph?.stats?.source_total_edges || graph?.stats?.total_edges || graph?.edges?.length || 0} />
        </div>
        <div ref={wrapperRef} className="relative min-h-0 flex-1 bg-[#f8fafc]">
          <canvas
            ref={canvasRef}
            className="h-full w-full cursor-grab active:cursor-grabbing"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerLeave={() => {
              setHoverId('')
              onPointerUp()
            }}
            onWheel={onWheel}
          />
          {visibleAtlas.nodes.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-sm text-text-muted">
              {t('没有可展示的记忆图。', 'No memory graph to display.')}
            </div>
          )}
        </div>
      </section>
      <aside className="min-h-0 overflow-auto rounded-xl border border-black/5 bg-white p-4 shadow-sm">
        <h3 className="mb-3 text-sm font-semibold text-text-strong">{t('节点详情', 'Node detail')}</h3>
        {selectedNode ? (
          <div className="space-y-3 text-xs">
            <div>
              <div className="mb-1 text-text-muted">{t('类型', 'Type')}</div>
              <div className="font-semibold text-brand-700">{selectedNode.type} · {selectedNode.layer}</div>
            </div>
            <div>
              <div className="mb-1 text-text-muted">{t('内容', 'Content')}</div>
              <p className="break-words leading-6 text-text-normal">{selectedNode.content || selectedNode.label}</p>
            </div>
            <div>
              <div className="mb-1 text-text-muted">{t('连接', 'Connections')}</div>
              <div className="text-text-normal">{countEdges(atlas.edges, selectedNode.id)}</div>
            </div>
            <div className="break-all rounded-lg bg-bg-page p-2 font-mono text-[10px] text-text-muted">{selectedNode.id}</div>
          </div>
        ) : (
          <p className="text-xs leading-6 text-text-muted">
            {t('主题模式展示记忆簇，关联模式只看中心节点周边，全量模式保留完整图。拖动画布、滚轮缩放，点击节点查看详情。', 'Atlas mode shows memory clusters, Focus mode keeps a local neighborhood, and Full mode preserves the whole graph. Drag, zoom, and select nodes for details.')}
          </p>
        )}
      </aside>
    </div>
  )
}

function AtlasStat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-bg-page px-3 py-2">
      <div className="text-[10px] uppercase text-text-muted">{label}</div>
      <div className="mt-1 truncate font-semibold text-text-strong" title={String(value)}>{value}</div>
    </div>
  )
}

function projectAtlas(atlas: ReturnType<typeof buildAtlas>, mode: AtlasViewMode, selectedId: string, activeQuery: string) {
  if (mode === 'full' || atlas.nodes.length <= 0) return atlas
  if (mode === 'focus') return buildFocusProjection(atlas, selectedId || chooseFocusNode(atlas, activeQuery))
  return buildCuratedProjection(atlas)
}

function buildCuratedProjection(atlas: ReturnType<typeof buildAtlas>) {
  const clusters = new Map<string, AtlasNode[]>()
  atlas.nodes.forEach((node) => {
    const key = node.type || node.layer || 'memory'
    const rows = clusters.get(key) || []
    rows.push(node)
    clusters.set(key, rows)
  })
  const rankedClusters = Array.from(clusters.entries())
    .map(([key, nodes]) => ({
      key,
      nodes: nodes.slice().sort((a, b) => countEdges(atlas.edges, b.id) - countEdges(atlas.edges, a.id)),
      score: nodes.length + nodes.reduce((sum, node) => sum + countEdges(atlas.edges, node.id), 0) * 0.2,
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, 7)

  const nodes: AtlasNode[] = []
  const edges: AtlasEdge[] = []
  const kept = new Set<string>()
  const clusterCount = Math.max(1, rankedClusters.length)
  rankedClusters.forEach((cluster, clusterIndex) => {
    const angle = (clusterIndex / clusterCount) * Math.PI * 2 - Math.PI / 2
    const hubDistance = clusterCount <= 1 ? 0 : 210
    const hub: AtlasNode = {
      id: `cluster:${cluster.key}`,
      label: compactLabel(cluster.key.replace(/_/g, ' '), 18),
      content: `${cluster.key} (${cluster.nodes.length})`,
      type: 'cluster',
      layer: 'virtual',
      color: NODE_COLORS[cluster.key] || '#334155',
      radius: Math.max(18, Math.min(30, 16 + cluster.nodes.length * 0.7)),
      x: Math.cos(angle) * hubDistance,
      y: Math.sin(angle) * hubDistance,
      raw: { cluster: cluster.key, count: cluster.nodes.length },
      virtual: true,
    }
    nodes.push(hub)
    cluster.nodes.slice(0, 9).forEach((sourceNode, index) => {
      kept.add(sourceNode.id)
      const orbit = 62 + (index % 3) * 28
      const localAngle = angle + ((index / Math.max(1, Math.min(9, cluster.nodes.length))) - 0.5) * 1.55
      const node = {
        ...sourceNode,
        x: hub.x + Math.cos(localAngle) * orbit,
        y: hub.y + Math.sin(localAngle) * orbit,
      }
      nodes.push(node)
      edges.push({
        id: `${hub.id}:${node.id}`,
        source: hub.id,
        target: node.id,
        type: 'contains',
        weight: 0.7,
        color: EDGE_COLORS.contains,
      })
    })
  })
  atlas.edges.forEach((edge) => {
    if (kept.has(edge.source) && kept.has(edge.target)) edges.push(edge)
  })
  const byId = new Map(nodes.map((node) => [node.id, node]))
  return { nodes, edges: edges.filter((edge) => byId.has(edge.source) && byId.has(edge.target)), byId }
}

function buildFocusProjection(atlas: ReturnType<typeof buildAtlas>, centerId: string) {
  const center = atlas.byId.get(centerId) || atlas.nodes[0]
  if (!center) return atlas
  const first = new Set<string>()
  const second = new Set<string>()
  atlas.edges.forEach((edge) => {
    if (edge.source === center.id) first.add(edge.target)
    if (edge.target === center.id) first.add(edge.source)
  })
  atlas.edges.forEach((edge) => {
    if (first.has(edge.source) && edge.target !== center.id && !first.has(edge.target)) second.add(edge.target)
    if (first.has(edge.target) && edge.source !== center.id && !first.has(edge.source)) second.add(edge.source)
  })
  const rankedFirst = Array.from(first).sort((a, b) => countEdges(atlas.edges, b) - countEdges(atlas.edges, a)).slice(0, 24)
  const rankedSecond = Array.from(second).sort((a, b) => countEdges(atlas.edges, b) - countEdges(atlas.edges, a)).slice(0, 36)
  const keep = new Set<string>([center.id, ...rankedFirst, ...rankedSecond])
  const nodes: AtlasNode[] = []
  nodes.push({ ...center, x: 0, y: 0, radius: Math.max(center.radius + 6, 18) })
  rankedFirst.forEach((id, index) => {
    const node = atlas.byId.get(id)
    if (!node) return
    const angle = (index / Math.max(1, rankedFirst.length)) * Math.PI * 2 - Math.PI / 2
    nodes.push({ ...node, x: Math.cos(angle) * 150, y: Math.sin(angle) * 150 })
  })
  rankedSecond.forEach((id, index) => {
    const node = atlas.byId.get(id)
    if (!node) return
    const angle = (index / Math.max(1, rankedSecond.length)) * Math.PI * 2 + hashToUnit(id)
    nodes.push({ ...node, x: Math.cos(angle) * 285, y: Math.sin(angle) * 285 })
  })
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const edges = atlas.edges.filter((edge) => keep.has(edge.source) && keep.has(edge.target) && byId.has(edge.source) && byId.has(edge.target))
  return { nodes, edges, byId }
}

function chooseFocusNode(atlas: ReturnType<typeof buildAtlas>, activeQuery: string) {
  const query = activeQuery.trim().toLowerCase()
  const candidates = query
    ? atlas.nodes.filter((node) => `${node.label} ${node.content} ${node.type}`.toLowerCase().includes(query))
    : atlas.nodes
  const pool = candidates.length ? candidates : atlas.nodes
  return pool.slice().sort((a, b) => countEdges(atlas.edges, b.id) - countEdges(atlas.edges, a.id))[0]?.id || ''
}

function buildAtlas(graph: any) {
  const sourceNodes = Array.isArray(graph?.nodes) ? graph.nodes : []
  const sourceEdges = Array.isArray(graph?.edges) ? graph.edges : []
  const degree = new Map<string, number>()
  sourceEdges.forEach((edge: any) => {
    const source = String(edge.source || edge.from || edge.source_id || '')
    const target = String(edge.target || edge.to || edge.target_id || '')
    if (!source || !target) return
    degree.set(source, (degree.get(source) || 0) + 1)
    degree.set(target, (degree.get(target) || 0) + 1)
  })
  const nodes: AtlasNode[] = sourceNodes.map((node: any, index: number) => {
    const id = String(node.id || node.memory_id || node.node_id || `node-${index + 1}`)
    const type = normalizeNodeType(node)
    const layer = normalizeLayer(node)
    const importance = Number(node.importance || 0.5)
    const nodeDegree = degree.get(id) || 0
    const ring = layer === 'hot' ? 160 : layer === 'warm' ? 245 : layer === 'cold' ? 330 : 390
    const angle = (index / Math.max(1, sourceNodes.length)) * Math.PI * 2 + hashToUnit(id) * 0.9
    const radiusOffset = (hashToUnit(`${id}:r`) - 0.5) * 75
    return {
      id,
      label: compactLabel(node.label || node.title || node.content || node.text || id, 22),
      content: String(node.label || node.title || node.content || node.text || id),
      type,
      layer,
      color: NODE_COLORS[type] || NODE_COLORS.memory,
      radius: Math.max(5, Math.min(18, 6 + nodeDegree * 0.9 + importance * 5)),
      x: Math.cos(angle) * (ring + radiusOffset),
      y: Math.sin(angle) * (ring + radiusOffset),
      raw: node,
    }
  })
  const byId = new Map(nodes.map((node) => [node.id, node]))
  const edges: AtlasEdge[] = sourceEdges.map((edge: any, index: number) => {
    const source = String(edge.source || edge.from || edge.source_id || '')
    const target = String(edge.target || edge.to || edge.target_id || '')
    const type = normalizeEdgeType(edge)
    return {
      id: String(edge.id || `${source}-${target}-${index}`),
      source,
      target,
      type,
      weight: Number(edge.weight || edge.score || 1),
      color: EDGE_COLORS[type] || EDGE_COLORS.related,
    }
  }).filter((edge: AtlasEdge) => byId.has(edge.source) && byId.has(edge.target))
  return { nodes, edges, byId }
}

function drawBackground(ctx: CanvasRenderingContext2D, width: number, height: number) {
  const gradient = ctx.createRadialGradient(width / 2, height / 2, 20, width / 2, height / 2, Math.max(width, height) * 0.72)
  gradient.addColorStop(0, '#ffffff')
  gradient.addColorStop(1, '#eef2f7')
  ctx.fillStyle = gradient
  ctx.fillRect(0, 0, width, height)
}

function drawEdgeLabel(ctx: CanvasRenderingContext2D, edge: AtlasEdge, source: AtlasNode, target: AtlasNode, scale: number) {
  const label = compactLabel(edge.type.replace(/_/g, ' '), 18)
  if (!label || label === 'related') return
  const x = (source.x + target.x) / 2
  const y = (source.y + target.y) / 2
  ctx.save()
  ctx.font = `${Math.max(8, 10 / scale)}px Inter, system-ui, sans-serif`
  const width = ctx.measureText(label).width + 10 / scale
  const height = 16 / scale
  ctx.fillStyle = 'rgba(255,255,255,0.78)'
  ctx.strokeStyle = 'rgba(148,163,184,0.35)'
  ctx.lineWidth = 1 / scale
  roundRect(ctx, x - width / 2, y - height / 2, width, height, 7 / scale)
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle = 'rgba(71,85,105,0.78)'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label, x, y + 0.5 / scale)
  ctx.restore()
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, width: number, height: number, radius: number) {
  const r = Math.min(radius, width / 2, height / 2)
  ctx.beginPath()
  ctx.moveTo(x + r, y)
  ctx.arcTo(x + width, y, x + width, y + height, r)
  ctx.arcTo(x + width, y + height, x, y + height, r)
  ctx.arcTo(x, y + height, x, y, r)
  ctx.arcTo(x, y, x + width, y, r)
  ctx.closePath()
}

function normalizeLayer(node: any) {
  const raw = node?.layer ?? node?.source_layer ?? node?.memory_layer ?? ''
  if (raw === 0 || raw === '0') return 'hot'
  if (raw === 1 || raw === '1') return 'warm'
  if (raw === 2 || raw === '2') return 'cold'
  const text = String(raw || '').trim().toLowerCase()
  if (['hot', 'warm', 'cold'].includes(text)) return text
  if (['direct', 'recent', 'raw_log', 'message'].includes(text)) return 'hot'
  if (['concept', 'related', 'semantic', 'token'].includes(text)) return 'warm'
  if (['summary', 'archive', 'long_term'].includes(text)) return 'cold'
  return 'other'
}

function normalizeNodeType(node: any) {
  const raw = String(node?.memory_type || node?.type || node?.node_type || node?.role || 'memory').trim().toLowerCase()
  if (raw.includes('project')) return 'project_state'
  if (raw.includes('prefer')) return 'preference'
  if (raw.includes('identity')) return 'identity'
  if (raw.includes('concept')) return 'concept'
  if (raw.includes('summary')) return 'summary'
  if (raw.includes('message')) return 'message'
  if (raw.includes('entity')) return 'entity'
  if (raw.includes('action')) return 'action'
  if (raw.includes('time')) return 'time'
  if (raw.includes('location')) return 'location'
  return raw || 'memory'
}

function normalizeEdgeType(edge: any) {
  return String(edge?.relation || edge?.type || edge?.edge_type || edge?.label || 'related').trim().toLowerCase()
}

function compactLabel(value: unknown, maxLength: number) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= maxLength) return text || '-'
  return `${text.slice(0, Math.max(1, maxLength - 1))}...`
}

function hashToUnit(value: string) {
  let hash = 0
  for (let i = 0; i < value.length; i += 1) {
    hash = (hash * 31 + value.charCodeAt(i)) >>> 0
  }
  return (hash % 1000) / 1000
}

function countEdges(edges: AtlasEdge[], nodeId: string) {
  return edges.filter((edge) => edge.source === nodeId || edge.target === nodeId).length
}

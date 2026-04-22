class MemoryGraphVisualization {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.modal = document.getElementById('memoryGraphModal');
        this.closeBtn = this.modal.querySelector('.close-modal');
        this.graphCanvas = document.getElementById('graphCanvas');
        this.graphStats = document.getElementById('graphStats');
        this.searchInput = document.getElementById('memorySearchInput');
        this.layerFilter = document.getElementById('memoryLayerFilter');
        this.typeFilter = document.getElementById('memoryTypeFilter');
        this.nodeList = document.getElementById('memoryNodeList');
        this.nodeDetail = document.getElementById('memoryNodeDetail');
        this.nodeCount = document.getElementById('memoryNodeCount');
        this.openNeo4jBtn = document.getElementById('memoryOpenNeo4jBtn');
        this.refreshBtn = document.getElementById('memoryRefreshBtn');
        this.clusterBtn = document.getElementById('memoryClusterBtn');
        this.summarizeBtn = document.getElementById('memorySummarizeBtn');
        this.decayBtn = document.getElementById('memoryDecayBtn');
        this.cleanupBtn = document.getElementById('memoryCleanupBtn');
        this.viewModeSelect = document.getElementById('memoryViewMode');
        this.importanceRange = document.getElementById('memoryImportanceRange');
        this.importanceValue = document.getElementById('memoryImportanceValue');
        this.hideWeakSignals = document.getElementById('memoryHideWeakSignals');

        this.currentSessionId = null;
        this.rawNodes = [];
        this.rawEdges = [];
        this.filteredNodes = [];
        this.filteredEdges = [];
        this.selectedNodeId = null;
        this.simulation = null;
        this.svg = null;
        this.graphLayer = null;
        this.viewMode = String(this.viewModeSelect?.value || 'network');

        this.bindEvents();
    }

    bindEvents() {
        this.closeBtn.addEventListener('click', () => this.hide());
        this.modal.addEventListener('click', (event) => {
            if (event.target === this.modal) this.hide();
        });

        this.searchInput?.addEventListener('input', () => this.applyFilters());
        this.layerFilter?.addEventListener('change', () => this.applyFilters());
        this.typeFilter?.addEventListener('change', () => this.applyFilters());
        this.openNeo4jBtn?.addEventListener('click', () => this.openNeo4jBrowser());
        this.refreshBtn?.addEventListener('click', () => this.refreshGraph());
        this.clusterBtn?.addEventListener('click', () => this.runMemoryAction('cluster', 'ui_memory_cluster'));
        this.summarizeBtn?.addEventListener('click', () => this.runMemoryAction('summarize', 'ui_memory_summary'));
        this.decayBtn?.addEventListener('click', () => this.runMemoryAction('decay', 'ui_memory_decay'));
        this.cleanupBtn?.addEventListener('click', () => this.runMemoryAction('cleanup', 'ui_memory_cleanup'));
        this.viewModeSelect?.addEventListener('change', () => {
            this.viewMode = String(this.viewModeSelect?.value || 'network');
            this.renderGraph(this.filteredNodes, this.filteredEdges);
        });
        this.importanceRange?.addEventListener('input', () => {
            this.updateImportanceValue();
            this.applyFilters();
        });
        this.hideWeakSignals?.addEventListener('change', () => this.applyFilters());
    }
    
    async show(sessionId) {
        this.currentSessionId = sessionId || null;
        this.modal.style.display = 'flex';
        this.updateImportanceValue();
        await this.refreshGraph();
    }

    hide() {
        this.modal.style.display = 'none';
        if (this.simulation) {
            this.simulation.stop();
            this.simulation = null;
        }
    }

    async refreshGraph() {
        this.graphStats.innerHTML = `<p>${t("memory_loading")}</p>`;
        this.graphCanvas.innerHTML = '';
        this.nodeList.innerHTML = '';
        this.nodeDetail.textContent = t("memory_select_detail");
        this.nodeCount.textContent = '0';

        try {
            const graphUrl = this.currentSessionId
                ? `${this.apiBaseUrl}/api/memory/graph/${this.currentSessionId}`
                : `${this.apiBaseUrl}/api/memory/graph`;
            const response = await window.AppHttp.authFetch(graphUrl);
            let data = null;
            try {
                data = await response.json();
            } catch (e) {
                data = null;
            }

            if (!response.ok) {
                const detail = data?.detail || data?.message || `HTTP ${response.status}`;
                this.graphStats.innerHTML = `<p class="error">${t("memory_fail", { msg: detail })}</p>`;
                this.renderStats(data?.stats || null);
                return;
            }

            if (!data || (data.status && data.status !== 'success')) {
                const msg = data?.message || (data?.status === 'disabled' ? t("memory_disabled") : t("auth_failed"));
                this.graphStats.innerHTML = `<p class="thinking-status">${msg}</p>`;
                this.renderStats(data?.stats || null);
                return;
            }

            this.rawNodes = data.nodes || [];
            this.rawEdges = data.edges || [];
            this.populateTypeFilter(this.rawNodes);
            this.renderStats(data.stats || null);
            this.applyFilters();
        } catch (error) {
            this.graphStats.innerHTML = `<p class="error">${t("memory_fail", { msg: error.message })}</p>`;
        }
    }

    populateTypeFilter(nodes) {
        if (!this.typeFilter) return;
        const keepValue = this.typeFilter.value || 'all';
        const types = [...new Set(nodes.map(n => n.type).filter(Boolean))].sort();
        this.typeFilter.innerHTML = `<option value="all">${t("ui_memory_filter_all_types")}</option>`;
        for (const type of types) {
            const opt = document.createElement('option');
            opt.value = type;
            opt.textContent = type;
            this.typeFilter.appendChild(opt);
        }
        this.typeFilter.value = types.includes(keepValue) ? keepValue : 'all';
    }

    applyFilters() {
        const query = (this.searchInput?.value || '').trim().toLowerCase();
        const layer = this.layerFilter?.value || 'all';
        const type = this.typeFilter?.value || 'all';
        const minImportance = Number.parseFloat(this.importanceRange?.value || '0');
        const hideWeak = this.hideWeakSignals ? Boolean(this.hideWeakSignals.checked) : true;

        this.filteredNodes = this.rawNodes.filter((node) => {
            const hitQuery = !query
                || (node.content || '').toLowerCase().includes(query)
                || (node.id || '').toLowerCase().includes(query)
                || (node.type || '').toLowerCase().includes(query);
            const hitLayer = layer === 'all' || String(node.layer) === layer;
            const hitType = type === 'all' || node.type === type;
            const hitImportance = Number(node.importance || 0) >= minImportance;
            const hitWeakSignal = !hideWeak || !this.isWeakSignalNode(node);
            return hitQuery && hitLayer && hitType && hitImportance && hitWeakSignal;
        });

        const nodeSet = new Set(this.filteredNodes.map(n => n.id));
        this.filteredEdges = this.rawEdges.filter((edge) => {
            const source = typeof edge.source === 'object' ? edge.source.id : edge.source;
            const target = typeof edge.target === 'object' ? edge.target.id : edge.target;
            return nodeSet.has(source) && nodeSet.has(target);
        });

        this.renderNodeList(this.filteredNodes);
        this.renderGraph(this.filteredNodes, this.filteredEdges);
        this.nodeCount.textContent = String(this.filteredNodes.length);
    }

    updateImportanceValue() {
        if (!this.importanceValue) return;
        const val = Number.parseFloat(this.importanceRange?.value || '0');
        this.importanceValue.textContent = Number.isFinite(val) ? val.toFixed(2) : '0.00';
    }

    renderStats(stats) {
        if (!stats) {
            stats = { total_nodes: 0, total_edges: 0, layers: { hot: 0, warm: 0, cold: 0 } };
        }
        if (!stats.layers) stats.layers = { hot: 0, warm: 0, cold: 0 };
        this.graphStats.innerHTML = `
            <div class="memory-stat-grid">
                <div class="memory-stat-card">
                    <strong>${t("ui_memory_total_nodes")}</strong>
                    <span>${stats.total_nodes}</span>
                </div>
                <div class="memory-stat-card">
                    <strong>${t("ui_memory_total_edges")}</strong>
                    <span>${stats.total_edges}</span>
                </div>
                <div class="memory-stat-card hot">
                    <strong>${t("ui_memory_hot")}</strong>
                    <span>${stats.layers.hot || 0}</span>
                </div>
                <div class="memory-stat-card warm">
                    <strong>${t("ui_memory_warm")}</strong>
                    <span>${stats.layers.warm || 0}</span>
                </div>
                <div class="memory-stat-card cold">
                    <strong>${t("ui_memory_cold")}</strong>
                    <span>${stats.layers.cold || 0}</span>
                </div>
            </div>
        `;
    }

    isNoisyMemoryNode(node) {
        const text = String(node?.content || '').trim();
        if (!text) return false;
        const lowered = text.toLowerCase();
        const noisySignals = ['traceback', 'exception', 'stack trace', 'tool_call', 'tool_result', 'http status', 'status_code', 'stderr', 'stdout'];
        const hitCount = noisySignals.reduce((acc, s) => acc + (lowered.includes(s) ? 1 : 0), 0);
        return hitCount >= 2 || lowered.startsWith('error:') || lowered.startsWith('failed:');
    }

    isWeakSignalNode(node) {
        if (this.isNoisyMemoryNode(node)) return true;
        const text = String(node?.content || '').trim();
        if (!text) return true;
        const lowered = text.toLowerCase();
        const t = String(node?.type || '').toLowerCase();
        const importance = Number(node?.importance || 0);

        if (/^[-_.,;:!?()\[\]{}]+$/.test(text)) return true;
        if (/^(ok|yes|no|thanks?|收到|好的|嗯|好)$/.test(lowered)) return true;
        if (['entity', 'action', 'time', 'location'].includes(t) && text.length <= 3) return true;
        if (text.length <= 2) return true;
        if (importance < 0.15 && text.length < 8) return true;
        return false;
    }

    readableNodeTitle(node) {
        const type = String(node?.type || '').toLowerCase();
        const content = String(node?.content || '').trim();
        const short = content.length > 80 ? `${content.slice(0, 80)}...` : content;
        if (!content) return `${type || 'node'}(${node?.id || ''})`;
        if (type === 'message') {
            const memoryType = String(node?.memory_type || '').trim();
            if (memoryType) return `[${memoryType}] ${short}`;
            const role = String(node?.role || '').trim();
            if (role) return `[${role}] ${short}`;
            return `[memory] ${short}`;
        }
        if (type === 'entity') return `[entity] ${short}`;
        if (type === 'action') return `[relation] ${short}`;
        if (type === 'concept') return `[concept] ${short}`;
        if (type === 'summary') return `[summary] ${short}`;
        return short;
    }

    renderNodeList(nodes) {
        this.nodeList.innerHTML = '';
        if (!nodes.length) {
            this.nodeList.innerHTML = `<div class="memory-node-item empty">${t("memory_no_data")}</div>`;
            return;
        }

        const sorted = [...nodes].sort((a, b) => (b.importance || 0) - (a.importance || 0));
        for (const node of sorted) {
            const item = document.createElement('button');
            item.className = `memory-node-item layer-${node.layer}`;
            item.dataset.nodeId = node.id;
            item.innerHTML = `
                <div class="memory-node-title">${this.escapeHtml(this.readableNodeTitle(node))}</div>
                <div class="memory-node-meta">
                    <span>${this.escapeHtml(node.type || 'unknown')}</span>
                    <span>imp ${(node.importance || 0).toFixed(2)}</span>
                    <span>acc ${node.access_count || 0}</span>
                </div>
            `;
            item.addEventListener('click', () => this.selectNode(node.id));
            this.nodeList.appendChild(item);
        }
    }

    selectNode(nodeId) {
        this.selectedNodeId = nodeId;
        const node = this.filteredNodes.find(n => n.id === nodeId) || this.rawNodes.find(n => n.id === nodeId);
        if (!node) return;

        const layerName = [t("ui_memory_hot"), t("ui_memory_warm"), t("ui_memory_cold")][node.layer] || `Layer ${node.layer ?? '?'}`;
        const linkedCount = this.rawEdges.filter((edge) => {
            const source = typeof edge.source === 'object' ? edge.source.id : edge.source;
            const target = typeof edge.target === 'object' ? edge.target.id : edge.target;
            return source === nodeId || target === nodeId;
        }).length;

        this.nodeDetail.innerHTML = `
            <div class="memory-detail-row"><span>${t("ui_memory_detail_id")}</span><code>${this.escapeHtml(node.id || '')}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_type")}</span><code>${this.escapeHtml(node.type || '')}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_layer")}</span><code>${layerName}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_importance")}</span><code>${(node.importance || 0).toFixed(3)}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_access")}</span><code>${node.access_count || 0}</code></div>
            <div class="memory-detail-row"><span>${t("ui_memory_detail_edges")}</span><code>${linkedCount}</code></div>
            <div class="memory-detail-content">${this.escapeHtml(node.content || '')}</div>
        `;

        this.nodeList.querySelectorAll('.memory-node-item').forEach((el) => {
            el.classList.toggle('active', el.dataset.nodeId === nodeId);
        });

        if (this.graphLayer) {
            this.graphLayer.selectAll('.memory-node').classed('selected', d => d.id === nodeId);
            this.graphLayer.selectAll('.memory-edge').classed('related', d => {
                const source = typeof d.source === 'object' ? d.source.id : d.source;
                const target = typeof d.target === 'object' ? d.target.id : d.target;
                return source === nodeId || target === nodeId;
            });
        }
        if (this.viewMode === 'mindmap') {
            this.renderGraph(this.filteredNodes, this.filteredEdges);
        }
    }

    renderGraph(nodes, edges) {
        if (String(this.viewMode || 'network') === 'mindmap') {
            return this.renderMindMap(nodes, edges);
        }
        let width = this.graphCanvas.clientWidth;
        let height = this.graphCanvas.clientHeight;
        if (width < 120 || height < 120) {
            const rect = this.graphCanvas.getBoundingClientRect();
            width = Math.max(width, Math.floor(rect.width || 0));
            height = Math.max(height, Math.floor(rect.height || 0));
        }
        if (width < 120 || height < 120) {
            this.graphCanvas.innerHTML = `<div class="memory-empty">${t("memory_loading")}</div>`;
            return;
        }

        if (typeof window.d3 === 'undefined') {
            this.renderGraphFallback(nodes, edges, width, height);
            return;
        }

        d3.select(this.graphCanvas).selectAll('*').remove();
        if (this.simulation) {
            this.simulation.stop();
            this.simulation = null;
        }

        if (!nodes.length) {
            this.graphCanvas.innerHTML = `<div class="memory-empty">${t("memory_no_nodes")}</div>`;
            return;
        }

        const layerColors = { 0: '#ff5a6b', 1: '#f59e0b', 2: '#0ea5e9' };

        const svg = d3.select(this.graphCanvas)
            .append('svg')
            .attr('width', width)
            .attr('height', height);

        const zoomLayer = svg.append('g').attr('class', 'memory-zoom-layer');
        this.graphLayer = zoomLayer;

        svg.call(
            d3.zoom()
                .scaleExtent([0.2, 4])
                .on('zoom', (event) => {
                    zoomLayer.attr('transform', event.transform);
                })
        );

        this.simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(edges).id(d => d.id).distance(95).strength(0.18))
            .force('charge', d3.forceManyBody().strength(-280))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(d => 10 + (d.importance || 0) * 14))
            .force('y', d3.forceY().y(d => {
                const ratio = d.layer === 0 ? 0.75 : d.layer === 1 ? 0.5 : 0.25;
                return height * ratio;
            }).strength(0.2));

        const simulation = this.simulation;

        const link = zoomLayer.append('g')
            .attr('class', 'memory-edges')
            .selectAll('line')
            .data(edges)
            .enter()
            .append('line')
            .attr('class', 'memory-edge')
            .attr('stroke', '#64748b')
            .attr('stroke-opacity', d => Math.min(0.85, 0.18 + ((d.weight || 1) * 0.22)))
            .attr('stroke-width', d => Math.max(1, (d.weight || 1) * 1.4));

        const nodeGroup = zoomLayer.append('g')
            .attr('class', 'memory-nodes')
            .selectAll('g')
            .data(nodes)
            .enter()
            .append('g')
            .attr('class', 'memory-node')
            .on('click', (_, d) => this.selectNode(d.id))
            .call(d3.drag()
                .on('start', dragstarted)
                .on('drag', dragged)
                .on('end', dragended));

        nodeGroup.append('circle')
            .attr('r', d => 12 + (d.importance || 0) * 14)
            .attr('fill', d => layerColors[d.layer] || '#94a3b8')
            .attr('stroke', '#fff')
            .attr('stroke-width', 1.8);

        nodeGroup.append('circle')
            .attr('r', d => 4 + (d.importance || 0) * 4)
            .attr('fill', 'rgba(255,255,255,0.9)');

        nodeGroup.append('text')
            .text(d => (d.content || '').slice(0, 12))
            .attr('x', 0)
            .attr('y', d => -(13 + (d.importance || 0) * 12))
            .attr('text-anchor', 'middle')
            .attr('font-size', '11px')
            .attr('fill', '#1e293b')
            .attr('font-weight', 700)
            .style('paint-order', 'stroke')
            .style('stroke', '#ffffff')
            .style('stroke-width', 4)
            .style('stroke-linecap', 'round')
            .style('stroke-linejoin', 'round');

        nodeGroup.append('title')
            .text(d => `${d.type || 'node'} | ${(d.content || '').slice(0, 120)}`);

        this.simulation.on('tick', () => {
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);

            nodeGroup.attr('transform', d => `translate(${d.x},${d.y})`);
        });

        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }

        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }

        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }

        if (this.selectedNodeId) {
            this.selectNode(this.selectedNodeId);
        }
    }

    renderMindMap(nodes, edges) {
        this.graphCanvas.innerHTML = '';
        this.graphLayer = null;
        if (this.simulation) {
            this.simulation.stop();
            this.simulation = null;
        }
        if (!nodes.length) {
            this.graphCanvas.innerHTML = `<div class="memory-empty">${t("memory_no_nodes")}</div>`;
            return;
        }

        let width = this.graphCanvas.clientWidth;
        let height = this.graphCanvas.clientHeight;
        if (width < 120 || height < 120) {
            const rect = this.graphCanvas.getBoundingClientRect();
            width = Math.max(width, Math.floor(rect.width || 0));
            height = Math.max(height, Math.floor(rect.height || 0));
        }
        if (width < 120 || height < 120) {
            this.graphCanvas.innerHTML = `<div class="memory-empty">${t("memory_loading")}</div>`;
            return;
        }

        const nodesById = new Map(nodes.map((n) => [String(n.id), n]));
        const neighbors = new Map();
        for (const node of nodes) {
            neighbors.set(String(node.id), new Set());
        }
        for (const edge of edges || []) {
            const source = String(typeof edge.source === 'object' ? edge.source?.id : edge.source);
            const target = String(typeof edge.target === 'object' ? edge.target?.id : edge.target);
            if (!nodesById.has(source) || !nodesById.has(target)) continue;
            neighbors.get(source)?.add(target);
            neighbors.get(target)?.add(source);
        }

        const sortedNodes = [...nodes].sort((a, b) => (b.importance || 0) - (a.importance || 0));
        const chooseRoot = () => {
            const summary = sortedNodes.find((x) => String(x.type || '').toLowerCase() === 'summary');
            if (summary) return summary;
            const concept = sortedNodes.find((x) => String(x.type || '').toLowerCase() === 'concept');
            if (concept) return concept;
            return sortedNodes[0];
        };
        const root = chooseRoot();
        const rootId = String(root.id);

        const rank = (node) => {
            const t = String(node?.type || '').toLowerCase();
            const typeScore = t === 'concept' ? 40 : t === 'summary' ? 35 : t === 'entity' ? 20 : t === 'action' ? 18 : t === 'message' ? 10 : 0;
            return typeScore + Number(node?.importance || 0);
        };

        let firstLevel = [...(neighbors.get(rootId) || [])]
            .map((id) => nodesById.get(id))
            .filter(Boolean)
            .sort((a, b) => rank(b) - rank(a))
            .slice(0, 10);
        if (!firstLevel.length) {
            firstLevel = sortedNodes.filter((x) => String(x.id) !== rootId).slice(0, 8);
        }

        const used = new Set([rootId, ...firstLevel.map((x) => String(x.id))]);
        const branches = firstLevel.map((parent) => {
            const pid = String(parent.id);
            const children = [...(neighbors.get(pid) || [])]
                .filter((id) => id !== rootId && !used.has(id))
                .map((id) => nodesById.get(id))
                .filter(Boolean)
                .sort((a, b) => rank(b) - rank(a))
                .slice(0, 4);
            children.forEach((x) => used.add(String(x.id)));
            return { parent, children };
        });

        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('width', String(width));
        svg.setAttribute('height', String(height));
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
        svg.classList.add('memory-mindmap-svg');

        const layerColor = (node) => {
            const layer = Number(node?.layer ?? -1);
            if (layer === 0) return '#ff5a6b';
            if (layer === 1) return '#f59e0b';
            if (layer === 2) return '#0ea5e9';
            return '#64748b';
        };
        const label = (node, max = 28) => {
            const text = this.readableNodeTitle(node);
            return text.length > max ? `${text.slice(0, max)}...` : text;
        };

        const rootPos = { x: Math.max(180, Math.floor(width * 0.28)), y: Math.floor(height * 0.5) };
        const x1 = Math.max(rootPos.x + 220, Math.floor(width * 0.58));
        const x2 = Math.max(x1 + 180, Math.floor(width * 0.84));
        const count = Math.max(1, branches.length);
        const gap1 = height / (count + 1);

        const drawEdge = (from, to, widthScale = 1) => {
            const path = document.createElementNS(ns, 'path');
            const cx1 = Math.floor((from.x + to.x) / 2 - 30);
            const cx2 = Math.floor((from.x + to.x) / 2 + 30);
            path.setAttribute('d', `M ${from.x} ${from.y} C ${cx1} ${from.y}, ${cx2} ${to.y}, ${to.x} ${to.y}`);
            path.setAttribute('fill', 'none');
            path.setAttribute('stroke', '#94a3b8');
            path.setAttribute('stroke-width', String(1.2 + widthScale));
            path.setAttribute('stroke-opacity', '0.8');
            svg.appendChild(path);
        };
        const drawNode = (node, pos, depth) => {
            const group = document.createElementNS(ns, 'g');
            group.classList.add('mindmap-node');
            if (String(node.id) === String(this.selectedNodeId || '')) {
                group.classList.add('selected');
            }
            group.style.cursor = 'pointer';
            group.addEventListener('click', () => this.selectNode(node.id));

            const box = document.createElementNS(ns, 'rect');
            const w = depth === 0 ? 220 : depth === 1 ? 210 : 190;
            const h = 36;
            box.setAttribute('x', String(pos.x - Math.floor(w / 2)));
            box.setAttribute('y', String(pos.y - Math.floor(h / 2)));
            box.setAttribute('rx', '10');
            box.setAttribute('ry', '10');
            box.setAttribute('width', String(w));
            box.setAttribute('height', String(h));
            box.setAttribute('fill', '#ffffff');
            box.setAttribute('stroke', layerColor(node));
            box.setAttribute('stroke-width', depth === 0 ? '2.2' : '1.4');
            group.appendChild(box);

            const text = document.createElementNS(ns, 'text');
            text.setAttribute('x', String(pos.x));
            text.setAttribute('y', String(pos.y + 4));
            text.setAttribute('text-anchor', 'middle');
            text.setAttribute('font-size', depth === 0 ? '13' : '12');
            text.setAttribute('font-weight', depth === 0 ? '700' : '600');
            text.setAttribute('fill', '#1e293b');
            text.textContent = label(node, depth === 0 ? 30 : 26);
            group.appendChild(text);

            const title = document.createElementNS(ns, 'title');
            title.textContent = `${node.type || 'node'}\n${node.content || ''}`;
            group.appendChild(title);

            svg.appendChild(group);
        };

        drawNode(root, rootPos, 0);
        branches.forEach((branch, idx) => {
            const pPos = { x: x1, y: Math.floor(gap1 * (idx + 1)) };
            drawEdge(rootPos, pPos, Number(branch.parent?.importance || 0));
            drawNode(branch.parent, pPos, 1);
            const childCount = Math.max(1, branch.children.length);
            const spread = Math.min(120, 24 * childCount);
            const startY = pPos.y - spread / 2;
            branch.children.forEach((child, cIdx) => {
                const cPos = { x: x2, y: Math.floor(startY + (spread * (cIdx + 0.5)) / childCount) };
                drawEdge(pPos, cPos, Number(child?.importance || 0) * 0.8);
                drawNode(child, cPos, 2);
            });
        });

        this.graphCanvas.appendChild(svg);
    }

    renderGraphFallback(nodes, edges, width, height) {
        this.graphCanvas.innerHTML = '';
        if (!nodes.length) {
            this.graphCanvas.innerHTML = `<div class="memory-empty">${t("memory_no_nodes")}</div>`;
            return;
        }
        const cx = width / 2;
        const cy = height / 2;
        const radius = Math.max(80, Math.min(width, height) * 0.35);
        const byId = new Map(nodes.map((n) => [n.id, n]));
        const pos = new Map();
        nodes.forEach((n, idx) => {
            const angle = (Math.PI * 2 * idx) / Math.max(1, nodes.length);
            pos.set(n.id, {
                x: cx + Math.cos(angle) * radius,
                y: cy + Math.sin(angle) * radius,
            });
        });

        const layerColors = { 0: '#ff5a6b', 1: '#f59e0b', 2: '#0ea5e9' };
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('width', String(width));
        svg.setAttribute('height', String(height));
        svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

        edges.forEach((edge) => {
            const sourceId = typeof edge.source === 'object' ? edge.source?.id : edge.source;
            const targetId = typeof edge.target === 'object' ? edge.target?.id : edge.target;
            const a = pos.get(sourceId);
            const b = pos.get(targetId);
            if (!a || !b || !byId.has(sourceId) || !byId.has(targetId)) return;
            const line = document.createElementNS(ns, 'line');
            line.setAttribute('x1', String(a.x));
            line.setAttribute('y1', String(a.y));
            line.setAttribute('x2', String(b.x));
            line.setAttribute('y2', String(b.y));
            line.setAttribute('stroke', '#64748b');
            line.setAttribute('stroke-opacity', '0.45');
            line.setAttribute('stroke-width', '1.2');
            svg.appendChild(line);
        });

        nodes.forEach((node) => {
            const p = pos.get(node.id);
            if (!p) return;
            const g = document.createElementNS(ns, 'g');
            g.style.cursor = 'pointer';
            g.addEventListener('click', () => this.selectNode(node.id));

            const circle = document.createElementNS(ns, 'circle');
            circle.setAttribute('cx', String(p.x));
            circle.setAttribute('cy', String(p.y));
            circle.setAttribute('r', String(10 + (node.importance || 0) * 8));
            circle.setAttribute('fill', layerColors[node.layer] || '#94a3b8');
            circle.setAttribute('stroke', '#ffffff');
            circle.setAttribute('stroke-width', '1.5');
            g.appendChild(circle);

            const title = document.createElementNS(ns, 'title');
            title.textContent = `${node.type || 'node'} | ${(node.content || '').slice(0, 120)}`;
            g.appendChild(title);

            svg.appendChild(g);
        });

        this.graphCanvas.appendChild(svg);
    }

    onGraphTabVisible() {
        if (!this.modal || this.modal.style.display === 'none') return;
        if (!Array.isArray(this.filteredNodes) || !Array.isArray(this.filteredEdges)) return;
        this.renderGraph(this.filteredNodes, this.filteredEdges);
    }

    async runMemoryAction(action, labelKey) {
        if (!this.currentSessionId) return;
        const label = t(labelKey);

        try {
            const response = await window.AppHttp.authFetch(
                `${this.apiBaseUrl}/api/memory/${action}/${this.currentSessionId}`,
                { method: 'POST' }
            );
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.detail || data.message || `${label} failed`);
            }
            await this.refreshGraph();
        } catch (error) {
            alert(t("memory_action_fail", { label, msg: error.message }));
        }
    }

    openNeo4jBrowser() {
        window.open(`${window.AppHttp.resolveApiBase().replace(':8000', ':7474')}`, '_blank', 'noopener,noreferrer');
    }

    escapeHtml(value) {
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }
}


/**
 * Full Width Topology Explorer & Interactive Graph View.
 *
 * Supports two distinct navigation paradigms without any hardcoding:
 *
 * 1. IP Network (Physical Adjacency Network):
 *    - Undirected physical mesh (99,780 devices, 110,916 physical port links in topoIP.csv).
 *    - Preserves real telecom network classes:
 *      AGG_DISTRICT / AGG_LAYER (Aggregation Router), CORE_PROVINCE / CORE_AREA / CORE_LAYER (Core Router),
 *      SITE_ROUTER (Cell Site Router), GPON_OLT (Optical Line Terminal), SWITCH / ACCESS_LAYER (Access Switch), BRAS (Gateway).
 *    - Physical port connections (interface_port <-> interface_port_relation).
 *    - Focused Ego-Network projection around a focal hub device (1-hop / 2-hop / 3-hop).
 *    - Dynamic Top Hub presets loaded directly from /api/topology/roots (no hardcoding).
 *    - Automatic viewport centering (zoomToFit) on every load.
 *    - Seamless hop-by-hop traversal (walk through all 99,780 devices by double-clicking or re-centering).
 *    - Real-time search across 100% of all 99,780 devices with instant autocomplete.
 *
 * 2. IT Services (Multi-Tier IT Architecture):
 *    - 128,322 nodes across 4 architectural tiers in topoIT/:
 *      Service -> Modules -> Server Instances & Databases -> Storage Volumes.
 *    - Dynamic Top Service presets loaded directly from /api/topology/roots.
 *    - Multi-parent indicator for shared databases/hosts, cycle markers for architectural loops.
 *    - Real-time search across all 2,179 services and 128,322 resources.
 */

import { api } from './api.js';

// Configuration for node resource types and telecom classes
const NODE_CONFIG = {
  // IT Services Tiers
  SERVICE: {
    icon: '🌐',
    color: '#38bdf8',
    glow: 'rgba(56, 189, 248, 0.45)',
    badgeBg: 'rgba(56, 189, 248, 0.15)',
    label: 'Service',
    desc: 'Business Application / Top-Level Service',
  },
  MODULE: {
    icon: '📦',
    color: '#c084fc',
    glow: 'rgba(192, 132, 252, 0.45)',
    badgeBg: 'rgba(192, 132, 252, 0.15)',
    label: 'Module',
    desc: 'Application Component / Microservice Module',
  },
  INSTANCE: {
    icon: '💻',
    color: '#4ade80',
    glow: 'rgba(74, 222, 128, 0.45)',
    badgeBg: 'rgba(74, 222, 128, 0.15)',
    label: 'Host / Server',
    desc: 'Compute Instance / Physical Host Server IP',
  },
  DATABASE: {
    icon: '🗄️',
    color: '#facc15',
    glow: 'rgba(250, 204, 21, 0.45)',
    badgeBg: 'rgba(250, 204, 21, 0.15)',
    label: 'Database',
    desc: 'Relational or In-Memory Database Instance',
  },
  STORAGE: {
    icon: '💾',
    color: '#f472b6',
    glow: 'rgba(244, 114, 182, 0.45)',
    badgeBg: 'rgba(244, 114, 182, 0.15)',
    label: 'Storage',
    desc: 'SAN Storage Volume / Block Storage',
  },

  // IP Network Telecom Classes (from topoIP.csv)
  CORE_PROVINCE: {
    icon: '🌐',
    color: '#ef4444',
    glow: 'rgba(239, 68, 68, 0.5)',
    badgeBg: 'rgba(239, 68, 68, 0.18)',
    label: 'Core Router (Province)',
    desc: 'Provincial Backbone Core Router',
  },
  CORE_AREA: {
    icon: '🌐',
    color: '#ef4444',
    glow: 'rgba(239, 68, 68, 0.5)',
    badgeBg: 'rgba(239, 68, 68, 0.18)',
    label: 'Core Router (Area)',
    desc: 'Regional Backbone Core Router',
  },
  CORE_LAYER: {
    icon: '🌐',
    color: '#ef4444',
    glow: 'rgba(239, 68, 68, 0.5)',
    badgeBg: 'rgba(239, 68, 68, 0.18)',
    label: 'Core Router',
    desc: 'National Backbone Core Router',
  },
  AGG_DISTRICT: {
    icon: '🔀',
    color: '#f59e0b',
    glow: 'rgba(245, 158, 11, 0.5)',
    badgeBg: 'rgba(245, 158, 11, 0.18)',
    label: 'Aggregation Router',
    desc: 'District Metro Aggregation Hub Router',
  },
  AGG_LAYER: {
    icon: '🔀',
    color: '#f59e0b',
    glow: 'rgba(245, 158, 11, 0.5)',
    badgeBg: 'rgba(245, 158, 11, 0.18)',
    label: 'Aggregation Router',
    desc: 'Regional Aggregation Layer Router',
  },
  SITE_ROUTER: {
    icon: '📡',
    color: '#38bdf8',
    glow: 'rgba(56, 189, 248, 0.45)',
    badgeBg: 'rgba(56, 189, 248, 0.15)',
    label: 'Site Router',
    desc: 'Cell Site / BTS Edge Access Router',
  },
  GPON_OLT: {
    icon: '⚡',
    color: '#10b981',
    glow: 'rgba(16, 185, 129, 0.45)',
    badgeBg: 'rgba(16, 185, 129, 0.15)',
    label: 'GPON OLT',
    desc: 'Optical Line Terminal (Broadband Access)',
  },
  SWITCH: {
    icon: '🔌',
    color: '#06b6d4',
    glow: 'rgba(6, 182, 212, 0.45)',
    badgeBg: 'rgba(6, 182, 212, 0.15)',
    label: 'Access Switch',
    desc: 'L2/L3 Access Switch',
  },
  ACCESS_LAYER: {
    icon: '🔌',
    color: '#06b6d4',
    glow: 'rgba(6, 182, 212, 0.45)',
    badgeBg: 'rgba(6, 182, 212, 0.15)',
    label: 'Access Switch',
    desc: 'Access Layer Switch / Concentrator',
  },
  BRAS: {
    icon: '🛡️',
    color: '#a855f7',
    glow: 'rgba(168, 85, 247, 0.5)',
    badgeBg: 'rgba(168, 85, 247, 0.18)',
    label: 'BRAS / BNG',
    desc: 'Broadband Remote Access Server Gateway',
  },
  EDGE_LAYER: {
    icon: '🛰️',
    color: '#ec4899',
    glow: 'rgba(236, 72, 153, 0.45)',
    badgeBg: 'rgba(236, 72, 153, 0.15)',
    label: 'Edge Router',
    desc: 'Multi-Service Edge Router',
  },
  DEVICE: {
    icon: '🔀',
    color: '#fb923c',
    glow: 'rgba(251, 146, 60, 0.45)',
    badgeBg: 'rgba(251, 146, 60, 0.15)',
    label: 'Network Device',
    desc: 'IP Network Router or Switch',
  },
};

function getNodeConfig(type, resourceId = '') {
  const upper = String(type || '').toUpperCase().trim();
  const idUpper = String(resourceId || '').toUpperCase().trim();

  // 1. Direct match on recognized specific types (excluding generic OTHER / DEVICE / UNKNOWN)
  if (NODE_CONFIG[upper] && upper !== 'DEVICE' && upper !== 'OTHER' && upper !== 'UNKNOWN') {
    return NODE_CONFIG[upper];
  }

  // 2. Keyword check on type string
  if (upper.includes('DATA') || upper.includes('DB') || upper.includes('SQL')) return NODE_CONFIG.DATABASE;
  if (upper.includes('INST') || upper.includes('HOST') || upper.includes('VM') || upper.includes('SERVER')) return NODE_CONFIG.INSTANCE;
  if (upper.includes('SERVICE') || upper.includes('APP')) return NODE_CONFIG.SERVICE;
  if (upper.includes('MOD') || upper.includes('COMP')) return NODE_CONFIG.MODULE;
  if (upper.includes('STOR') || upper.includes('SAN') || upper.includes('DISK')) return NODE_CONFIG.STORAGE;
  if (upper.includes('CORE')) return NODE_CONFIG.CORE_LAYER;
  if (upper.includes('AGG')) return NODE_CONFIG.AGG_DISTRICT;
  if (upper.includes('OLT') || upper.includes('XGS') || upper.includes('GPON')) return NODE_CONFIG.GPON_OLT;
  if (upper.includes('SWITCH') || upper.includes('SW') || upper.includes('ACCESS')) return NODE_CONFIG.SWITCH;
  if (upper.includes('BRAS') || upper.includes('BNG')) return NODE_CONFIG.BRAS;
  if (upper.includes('SRT') || upper.includes('SITE')) return NODE_CONFIG.SITE_ROUTER;

  // 3. Telecom naming conventions based on device code / resource ID (e.g. ADC9001ASW03 -> SWITCH)
  if (idUpper.includes('ASW') || idUpper.includes('CSW') || idUpper.includes('DSW') || idUpper.includes('SWITCH')) return NODE_CONFIG.SWITCH;
  if (idUpper.includes('SRT') || idUpper.includes('SITE')) return NODE_CONFIG.SITE_ROUTER;
  if (idUpper.includes('OLT') || idUpper.includes('XGS') || idUpper.includes('GPON')) return NODE_CONFIG.GPON_OLT;
  if (idUpper.includes('AGG')) return NODE_CONFIG.AGG_DISTRICT;
  if (idUpper.includes('BRAS') || idUpper.includes('BNG')) return NODE_CONFIG.BRAS;
  if (idUpper.includes('COR') || idUpper.includes('CR') || idUpper.includes('CORE')) return NODE_CONFIG.CORE_LAYER;

  return NODE_CONFIG[upper] || NODE_CONFIG.DEVICE;
}

export class TopologyInspectorScreen {
  constructor(container) {
    this.container = container;
    this.profileId = 'IT_SERVICES';
    this.metadata = null;
    this.loading = false;

    // Viewport transform
    this.scale = 1.0;
    this.panX = 40;
    this.panY = 60;
    this.isDragging = false;
    this.dragStartX = 0;
    this.dragStartY = 0;

    // Active Projection Graph State (Used for both IP and IT)
    this.currentFocalId = null;
    this.currentDepth = 2;
    this.childLimit = 40;
    this.graphNodes = [];
    this.graphLinks = [];
    this.nodesMap = new Map();
    this.focalNode = null;
    this.selectedNode = null;

    // Dynamic presets loaded straight from /api/topology/roots (no hardcoded arrays!)
    this.dynamicPresets = [];

    // Search debounce timer
    this._searchDebounceTimer = null;
  }

  async init() {
    this._renderBaseLayout();
    this._attachEventListeners();
    await this.loadMetadata();
    await this.loadDynamicPresets();
    await this.loadProjection();
  }

  _renderBaseLayout() {
    this.container.innerHTML = `
      <div class="topo-canvas">
        <div class="topo-graph-viewport">
          <!-- Canonical KPI Banner (dynamically read from metadata API) -->
          <div class="topo-kpi-banner" id="topo-kpi-bar">
            <div class="topo-kpi-group">
              <span class="topo-kpi-pill" id="kpi-profile-pill">Loading Canonical...</span>
              <div class="topo-kpi-item">
                <span class="topo-kpi-label">Nodes:</span>
                <span class="topo-kpi-val" id="kpi-nodes">-</span>
              </div>
              <div class="topo-kpi-item">
                <span class="topo-kpi-label">Edges:</span>
                <span class="topo-kpi-val" id="kpi-edges">-</span>
              </div>
              <div class="topo-kpi-item">
                <span class="topo-kpi-label">Aliases:</span>
                <span class="topo-kpi-val" id="kpi-aliases">-</span>
              </div>
              <div class="topo-kpi-item">
                <span class="topo-kpi-label">Model:</span>
                <span class="topo-kpi-val" id="kpi-model">-</span>
              </div>
            </div>
            <div style="display: flex; align-items: center; gap: 0.75rem;">
              <span style="font-size: 0.7rem; font-family: var(--font-mono); color: var(--text-dim);" id="kpi-version">-</span>
            </div>
          </div>

          <!-- Error Banner (shown only on true failure, no silent mock fallback) -->
          <div class="topo-error-banner" id="topo-error-banner" style="display: none;">
            <span id="topo-error-msg">Failed to load topology</span>
            <button class="btn btn-secondary btn-sm" id="btn-topo-retry" style="margin-left: 1rem;">🔄 Retry</button>
          </div>

          <!-- Top Control & Search Bar -->
          <div class="topo-graph-header">
            <div style="display: flex; align-items: center; gap: 1.25rem; flex-wrap: wrap;">
              <!-- Profile Selector -->
              <div style="display: flex; gap: 0.4rem; align-items: center;">
                <span style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); margin-right: 0.25rem;">Profile:</span>
                <button class="topo-profile-btn active" id="btn-profile-it" data-profile="IT_SERVICES">
                  <span>🌐</span> IT Services
                </button>
                <button class="topo-profile-btn" id="btn-profile-ip" data-profile="IP_NETWORK">
                  <span>🔀</span> IP Network
                </button>
              </div>

              <!-- Search Input with Real-time Autocomplete Dropdown across full dataset -->
              <div class="topo-search-wrapper">
                <input type="text" id="topo-search-input" placeholder="🔍 Search device / service across full network..." class="topo-search-input" autocomplete="off" title="Search all nodes in dataset">
                <div class="topo-search-dropdown" id="topo-search-dropdown" style="display: none;"></div>
              </div>

              <!-- Dynamic Legend Bar based on active Profile -->
              <div id="topo-legend-bar" style="display: flex; align-items: center; gap: 0.85rem; font-size: 0.75rem; color: var(--text-dim); border-left: 1px solid var(--border-subtle); padding-left: 1rem;">
              </div>
            </div>

            <!-- Stats & Fit Controls -->
            <div style="display: flex; align-items: center; gap: 0.75rem;">
              <span class="badge badge-info" id="topo-stats-badge" style="font-family: var(--font-mono); font-size: 0.75rem;">0 nodes</span>
              <button class="btn btn-secondary btn-sm" id="btn-auto-fit" title="Fit topology perfectly to screen">
                <span>⊡</span> Fit View
              </button>
            </div>
          </div>

          <!-- Dynamic Presets & Hop Distance Sub-Bar -->
          <div class="topo-controls-subbar" id="topo-subbar">
            <div style="display: flex; align-items: center; gap: 0.4rem;">
              <span style="font-weight: 700; font-size: 0.72rem; text-transform: uppercase;" id="topo-subbar-title">Presets:</span>
              <div id="topo-subbar-presets" style="display: inline-flex; gap: 0.35rem; flex-wrap: wrap;"></div>
            </div>
            <div style="display: flex; align-items: center; gap: 0.4rem; margin-left: auto;">
              <span style="font-weight: 700; color: var(--text-dim); font-size: 0.72rem; text-transform: uppercase;">Hop Distance:</span>
              <div class="topo-hop-group" id="topo-subbar-hops">
                <button class="topo-hop-btn" data-hop="1">1 Hop</button>
                <button class="topo-hop-btn active" data-hop="2">2 Hops</button>
                <button class="topo-hop-btn" data-hop="3">3 Hops</button>
              </div>
              <span style="font-size: 0.72rem; color: var(--text-dim); margin-left: 0.5rem;" id="topo-subbar-tip">💡 Double-click any node to re-center</span>
            </div>
          </div>

          <!-- Interactive Canvas -->
          <div class="topo-graph-canvas-container" id="topo-canvas-container">
            <svg class="topo-graph-svg" id="topo-graph-svg">
              <defs>
                <filter id="card-shadow" x="-10%" y="-10%" width="130%" height="130%">
                  <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000" flood-opacity="0.5" />
                </filter>
                <filter id="node-active-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="0" stdDeviation="8" flood-color="#38bdf8" flood-opacity="0.8" />
                </filter>
                <filter id="focal-active-glow" x="-20%" y="-20%" width="140%" height="140%">
                  <feDropShadow dx="0" dy="0" stdDeviation="12" flood-color="#f59e0b" flood-opacity="0.75" />
                </filter>
                <marker id="edge-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                  <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="rgba(255,255,255,0.4)" />
                </marker>
              </defs>

              <g id="topo-viewport-g" transform="translate(40, 60) scale(1)">
                <g id="topo-edges-layer"></g>
                <g id="topo-nodes-layer"></g>
              </g>
            </svg>

            <!-- Floating Zoom / Reset HUD -->
            <div class="topo-graph-controls">
              <button class="topo-graph-control-btn" id="btn-zoom-in" title="Zoom In">+</button>
              <button class="topo-graph-control-btn" id="btn-zoom-out" title="Zoom Out">−</button>
              <button class="topo-graph-control-btn" id="btn-zoom-reset" title="Reset 1:1">1:1</button>
              <button class="topo-graph-control-btn" id="btn-zoom-fit" title="Fit Content to View">⊡</button>
            </div>
          </div>

          <!-- Slide-over Node Inspector Drawer -->
          <div class="topo-inspector-drawer" id="topo-inspector-drawer">
            <div class="topo-inspector-header">
              <div style="display: flex; align-items: center; gap: 0.6rem;">
                <span style="font-weight: 700; font-size: 0.95rem; color: var(--text-main);">Node Inspector</span>
                <span class="badge badge-info" id="inspector-badge-type">NODE</span>
              </div>
              <button id="btn-close-drawer" style="background: transparent; border: none; color: var(--text-dim); font-size: 1.25rem; cursor: pointer; padding: 0.25rem 0.5rem; line-height: 1; border-radius: var(--radius-sm); transition: all 0.15s;" title="Close Inspector">✕</button>
            </div>
            <div class="topo-inspector-body" id="topo-inspector-content">
            </div>
          </div>
        </div>
      </div>
    `;

    this._updateLegend();
  }

  _updateLegend() {
    const legendEl = document.getElementById('topo-legend-bar');
    if (!legendEl) return;

    if (this.profileId === 'IP_NETWORK') {
      legendEl.innerHTML = `
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #ef4444;">🌐</span> Core Router</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #f59e0b;">🔀</span> Aggregation</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #38bdf8;">📡</span> Site Router</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #10b981;">⚡</span> GPON OLT</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #06b6d4;">🔌</span> Switch</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #a855f7;">🛡️</span> BRAS</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #fbbf24;">⟲</span> Ring Cycle</span>
      `;
    } else {
      legendEl.innerHTML = `
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #38bdf8;">🌐</span> Service</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #c084fc;">📦</span> Module</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #4ade80;">💻</span> Server (Host)</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #facc15;">🗄️</span> Database</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #f472b6;">💾</span> Storage</span>
        <span style="display: inline-flex; align-items: center; gap: 0.3rem;"><span style="color: #fbbf24;">⟲</span> Loop / Multi</span>
      `;
    }
  }

  async loadDynamicPresets() {
    const titleEl = document.getElementById('topo-subbar-title');
    const tipEl = document.getElementById('topo-subbar-tip');
    const isIp = this.profileId === 'IP_NETWORK';

    if (titleEl) {
      titleEl.textContent = isIp ? 'Core Hubs:' : 'Top Services:';
      titleEl.style.color = isIp ? '#fb923c' : '#38bdf8';
    }
    if (tipEl) {
      tipEl.textContent = isIp
        ? '💡 Double-click any node to re-center graph'
        : '💡 Click service to inspect multi-tier architecture';
    }

    try {
      // Query top 8 real roots by degree / child count directly from the backend (NO HARDCODING)
      const res = await api.getTopologyRoots(this.profileId, 8);
      if (res && res.roots && res.roots.length > 0) {
        this.dynamicPresets = res.roots.map(r => ({
          id: r.resource_id,
          label: `${r.display_name || r.resource_id} (${(r.child_count || 0).toLocaleString()})`,
          type: r.resource_type,
          child_count: r.child_count,
        }));
      } else {
        this.dynamicPresets = [];
      }
    } catch (err) {
      console.warn('Failed to load dynamic presets:', err);
      this.dynamicPresets = [];
    }

    // Default focal ID to the top real root if not set
    if (!this.currentFocalId && this.dynamicPresets.length > 0) {
      this.currentFocalId = this.dynamicPresets[0].id;
    }

    this._renderDynamicPresets();
  }

  _renderDynamicPresets() {
    const container = document.getElementById('topo-subbar-presets');
    if (!container) return;

    if (this.dynamicPresets.length === 0) {
      container.innerHTML = `<span style="color: var(--text-dim); font-size: 0.72rem;">No preset hubs available</span>`;
      return;
    }

    container.innerHTML = this.dynamicPresets.map(p => {
      const cfg = getNodeConfig(p.type, p.id);
      return `
        <button class="topo-preset-chip ${p.id === this.currentFocalId ? 'active' : ''}" data-preset-id="${p.id}" style="font-size: 0.72rem; padding: 0.15rem 0.55rem;">
          <span>${cfg.icon}</span> ${this._escapeHtml(p.label)}
        </button>
      `;
    }).join('');
  }

  _attachEventListeners() {
    const container = document.getElementById('topo-canvas-container');
    const svg = document.getElementById('topo-graph-svg');

    // Pan (Drag)
    container.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      if (e.target.closest('.topo-svg-node')) return;
      this.isDragging = true;
      this.dragStartX = e.clientX - this.panX;
      this.dragStartY = e.clientY - this.panY;
      container.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', (e) => {
      if (!this.isDragging) return;
      this.panX = e.clientX - this.dragStartX;
      this.panY = e.clientY - this.dragStartY;
      this._updateTransform();
    });

    window.addEventListener('mouseup', () => {
      if (this.isDragging) {
        this.isDragging = false;
        container.style.cursor = 'grab';
      }
    });

    // Zoom (Wheel)
    container.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = container.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const zoomFactor = e.deltaY < 0 ? 1.12 : 0.89;
      const newScale = Math.min(Math.max(0.15, this.scale * zoomFactor), 3.0);

      this.panX = mouseX - (mouseX - this.panX) * (newScale / this.scale);
      this.panY = mouseY - (mouseY - this.panY) * (newScale / this.scale);
      this.scale = newScale;
      this._updateTransform();
    }, { passive: false });

    // Zoom Buttons
    document.getElementById('btn-zoom-in')?.addEventListener('click', () => {
      this._zoomStep(1.25);
    });
    document.getElementById('btn-zoom-out')?.addEventListener('click', () => {
      this._zoomStep(0.8);
    });
    document.getElementById('btn-zoom-reset')?.addEventListener('click', () => {
      this.scale = 1.0;
      this.zoomToFit();
    });
    document.getElementById('btn-zoom-fit')?.addEventListener('click', () => {
      this.zoomToFit();
    });
    document.getElementById('btn-auto-fit')?.addEventListener('click', () => {
      this.zoomToFit();
    });

    // Profile Switchers
    document.getElementById('btn-profile-it')?.addEventListener('click', () => {
      this.switchProfile('IT_SERVICES');
    });
    document.getElementById('btn-profile-ip')?.addEventListener('click', () => {
      this.switchProfile('IP_NETWORK');
    });

    // Sub-bar dynamic preset chips delegation
    const presetsContainer = document.getElementById('topo-subbar-presets');
    presetsContainer?.addEventListener('click', (e) => {
      const chip = e.target.closest('[data-preset-id]');
      if (chip) {
        const id = chip.getAttribute('data-preset-id');
        if (id) {
          this.currentFocalId = id;
          this._renderDynamicPresets();
          this.loadProjection();
        }
      }
    });

    // Sub-bar hop distance buttons
    document.querySelectorAll('.topo-hop-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.topo-hop-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const hop = parseInt(btn.getAttribute('data-hop') || '2', 10);
        this.currentDepth = hop;
        this.loadProjection();
      });
    });

    // Retry button on error banner
    document.getElementById('btn-topo-retry')?.addEventListener('click', () => {
      this.loadProjection();
    });

    // Search Input with Real-time autocomplete across 100% of all nodes
    const searchInput = document.getElementById('topo-search-input');
    const dropdown = document.getElementById('topo-search-dropdown');

    if (searchInput && dropdown) {
      searchInput.addEventListener('input', () => {
        clearTimeout(this._searchDebounceTimer);
        const q = searchInput.value.trim();
        if (!q) {
          dropdown.style.display = 'none';
          dropdown.innerHTML = '';
          return;
        }

        this._searchDebounceTimer = setTimeout(async () => {
          try {
            const res = await api.searchTopology(this.profileId, q, 12);
            const results = res?.results || [];
            if (results.length === 0) {
              dropdown.innerHTML = `<div style="padding: 0.75rem; text-align: center; color: var(--text-dim); font-size: 0.75rem;">No matching ${this.profileId === 'IP_NETWORK' ? 'devices' : 'services'} found</div>`;
            } else {
              dropdown.innerHTML = results.map(r => {
                const cfg = getNodeConfig(r.resource_type, r.resource_id);
                return `
                  <div class="topo-search-item" data-search-id="${r.resource_id}">
                    <div class="topo-search-item-left">
                      <span>${cfg.icon}</span>
                      <span class="topo-search-item-name">${this._escapeHtml(r.display_name || r.resource_id)}</span>
                    </div>
                    <span class="topo-search-item-badge" style="color: ${cfg.color}; border: 1px solid ${cfg.color}33;">${this._escapeHtml(cfg.label)}</span>
                  </div>
                `;
              }).join('');
            }
            dropdown.style.display = 'flex';
          } catch (err) {
            console.warn('Search query failed:', err);
          }
        }, 180);
      });

      // Dropdown selection
      dropdown.addEventListener('click', (e) => {
        const item = e.target.closest('[data-search-id]');
        if (item) {
          const selectedId = item.getAttribute('data-search-id');
          dropdown.style.display = 'none';
          searchInput.value = selectedId;
          this.currentFocalId = selectedId;
          this.loadProjection();
        }
      });

      // Close dropdown when clicking outside
      window.addEventListener('click', (e) => {
        if (!e.target.closest('.topo-search-wrapper')) {
          dropdown.style.display = 'none';
        }
      });
    }

    // Close Inspector Drawer
    document.getElementById('btn-close-drawer')?.addEventListener('click', () => {
      this.closeInspector();
    });

    // SVG Node Click: Select node and open drawer
    svg.addEventListener('click', (e) => {
      const nodeEl = e.target.closest('[data-node-id]');
      if (nodeEl) {
        e.stopPropagation();
        const nodeId = nodeEl.getAttribute('data-node-id');
        const node = this.nodesMap.get(nodeId);
        if (node) {
          this.selectNode(node);
        }
      }
    });

    // SVG Node Double Click: Instantly re-center projection graph on clicked node
    svg.addEventListener('dblclick', (e) => {
      const nodeEl = e.target.closest('[data-node-id]');
      if (nodeEl) {
        e.stopPropagation();
        const nodeId = nodeEl.getAttribute('data-node-id');
        if (nodeId) {
          this.currentFocalId = nodeId;
          this.loadProjection();
        }
      }
    });
  }

  _zoomStep(factor) {
    const container = document.getElementById('topo-canvas-container');
    const cx = (container?.clientWidth || 800) / 2;
    const cy = (container?.clientHeight || 600) / 2;
    const newScale = Math.min(Math.max(0.15, this.scale * factor), 3.0);

    this.panX = cx - (cx - this.panX) * (newScale / this.scale);
    this.panY = cy - (cy - this.panY) * (newScale / this.scale);
    this.scale = newScale;
    this._updateTransform();
  }

  _updateTransform() {
    const viewportG = document.getElementById('topo-viewport-g');
    if (viewportG) {
      viewportG.setAttribute('transform', `translate(${this.panX.toFixed(1)}, ${this.panY.toFixed(1)}) scale(${this.scale.toFixed(3)})`);
    }
  }

  async switchProfile(profileId) {
    if (this.profileId === profileId) return;
    this.profileId = profileId;
    this.currentFocalId = null; // Reset to let dynamic presets pick top hub

    document.querySelectorAll('.topo-profile-btn').forEach(btn => {
      btn.classList.toggle('active', btn.getAttribute('data-profile') === profileId);
    });

    this._updateLegend();
    this.closeInspector();
    await this.loadMetadata();
    await this.loadDynamicPresets();
    await this.loadProjection();
  }

  async loadMetadata() {
    try {
      const res = await api.getTopologyMetadata(this.profileId);
      if (res && res.metadata) {
        this.metadata = res.metadata;
        this._renderKpiBanner(res.metadata);
      }
    } catch (err) {
      console.warn('Failed to load topology metadata:', err);
    }
  }

  _renderKpiBanner(meta) {
    const isIt = meta.profile_id === 'IT_SERVICES';
    const profilePill = document.getElementById('kpi-profile-pill');
    const nodesEl = document.getElementById('kpi-nodes');
    const edgesEl = document.getElementById('kpi-edges');
    const aliasesEl = document.getElementById('kpi-aliases');
    const modelEl = document.getElementById('kpi-model');
    const verEl = document.getElementById('kpi-version');

    if (profilePill) {
      profilePill.textContent = isIt ? 'IT Services Canonical Truth' : 'IP Network Canonical Truth';
      profilePill.style.color = isIt ? '#38bdf8' : '#fb923c';
      profilePill.style.borderColor = isIt ? 'rgba(56, 189, 248, 0.4)' : 'rgba(251, 146, 60, 0.4)';
      profilePill.style.background = isIt ? 'rgba(56, 189, 248, 0.12)' : 'rgba(251, 146, 60, 0.12)';
    }
    if (nodesEl) nodesEl.textContent = (meta.stats?.node_count || 0).toLocaleString() + ' nodes';
    if (edgesEl) edgesEl.textContent = (meta.stats?.edge_count || 0).toLocaleString() + ' edges';
    if (aliasesEl) aliasesEl.textContent = (meta.stats?.alias_count || 0).toLocaleString() + ' aliases';
    if (modelEl) {
      const model = meta.capabilities?.relation_model || (isIt ? 'SOURCE_RELATION' : 'PHYSICAL_ADJACENCY');
      const sem = meta.capabilities?.dependency_semantics || (isIt ? 'UNVERIFIED' : 'NONE');
      modelEl.textContent = `${model} · ${sem}`;
    }
    if (verEl) {
      verEl.textContent = meta.canonical_version ? `Canonical: ${meta.canonical_version}` : '';
    }
  }

  // =========================================================================
  // CORE TOPOLOGY PROJECTION ENGINE (Used for both IP Network & IT Services)
  // =========================================================================

  async loadProjection() {
    this.loading = true;
    const statsBadge = document.getElementById('topo-stats-badge');
    const errorBanner = document.getElementById('topo-error-banner');
    const errorMsg = document.getElementById('topo-error-msg');
    if (errorBanner) errorBanner.style.display = 'none';

    const focalId = this.currentFocalId || (this.dynamicPresets[0]?.id || '');
    this.currentFocalId = focalId;

    if (statsBadge) {
      statsBadge.textContent = `Loading ${this.profileId === 'IP_NETWORK' ? 'device network' : 'service architecture'}...`;
    }

    try {
      const res = await api.getTopologyProjection(this.profileId, focalId, this.currentDepth, this.childLimit);
      if (!res || !res.tree) {
        throw new Error(res?.reason || 'Topology projection not available');
      }

      const { nodes, links, nodeMap } = this._flattenProjection(res.tree);
      this.graphNodes = nodes;
      this.graphLinks = links;
      this.nodesMap = nodeMap;
      this.focalNode = nodeMap.get(focalId) || nodes[0];

      this.layoutGraph(nodes, links, this.focalNode);
      this.renderGraph();
      this.zoomToFit(); // Automatically fit and center comfortably on screen!

      if (statsBadge) {
        const canonicalTotal = this.metadata?.stats?.node_count || (this.profileId === 'IP_NETWORK' ? 99780 : 128322);
        const prefix = this.profileId === 'IP_NETWORK' ? 'Focal Hub' : 'Service';
        statsBadge.textContent = `${prefix}: ${focalId} · ${nodes.length} visible units · ${links.length} links · ${canonicalTotal.toLocaleString()} in dataset`;
      }

      this._renderDynamicPresets();
    } catch (err) {
      console.error('Failed to load topology projection:', err);
      if (statsBadge) statsBadge.textContent = 'API Error';
      if (errorBanner && errorMsg) {
        errorMsg.textContent = `⚠️ Topology Error: ${err.message || 'Unable to connect to server'}.`;
        errorBanner.style.display = 'flex';
      }
    } finally {
      this.loading = false;
    }
  }

  _flattenProjection(treeRoot) {
    const nodes = [];
    const links = [];
    const nodeMap = new Map();
    const seenEdges = new Set();

    const walk = (item, parent = null, depth = 0) => {
      if (!item || !item.resource_id) return;
      const rId = item.resource_id;

      let existing = nodeMap.get(rId);
      if (!existing) {
        existing = {
          resource_id: rId,
          display_name: item.display_name || rId,
          resource_type: item.resource_type || (this.profileId === 'IP_NETWORK' ? 'DEVICE' : 'MODULE'),
          depth: depth,
          isFocal: depth === 0,
          childrenCount: (item.children || []).length + (item.hidden_child_count || 0),
          relation_type: item.relation_type,
          reference_kind: item.reference_kind,
          linked_parent_count: item.linked_parent_count || 0,
          source_port: item.source_port,
          target_port: item.target_port,
          connections: [],
        };
        nodeMap.set(rId, existing);
        nodes.push(existing);
      } else if (depth < existing.depth) {
        existing.depth = depth;
      }

      if (parent) {
        const pId = parent.resource_id;
        const edgeKey = [pId, rId].sort().join('<->');
        if (!seenEdges.has(edgeKey)) {
          seenEdges.add(edgeKey);
          links.push({
            source: pId,
            target: rId,
            relation: item.relation_type || (this.profileId === 'IP_NETWORK' ? 'ADJACENT_TO' : 'SOURCE_RELATION'),
            reference_kind: item.reference_kind,
            source_port: item.source_port,
            target_port: item.target_port,
          });
        }

        // Record bidirectional connection for drawer
        const connToChild = {
          targetId: rId,
          relation: item.relation_type || 'CONNECTED',
          source_port: item.source_port,
          target_port: item.target_port,
          dir: '→ Outgoing',
        };
        const connToParent = {
          targetId: pId,
          relation: item.relation_type || 'CONNECTED',
          source_port: item.target_port,
          target_port: item.source_port,
          dir: '← Incoming',
        };
        const pNode = nodeMap.get(pId);
        if (pNode && !pNode.connections.some(c => c.targetId === rId)) pNode.connections.push(connToChild);
        if (!existing.connections.some(c => c.targetId === pId)) existing.connections.push(connToParent);
      }

      if (item.children && item.children.length > 0 && !item.reference_kind) {
        item.children.forEach(c => walk(c, item, depth + 1));
      }
    };

    walk(treeRoot);
    return { nodes, links, nodeMap };
  }

  layoutGraph(nodes, links, focalNode) {
    const cardWidth = 220;
    const cardHeight = 68;
    const slotH = 84;
    const horizontalSpacing = 350;

    // Group nodes by depth
    const depthGroups = {};
    nodes.forEach(n => {
      const d = n.depth || 0;
      if (!depthGroups[d]) depthGroups[d] = [];
      depthGroups[d].push(n);
    });

    const d0 = depthGroups[0] || [focalNode];
    const d1 = depthGroups[1] || [];
    const d2 = depthGroups[2] || [];
    const d3 = depthGroups[3] || [];

    // Sort Level 1 nodes deterministically
    d1.sort((a, b) => a.resource_id.localeCompare(b.resource_id));

    // Depth 0: Focal Root
    if (focalNode) {
      focalNode.x = 60;
    }

    // Depth 1: 1-hop elements
    d1.forEach((node, idx) => {
      node.x = 60 + horizontalSpacing;
      node.y = idx * slotH;
    });

    // Vertically center Depth 0 relative to Depth 1
    if (focalNode) {
      focalNode.y = d1.length > 0
        ? (d1[0].y + d1[d1.length - 1].y) / 2
        : 100;
    }

    // Depth 2: Clustered next to their parents
    let curD2Y = 0;
    const assignedD2 = new Set();

    d1.forEach(pNode => {
      const children = d2.filter(c =>
        !assignedD2.has(c.resource_id) &&
        links.some(l => (l.source === pNode.resource_id && l.target === c.resource_id) || (l.target === pNode.resource_id && l.source === c.resource_id))
      );

      const clusterH = Math.max(1, children.length) * slotH;
      const idealY = Math.max(curD2Y, pNode.y + cardHeight / 2 - clusterH / 2);

      children.forEach((c, idx) => {
        c.x = 60 + horizontalSpacing * 2;
        c.y = idealY + idx * slotH;
        assignedD2.add(c.resource_id);
      });

      if (children.length > 0) {
        curD2Y = idealY + clusterH + 12;
      }
    });

    // Remaining Depth 2 nodes
    d2.filter(c => !assignedD2.has(c.resource_id)).forEach(c => {
      c.x = 60 + horizontalSpacing * 2;
      c.y = curD2Y;
      curD2Y += slotH;
    });

    // Depth 3: Next column
    d3.forEach((node, idx) => {
      node.x = 60 + horizontalSpacing * 3;
      node.y = idx * slotH;
    });

    // Normalize all Y coordinates so the top of the graph is at Y = 60
    let minY = Infinity;
    nodes.forEach(n => {
      if (n.y !== undefined && n.y < minY) minY = n.y;
    });
    if (minY !== Infinity) {
      const shiftY = 60 - minY;
      nodes.forEach(n => {
        n.y = (n.y || 0) + shiftY;
      });
    }
  }

  renderGraph() {
    const edgesLayer = document.getElementById('topo-edges-layer');
    const nodesLayer = document.getElementById('topo-nodes-layer');
    if (!edgesLayer || !nodesLayer) return;

    const cardWidth = 220;
    const cardHeight = 68;
    let edgesHtml = '';
    let nodesHtml = '';

    // 1. Render Edges (Links, Ports, and Cycles)
    this.graphLinks.forEach(link => {
      const p1 = this.nodesMap.get(link.source);
      const p2 = this.nodesMap.get(link.target);
      if (!p1 || !p2) return;

      const isCycle = link.reference_kind === 'CYCLE' || (p1.depth > 0 && p1.depth === p2.depth) || (p1.depth > p2.depth);
      const portInfo = (link.source_port && link.target_port) ? `${link.source_port} ↔ ${link.target_port}` : (link.relation || '');

      if (isCycle) {
        // Redundant Ring Loop (curved amber dashed path)
        const x1 = p1.x + (p1.depth >= p2.depth ? 0 : cardWidth);
        const y1 = p1.y + cardHeight / 2;
        const x2 = p2.x + (p1.depth >= p2.depth ? cardWidth : 0);
        const y2 = p2.y + cardHeight / 2;
        const offset = Math.abs(y2 - y1) < 40 ? 60 : 40;
        const d = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 - offset).toFixed(1)} ${(y1 - 30).toFixed(1)}, ${(x2 + offset).toFixed(1)} ${(y2 + 30).toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;

        edgesHtml += `
          <g class="topo-edge-group" title="Ring Cycle: ${link.source} ⟷ ${link.target}">
            <path class="topo-svg-edge cycle" d="${d}" />
            <path class="topo-svg-edge-hitbox" d="${d}" />
          </g>
        `;
      } else {
        // Forward Directed / Adjacency Link
        const x1 = p1.x + cardWidth;
        const y1 = p1.y + cardHeight / 2;
        const x2 = p2.x;
        const y2 = p2.y + cardHeight / 2;
        const dx = x2 - x1;
        const d = `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${(x1 + dx * 0.5).toFixed(1)} ${y1.toFixed(1)}, ${(x2 - dx * 0.5).toFixed(1)} ${y2.toFixed(1)}, ${x2.toFixed(1)} ${y2.toFixed(1)}`;

        edgesHtml += `
          <g class="topo-edge-group" title="${this._escapeHtml(link.relation)}: ${link.source} ⟷ ${link.target} ${portInfo ? `(${portInfo})` : ''}">
            <path class="topo-svg-edge" d="${d}" stroke="rgba(56, 189, 248, 0.45)" stroke-width="2" />
            <path class="topo-svg-edge-hitbox" d="${d}" />
          </g>
        `;
      }
    });

    // 2. Render Nodes (Service, Module, Server, Database, Storage, or Specific Telecom Router/Switch/OLT)
    this.graphNodes.forEach(node => {
      const isSelected = this.selectedNode?.resource_id === node.resource_id;
      const isFocal = node.isFocal;
      const cfg = getNodeConfig(node.resource_type, node.resource_id);
      const strokeColor = isFocal ? '#f59e0b' : (isSelected ? '#38bdf8' : cfg.color);
      const filterAttr = isFocal ? 'filter="url(#focal-active-glow)"' : (isSelected ? 'filter="url(#node-active-glow)"' : 'filter="url(#card-shadow)"');

      const shortTitle = (node.display_name && node.display_name.length > 18)
        ? node.display_name.substring(0, 17) + '…'
        : (node.display_name || node.resource_id);

      // Top right badge
      let badgeHtml = '';
      if (isFocal) {
        badgeHtml = `<text x="${(node.x + cardWidth - 10).toFixed(1)}" y="${(node.y + 17).toFixed(1)}" font-family="var(--font-mono)" font-size="8" font-weight="800" text-anchor="end" fill="#f59e0b">🎯 CENTER</text>`;
      } else if (node.reference_kind === 'CYCLE') {
        badgeHtml = `<text x="${(node.x + cardWidth - 10).toFixed(1)}" y="${(node.y + 17).toFixed(1)}" font-family="var(--font-mono)" font-size="8" font-weight="700" text-anchor="end" fill="#fbbf24">⟲ CYCLE</text>`;
      } else if (node.reference_kind === 'MULTI_PARENT') {
        badgeHtml = `<text x="${(node.x + cardWidth - 10).toFixed(1)}" y="${(node.y + 17).toFixed(1)}" font-family="var(--font-mono)" font-size="8" font-weight="700" text-anchor="end" fill="#38bdf8">+${node.linked_parent_count || 1} REF</text>`;
      } else {
        badgeHtml = `<text x="${(node.x + cardWidth - 10).toFixed(1)}" y="${(node.y + 17).toFixed(1)}" font-family="var(--font-mono)" font-size="8" font-weight="600" text-anchor="end" fill="#94a3b8">HOP ${node.depth}</text>`;
      }

      // Bottom port connection text if available
      let portLineHtml = '';
      if (node.source_port && node.target_port) {
        const portStr = `${node.target_port}`;
        portLineHtml = `<text x="${(node.x + 48).toFixed(1)}" y="${(node.y + 55).toFixed(1)}" font-family="monospace" font-size="8" fill="#38bdf8">Port: ${this._escapeHtml(portStr.substring(0, 20))}</text>`;
      } else {
        portLineHtml = `<text x="${(node.x + 48).toFixed(1)}" y="${(node.y + 55).toFixed(1)}" font-family="monospace" font-size="8" font-weight="600" fill="${isFocal ? '#f59e0b' : cfg.color}">${node.connections.length} link${node.connections.length === 1 ? '' : 's'}</text>`;
      }

      nodesHtml += `
        <g class="topo-svg-node ${isFocal ? 'is-focal' : ''} ${isSelected ? 'selected' : ''}" data-node-id="${node.resource_id}">
          <!-- Card Base Box -->
          <rect class="node-box" x="${node.x.toFixed(1)}" y="${node.y.toFixed(1)}" width="${cardWidth}" height="${cardHeight}" rx="10"
                fill="#131a29" stroke="${strokeColor}" stroke-width="${isFocal || isSelected ? 2.5 : 1.5}" ${filterAttr} />

          <!-- Left Device Icon Circle -->
          <circle cx="${(node.x + 24).toFixed(1)}" cy="${(node.y + cardHeight / 2).toFixed(1)}" r="15"
                  fill="${cfg.badgeBg}" stroke="${strokeColor}" stroke-width="1.2" />
          <text x="${(node.x + 24).toFixed(1)}" y="${(node.y + cardHeight / 2 + 5).toFixed(1)}"
                font-size="14" text-anchor="middle">${cfg.icon}</text>

          <!-- Node Title Name -->
          <text class="node-title" x="${(node.x + 48).toFixed(1)}" y="${(node.y + 24).toFixed(1)}"
                font-family="system-ui, -apple-system, sans-serif" font-size="12" font-weight="700" fill="#f8fafc">
            ${this._escapeHtml(shortTitle)}
          </text>

          <!-- Subtitle / Exact Role Badge -->
          <text class="node-sub" x="${(node.x + 48).toFixed(1)}" y="${(node.y + 40).toFixed(1)}"
                font-family="monospace" font-size="8.5" font-weight="600" fill="${cfg.color}">
            ${this._escapeHtml(cfg.label.toUpperCase())}
          </text>

          ${portLineHtml}
          ${badgeHtml}
        </g>
      `;
    });

    edgesLayer.innerHTML = edgesHtml;
    nodesLayer.innerHTML = nodesHtml;
  }

  // =========================================================================
  // VIEWPORT CENTERING & ZOOM-TO-FIT (No more tiny, clustered, off-screen nodes!)
  // =========================================================================

  zoomToFit() {
    const container = document.getElementById('topo-canvas-container');
    if (!container || this.graphNodes.length === 0) return;

    const cardWidth = 220;
    const cardHeight = 68;
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    this.graphNodes.forEach(node => {
      minX = Math.min(minX, node.x);
      maxX = Math.max(maxX, node.x + cardWidth);
      minY = Math.min(minY, node.y);
      maxY = Math.max(maxY, node.y + cardHeight);
    });

    if (minX === Infinity) return;

    const graphW = maxX - minX;
    const graphH = maxY - minY;
    const viewW = container.clientWidth - 100;
    const viewH = container.clientHeight - 100;

    // Scale comfortably so small 2-node graphs stay at 100% (1.0) and large 80-node graphs scale down gracefully
    const scaleX = viewW / Math.max(graphW, 100);
    const scaleY = viewH / Math.max(graphH, 100);
    this.scale = Math.min(1.0, Math.max(0.35, Math.min(scaleX, scaleY)));

    // Center both horizontally and vertically
    this.panX = (container.clientWidth - graphW * this.scale) / 2 - minX * this.scale;
    this.panY = (container.clientHeight - graphH * this.scale) / 2 - minY * this.scale;

    this._updateTransform();
  }

  centerOnNode(node) {
    const container = document.getElementById('topo-canvas-container');
    const cw = container?.clientWidth || 800;
    const ch = container?.clientHeight || 600;
    const cardWidth = 210;
    const cardHeight = 60;

    this.panX = cw / 2 - (node.x + cardWidth / 2) * this.scale;
    this.panY = ch / 2 - (node.y + cardHeight / 2) * this.scale;
    this._updateTransform();
  }

  // =========================================================================
  // INSPECTOR DRAWER (Exact telecom classes, ports, and hop navigation)
  // =========================================================================

  selectNode(node) {
    this.selectedNode = node;
    this.renderGraph();

    const drawer = document.getElementById('topo-inspector-drawer');
    const content = document.getElementById('topo-inspector-content');
    const typeBadge = document.getElementById('inspector-badge-type');

    if (!drawer || !content) return;

    const cfg = getNodeConfig(node.resource_type, node.resource_id);
    if (typeBadge) {
      typeBadge.textContent = cfg.label.toUpperCase();
      typeBadge.style.color = cfg.color;
      typeBadge.style.borderColor = cfg.color;
      typeBadge.style.backgroundColor = cfg.badgeBg;
    }

    const connections = node.connections || [];
    const isIp = this.profileId === 'IP_NETWORK';

    content.innerHTML = `
      <!-- Top Hero Card -->
      <div style="background: rgba(20, 27, 43, 0.85); border: 1px solid ${cfg.color}55; border-radius: var(--radius-lg); padding: 1.5rem 1.25rem; text-align: center; margin-bottom: 1.25rem; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);">
        <div style="width: 56px; height: 56px; border-radius: 50%; background: ${cfg.badgeBg}; border: 2px solid ${cfg.color}; display: inline-flex; align-items: center; justify-content: center; font-size: 26px; box-shadow: 0 0 16px ${cfg.glow}; margin-bottom: 0.75rem;">
          ${cfg.icon}
        </div>
        <h3 style="font-size: 1.2rem; font-weight: 700; color: #f8fafc; margin-bottom: 0.25rem; word-break: break-word;">
          ${this._escapeHtml(node.display_name || node.resource_id)}
        </h3>
        <div style="font-family: var(--font-mono); font-size: 0.825rem; color: ${cfg.color}; margin-bottom: 0.5rem; word-break: break-all;">
          ${this._escapeHtml(node.resource_id)}
        </div>
        <div style="font-size: 0.75rem; color: var(--text-dim);">
          ${this._escapeHtml(cfg.desc)}
        </div>
      </div>

      <!-- Properties Grid -->
      <div style="display: flex; flex-direction: column; gap: 0.65rem; font-size: 0.825rem; margin-bottom: 1.25rem; padding-bottom: 1.25rem; border-bottom: 1px solid var(--border-subtle);">
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-dim); font-family: var(--font-mono);">${isIp ? 'Telecom Class' : 'Resource Type'}</span>
          <span style="font-weight: 700; color: ${cfg.color}; font-family: var(--font-mono);">${this._escapeHtml(cfg.label)}</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-dim); font-family: var(--font-mono);">Hop Distance</span>
          <span style="color: #f8fafc; font-family: var(--font-mono);">${node.isFocal ? '0 (Focal Center)' : `${node.depth}-Hop Neighbor`}</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-dim); font-family: var(--font-mono);">Direct Connections</span>
          <span style="color: #f8fafc; font-family: var(--font-mono); font-weight: 600;">${connections.length} in view</span>
        </div>
        ${node.source_port && node.target_port ? `
          <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="color: var(--text-dim); font-family: var(--font-mono);">Connected Port</span>
            <span style="color: #38bdf8; font-family: var(--font-mono); font-size: 0.75rem;">${this._escapeHtml(node.target_port)}</span>
          </div>
        ` : ''}
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="color: var(--text-dim); font-family: var(--font-mono);">Link Path Status</span>
          <span style="color: ${node.reference_kind === 'CYCLE' ? '#fbbf24' : '#94a3b8'}; font-family: var(--font-mono);">
            ${node.reference_kind === 'CYCLE' ? '⟲ Ring Cycle Loop' : (node.reference_kind === 'MULTI_PARENT' ? 'Shared Multi-Parent Link' : 'Primary Path')}
          </span>
        </div>
      </div>

      <!-- Action Buttons -->
      <div style="display: flex; gap: 0.5rem; margin-bottom: 1.5rem;">
        <button class="btn btn-primary btn-sm" id="btn-recenter-graph" style="flex: 1;" title="Re-center graph projection on this node">
          🎯 Re-center Graph Here
        </button>
        <button class="btn btn-secondary btn-sm" id="btn-drawer-center" style="white-space: nowrap;" title="Pan view to this node">
          🔍 Center
        </button>
        <button class="btn btn-secondary btn-sm" id="btn-drawer-copy" style="white-space: nowrap;" title="Copy ID">
          📋 Copy
        </button>
      </div>

      <!-- Direct Connections List with Port Details -->
      <div>
        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); margin-bottom: 0.75rem;">
          ${isIp ? 'PHYSICAL PORT CONNECTIONS' : 'CONNECTED ARCHITECTURE UNITS'} (${connections.length})
        </div>
        <div style="display: flex; flex-direction: column; gap: 0.4rem; max-height: 260px; overflow-y: auto;" id="drawer-connections-list">
          ${connections.length === 0 ? `
            <div style="padding: 1rem; text-align: center; color: var(--text-muted); font-size: 0.8rem; background: rgba(255,255,255,0.02); border-radius: var(--radius-md);">
              No connected neighbors in current projection depth.
            </div>
          ` : connections.map(conn => {
            const targetNode = this.nodesMap.get(conn.targetId);
            const targetCfg = targetNode ? getNodeConfig(targetNode.resource_type, targetNode.resource_id) : getNodeConfig('DEVICE', conn.targetId);
            const portLabel = (conn.source_port && conn.target_port) ? `${conn.source_port} ↔ ${conn.target_port}` : conn.relation;

            return `
              <div class="drawer-conn-item" data-conn-id="${conn.targetId}" style="display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0.75rem; background: #182235; border: 1px solid var(--border-subtle); border-radius: var(--radius-md); cursor: pointer; transition: all 0.15s;">
                <div style="display: flex; align-items: center; gap: 0.5rem; overflow: hidden;">
                  <span>${targetCfg.icon}</span>
                  <div style="display: flex; flex-direction: column; overflow: hidden;">
                    <span style="font-size: 0.8rem; font-weight: 600; color: #f1f5f9; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
                      ${this._escapeHtml(targetNode?.display_name || conn.targetId)}
                    </span>
                    <span style="font-family: var(--font-mono); font-size: 0.7rem; color: #38bdf8; text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
                      ${this._escapeHtml(portLabel)}
                    </span>
                  </div>
                </div>
                <span class="badge badge-info" style="font-size: 0.65rem; font-family: var(--font-mono); color: ${targetCfg.color}; border-color: ${targetCfg.color}44;">
                  ${this._escapeHtml(targetCfg.label)}
                </span>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `;

    document.getElementById('btn-recenter-graph')?.addEventListener('click', () => {
      this.currentFocalId = node.resource_id;
      this.loadProjection();
    });

    document.getElementById('btn-drawer-center')?.addEventListener('click', () => {
      this.centerOnNode(node);
    });

    document.getElementById('btn-drawer-copy')?.addEventListener('click', () => {
      navigator.clipboard?.writeText(node.resource_id);
      const copyBtn = document.getElementById('btn-drawer-copy');
      if (copyBtn) {
        copyBtn.textContent = '✓ Copied!';
        setTimeout(() => { copyBtn.textContent = '📋 Copy'; }, 1500);
      }
    });

    document.querySelectorAll('.drawer-conn-item').forEach(item => {
      item.addEventListener('click', () => {
        const targetId = item.getAttribute('data-conn-id');
        const targetNode = this.nodesMap.get(targetId);
        if (targetNode) {
          this.selectNode(targetNode);
          this.centerOnNode(targetNode);
        } else {
          this.currentFocalId = targetId;
          this.loadProjection();
        }
      });
    });

    drawer.classList.add('open');
  }

  closeInspector() {
    const drawer = document.getElementById('topo-inspector-drawer');
    if (drawer) drawer.classList.remove('open');
    this.selectedNode = null;
    this.renderGraph();
  }

  _escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}

/**
 * Slide-over Drawer Component for inspecting 100% full verbatim raw columns.
 */

export class DetailDrawer {
  constructor() {
    this.backdrop = null;
    this.drawer = null;
    this.currentData = null;
    this._initDom();
  }

  _initDom() {
    this.backdrop = document.createElement('div');
    this.backdrop.className = 'drawer-backdrop';

    this.drawer = document.createElement('div');
    this.drawer.className = 'drawer';
    this.drawer.innerHTML = `
      <div class="drawer-header">
        <div>
          <div class="drawer-title" id="drawer-title">Alarm Details</div>
          <div style="font-size: 0.75rem; color: var(--text-dim); margin-top: 0.2rem;" id="drawer-subtitle">Verbatim 96-column inspection</div>
        </div>
        <button class="drawer-close-btn" id="drawer-close">&times;</button>
      </div>
      <div style="padding: 0.75rem 1.5rem; background: var(--bg-surface-elevated); border-bottom: 1px solid var(--border-subtle); display: flex; gap: 0.75rem; align-items: center;">
        <input type="text" id="drawer-search" class="form-input" placeholder="Filter columns or values..." style="flex: 1; font-size: 0.8rem;">
        <label style="display: flex; align-items: center; gap: 0.4rem; font-size: 0.75rem; color: var(--text-muted); cursor: pointer; white-space: nowrap; user-select: none;">
          <input type="checkbox" id="drawer-hide-empty" checked> Hide Empty
        </label>
      </div>
      <div class="drawer-body" id="drawer-content">
        <!-- Key value grid rendered dynamically -->
      </div>
    `;

    document.body.appendChild(this.backdrop);
    document.body.appendChild(this.drawer);

    this.backdrop.addEventListener('click', () => this.close());
    this.drawer.querySelector('#drawer-close').addEventListener('click', () => this.close());

    const searchInput = this.drawer.querySelector('#drawer-search');
    searchInput.addEventListener('input', (e) => this._filterColumns(e.target.value));

    const hideEmptyCheckbox = this.drawer.querySelector('#drawer-hide-empty');
    if (hideEmptyCheckbox) {
      hideEmptyCheckbox.addEventListener('change', () => {
        this._filterColumns(searchInput.value);
      });
    }
  }


  open(detail) {
    this.currentData = detail;
    const title = this.drawer.querySelector('#drawer-title');
    const subtitle = this.drawer.querySelector('#drawer-subtitle');
    const searchInput = this.drawer.querySelector('#drawer-search');
    searchInput.value = '';

    const canonical = detail.canonical || {};
    const alarmId = canonical.alarm_id || '';
    const chainId = canonical.chaining_id ? `#${canonical.chaining_id}` : 'None';
    title.textContent = `Alarm ${canonical.logical_row || ''}: ${alarmId}`;
    subtitle.textContent = `Chain: ${chainId} | Device: ${canonical.device_code || 'None'} | Severity: ${canonical.severity || 'INFO'}`;

    this._renderDrawerBody('', detail);

    this.backdrop.classList.add('active');
    this.drawer.classList.add('open');
  }

  close() {
    this.backdrop.classList.remove('active');
    this.drawer.classList.remove('open');
  }

  _filterColumns(query) {
    if (!this.currentData) return;
    this._renderDrawerBody(query, this.currentData);
  }

  _renderDrawerBody(query, detail) {
    const container = this.drawer.querySelector('#drawer-content');
    const canonical = detail.canonical || {};
    const rawDict = detail.raw || {};

    const q = (query || '').trim().toLowerCase();
    const hideEmpty = this.drawer.querySelector('#drawer-hide-empty')?.checked ?? true;
    const filteredRaw = {};
    let emptyCount = 0;

    for (const [k, v] of Object.entries(rawDict)) {
      const isValEmpty = (v === null || v === undefined || String(v).trim() === '' || String(v).trim() === '[]');
      if (isValEmpty) emptyCount++;
      if (hideEmpty && isValEmpty) continue;
      if (!q || k.toLowerCase().includes(q) || String(v).toLowerCase().includes(q)) {
        filteredRaw[k] = v;
      }
    }

    const rawCount = Object.keys(rawDict).length;
    const matchCount = Object.keys(filteredRaw).length;

    // Severity badge color
    const sev = String(canonical.severity || 'INFO').toUpperCase();
    let sevBadgeCls = 'info';
    if (sev === 'CRITICAL') sevBadgeCls = 'danger';
    else if (sev === 'MAJOR') sevBadgeCls = 'warning';
    else if (sev === 'MINOR') sevBadgeCls = 'purple';

    const qualityFlags = (canonical.quality_flags || []).length > 0
      ? canonical.quality_flags.map(f => `<span class="badge badge-warning" style="font-size: 0.65rem;">${escapeHtml(f)}</span>`).join(' ')
      : '<span class="badge badge-success" style="font-size: 0.65rem;">CLEAN</span>';

    const mappingBadgeCls = (canonical.mapping_status === 'EXACT' || canonical.mapping_status === 'VERIFIED_ALIAS')
      ? 'success'
      : (canonical.mapping_status === 'AMBIGUOUS' ? 'danger' : 'info');

    const hasGroundTruth = Boolean(
      canonical.cah_reason ||
      canonical.cah_comment ||
      canonical.cah_resolve ||
      (canonical.parent_id && canonical.parent_id !== '[]') ||
      (canonical.child_id && canonical.child_id !== '[]')
    );

    let html = `
      <!-- Canonical Key Summary Card -->
      <div style="background: rgba(30, 41, 59, 0.7); border: 1px solid var(--border-medium); border-radius: var(--radius-md); padding: 1rem; margin-bottom: 1.25rem;">
        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: var(--accent-primary); margin-bottom: 0.75rem; display: flex; justify-content: space-between; align-items: center;">
          <span>⚡ Key Operational Attributes</span>
          <button class="btn btn-secondary btn-sm" id="btn-copy-alarm-json" style="padding: 0.15rem 0.5rem; font-size: 0.675rem;">
            Copy JSON
          </button>
        </div>
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 0.6rem; font-size: 0.8rem;">
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">ALARM ID</div>
            <div style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-primary);">${escapeHtml(canonical.alarm_id || '-')}</div>
          </div>
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">CHAINING</div>
            <div>
              <span class="badge badge-purple font-mono" style="font-size: 0.725rem;">${canonical.chaining_id ? '#' + escapeHtml(canonical.chaining_id) : 'Singleton / None'}</span>
              ${canonical.chaining_name ? `<div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 0.2rem; word-break: break-word;">${escapeHtml(canonical.chaining_name)}</div>` : ''}
            </div>
          </div>
          <div style="grid-column: span 2;">
            <div style="color: var(--text-dim); font-size: 0.7rem;">ALARM NAME</div>
            <div style="font-weight: 600; color: var(--text-main); font-size: 0.85rem;">${escapeHtml(canonical.alarm_name || '-')}</div>
            ${canonical.component ? `<div style="font-size: 0.725rem; color: var(--text-dim); margin-top: 0.15rem;"><span style="color: var(--accent-primary);">Port / Component:</span> <code style="color: var(--text-main);">${escapeHtml(canonical.component)}</code></div>` : ''}
          </div>
          ${canonical.content ? `
          <div style="grid-column: span 2; background: rgba(0, 0, 0, 0.25); padding: 0.6rem; border-radius: var(--radius-sm); border-left: 3px solid var(--accent-primary);">
            <div style="color: var(--text-dim); font-size: 0.7rem; font-weight: 600;">RAW EVENT CONTENT / TELEMETRY MESSAGE</div>
            <div style="font-family: var(--font-mono); font-size: 0.775rem; color: #e2e8f0; margin-top: 0.25rem; white-space: pre-wrap; word-break: break-all;">${escapeHtml(canonical.content)}</div>
          </div>` : ''}
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">DEVICE / NODE REF</div>
            <div style="display: flex; align-items: center; gap: 0.35rem; flex-wrap: wrap;">
              <span style="font-family: var(--font-mono); font-weight: 600; color: var(--text-main);">${escapeHtml(canonical.device_code || '-')}</span>
              ${canonical.device_type_name ? `<span class="badge badge-purple" style="font-size: 0.65rem;">${escapeHtml(canonical.device_type_name)}</span>` : ''}
            </div>
            ${canonical.device_ip ? `<div style="font-family: var(--font-mono); font-size: 0.725rem; color: var(--text-muted);">IP: ${escapeHtml(canonical.device_ip)}</div>` : ''}
            ${canonical.device_name && canonical.device_name !== canonical.device_code ? `<div style="font-size: 0.725rem; color: var(--text-dim);">${escapeHtml(canonical.device_name)}</div>` : ''}
          </div>
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">DOMAIN &amp; VENDOR</div>
            <div style="display: flex; gap: 0.35rem; align-items: center; flex-wrap: wrap;">
              ${canonical.network_type_name ? `<span class="badge badge-info" style="font-size: 0.675rem;">${escapeHtml(canonical.network_type_name)}</span>` : ''}
              ${canonical.network_class_name ? `<span class="badge badge-cyan" style="font-size: 0.675rem;">${escapeHtml(canonical.network_class_name)}</span>` : ''}
              ${canonical.vendor_name ? `<span class="badge badge-secondary" style="font-size: 0.675rem; background: var(--bg-surface-elevated);">${escapeHtml(canonical.vendor_name)}</span>` : '<span style="color: var(--text-dim);">-</span>'}
            </div>
          </div>
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">SEVERITY &amp; STATUS</div>
            <div style="display: flex; gap: 0.35rem; align-items: center;">
              <span class="badge badge-${sevBadgeCls}">${escapeHtml(canonical.severity || 'INFO')}</span>
              ${canonical.alarm_status === '1' || !canonical.canonical_end_time
                ? '<span class="badge badge-danger" style="font-size: 0.65rem;">ACTIVE</span>'
                : '<span class="badge badge-success" style="font-size: 0.65rem;">CLEARED</span>'}
            </div>
          </div>
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">TOPOLOGY MAPPING</div>
            <div>
              <span class="badge badge-${mappingBadgeCls}">${escapeHtml(canonical.mapping_status || 'UNMAPPED')}</span>
              ${canonical.resource_id ? `<code style="font-size: 0.7rem; display: block; margin-top: 0.2rem;">${escapeHtml(canonical.resource_id)}</code>` : ''}
            </div>
          </div>
          ${(canonical.trouble_code || canonical.kedb_code) ? `
          <div style="grid-column: span 2; display: flex; gap: 0.5rem; flex-wrap: wrap; margin-top: 0.25rem;">
            ${canonical.trouble_code ? `<span class="badge badge-indigo font-mono">🎫 TT: ${escapeHtml(canonical.trouble_code)}</span>` : ''}
            ${canonical.kedb_code ? `<span class="badge badge-info font-mono">📖 KEDB: ${escapeHtml(canonical.kedb_code)}</span>` : ''}
          </div>` : ''}
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">START TIME</div>
            <div style="font-family: var(--font-mono); font-size: 0.75rem;">${escapeHtml(canonical.canonical_start_time || '-')}</div>
          </div>
          <div>
            <div style="color: var(--text-dim); font-size: 0.7rem;">END TIME</div>
            <div style="font-family: var(--font-mono); font-size: 0.75rem;">${escapeHtml(canonical.canonical_end_time || '-')}</div>
          </div>
          ${canonical.location_name ? `
          <div style="grid-column: span 2;">
            <div style="color: var(--text-dim); font-size: 0.7rem;">LOCATION</div>
            <div style="font-size: 0.75rem; color: var(--text-main);">${escapeHtml(canonical.location_name)}</div>
          </div>` : ''}
          ${canonical.addition_info ? `
          <div style="grid-column: span 2;">
            <div style="color: var(--text-dim); font-size: 0.7rem;">ADDITIONAL INFO / PEER CONTEXT</div>
            <div style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);">${escapeHtml(canonical.addition_info)}</div>
          </div>` : ''}
          <div style="grid-column: span 2;">
            <div style="color: var(--text-dim); font-size: 0.7rem;">QUALITY FLAGS</div>
            <div style="display: flex; gap: 0.3rem; flex-wrap: wrap; margin-top: 0.2rem;">${qualityFlags}</div>
          </div>
        </div>
      </div>

      ${hasGroundTruth ? `
      <!-- Operator Ground Truth & Causality Card -->
      <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.35); border-radius: var(--radius-md); padding: 1rem; margin-bottom: 1.25rem;">
        <div style="font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.05em; color: #10b981; margin-bottom: 0.75rem; display: flex; align-items: center; gap: 0.4rem;">
          <span>🎯 Operator Ground Truth &amp; Causality</span>
        </div>
        <div style="display: flex; flex-direction: column; gap: 0.6rem; font-size: 0.8rem;">
          ${canonical.cah_reason ? `
            <div>
              <div style="color: var(--text-dim); font-size: 0.7rem;">ROOT CAUSE REASON (cah.reason)</div>
              <div style="font-weight: 600; color: #34d399; margin-top: 0.15rem;">${escapeHtml(canonical.cah_reason)}</div>
            </div>` : ''}
          ${canonical.cah_comment ? `
            <div>
              <div style="color: var(--text-dim); font-size: 0.7rem;">OPERATOR COMMENT (cah.comment)</div>
              <div style="color: var(--text-main); font-style: italic; background: rgba(0,0,0,0.25); padding: 0.45rem 0.65rem; border-radius: var(--radius-sm); margin-top: 0.15rem;">${escapeHtml(canonical.cah_comment)}</div>
            </div>` : ''}
          ${canonical.cah_resolve ? `
            <div>
              <div style="color: var(--text-dim); font-size: 0.7rem;">RESOLUTION (cah.resolve)</div>
              <div style="color: var(--text-main); margin-top: 0.15rem;">${escapeHtml(canonical.cah_resolve)}</div>
            </div>` : ''}
          ${(canonical.parent_id && canonical.parent_id !== '[]') || (canonical.child_id && canonical.child_id !== '[]') ? `
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.6rem; margin-top: 0.2rem; padding-top: 0.5rem; border-top: 1px dashed rgba(16, 185, 129, 0.2);">
              <div>
                <div style="color: var(--text-dim); font-size: 0.7rem;">PARENT ALARM ID</div>
                <div style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-primary);">${escapeHtml(canonical.parent_id || 'None')}</div>
              </div>
              <div>
                <div style="color: var(--text-dim); font-size: 0.7rem;">CHILD ALARM IDS</div>
                <div style="font-family: var(--font-mono); font-weight: 600; color: #a855f7;">${escapeHtml(canonical.child_id || 'None')}</div>
              </div>
            </div>` : ''}
        </div>
      </div>` : ''}

      <!-- Raw Columns Header -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
        <div style="font-size: 0.8rem; font-weight: 700; color: var(--text-muted);">
          Raw Export Columns (${rawCount} total${hideEmpty ? `, ${emptyCount} empty hidden` : ''})
        </div>
        <span class="badge badge-info" style="font-size: 0.7rem;">${matchCount} matching</span>
      </div>
    `;


    if (matchCount === 0) {
      html += `<div style="color: var(--text-dim); text-align: center; padding: 2rem;">No matching columns found.</div>`;
    } else {
      html += `<div class="detail-grid">`;
      for (const [key, val] of Object.entries(filteredRaw)) {
        const isEmpty = (val === null || val === undefined || val === '');
        const displayVal = isEmpty
          ? '<span style="color: var(--text-dim); font-style: italic;">[empty]</span>'
          : escapeHtml(String(val));
        html += `
          <div class="detail-key" title="${escapeHtml(key)}">${escapeHtml(key)}</div>
          <div class="detail-val" style="${isEmpty ? 'opacity: 0.6;' : ''}">${displayVal}</div>
        `;
      }
      html += `</div>`;
    }

    container.innerHTML = html;

    const copyBtn = container.querySelector('#btn-copy-alarm-json');
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        navigator.clipboard.writeText(JSON.stringify(detail, null, 2)).then(() => {
          copyBtn.textContent = 'Copied!';
          setTimeout(() => { copyBtn.textContent = 'Copy JSON'; }, 1500);
        });
      });
    }
  }
}

function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (m) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[m]));
}

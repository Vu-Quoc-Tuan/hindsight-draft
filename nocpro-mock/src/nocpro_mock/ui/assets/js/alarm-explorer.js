/**
 * Screen 1: Dataset & Alarm Explorer.
 */

import { api } from './api.js';
import { renderTable } from '../components/table.js';

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

const HUMAN_FLAG_MAP = {
  TIMESTAMP_FUTURE_OUTLIER: 'Future Outlier',
  TIMESTAMP_END_BEFORE_START: 'End < Start',
  TIMESTAMP_PARSING_FAILED: 'Parse Error',
  MISSING_DEVICE_CODE: 'Missing Device',
  EMPTY_ALARM_ID: 'Empty ID',
  EMPTY_TIMESTAMP: 'Empty Time',
  DURATION_EXCEEDS_MAX_REASONABLE: 'Excessive Duration',
};

const SHORT_DATASET_NAMES = {
  alarm_ip: 'IP Network (212k)',
  alarm_it: 'IT Services (258k)',
  alarm_data: 'Legacy Alarms (8.7k)',
};

export class AlarmExplorerScreen {

  constructor(container) {
    this.container = container;
    this.currentCursor = null;
    this.cursorStack = [];
    this.pageNumber = 1;
    this._renderShell();
    this._attachEvents();
  }

  _renderShell() {
    this.container.innerHTML = `
      <!-- Header & Dataset Selector -->
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; flex-wrap: wrap; gap: 1rem;">
        <div>
          <h2 style="font-size: 1.35rem; font-weight: 700; color: var(--text-main);">Dataset &amp; Alarm Explorer</h2>
        </div>
        <div style="display: flex; align-items: center; gap: 0.75rem;">
          <label style="font-size: 0.8rem; color: var(--text-muted); font-weight: 600;">Dataset:</label>
          <select id="dataset-select" class="form-select" style="min-width: 180px;">
            <option value="alarm_ip">IP Network (212k)</option>
            <option value="alarm_it">IT Services (258k)</option>
            <option value="alarm_data">Legacy Alarms (8.7k)</option>
          </select>
          <button class="btn btn-secondary btn-sm" id="btn-refresh-alarms">Refresh</button>
        </div>
      </div>

      <!-- Facet Cards Grid -->
      <div class="grid-cols-4" id="facet-cards" style="margin-bottom: 1.5rem;">
        <div class="stat-card">
          <span class="stat-label">Total Alarms</span>
          <span class="stat-value" id="facet-total">--</span>
          <span class="stat-desc" id="facet-time-range">Loading range...</span>
        </div>
        <div class="stat-card">
          <span class="stat-label">Severities</span>
          <div id="facet-severities" style="display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.35rem;">
            <span class="badge badge-info">--</span>
          </div>
        </div>
        <div class="stat-card">
          <span class="stat-label">Quality Flags</span>
          <div id="facet-flags" style="display: flex; gap: 0.4rem; flex-wrap: wrap; margin-top: 0.35rem;">
            <span class="badge badge-warning">--</span>
          </div>
        </div>
        <div class="stat-card">
          <span class="stat-label">Chains / Correlation</span>
          <span class="stat-value" id="facet-chains">--</span>
          <span class="stat-desc" id="facet-mapping-rate">Mapping status</span>
        </div>
      </div>

      <!-- Alarm Table Panel -->
      <div class="panel">
        <div class="panel-header">
          <div class="panel-title">
            <span>Alarm Records</span>
            <span class="badge badge-info" id="table-count-badge">0 records</span>
          </div>
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span id="page-indicator" style="font-size: 0.775rem; color: var(--text-muted); font-family: var(--font-mono); margin-right: 0.25rem;">Page 1</span>
            <button class="btn btn-secondary btn-sm" id="btn-prev-page" disabled>&larr; Prev</button>
            <button class="btn btn-secondary btn-sm" id="btn-next-page" disabled>Next &rarr;</button>
          </div>
        </div>

        <div id="alarm-table-container">
          <!-- Rendered via table component -->
        </div>
      </div>
    `;
  }

  _attachEvents() {
    this.container.querySelector('#dataset-select').addEventListener('change', () => {
      this.currentCursor = null;
      this.cursorStack = [];
      this.pageNumber = 1;
      this.refresh();
    });

    this.container.querySelector('#btn-refresh-alarms').addEventListener('click', () => this.refresh());

    this.container.querySelector('#btn-next-page').addEventListener('click', () => {
      if (this.nextCursor) {
        this.cursorStack.push(this.currentCursor);
        this.currentCursor = this.nextCursor;
        this.pageNumber++;
        this.loadAlarms();
      }
    });

    this.container.querySelector('#btn-prev-page').addEventListener('click', () => {
      if (this.cursorStack.length > 0) {
        this.currentCursor = this.cursorStack.pop();
        this.pageNumber = Math.max(1, this.pageNumber - 1);
        this.loadAlarms();
      }
    });
  }

  async init() {
    await this.loadDatasets();
    await this.loadFacets();
    await this.loadAlarms();
  }

  async refresh() {
    await this.loadFacets();
    await this.loadAlarms();
  }

  async loadDatasets() {
    try {
      const res = await api.getDatasets();
      const select = this.container.querySelector('#dataset-select');
      select.innerHTML = '';
      res.datasets.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.id;
        opt.textContent = SHORT_DATASET_NAMES[d.id] || d.name.split('(')[0].trim();
        select.appendChild(opt);
      });
    } catch (err) {
      console.error('Failed to load datasets', err);
    }
  }

  async loadFacets() {
    try {
      const datasetId = this.container.querySelector('#dataset-select')?.value || 'alarm_ip';
      const res = await api.getAlarmFacets(datasetId);
      if (!res.ok) return;
      const f = res.facets || {};

      this.container.querySelector('#facet-total').textContent = (f.record_count || 0).toLocaleString();
      this.container.querySelector('#facet-chains').textContent = (f.chain_count || 0).toLocaleString();

      if (f.earliest_time && f.latest_time) {
        const d1 = f.earliest_time.split('T')[0];
        const d2 = f.latest_time.split('T')[0];
        this.container.querySelector('#facet-time-range').textContent = `${d1} to ${d2}`;
      } else {
        this.container.querySelector('#facet-time-range').textContent = 'No timestamp bounds';
      }

      // Severities
      const sevContainer = this.container.querySelector('#facet-severities');
      sevContainer.innerHTML = '';
      Object.entries(f.severities || {}).forEach(([sev, count]) => {
        const badge = document.createElement('span');
        badge.className = `badge badge-${this._getSeverityClass(sev)}`;
        badge.textContent = `${sev}: ${count.toLocaleString()}`;
        sevContainer.appendChild(badge);
      });

      // Flags
      const flagContainer = this.container.querySelector('#facet-flags');
      flagContainer.innerHTML = '';
      const flagEntries = Object.entries(f.quality_flags || {});
      if (flagEntries.length === 0) {
        flagContainer.innerHTML = '<span class="badge badge-success">100% Clean</span>';
      } else {
        flagEntries.slice(0, 4).forEach(([flag, count]) => {
          const badge = document.createElement('span');
          badge.className = 'badge badge-warning';
          const label = HUMAN_FLAG_MAP[flag] || flag.replace('TIMESTAMP_', '').replace(/_/g, ' ');
          badge.textContent = `${label}: ${count.toLocaleString()}`;
          badge.title = `${flag}: ${count} occurrences`;
          flagContainer.appendChild(badge);
        });
      }

      // Mapping status summary
      const m = f.mapping_statuses || {};
      const exactMapped = (m.EXACT || 0) + (m.VERIFIED_ALIAS || 0);
      const unavailable = m.UNAVAILABLE || 0;
      const total = f.record_count || 1;
      if (unavailable === total && total > 0) {
        this.container.querySelector('#facet-mapping-rate').textContent = `Mapping: UNAVAILABLE (profile)`;
      } else {
        const rate = ((exactMapped / total) * 100).toFixed(1);
        this.container.querySelector('#facet-mapping-rate').textContent = `Exact mapped: ${rate}% (${exactMapped.toLocaleString()})`;
      }
    } catch (err) {
      console.error('Failed loading facets', err);
    }
  }

  async loadAlarms() {
    const tableContainer = this.container.querySelector('#alarm-table-container');
    tableContainer.innerHTML = '<div style="padding: 2.5rem; text-align: center; color: var(--text-dim); font-size: 0.9rem;">Loading alarms...</div>';

    const selectEl = this.container.querySelector('#dataset-select');
    const params = {
      dataset_id: (selectEl && selectEl.value) ? selectEl.value : 'alarm_ip',
      cursor: this.currentCursor || '',
      limit: 50,
    };

    try {
      const res = await api.getAlarms(params);
      this.nextCursor = res.next_cursor;

      const prevBtn = this.container.querySelector('#btn-prev-page');
      const nextBtn = this.container.querySelector('#btn-next-page');
      prevBtn.disabled = this.cursorStack.length === 0;
      nextBtn.disabled = !res.next_cursor;

      const pageIndicator = this.container.querySelector('#page-indicator');
      if (pageIndicator) {
        pageIndicator.textContent = `Page ${this.pageNumber}`;
      }

      const countBadge = this.container.querySelector('#table-count-badge');
      if (countBadge) {
        const count = res.total_estimate || res.items?.length || 0;
        countBadge.textContent = `${count.toLocaleString()} records`;
      }

      const stickyKeys = new Set(['canonical_start_time', 'alarm_id', 'chaining_id']);
      const columns = (res.columns || []).map((column) => ({
        ...column,
        className: stickyKeys.has(column.key) ? `sticky-field sticky-${column.key.replaceAll('_', '-')}` : '',
        render: (row) => this._renderActiveCell(column.key, row[column.key]),
      }));

      renderTable(tableContainer, {
        columns,
        rows: res.items,
      });
    } catch (err) {
      tableContainer.innerHTML = `<div style="padding: 2rem; color: var(--color-danger); text-align: center;">Error loading alarms: ${escapeHtml(err.message)}</div>`;
    }
  }

  _renderActiveCell(key, value) {
    if (value === null || value === undefined || value === '' || (Array.isArray(value) && value.length === 0)) {
      return '<span class="alarm-cell-missing">—</span>';
    }
    if (key === 'quality_flags') {
      return value.map(flag => `<span class="badge badge-warning" title="${escapeHtml(flag)}">${escapeHtml(HUMAN_FLAG_MAP[flag] || flag)}</span>`).join(' ');
    }
    if (key === 'severity_name') {
      return `<span class="badge badge-${this._getSeverityClass(value)}">${escapeHtml(value)}</span>`;
    }
    if (key === 'alarm_status') {
      const cls = String(value) === '1' ? 'danger' : (String(value).toUpperCase() === 'UNKNOWN' ? 'info' : 'success');
      return `<span class="badge badge-${cls}">${escapeHtml(value)}</span>`;
    }
    if (key === 'mapping_status') {
      const normalized = String(value).toUpperCase();
      const cls = ['EXACT', 'VERIFIED_ALIAS'].includes(normalized) ? 'success'
        : (normalized === 'AMBIGUOUS' ? 'danger' : (normalized === 'UNAVAILABLE' ? 'info' : 'warning'));
      return `<span class="badge badge-${cls}">${escapeHtml(value)}</span>`;
    }
    if (key === 'content') {
      const text = String(value);
      return `<span class="alarm-cell-value cell-truncate" style="max-width: 320px;" title="${escapeHtml(text)}">${escapeHtml(text)}</span>`;
    }
    const text = String(value);
    const display = key.includes('canonical_') ? text.replace('T', ' ') : text;
    return `<span class="alarm-cell-value" title="${escapeHtml(text)}">${escapeHtml(display)}</span>`;
  }

  _getSeverityClass(sev) {
    switch (String(sev).toUpperCase()) {
      case 'CRITICAL': return 'danger';
      case 'MAJOR': return 'warning';
      case 'MINOR': return 'purple';
      case 'WARNING': return 'warning';
      default: return 'info';
    }
  }
}

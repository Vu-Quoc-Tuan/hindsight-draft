/**
 * Main Application Orchestrator for NocPro Mock Studio.
 */

import { api } from './api.js';
import { store } from './state.js';
import { AlarmExplorerScreen } from './alarm-explorer.js';
import { TopologyInspectorScreen } from './topology-inspector.js';
import { SnapshotStudioScreen } from './snapshot-studio.js';

class MockStudioApp {
  constructor() {
    this.screens = {};
    this._initDom();
    this._attachTabs();
  }

  async start() {
    // Instantiate screens
    this.screens.explorer = new AlarmExplorerScreen(document.getElementById('screen-explorer'));
    this.screens.topology = new TopologyInspectorScreen(document.getElementById('screen-topology'));
    this.screens.studio = new SnapshotStudioScreen(document.getElementById('screen-studio'));

    // Start with Screen 1 immediately (never block on network calls)
    this.switchScreen('explorer');

    // Check Kafka status asynchronously in background
    this._checkKafka().catch(() => {});
  }

  _initDom() {
    if (document.getElementById('kafka-status-pill')) {
      return;
    }
    const headerHtml = `
      <div class="brand-section">
        <span class="brand-badge">NOCPRO MOCK</span>
      </div>

      <div class="nav-tabs">
        <button class="nav-tab-btn active" data-tab="explorer">
          <span>📊</span> Dataset &amp; Alarms
        </button>
        <button class="nav-tab-btn nav-btn-topology" id="nav-btn-topology" data-tab="topology">
          <span>🌐</span> Topology Explorer
        </button>
        <button class="nav-tab-btn nav-btn-slicer" id="nav-btn-slicer" data-tab="studio">
          <span>⚡</span> Sequence Slicer &amp; Kafka
        </button>
      </div>

      <div class="header-meta">
        <div class="kafka-status-pill" id="kafka-status-pill" title="Target Kafka Cluster">
          <span class="status-dot" id="kafka-status-dot"></span>
          <span id="kafka-status-text">Checking Kafka...</span>
        </div>
      </div>
    `;

    document.getElementById('app-header').innerHTML = headerHtml;
  }

  _attachTabs() {
    const tabs = document.querySelectorAll('.nav-tab-btn');
    tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const screenKey = tab.dataset.tab;
        this.switchScreen(screenKey);
      });
    });
  }

  switchScreen(screenKey) {
    // Update active tab buttons
    document.querySelectorAll('.nav-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset?.tab === screenKey);
    });

    // Update screen containers
    document.querySelectorAll('.screen-container').forEach(el => {
      el.classList.remove('active');
    });

    const activeEl = document.getElementById(`screen-${screenKey}`);
    if (activeEl) {
      activeEl.classList.add('active');
    }

    store.setState({ activeScreen: screenKey });

    // Initialize screen on demand if first time
    const screen = this.screens[screenKey];
    if (screen && screen.init && !screen._initialized) {
      screen.init();
      screen._initialized = true;
    }
  }

  async _checkKafka() {
    const dot = document.getElementById('kafka-status-dot');
    const text = document.getElementById('kafka-status-text');
    try {
      const res = await api.checkKafka();
      if (res.ok) {
        dot.className = 'status-dot connected';
        text.textContent = `Kafka: ${res.bootstrap || 'Connected'}`;
      } else {
        dot.className = 'status-dot disconnected';
        text.textContent = `Kafka: Offline (${res.bootstrap || '9092'})`;
      }
    } catch (_) {
      dot.className = 'status-dot disconnected';
      text.textContent = 'Kafka: Unreachable';
    }
  }
}

// Bootstrap once DOM is ready
function bootstrap() {
  const app = new MockStudioApp();
  app.start().catch(console.error);
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrap);
  } else {
    bootstrap();
  }
}

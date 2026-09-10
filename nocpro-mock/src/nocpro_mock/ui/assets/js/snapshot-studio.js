/**
 * Screen 3: Alarm Snapshot Queue & Kafka Dispatcher.
 *
 * Provides a clean interactive Queue view of alarm snapshots:
 * - Dynamic list of pending snapshots ready for dispatch.
 * - Button [+] opens modal to slice/create new alarm sequence.
 * - Button [Push to Explain] opens modal to stream/push snapshots to Kafka topic nocpro.snapshot.v1.
 * - Real-time Queue Depletion ("Rút ngắn dần"):
 *   As snapshots are dispatched to Kafka/Explain, they animate out and are removed
 *   from the pending queue in real-time.
 * - Dispatched history tab to inspect delivered snapshots.
 * - Live Streaming HUD with Pause / Resume / Stop controls.
 * - Live Kafka Dispatcher Console.
 */

import { api } from './api.js';
import { StreamingTerminal } from '../components/terminal.js';
import { JobEventStream } from './job-events.js';

export class SnapshotStudioScreen {
  constructor(container) {
    this.container = container;
    this.terminal = null;
    this.currentJobId = null;
    this.currentJobStream = null;
    this.sequences = [];
    this.activeSequence = null;

    // Queue state
    this.activeTab = 'pending'; // 'pending' | 'dispatched' | 'all'
    this.pendingSnapshots = [];
    this.dispatchedSnapshots = [];
    this.isStreaming = false;

    this._renderShell();
    this._attachEvents();
  }

  _renderShell() {
    const termContainer = this.container.querySelector('#studio-terminal-container');
    if (termContainer && !this.terminal) {
      this.terminal = new StreamingTerminal(termContainer, { title: 'Kafka Dispatcher Console' });
    }
  }

  _attachEvents() {
    // Sequence dropdown switcher
    const seqSelect = this.container.querySelector('#studio-sequence-select');
    seqSelect?.addEventListener('change', () => this.onSequenceSelected(seqSelect.value));

    // Modal Triggers: [+] Slice and [Push]
    this.container.querySelector('#btn-open-slice-modal')?.addEventListener('click', () => this.openSliceModal());
    this.container.querySelector('#btn-close-slice-modal')?.addEventListener('click', () => this.closeSliceModal());
    this.container.querySelector('#btn-cancel-slice-modal')?.addEventListener('click', () => this.closeSliceModal());

    this.container.querySelector('#btn-open-push-modal')?.addEventListener('click', () => this.openPushModal());
    this.container.querySelector('#btn-close-push-modal')?.addEventListener('click', () => this.closePushModal());
    this.container.querySelector('#btn-cancel-push-modal')?.addEventListener('click', () => this.closePushModal());

    // Modal Action Buttons
    this.container.querySelector('#btn-run-slicer')?.addEventListener('click', () => this.submitSliceJob());
    this.container.querySelector('#btn-confirm-push-kafka')?.addEventListener('click', () => this.submitPushJob());

    // Close modals when clicking backdrop
    this.container.querySelectorAll('.modal-backdrop').forEach((backdrop) => {
      backdrop.addEventListener('click', (e) => {
        if (e.target === backdrop) {
          backdrop.classList.remove('open');
        }
      });
    });

    // Close on Escape key
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        this.closeSliceModal();
        this.closePushModal();
      }
    });

    // Queue Filter Tabs
    this.container.querySelectorAll('.queue-tab-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        const tab = btn.getAttribute('data-queue-tab');
        this.switchQueueTab(tab);
      });
    });

    // Live Stream HUD Controls
    this.container.querySelector('#btn-hud-pause')?.addEventListener('click', () => this.pauseStream());
    this.container.querySelector('#btn-hud-resume')?.addEventListener('click', () => this.resumeStream());
    this.container.querySelector('#btn-hud-stop')?.addEventListener('click', () => this.stopStream());

    // Clear Terminal Button
    this.container.querySelector('#btn-clear-terminal')?.addEventListener('click', () => {
      this.terminal?.clear();
    });

    // Toggle delay input based on modal push mode
    this.container.querySelectorAll('input[name="modal-stream-mode"]').forEach((radio) => {
      radio.addEventListener('change', (e) => {
        const delayInput = this.container.querySelector('#modal-stream-delay-sec');
        if (delayInput) {
          delayInput.disabled = (e.target.value === 'single_shot');
        }
      });
    });

    // CSV Profile autoselect in Slice Modal
    const slicerCsvSelect = this.container.querySelector('#select-slicer-alarm-csv');
    const slicerProfileSelect = this.container.querySelector('#slice-profile-id');
    if (slicerCsvSelect && slicerProfileSelect) {
      slicerCsvSelect.addEventListener('change', (e) => {
        const val = e.target.value.toLowerCase();
        if (val.includes('alarmit') || val.includes('alarm_it')) {
          slicerProfileSelect.value = 'IT_SERVICES';
        } else if (val.includes('alarmip') || val.includes('alarm_ip')) {
          slicerProfileSelect.value = 'IP_NETWORK';
        } else {
          slicerProfileSelect.value = 'IP_NETWORK';
        }
      });
    }
  }

  async init() {
    await this.loadSequences();
  }

  async loadSequences() {
    try {
      const res = await api.getStatus();
      this.sequences = res.sequences || [];

      const select = this.container.querySelector('#studio-sequence-select');
      const modalSelect = this.container.querySelector('#modal-push-sequence-select');
      if (!select) return;

      select.innerHTML = '';
      if (modalSelect) modalSelect.innerHTML = '';

      if (this.sequences.length === 0) {
        select.innerHTML = '<option value="">No sequences available</option>';
        if (modalSelect) modalSelect.innerHTML = '<option value="">No sequences available</option>';
        this.renderQueue();
        return;
      }

      this.sequences.forEach((seq) => {
        const snapCount = seq.snapshots ? seq.snapshots.length : 0;
        const text = `${seq.name || seq.id} (${snapCount} snapshots)`;

        const opt1 = document.createElement('option');
        opt1.value = seq.path;
        opt1.textContent = text;
        select.appendChild(opt1);

        if (modalSelect) {
          const opt2 = document.createElement('option');
          opt2.value = seq.path;
          opt2.textContent = text;
          modalSelect.appendChild(opt2);
        }
      });

      // Default select first sequence
      const targetSeq = this.activeSequence
        ? this.sequences.find(s => s.path === this.activeSequence.path) || this.sequences[0]
        : this.sequences[0];

      if (targetSeq) {
        select.value = targetSeq.path;
        if (modalSelect) modalSelect.value = targetSeq.path;
        this.onSequenceSelected(targetSeq.path);
      }
    } catch (err) {
      console.error('Failed loading sequences:', err);
    }
  }

  onSequenceSelected(path) {
    const seq = this.sequences.find((s) => s.path === path);
    this.activeSequence = seq || null;

    if (!seq) {
      this.pendingSnapshots = [];
      this.dispatchedSnapshots = [];
      this.renderQueue();
      return;
    }

    // Sync modal select
    const modalSelect = this.container.querySelector('#modal-push-sequence-select');
    if (modalSelect && modalSelect.value !== path) {
      modalSelect.value = path;
    }

    // Initialize the pending queue with all snapshots in this sequence
    const snapshots = seq.snapshots || [];
    this.pendingSnapshots = snapshots.map((s, idx) => ({
      name: s,
      step: idx + 1,
      total: snapshots.length,
      sequenceId: seq.id,
      sequenceName: seq.name || seq.id,
      sequencePath: seq.path,
      type: seq.sequence_type || 'EVOLUTION',
      status: 'pending', // 'pending' | 'dispatching' | 'dispatched'
      dispatchedAt: null,
    }));

    this.dispatchedSnapshots = [];
    this.updateBadges();
    this.renderQueue();
  }

  switchQueueTab(tabName) {
    this.activeTab = tabName;
    this.container.querySelectorAll('.queue-tab-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-queue-tab') === tabName);
    });
    this.renderQueue();
  }

  updateBadges() {
    const badgePending = this.container.querySelector('#badge-count-pending');
    const badgeDispatched = this.container.querySelector('#badge-count-dispatched');
    const badgeAll = this.container.querySelector('#badge-count-all');

    const pCount = this.pendingSnapshots.length;
    const dCount = this.dispatchedSnapshots.length;

    if (badgePending) badgePending.textContent = String(pCount);
    if (badgeDispatched) badgeDispatched.textContent = String(dCount);
    if (badgeAll) badgeAll.textContent = String(pCount + dCount);
  }

  renderQueue() {
    const container = this.container.querySelector('#snapshot-queue-container');
    if (!container) return;

    let items = [];
    if (this.activeTab === 'pending') {
      items = this.pendingSnapshots;
    } else if (this.activeTab === 'dispatched') {
      items = this.dispatchedSnapshots;
    } else {
      items = [...this.pendingSnapshots, ...this.dispatchedSnapshots];
    }

    // Empty state
    if (items.length === 0) {
      if (this.activeTab === 'pending') {
        if (this.dispatchedSnapshots.length > 0) {
          container.innerHTML = `
            <div class="queue-empty-state">
              <div class="queue-empty-icon">🎉</div>
              <h3 style="color: #f8fafc; font-size: 1.1rem; font-weight: 700;">Queue Clear!</h3>
              <p style="color: var(--text-dim); font-size: 0.85rem; max-width: 460px;">
                All snapshots in <strong>${this._escape(this.activeSequence?.name || 'this sequence')}</strong> have been successfully dispatched to Explain.
              </p>
              <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                <button class="btn btn-secondary btn-sm" id="btn-reset-queue">
                  🔄 Reset / Reload Queue
                </button>
                <button class="btn btn-primary btn-sm" id="btn-empty-slice-more">
                  ➕ Slice New Sequence
                </button>
              </div>
            </div>
          `;
          container.querySelector('#btn-reset-queue')?.addEventListener('click', () => {
            if (this.activeSequence) this.onSequenceSelected(this.activeSequence.path);
          });
          container.querySelector('#btn-empty-slice-more')?.addEventListener('click', () => {
            this.openSliceModal();
          });
          return;
        }
        container.innerHTML = `
          <div class="queue-empty-state">
            <div class="queue-empty-icon">📥</div>
            <h3 style="color: #f8fafc; font-size: 1.1rem; font-weight: 700;">No Pending Snapshots</h3>
            <p style="color: var(--text-dim); font-size: 0.85rem;">
              Select a sequence above or click <strong>➕ Slice Alarms</strong> to generate new evolution snapshots.
            </p>
            <button class="btn btn-primary btn-sm" id="btn-empty-slice-start" style="margin-top: 0.5rem;">
              ➕ Slice Alarms Now
            </button>
          </div>
        `;
        container.querySelector('#btn-empty-slice-start')?.addEventListener('click', () => this.openSliceModal());
        return;
      }

      if (this.activeTab === 'dispatched') {
        container.innerHTML = `
          <div class="queue-empty-state">
            <div class="queue-empty-icon">🚀</div>
            <h3 style="color: #f8fafc; font-size: 1.1rem; font-weight: 700;">No Dispatched Snapshots Yet</h3>
            <p style="color: var(--text-dim); font-size: 0.85rem;">
              Click <strong>🚀 Push to Explain</strong> to begin streaming snapshots to Kafka.
            </p>
          </div>
        `;
        return;
      }
    }

    // Render snapshot cards
    container.innerHTML = items.map((item) => {
      const isDispatched = item.status === 'dispatched';
      const isDispatching = item.status === 'dispatching';

      return `
        <div class="queue-card ${isDispatching ? 'dispatching' : ''}" data-snap-name="${this._escape(item.name)}">
          <div class="queue-card-left">
            <div class="queue-card-step-badge ${isDispatched ? 'dispatched' : ''}">
              ${isDispatched ? '✓' : `#${item.step}`}
            </div>
            <div class="queue-card-details">
              <div class="queue-card-title">
                <span>📄 ${this._escape(item.name)}</span>
                <span class="badge ${isDispatched ? 'badge-success' : 'badge-info'}" style="font-size: 0.65rem; font-family: var(--font-mono);">
                  ${this._escape(item.type)}
                </span>
              </div>
              <div class="queue-card-meta">
                <span>Sequence: <strong>${this._escape(item.sequenceName)}</strong></span>
                <span>•</span>
                <span>Step ${item.step} of ${item.total}</span>
                ${isDispatched && item.dispatchedAt ? `
                  <span>•</span>
                  <span style="color: #10b981;">Dispatched at ${item.dispatchedAt}</span>
                ` : ''}
              </div>
            </div>
          </div>

          <div class="queue-card-right">
            ${isDispatched ? `
              <span class="badge badge-success" style="display: inline-flex; align-items: center; gap: 0.3rem;">
                <span>✅</span> Delivered to Explain
              </span>
            ` : (isDispatching ? `
              <span class="badge badge-warning" style="display: inline-flex; align-items: center; gap: 0.3rem;">
                <span class="status-dot online"></span> Dispatching...
              </span>
            ` : `
              <span class="badge badge-secondary" style="font-family: var(--font-mono); font-size: 0.72rem;">
                ⏳ Queued
              </span>
              <button class="btn btn-secondary btn-sm btn-publish-single" data-single-snap="${this._escape(item.name)}" title="Push this single snapshot to Kafka">
                Publish
              </button>
            `)}
          </div>
        </div>
      `;
    }).join('');

    // Attach single publish clicks
    container.querySelectorAll('.btn-publish-single').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const snapName = btn.getAttribute('data-single-snap');
        if (snapName) this.publishSingleSnapshot(snapName);
      });
    });
  }

  // =========================================================================
  // MODAL CONTROLS
  // =========================================================================

  openSliceModal() {
    const modal = this.container.querySelector('#modal-slice-alarm');
    if (modal) modal.classList.add('open');
  }

  closeSliceModal() {
    const modal = this.container.querySelector('#modal-slice-alarm');
    if (modal) modal.classList.remove('open');
  }

  openPushModal() {
    if (!this.activeSequence) {
      alert('Please select or slice a sequence first.');
      return;
    }
    const modal = this.container.querySelector('#modal-push-explain');
    const seqSelect = this.container.querySelector('#modal-push-sequence-select');
    if (seqSelect && this.activeSequence) {
      seqSelect.value = this.activeSequence.path;
    }
    if (modal) modal.classList.add('open');
  }

  closePushModal() {
    const modal = this.container.querySelector('#modal-push-explain');
    if (modal) modal.classList.remove('open');
  }

  // =========================================================================
  // SLICE JOB (Modal 1)
  // =========================================================================

  async submitSliceJob() {
    const btn = this.container.querySelector('#btn-run-slicer');
    btn.disabled = true;
    btn.textContent = 'Submitting...';

    this.terminal?.clear();
    this.terminal?.append('Submitting background slice job...', 'info');

    const scenarioId = this.container.querySelector('#slice-scenario-id').value.trim();
    const profileId = this.container.querySelector('#slice-profile-id').value;
    const alarmCsv = this.container.querySelector('#select-slicer-alarm-csv')?.value || 'datasets/raw/alarm/alarm_data.csv';
    const numSnaps = parseInt(this.container.querySelector('#slice-num-snaps').value, 10);
    const stepMins = parseInt(this.container.querySelector('#slice-step-mins').value, 10);
    const windowMins = parseInt(this.container.querySelector('#slice-window-mins').value, 10);

    try {
      const res = await api.submitSliceJob({
        scenario_id: scenarioId,
        profile_id: profileId,
        alarm_csv: alarmCsv,
        num_snapshots: numSnaps,
        step_minutes: stepMins,
        window_minutes: windowMins,
      });

      if (!res.ok) throw new Error(res.error || 'Failed submitting job');
      const job = res.job;
      this.terminal?.append(`Slice job accepted: ${job.job_id}. Tracking progress...`, 'success');
      this.closeSliceModal();

      new JobEventStream(job.job_id, {
        onTerminalMessage: (msg, type) => this.terminal?.append(msg, type),
        onComplete: async (status) => {
          btn.disabled = false;
          btn.innerHTML = `<span>⚡</span> Generate Sliding Sequence`;
          if (status === 'COMPLETED') {
            this.terminal?.append(`Sequence slicing completed! Reloading sequences...`, 'success');
            await this.loadSequences();
            // Find newly generated sequence and select it
            const matched = this.sequences.find(s => s.id === scenarioId || s.path.includes(scenarioId));
            if (matched) {
              const select = this.container.querySelector('#studio-sequence-select');
              if (select) select.value = matched.path;
              this.onSequenceSelected(matched.path);
            }
          } else {
            this.terminal?.append(`Slicing job ended with status: ${status}`, 'error');
          }
        },
      });
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = `<span>⚡</span> Generate Sliding Sequence`;
      this.terminal?.append(`Slice submission failed: ${err.message}`, 'error');
      alert(`Slice error: ${err.message}`);
    }
  }

  // =========================================================================
  // STREAM PUSH TO EXPLAIN & REAL-TIME QUEUE DEPLETION ("RÚT NGẮN DẦN")
  // =========================================================================

  async submitPushJob() {
    const modalSelect = this.container.querySelector('#modal-push-sequence-select');
    const selectedPath = modalSelect?.value || this.activeSequence?.path;
    if (!selectedPath) {
      alert('Please select a sequence to push.');
      return;
    }

    const mode = this.container.querySelector('input[name="modal-stream-mode"]:checked')?.value || 'paced';
    const delaySec = parseFloat(this.container.querySelector('#modal-stream-delay-sec')?.value) || 0.5;
    const topic = this.container.querySelector('#modal-stream-topic')?.value || 'nocpro.snapshot.v1';

    this.closePushModal();
    this.startStreamingPipeline(selectedPath, mode, delaySec, topic);
  }

  async startStreamingPipeline(sequencePath, mode, delaySeconds, topic) {
    this.isStreaming = true;

    // Show Live Streaming HUD
    const hud = this.container.querySelector('#active-stream-hud');
    const hudTitle = this.container.querySelector('#hud-stream-title');
    const hudSub = this.container.querySelector('#hud-stream-sub');
    const hudMode = this.container.querySelector('#hud-stream-mode');
    const hudProgressBar = this.container.querySelector('#hud-progress-bar');
    const hudProgressText = this.container.querySelector('#hud-progress-text');
    const pauseBtn = this.container.querySelector('#btn-hud-pause');
    const resumeBtn = this.container.querySelector('#btn-hud-resume');
    const stopBtn = this.container.querySelector('#btn-hud-stop');

    if (hud) hud.style.display = 'flex';
    if (hudTitle) hudTitle.textContent = `Streaming ${this.activeSequence?.name || 'Sequence'} to Explain...`;
    if (hudSub) hudSub.textContent = `Target Kafka topic: ${topic} (consumer: nocpro-chain-explain)`;
    if (hudMode) hudMode.textContent = mode === 'paced' ? `Paced Delay (${delaySeconds}s)` : 'Single-Shot (Immediate)';
    if (hudProgressBar) hudProgressBar.style.width = '0%';
    if (hudProgressText) hudProgressText.textContent = '0%';

    if (pauseBtn) pauseBtn.disabled = false;
    if (resumeBtn) resumeBtn.disabled = true;
    if (stopBtn) stopBtn.disabled = false;

    this.terminal?.clear();
    this.terminal?.append(`Initializing ${mode === 'paced' ? 'continuous paced stream' : 'single-shot'} for '${sequencePath}'...`, 'info');

    try {
      const res = await api.submitPublishJob({
        type: 'sequence',
        sequence_path: sequencePath,
        mode,
        delay_seconds: delaySeconds,
        topic,
      });

      if (!res.ok) throw new Error(res.error || 'Failed to submit publish job');
      const job = res.job;
      this.currentJobId = job.job_id;
      this.terminal?.append(`Publish job launched: ${job.job_id}. Live Kafka pipe connected.`, 'success');

      if (this.currentJobStream) {
        this.currentJobStream.close();
      }

      this.currentJobStream = new JobEventStream(job.job_id, {
        onStatusChanged: (status) => {
          if (status === 'PAUSED') {
            if (pauseBtn) pauseBtn.disabled = true;
            if (resumeBtn) resumeBtn.disabled = false;
            if (hudTitle) hudTitle.textContent = `Stream Paused`;
          } else if (status === 'RUNNING') {
            if (pauseBtn) pauseBtn.disabled = false;
            if (resumeBtn) resumeBtn.disabled = true;
            if (hudTitle) hudTitle.textContent = `Streaming to Explain in progress...`;
          }
        },

        // Real-Time Queue Depletion ("Rút ngắn dần")
        onProgress: (p) => {
          if (hudProgressBar) hudProgressBar.style.width = `${p.percent}%`;
          if (hudProgressText) hudProgressText.textContent = `${p.percent}% (${p.current}/${p.total})`;

          // Determine which snapshot was just dispatched
          const snapIndex = p.current - 1; // 0-indexed
          this._dispatchSnapshotFromQueue(snapIndex);
        },

        onTerminalMessage: (msg, type) => {
          this.terminal?.append(msg, type);
        },

        onComplete: (status) => {
          this.isStreaming = false;
          if (pauseBtn) pauseBtn.disabled = true;
          if (resumeBtn) resumeBtn.disabled = true;
          if (stopBtn) stopBtn.disabled = true;

          if (status === 'COMPLETED') {
            if (hudProgressBar) hudProgressBar.style.width = '100%';
            if (hudProgressText) hudProgressText.textContent = '100%';
            if (hudTitle) hudTitle.textContent = `✅ All Snapshots Delivered to Explain!`;
            this.terminal?.append(`All snapshots published successfully to topic '${topic}'!`, 'success');

            // Drain any remaining pending snapshots to dispatched
            while (this.pendingSnapshots.length > 0) {
              this._dispatchSnapshotFromQueue(0, true);
            }

            setTimeout(() => {
              if (hud && !this.isStreaming) hud.style.display = 'none';
            }, 3500);
          } else if (status === 'STOPPED') {
            if (hudTitle) hudTitle.textContent = `Stream Stopped`;
            this.terminal?.append('Stream safely halted at snapshot barrier.', 'warn');
          } else {
            if (hudTitle) hudTitle.textContent = `Stream Ended: ${status}`;
            this.terminal?.append(`Stream ended with status: ${status}`, 'error');
          }
        },
      });
    } catch (err) {
      this.isStreaming = false;
      if (hud) hud.style.display = 'none';
      this.terminal?.append(`Publish error: ${err.message}`, 'error');
      alert(`Stream launch failed: ${err.message}`);
    }
  }

  /**
   * The magic "Rút ngắn dần" core logic:
   * Moves snapshot from pendingSnapshots to dispatchedSnapshots,
   * animates the card out of the DOM, and updates queue counts in real-time.
   */
  _dispatchSnapshotFromQueue(index, immediate = false) {
    if (this.pendingSnapshots.length === 0) return;

    // Pick snapshot at index or first pending
    const item = this.pendingSnapshots[index] || this.pendingSnapshots[0];
    if (!item) return;

    item.status = 'dispatched';
    item.dispatchedAt = new Date().toLocaleTimeString();

    // Move to dispatched list
    const pIdx = this.pendingSnapshots.indexOf(item);
    if (pIdx > -1) {
      this.pendingSnapshots.splice(pIdx, 1);
    }
    this.dispatchedSnapshots.push(item);

    // Update count badges immediately
    this.updateBadges();

    // DOM animation for pending tab
    if (this.activeTab === 'pending') {
      const card = this.container.querySelector(`[data-snap-name="${item.name}"]`);
      if (card) {
        if (immediate) {
          card.remove();
        } else {
          card.classList.add('dispatching');
          setTimeout(() => {
            card.classList.remove('dispatching');
            card.classList.add('dispatched-leaving');
            setTimeout(() => {
              card.remove();
              if (this.pendingSnapshots.length === 0) {
                this.renderQueue();
              }
            }, 350);
          }, 300);
        }
      } else if (this.pendingSnapshots.length === 0) {
        this.renderQueue();
      }
    } else {
      this.renderQueue();
    }
  }

  // =========================================================================
  // SINGLE SNAPSHOT PUBLISH
  // =========================================================================

  async publishSingleSnapshot(snapName) {
    if (!this.activeSequence) return;
    const item = this.pendingSnapshots.find(s => s.name === snapName);

    this.terminal?.clear();
    this.terminal?.append(`Publishing single snapshot '${snapName}' to Kafka...`, 'info');

    // Highlight card
    const card = this.container.querySelector(`[data-snap-name="${snapName}"]`);
    if (card) card.classList.add('dispatching');

    try {
      const res = await api.submitPublishJob({
        type: 'single',
        mode: 'sequence',
        sequence_path: this.activeSequence.path,
        sequence_snapshot: snapName,
        topic: 'nocpro.snapshot.v1',
      });

      if (!res.ok) throw new Error(res.error || 'Failed submitting publish job');
      const job = res.job;
      this.terminal?.append(`Single publish accepted: ${job.job_id}. Tracking...`, 'success');

      new JobEventStream(job.job_id, {
        onTerminalMessage: (msg, type) => this.terminal?.append(msg, type),
        onComplete: (status) => {
          if (status === 'COMPLETED') {
            this.terminal?.append(`Snapshot '${snapName}' successfully pushed to Explain!`, 'success');
            // Animate out of pending queue!
            const idx = this.pendingSnapshots.findIndex(s => s.name === snapName);
            if (idx > -1) {
              this._dispatchSnapshotFromQueue(idx);
            }
          } else {
            if (card) card.classList.remove('dispatching');
            this.terminal?.append(`Job ended with status: ${status}`, 'error');
          }
        },
      });
    } catch (err) {
      if (card) card.classList.remove('dispatching');
      this.terminal?.append(`Single publish failed: ${err.message}`, 'error');
      alert(`Publish error: ${err.message}`);
    }
  }

  // =========================================================================
  // STREAM CONTROL (Pause / Resume / Stop)
  // =========================================================================

  async pauseStream() {
    if (!this.currentJobId) return;
    this.terminal?.append(`Sending pause signal to Kafka streamer...`, 'warn');
    try {
      await api.pauseJob(this.currentJobId);
    } catch (err) {
      alert(`Pause failed: ${err.message}`);
    }
  }

  async resumeStream() {
    if (!this.currentJobId) return;
    this.terminal?.append(`Sending resume signal to Kafka streamer...`, 'info');
    try {
      await api.resumeJob(this.currentJobId);
    } catch (err) {
      alert(`Resume failed: ${err.message}`);
    }
  }

  async stopStream() {
    if (!this.currentJobId) return;
    this.terminal?.append(`Sending stop signal to Kafka streamer...`, 'warn');
    try {
      await api.stopJob(this.currentJobId);
    } catch (err) {
      alert(`Stop failed: ${err.message}`);
    }
  }

  _escape(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
}

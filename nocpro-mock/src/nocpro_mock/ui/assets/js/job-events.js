/**
 * SSE Job Event Stream Manager.
 */

import { api } from './api.js';

export class JobEventStream {
  constructor(jobId, { onProgress, onStatusChanged, onTerminalMessage, onComplete, onError }) {
    this.jobId = jobId;
    this.onProgress = onProgress;
    this.onStatusChanged = onStatusChanged;
    this.onTerminalMessage = onTerminalMessage;
    this.onComplete = onComplete;
    this.onError = onError;
    this.eventSource = null;
    this._connect();
  }

  _connect() {
    const url = api.getSseUrl(this.jobId);
    this.eventSource = new EventSource(url);

    this.eventSource.addEventListener('init', (e) => {
      try {
        const job = JSON.parse(e.data);
        if (this.onStatusChanged) this.onStatusChanged(job.status, job);
        if (this.onTerminalMessage) this.onTerminalMessage(`Connected to job ${this.jobId} (status: ${job.status})`, 'info');
      } catch (err) {
        console.error('Failed parsing init SSE event', err);
      }
    });

    this.eventSource.addEventListener('status_changed', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (this.onStatusChanged) this.onStatusChanged(data.to, data);
        if (this.onTerminalMessage) this.onTerminalMessage(`Status changed: ${data.from} -> ${data.to} ${data.message || ''}`, 'info');

        if (['COMPLETED', 'FAILED', 'STOPPED', 'CANCELLED'].includes(data.to)) {
          if (this.onComplete) this.onComplete(data.to);
          this.close();
        }
      } catch (err) {
        console.error('Failed parsing status_changed event', err);
      }
    });

    this.eventSource.addEventListener('progress', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (this.onProgress) this.onProgress(data);
        if (this.onTerminalMessage) {
          this.onTerminalMessage(`[${data.current}/${data.total}] ${data.message || ''}`, 'info');
        }
      } catch (err) {
        console.error('Failed parsing progress event', err);
      }
    });

    this.eventSource.addEventListener('paused', () => {
      if (this.onTerminalMessage) this.onTerminalMessage(`Job ${this.jobId} is PAUSED at snapshot barrier`, 'warn');
      if (this.onStatusChanged) this.onStatusChanged('PAUSED');
    });

    this.eventSource.addEventListener('resumed', () => {
      if (this.onTerminalMessage) this.onTerminalMessage(`Job ${this.jobId} RESUMED`, 'success');
      if (this.onStatusChanged) this.onStatusChanged('RUNNING');
    });

    this.eventSource.addEventListener('error', (e) => {
      if (e.data) {
        try {
          const data = JSON.parse(e.data);
          if (this.onTerminalMessage) this.onTerminalMessage(`Error: ${data.error}`, 'error');
        } catch (_) {}
      }
    });

    this.eventSource.onerror = () => {
      // EventSource reconnects automatically, or close if completed
    };
  }

  close() {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}

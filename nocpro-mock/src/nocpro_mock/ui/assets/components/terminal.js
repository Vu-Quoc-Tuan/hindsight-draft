/**
 * Terminal Component: Emulates a live streaming developer console.
 */

export class StreamingTerminal {
  constructor(container, { title = 'Event Console' } = {}) {
    this.container = container;
    this.title = title;
    this._renderShell();
  }

  _renderShell() {
    this.container.innerHTML = `
      <div class="terminal">
        <div class="terminal-header">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <div class="terminal-controls">
              <span class="term-dot red"></span>
              <span class="term-dot yellow"></span>
              <span class="term-dot green"></span>
            </div>
            <span style="font-weight: 600; font-size: 0.75rem; color: var(--text-muted); margin-left: 0.5rem;">${this.title}</span>
          </div>
          <button class="btn btn-sm btn-secondary" style="font-size: 0.7rem; padding: 0.15rem 0.5rem;" id="term-clear-btn">Clear</button>
        </div>
        <div class="terminal-body" id="terminal-lines">
          <div class="term-line"><span class="term-time">[READY]</span> <span class="term-msg info">Listening for events...</span></div>
        </div>
      </div>
    `;

    this.body = this.container.querySelector('#terminal-lines');
    this.container.querySelector('#term-clear-btn').addEventListener('click', () => this.clear());
  }

  append(message, type = 'info') {
    const now = new Date().toTimeString().split(' ')[0];
    const line = document.createElement('div');
    line.className = 'term-line';
    line.innerHTML = `
      <span class="term-time">[${now}]</span>
      <span class="term-msg ${type}">${escapeHtml(message)}</span>
    `;
    this.body.appendChild(line);

    // Keep maximum 500 lines
    while (this.body.children.length > 500) {
      this.body.removeChild(this.body.firstChild);
    }

    this.body.scrollTop = this.body.scrollHeight;
  }

  clear() {
    this.body.innerHTML = '';
  }
}

function escapeHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

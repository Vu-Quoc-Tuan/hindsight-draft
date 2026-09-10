/**
 * Centralized State Management for NocPro Mock Studio.
 */

class Store {
  constructor() {
    this.state = {
      activeScreen: 'explorer', // 'explorer' | 'topology' | 'slicer'
      datasets: [],
      selectedDatasetId: 'alarm_data',
      alarmFilters: {
        severity: '',
        quality_flag: '',
        device_code: '',
        alarm_name: '',
        chaining_id: '',
        search: '',
      },
      currentCursor: null,
      cursorStack: [],
      selectedAlarmRow: null,
      selectedTopoProfile: 'IP_NETWORK',
      activeJobs: {},
      kafkaConnected: false,
      kafkaBootstrap: 'localhost:9092',
    };
    this.listeners = new Set();
  }

  getState() {
    return this.state;
  }

  setState(updates) {
    this.state = { ...this.state, ...updates };
    this.notify();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    for (const listener of this.listeners) {
      try {
        listener(this.state);
      } catch (err) {
        console.error('State subscriber error:', err);
      }
    }
  }
}

export const store = new Store();

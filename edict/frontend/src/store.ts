/**
 * Zustand Store — 三省六部看板状态管理
 * HTTP 5s 轮询，无 WebSocket
 */

import { create } from 'zustand';
import {
  api,
  type AgentConfig,
  type AgentsStatusData,
  type ChangeLogEntry,
  type LiveStatus,
  type MorningBrief,
  type OfficialsData,
  type SubConfig,
} from './api';
import type { TabKey } from './constants';

interface AppStore {
  // Data
  liveStatus: LiveStatus | null;
  agentConfig: AgentConfig | null;
  changeLog: ChangeLogEntry[];
  officialsData: OfficialsData | null;
  agentsStatusData: AgentsStatusData | null;
  morningBrief: MorningBrief | null;
  subConfig: SubConfig | null;

  // UI State
  activeTab: TabKey;
  edictFilter: 'active' | 'archived' | 'all';
  sessFilter: string;
  tplCatFilter: string;
  selectedOfficial: string | null;
  modalTaskId: string | null;
  countdown: number;

  // Toast
  toasts: { id: number; msg: string; type: 'ok' | 'err' }[];

  // Actions
  setActiveTab: (tab: TabKey) => void;
  setEdictFilter: (f: 'active' | 'archived' | 'all') => void;
  setSessFilter: (f: string) => void;
  setTplCatFilter: (f: string) => void;
  setSelectedOfficial: (id: string | null) => void;
  setModalTaskId: (id: string | null) => void;
  setCountdown: (n: number) => void;
  toast: (msg: string, type?: 'ok' | 'err') => void;

  // Data fetching
  loadLive: () => Promise<void>;
  loadAgentConfig: () => Promise<void>;
  loadOfficials: () => Promise<void>;
  loadAgentsStatus: () => Promise<void>;
  loadMorning: () => Promise<void>;
  loadSubConfig: () => Promise<void>;
  loadAll: () => Promise<void>;
}

let toastId = 0;

export const useStore = create<AppStore>((set, get) => ({
  liveStatus: null,
  agentConfig: null,
  changeLog: [],
  officialsData: null,
  agentsStatusData: null,
  morningBrief: null,
  subConfig: null,

  activeTab: 'edicts',
  edictFilter: 'active',
  sessFilter: 'all',
  tplCatFilter: '全部',
  selectedOfficial: null,
  modalTaskId: null,
  countdown: 5,

  toasts: [],

  setActiveTab: (tab) => {
    set({ activeTab: tab });
    const state = get();
    if (['models', 'skills', 'sessions'].includes(tab) && !state.agentConfig) state.loadAgentConfig();
    if (tab === 'officials' && !state.officialsData) state.loadOfficials();
    if (tab === 'monitor') state.loadAgentsStatus();
    if (tab === 'morning' && !state.morningBrief) state.loadMorning();
  },
  setEdictFilter: (f) => set({ edictFilter: f }),
  setSessFilter: (f) => set({ sessFilter: f }),
  setTplCatFilter: (f) => set({ tplCatFilter: f }),
  setSelectedOfficial: (id) => set({ selectedOfficial: id }),
  setModalTaskId: (id) => set({ modalTaskId: id }),
  setCountdown: (n) => set({ countdown: n }),

  toast: (msg, type = 'ok') => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts, { id, msg, type }] }));
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
    }, 3000);
  },

  loadLive: async () => {
    try {
      const data = await api.liveStatus();
      set({ liveStatus: data });
      const state = get();
      if (!state.officialsData) {
        api.officialsStats().then((d) => set({ officialsData: d })).catch(() => {});
      }
    } catch {
      // silently fail
    }
  },

  loadAgentConfig: async () => {
    try {
      const [cfg, log] = await Promise.all([api.agentConfig(), api.modelChangeLog()]);
      set({ agentConfig: cfg, changeLog: log });
    } catch {
      // silently fail
    }
  },

  loadOfficials: async () => {
    try {
      const data = await api.officialsStats();
      set({ officialsData: data });
    } catch {
      // silently fail
    }
  },

  loadAgentsStatus: async () => {
    try {
      const data = await api.agentsStatus();
      set({ agentsStatusData: data });
    } catch {
      set({ agentsStatusData: null });
    }
  },

  loadMorning: async () => {
    try {
      const [brief, config] = await Promise.all([api.morningBrief(), api.morningConfig()]);
      set({ morningBrief: brief, subConfig: config });
    } catch {
      // silently fail
    }
  },

  loadSubConfig: async () => {
    try {
      const config = await api.morningConfig();
      set({ subConfig: config });
    } catch {
      // silently fail
    }
  },

  loadAll: async () => {
    const state = get();
    await state.loadLive();
    if (['models', 'skills'].includes(state.activeTab)) {
      await state.loadAgentConfig();
    }
  },
}));

let countdownTimer: ReturnType<typeof setInterval> | null = null;

export function startPolling() {
  if (countdownTimer) return;
  useStore.getState().loadAll();
  countdownTimer = setInterval(() => {
    const state = useStore.getState();
    const nextCountdown = state.countdown - 1;
    if (nextCountdown <= 0) {
      state.setCountdown(5);
      state.loadAll();
    } else {
      state.setCountdown(nextCountdown);
    }
  }, 1000);
}

export function stopPolling() {
  if (!countdownTimer) return;
  clearInterval(countdownTimer);
  countdownTimer = null;
}

export {
  DEPTS,
  PIPE,
  STATE_LABEL,
  TAB_DEFS,
  TEMPLATES,
  TPL_CATS,
  type TabKey,
} from './constants';
export { deptColor, getPipeStatus, inferTaskDept, isArchived, isEdict, isSession, stateLabel, type PipeStatus } from './utils/task';
export { esc, timeAgo } from './utils/time';
export type { Template, TemplateParam } from './types/template';

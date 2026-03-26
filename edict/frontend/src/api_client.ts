import type {
  ActionResult,
  AgentConfig,
  AgentsStatusData,
  ChangeLogEntry,
  CourtDiscussResult,
  CreateTaskPayload,
  LiveStatus,
  MorningBrief,
  OfficialsData,
  RemoteSkillsListResult,
  ScanAction,
  SchedulerStateData,
  SkillContentResult,
  SubConfig,
  TaskActivityData,
} from './api_types';

const API_BASE = import.meta.env.VITE_API_URL || '';

async function fetchJ<T>(url: string): Promise<T> {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(String(res.status));
  return res.json();
}

async function postJ<T>(url: string, data: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

export const api = {
  liveStatus: () => fetchJ<LiveStatus>(`${API_BASE}/api/live-status`),
  agentConfig: () => fetchJ<AgentConfig>(`${API_BASE}/api/agent-config`),
  modelChangeLog: () => fetchJ<ChangeLogEntry[]>(`${API_BASE}/api/model-change-log`).catch(() => []),
  officialsStats: () => fetchJ<OfficialsData>(`${API_BASE}/api/officials-stats`),
  morningBrief: () => fetchJ<MorningBrief>(`${API_BASE}/api/morning-brief`),
  morningConfig: () => fetchJ<SubConfig>(`${API_BASE}/api/morning-config`),
  agentsStatus: () => fetchJ<AgentsStatusData>(`${API_BASE}/api/agents-status`),

  taskActivity: (id: string) =>
    fetchJ<TaskActivityData>(`${API_BASE}/api/task-activity/${encodeURIComponent(id)}`),
  schedulerState: (id: string) =>
    fetchJ<SchedulerStateData>(`${API_BASE}/api/scheduler-state/${encodeURIComponent(id)}`),

  skillContent: (agentId: string, skillName: string) =>
    fetchJ<SkillContentResult>(
      `${API_BASE}/api/skill-content/${encodeURIComponent(agentId)}/${encodeURIComponent(skillName)}`
    ),

  setModel: (agentId: string, model: string) =>
    postJ<ActionResult>(`${API_BASE}/api/set-model`, { agentId, model }),
  setDispatchChannel: (channel: string) =>
    postJ<ActionResult>(`${API_BASE}/api/set-dispatch-channel`, { channel }),
  agentWake: (agentId: string) =>
    postJ<ActionResult>(`${API_BASE}/api/agent-wake`, { agentId }),
  taskAction: (taskId: string, action: string, reason: string) =>
    postJ<ActionResult>(`${API_BASE}/api/task-action`, { taskId, action, reason }),
  reviewAction: (taskId: string, action: string, comment: string) =>
    postJ<ActionResult>(`${API_BASE}/api/review-action`, { taskId, action, comment }),
  advanceState: (taskId: string, comment: string) =>
    postJ<ActionResult>(`${API_BASE}/api/advance-state`, { taskId, comment }),
  archiveTask: (taskId: string, archived: boolean) =>
    postJ<ActionResult>(`${API_BASE}/api/archive-task`, { taskId, archived }),
  archiveAllDone: () =>
    postJ<ActionResult & { count?: number }>(`${API_BASE}/api/archive-task`, { archiveAllDone: true }),
  deleteTask: (taskId: string) =>
    postJ<ActionResult>(`${API_BASE}/api/delete-task`, { taskId }),
  schedulerScan: (thresholdSec = 180) =>
    postJ<ActionResult & { count?: number; actions?: ScanAction[]; checkedAt?: string }>(
      `${API_BASE}/api/scheduler-scan`,
      { thresholdSec }
    ),
  schedulerRetry: (taskId: string, reason: string) =>
    postJ<ActionResult>(`${API_BASE}/api/scheduler-retry`, { taskId, reason }),
  schedulerEscalate: (taskId: string, reason: string) =>
    postJ<ActionResult>(`${API_BASE}/api/scheduler-escalate`, { taskId, reason }),
  schedulerRollback: (taskId: string, reason: string) =>
    postJ<ActionResult>(`${API_BASE}/api/scheduler-rollback`, { taskId, reason }),
  refreshMorning: () =>
    postJ<ActionResult>(`${API_BASE}/api/morning-brief/refresh`, {}),
  saveMorningConfig: (config: SubConfig) =>
    postJ<ActionResult>(`${API_BASE}/api/morning-config`, config),
  addSkill: (agentId: string, skillName: string, description: string, trigger: string) =>
    postJ<ActionResult>(`${API_BASE}/api/add-skill`, { agentId, skillName, description, trigger }),

  addRemoteSkill: (agentId: string, skillName: string, sourceUrl: string, description?: string) =>
    postJ<ActionResult & { skillName?: string; agentId?: string; source?: string; localPath?: string; size?: number; addedAt?: string }>(
      `${API_BASE}/api/add-remote-skill`,
      { agentId, skillName, sourceUrl, description: description || '' }
    ),
  remoteSkillsList: () =>
    fetchJ<RemoteSkillsListResult>(`${API_BASE}/api/remote-skills-list`),
  updateRemoteSkill: (agentId: string, skillName: string) =>
    postJ<ActionResult>(`${API_BASE}/api/update-remote-skill`, { agentId, skillName }),
  removeRemoteSkill: (agentId: string, skillName: string) =>
    postJ<ActionResult>(`${API_BASE}/api/remove-remote-skill`, { agentId, skillName }),

  createTask: (data: CreateTaskPayload) =>
    postJ<ActionResult & { taskId?: string }>(`${API_BASE}/api/create-task`, data),

  courtDiscussStart: (topic: string, officials: string[], taskId?: string) =>
    postJ<CourtDiscussResult>(`${API_BASE}/api/court-discuss/start`, { topic, officials, taskId }),
  courtDiscussAdvance: (sessionId: string, userMessage?: string, decree?: string) =>
    postJ<CourtDiscussResult>(`${API_BASE}/api/court-discuss/advance`, { sessionId, userMessage, decree }),
  courtDiscussConclude: (sessionId: string) =>
    postJ<ActionResult & { summary?: string }>(`${API_BASE}/api/court-discuss/conclude`, { sessionId }),
  courtDiscussDestroy: (sessionId: string) =>
    postJ<ActionResult>(`${API_BASE}/api/court-discuss/destroy`, { sessionId }),
  courtDiscussFate: () =>
    fetchJ<{ ok: boolean; event: string }>(`${API_BASE}/api/court-discuss/fate`),
};

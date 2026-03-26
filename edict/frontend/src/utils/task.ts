import type { Task } from '../api';
import { DEPT_COLOR, HANLIN_PIPE, PIPE, PIPE_STATE_IDX, STATE_LABEL } from '../constants';

export function deptColor(dept: string): string {
  return DEPT_COLOR[dept] || '#6a9eff';
}

export function stateLabel(task: Task): string {
  const reviewRound = task.review_round || 0;
  if (task.state === 'Menxia' && reviewRound > 1) return `门下审议（第${reviewRound}轮）`;
  if (task.state === 'Zhongshu' && reviewRound > 0) return `中书修订（第${reviewRound}轮）`;
  return STATE_LABEL[task.state] || task.state;
}

export function isEdict(task: Task): boolean {
  return /^JJC-/i.test(task.id || '');
}

export function isSession(task: Task): boolean {
  return /^(OC-|MC-)/i.test(task.id || '');
}

export function isArchived(task: Task): boolean {
  return task.archived || ['Done', 'Cancelled'].includes(task.state);
}

export type PipeStatus = {
  key: string;
  dept: string;
  icon: string;
  action: string;
  status: 'done' | 'active' | 'pending';
};

export function getPipeStatus(task: Task): PipeStatus[] {
  const flowLog = task.flow_log || [];
  const hasHanlin = (task.org || '') === '翰林院'
    || flowLog.some((f) => (f.from || '') === '翰林院' || (f.to || '') === '翰林院')
    || task.sourceMeta?.agentId === 'hanlinyuan';
  const hasClassic = flowLog.some((f) => ['中书省', '门下省', '尚书省', '礼部', '户部', '兵部', '刑部', '工部', '吏部'].includes(f.from || '')
    || ['中书省', '门下省', '尚书省', '礼部', '户部', '兵部', '刑部', '工部', '吏部'].includes(f.to || ''));
  const isHanlinFlow = (hasHanlin && !hasClassic)
    || ((task.title || '').startsWith('论文') && !hasClassic);

  if (isHanlinFlow) {
    const terminal = ['Done', 'Cancelled'].includes(task.state);
    const idx = terminal ? 3 : (
      ['Inbox', 'Pending'].includes(task.state) ? 0 : (task.state === 'Taizi' ? 1 : 2)
    );
    return HANLIN_PIPE.map((stage, index) => ({
      ...stage,
      status: (index < idx ? 'done' : index === idx ? 'active' : 'pending') as PipeStatus['status'],
    }));
  }

  const stateIndex = PIPE_STATE_IDX[task.state] ?? 4;
  return PIPE.map((stage, index) => ({
    ...stage,
    status: (index < stateIndex ? 'done' : index === stateIndex ? 'active' : 'pending') as PipeStatus['status'],
  }));
}

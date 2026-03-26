import type { Task } from '../api';
import { DEPT_COLOR, PIPE, PIPE_STATE_IDX, STATE_LABEL } from '../constants';

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
  const stateIndex = PIPE_STATE_IDX[task.state] ?? 4;
  return PIPE.map((stage, index) => ({
    ...stage,
    status: (index < stateIndex ? 'done' : index === stateIndex ? 'active' : 'pending') as PipeStatus['status'],
  }));
}

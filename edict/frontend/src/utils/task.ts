import type { Task } from '../api';
import { DEPT_COLOR, PAPER_PIPE, PAPER_PIPE_STATE_IDX, PIPE, PIPE_STATE_IDX, STATE_LABEL } from '../constants';

type PipelineConfig = {
  pipe: readonly { key: string; dept: string; icon: string; action: string }[];
  stateIndexMap: Record<string, number>;
};

export function deptColor(dept: string): string {
  return DEPT_COLOR[dept] || '#6a9eff';
}

export function isPaperTask(task: Task): boolean {
  return (task.title || '').trim().startsWith('论文');
}

function getPipelineConfig(task: Task): PipelineConfig {
  if (isPaperTask(task)) {
    return { pipe: PAPER_PIPE, stateIndexMap: PAPER_PIPE_STATE_IDX };
  }
  return { pipe: PIPE, stateIndexMap: PIPE_STATE_IDX };
}

function paperStateLabel(state: string, reviewRound: number): string | null {
  if (state === 'Zhongshu') return '翰林院执行';
  if (state === 'Menxia') return `大理寺审议${reviewRound > 1 ? `（第${reviewRound}轮）` : ''}`;
  if (['Assigned', 'Doing', 'Review', 'Next'].includes(state)) return '太子协调回奏';
  return null;
}

export function stateLabel(task: Task): string {
  const reviewRound = task.review_round || 0;
  if (isPaperTask(task)) {
    const label = paperStateLabel(task.state, reviewRound);
    if (label) return label;
  }

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
  const { pipe, stateIndexMap } = getPipelineConfig(task);
  const stateIndex = stateIndexMap[task.state] ?? 4;

  return pipe.map((stage, index) => ({
    ...stage,
    status: (index < stateIndex ? 'done' : index === stateIndex ? 'active' : 'pending') as PipeStatus['status'],
  }));
}

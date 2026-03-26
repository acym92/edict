# Hanlin 使用说明（论文路由）

本说明仅用于 **本项目内** 的论文路由约定，不会自动同步到 OpenClaw workspace。

## 入口规则

- 当太子接收到以 `论文` 开头的指令时，走翰林院专线（Hanlin）。
- 推荐格式：`论文/<关键字> <你的需求>`

## 关键字 → 技能映射

- `论文/主题` → `research-pipeline`
- `论文/审稿` → `auto-review-loop`
- `论文/修改` → `paper-writing`
- `论文/方向` → `experiment-bridge`
- 其他 `论文/...` → 由模型自行判断最合适技能

## 示例

```text
论文/主题 做一个关于长上下文检索增强的研究计划，给出实验路线
论文/审稿 这是我的方法章节草稿，请按会议审稿标准给出循环改进建议
论文/修改 把已有实验结果组织成可投稿论文结构并补齐叙事
论文/方向 评估这个想法是否值得投入实验，并给出最小可行实验
```

## 全流程能力（题目 → 高质量论文）

翰林院默认按以下链路执行（可按任务裁剪）：
1. 文献扫描（lit_scan）
2. 方案生成与筛选（idea_report）
3. 实验与回归（experiment_plan / runbook / experiment_log）
4. 论文初稿（paper_draft）
5. 审稿循环（review_loop，默认最多4轮）
6. 修订定稿（final_paper + final_summary）

> 产出目录统一：`/root/.openclaw/output/<任务ID>/`

## 与系统流转的关系

1. 太子识别到 `论文...` 前缀后，将任务状态置为 `Hanlin` 并转派 `hanlin`。
2. Hanlin 按上述映射选择技能执行。
3. 完成后通过 `kanban_update.py` 回写进度与完成态（`Done`）。

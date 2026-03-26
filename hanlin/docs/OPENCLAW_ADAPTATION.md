# OpenClaw 适配指南（ARIS Workflow）

> 目标：在**没有 Claude Code slash 技能**的情况下，把 ARIS 核心科研流程迁移到 OpenClaw，做到“给一个论文题目 → 自动完成文献、实验、写作、审稿、修改、定稿”。

## 1. 适配思路（完整版）

ARIS 的关键不是某个命令，而是可追踪的科研编排：

1. 文献扫描与问题定义（Research Brief）
2. 创新方案生成与筛选（Idea + Novelty Check）
3. 实验/回归计划与执行（Experiment + Regression）
4. 论文初稿生成（Paper Draft）
5. 审稿循环与最小修复动作（Auto Review Loop）
6. 修改后定稿与交付（Final Paper Package）

在 OpenClaw 中，使用“**阶段化任务 + 文件化产出 + 看板进度回写**”替代 slash 技能链路。

---

## 2. 对应关系（ARIS → OpenClaw）

| ARIS /skill | OpenClaw 等价执行方式 | 必交产出 |
|---|---|---|
| `/research-lit` | 扫描文献并形成结构化综述 | `lit_scan.md` |
| `/idea-creator` | 生成候选方案 + 风险 + MVP | `idea_report.md` |
| `/run-experiment` | 生成实验矩阵、运行脚本、回归计划 | `experiment_plan.md` / `runbook.md` / `experiment_log.md` |
| `/paper-writing` | 组织完整论文叙事与章节 | `paper_draft.md` |
| `/auto-review-loop` | 审稿打分、缺陷定位、最小修复动作 | `review_loop.md` |
| 全流程 | 串联执行并形成最终交付包 | `final_paper.md` / `submission_checklist.md` |

> 默认输出根目录：`/root/.openclaw/output/<task_id>/`

---

## 3. 一键全流程（论文题目驱动）

当收到 `论文/主题 <题目>`，按以下顺序执行（每步都要落盘）：

### 阶段 1：文献扫描 + 问题定义
```text
执行阶段1：围绕论文题目做文献扫描，输出 lit_scan.md（含10-30篇核心文献、差距表、5个研究空白）。
```

### 阶段 2：方案生成 + 新颖性筛选
```text
执行阶段2：基于 lit_scan.md 产出3个方案，输出 idea_report.md（每个方案含动机、创新点、失败信号、MVP），并选 Top1/Top2。
```

### 阶段 3：实验与回归
```text
执行阶段3：基于 Top1 生成 experiment_plan.md 与 runbook.md；执行后写 experiment_log.md，至少包含基线、主实验、消融、回归验证。
```

### 阶段 4：论文写作
```text
执行阶段4：把阶段1-3证据组织为 paper_draft.md，结构必须覆盖 摘要/引言/相关工作/方法/实验/结论/局限。
```

### 阶段 5：自动审稿循环（最多 4 轮）
```text
执行阶段5：启动 review loop，轮次<=4；每轮输出评分、主要缺陷、最小修复动作，并更新 review_loop.md。
```

### 阶段 6：修订与定稿交付
```text
执行阶段6：根据 review_loop.md 完成修订，输出 final_paper.md + submission_checklist.md + final_summary.md。
```

---

## 4. 质量闸门（未通过不得 Done）

1. **证据闭环**：final_paper 的核心结论必须可追溯到文献或实验日志。  
2. **实验完整性**：必须至少包含 baseline + 主结果 + 消融/回归之一。  
3. **审稿闭环**：review_loop 中每个关键缺陷都要有“修复动作/不修复理由”。  
4. **可交付性**：必须产出 `final_paper.md` 与 `submission_checklist.md`。  
5. **看板一致性**：阶段进展用 `progress` 回写，完成后 `done` 指向最终文件路径。  

---

## 5. OpenClaw 实施建议

1. **文件优先**：每阶段必须有明确文件，避免上下文漂移。  
2. **轮次控制**：review loop 默认最多 4 轮，防止无穷迭代。  
3. **证据可追溯**：引用文献需写来源链接/DOI/定位信息。  
4. **目录标准化**：统一在 `/root/.openclaw/output/<task_id>/` 存放产出。  
5. **失败可恢复**：每阶段产出可单独重跑，不需整链重来。  

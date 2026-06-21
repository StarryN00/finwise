# First Run Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让生产空库和新用户首次进入系统时，首页能明确引导完成开账准备，并把左侧菜单整理成更清晰的日常工作路径。
**Architecture:** 仅改前端展示与导航组织，不改后端接口。首页通过 `workspace` store 的企业、工作包和待确认数据推导当前引导状态。
**Tech Stack:** Vue 3、Element Plus、Vitest 源码测试。

---

## Task 1: 先补测试

- [ ] 新增 `WorkspaceHomeView.spec.js`，断言首页包含开账准备、六步路径、空库入口、关键路由和 `el-empty`。
- [ ] 更新 `AppLayout.spec.js`，断言新菜单分组、隐藏“账目明细”、保留 `/account-details` 路由、顶部创建工作包保护逻辑。
- [ ] 运行 `npm test -- WorkspaceHomeView AppLayout`，确认测试先失败。

## Task 2: 实现首页开账引导

- [ ] 在 `WorkspaceHomeView.vue` 新增“开账准备”区块。
- [ ] 根据企业和工作包状态计算主动作、辅助动作和步骤状态。
- [ ] 空工作包时展示清晰空状态，不再只显示空表。
- [ ] 保持月度工作包表格和状态筛选可用。

## Task 3: 整理主导航

- [ ] 在 `AppLayout.vue` 调整左侧菜单分组。
- [ ] 从主导航隐藏“账目明细”，保留路由。
- [ ] 顶部“创建本月工作包”在无企业时提示并跳转企业初始化页。

## Task 4: 验证

- [ ] 运行 `npm test -- WorkspaceHomeView AppLayout`。
- [ ] 运行前端构建 `npm run build`。
- [ ] 检查 git diff，确保未包含既有的后端依赖变更。

## Task 5: 提交与部署

- [ ] 仅暂存本次相关文件。
- [ ] 提交 commit。
- [ ] 推送远程分支。
- [ ] 如果当前环境允许访问生产服务器，则部署并验证生产页面；如果网络受限，明确说明未部署。

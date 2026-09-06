# Frontend Technical Decision V1

状态：Round 1 已实现的前端基线。本文只约束 `10_frontend/`，不改变根合同、后端、数据库或任何工程模块的实现。

## 1. 决策摘要

采用 Vue 3 + TypeScript + Vite + Pinia + Vue Router，使用 Tailwind CSS 4 作为令牌和布局层，使用 shadcn-vue / Reka UI 承载可访问的交互原语，使用 `@lucide/vue` 提供图标，使用 Apache ECharts 提供两类必要图表。前端以 typed service 和 mock adapter 作为边界，页面不直接访问模型、RAG、Safety 或 Python 模块。

Round 1 的目标是完成一条可运行的产品垂直切片：登录 → 学生首页 → CAT Focus Mode → 学生结果 → 教师工作区 → 复核队列 → 复核详情。真实后端接入、真实认证、生产数据和 Parent / Marketing / 复杂 Admin 不在本轮范围内。

## 2. 实际工具链

版本取自本次 `npm install` 后的实际依赖树：

| 层 | 版本 |
| --- | --- |
| Node.js | 24.15.0 |
| npm | 12.0.2 |
| Vue | 3.5.42 |
| TypeScript | 5.9.3 |
| Vite | 8.2.2 |
| Pinia | 4.0.3 |
| Vue Router | 5.3.1 |
| Tailwind CSS | 4.3.3 |
| `@tailwindcss/vite` | 4.3.3 |
| shadcn-vue | 2.8.2 |
| Reka UI | 2.10.4 |
| `@lucide/vue` | 1.41.0 |
| Apache ECharts | 6.1.0 |
| Vitest | 5.0.0 |
| Vue Test Utils | 2.5.0 |
| Playwright | 1.63.0 |
| ESLint / eslint-plugin-vue | 10.10.0 / 10.10.0 |
| vue-tsc | 3.3.11 |

## 3. 为什么采用这一组合

- Vue 3 和 TypeScript 与项目的前端任务及现有 Windows 开发环境匹配，组件边界清晰，适合本轮小而完整的纵向切片。
- Vite 提供直接的开发、构建和预览路径；`vue-tsc` 将模板类型检查纳入构建前置检查。
- Pinia 只保存会话和 CAT 进行中的前端状态，当前为内存态，不把用户身份写入 localStorage。
- Vue Router 通过 route meta 统一角色和布局守卫，避免学生误入教师或复核工作区。
- Tailwind CSS 只负责结构和令牌消费；品牌颜色、状态色和间距集中在 `src/styles/tokens.css`，不让页面散落颜色常量。
- shadcn-vue 的 open-code 方式允许保留项目自己的视觉令牌；Reka UI 提供 Dialog、RadioGroup 等无样式、可访问原语，减少自制交互控件的风险。
- Lucide 保持图标描边、尺寸和语义的一致性；ECharts 只承担结果结构占位和教师合成趋势，不把图表误写成临床结论。

## 4. 页面到数据的边界

```text
View
  ↓
Pinia / local composable
  ↓
typed frontend service
  ↓
MockApiProvider（当前）或未来 API adapter
  ↓
根合同 v0.1.0 的 envelope / endpoint
```

页面只消费 `view-models.ts` 中的角色视图模型。合成夹具集中在 `src/mocks/fixtures.ts`，mock adapter 集中处理延迟、失败、空态、部分元数据和幂等冲突。未来真实 adapter 应映射现有根合同，不在 Vue 组件内复刻后端业务规则。

安全状态由 adapter 返回并驱动工作流。前端不计算 CAT stopping、theta、SE、IRT，不实现 Safety policy，也不决定何时生成或通知监护人。

## 5. 备选方案与取舍

### Element Plus / Naive UI

没有作为 Round 1 主视觉系统。它们可以作为成熟组件参考，但本轮需要一个更可控、轻量、教育化而非通用后台模板的视觉基线；引入任一套完整组件主题会放大默认后台语言，并与已有 CALM INSTITUTIONAL EDUCATION UI 令牌产生冲突。

### Vue Vben Admin / vue-pure-admin / SoybeanAdmin

三者都作为工程组织和响应式后台参考，不直接作为基座。直接基于 Admin 模板会带入与学生表面不匹配的侧栏、统计卡和权限结构；本轮只保留教师 / 复核员工作区需要的固定侧栏和数据密度。

### Kiaalap

只采用教育工作区的信息架构启发：KPI、学生列表、详情、趋势和工作流分组；不复制品牌、Bootstrap 模板、完整页面或视觉样式。

### StyleKit Fluent

只采用焦点、选择、进度、遮罩、模态层级和有目的动效的交互原则；没有把 acrylic / blur / 玻璃透明面扩展到普通卡片、表格或侧栏。

### 自制 Dialog / RadioGroup

不采用。键盘、焦点、Escape、遮罩和语义状态交给 Reka UI 原语，再由项目令牌包裹，降低可访问性回归风险。

## 6. 路由与布局

| 路由 | 角色 | 布局 |
| --- | --- | --- |
| `/login` | 未登录 | AuthLayout |
| `/student/home` | student | StudentLayout |
| `/student/assessment` | student | FocusLayout |
| `/student/result/:id` | student | StudentLayout |
| `/teacher/overview` | teacher | TeacherLayout |
| `/teacher/students` | teacher | TeacherLayout |
| `/teacher/students/:id` | teacher | TeacherLayout |
| `/reviewer/queue` | reviewer | ReviewerLayout |
| `/reviewer/cases/:id` | reviewer | ReviewerLayout |

教师和复核员桌面端使用约 256px 固定侧栏，小于 1024px 改为带遮罩的 off-canvas；学生使用轻量顶栏；CAT 使用无侧栏的 Focus Layout。未知路由进入 404，不将内部模块名暴露给学生。

## 7. 安全和隐私决策

- 所有前端数据均为明确标注的 synthetic / 合成数据；没有真实学生数据。
- 学生结果不展示 theta、SE、IRT、模型评分、向量相似度、原始风险标签、开发 trace 或未经审核的生成内容。
- 高优先级复核状态改变普通生成流程：页面显示“普通生成已暂停，等待人工复核”，主动作转为“进入人工复核”。
- 本轮不发送监护人、紧急通知或外部消息；不使用诊断、治疗或临床阈值语言。
- 失败状态尽量携带可恢复动作；登录、队列、CAT、结果和详情均有加载 / 空 / 错误 / 部分元数据路径。

## 8. 验证策略

当前验证按影响范围分层：`vue-tsc` 与 ESLint 覆盖前端静态边界；Vitest 覆盖 mock adapter、路由角色守卫和学生展示边界；Playwright 覆盖垂直切片及 375 / 768 / 1024 / 1440 四档截图；根合同检查保持独立、只读。视觉截图是页面级证据，不等同于完整 WCAG 或生产后端验收。

## 9. 变更边界

本实现没有修改 `09_backend/`、`11_database/`、`01_cat-engine/`、`04_knowledge-pipeline/`、`05_rag-engine/`、`06_llm-runtime/`、`08_safety-engine/` 或根冻结合同。若真实接入需要破坏性合同变化，应另行记录 `PROPOSED_CONTRACT_CHANGE` 并等待批准。

# 管理员端与心理专业人员端前端交付记录

日期：2026-10-20

仓库：`D:\Projects\StudentMentalHealthAI-school-install-deps-20261016-ah`

前端目录：`10_frontend`

基线 HEAD：`03d329b7f74d4494baa35e05cc06d5983759cb3e`

本轮分支：`xiajiadi/admin-specialist-frontend-20261020`

## 页面与业务连接

| 路由 | 实现 | 业务/API 连接 | 占位与边界 |
|---|---|---|---|
| `/admin/tasks` | 任务搜索/状态筛选、按时间组织的任务列表、详情 Sheet、三步发布流程、专业人员分配与撤销 | `AdminSchoolOperations.vue` 继续使用既有学校任务与专业分配 API | 没有本地假发布成功；服务器错误/不可分配状态保留为错误或不可用态。未用管理员登录身份验证受保护接口 |
| `/admin/audit` | 待处理运营事项与本校可验证操作记录分 Tab 展示 | 使用现有安全指派和学校操作审计服务 | 不把心理正文、原始回答或个案明细放入审计视图；分页/过滤不超出接口范围 |
| `/admin/settings` | 依赖目录、状态详情、未知/不可用/关闭状态及安全事项入口 | `GET /health/dependencies`，通过 `readDependencyHealth()` | 未计算 uptime、历史可用率或总体健康百分比；API 失败显示 UNKNOWN |
| `/specialist/overview` | 专业复核、教育内容、研究资料、CAT 与安全流程入口 | 入口路由到对应现有工作页 | 没有未获 API 支持的待办 KPI 或虚构任务数 |
| `/specialist/resources` | 来源目录主从视图、权利/许可和审核元数据 | `SchoolResearchSourceCatalog.vue` 使用既有来源目录服务 | 不展示来源片段；工程审核状态不冒充心理学批准或使用许可 |
| `/specialist/cat` | CAT 工程模拟、题库/方案和研究管理分 Tab | 继续调用现有 CAT 管理、题库/方案与模拟服务 | 模拟前要求选择历史保存版本；不对草稿版本执行模拟；前端不重算 IRT 指标或停止规则 |
| `/specialist/tasks` | 三组工作类型与五条业务流分层切换 | 保留任务复核、研究反馈、独立教育审核、候选内容和安全工作流各自的现有组件/API | 不因 Tab 切换合并状态机；学校/角色上下文变化时清除对应私密状态；不自动发布学生反馈 |

## 保留的管理员前置工作

本轮同时保留热预览工作树中已有的管理员概览文件夹动效和账号目录工作：`AdminOperationsDesk`、`AdminWorkspaceFolder`、账号目录、成员选择和 CSV/XLSX 文件读取。相关新增依赖为 `read-excel-file@9.3.12` 与 `xls-reader@0.7.0`。这些文件原先未提交，已纳入本轮交付审查；没有覆盖学生端或普通教师端页面。

## 本地浏览器与服务证据

- `http://127.0.0.1:4206` 是当前工作树的 Vite 热预览；本轮实际代码位于上述仓库的 `10_frontend`。目标页入口：
  - `http://127.0.0.1:4206/admin/tasks`
  - `http://127.0.0.1:4206/admin/audit`
  - `http://127.0.0.1:4206/admin/settings`
  - `http://127.0.0.1:4206/specialist/overview`
  - `http://127.0.0.1:4206/specialist/resources`
  - `http://127.0.0.1:4206/specialist/cat`
  - `http://127.0.0.1:4206/specialist/tasks`
- 页面访问需要对应真实角色会话；交付不包含任何账号或密码。浏览器截图与本地 UI 交互检查使用隔离的合成测试上下文/受控响应，仅证明布局和前端状态表现，不作为受保护 API 的真实鉴权或业务成功证据。
- 七个页面均有 1440px 桌面截图；管理员任务页和心理专业工作事项页另有 375px、768px 截图，心理专业任务页另有 1024px 截图，CAT 页有 375px 截图。重点目录见 [`10_frontend/output/playwright/2026-10-20-admin-specialist/`](../../10_frontend/output/playwright/2026-10-20-admin-specialist/)。
- 后端 `127.0.0.1:8117` 的只读依赖健康响应已现场读取：`post_assessment_worker=READY`；`cat/rag/llm_runtime/safety=UNAVAILABLE`；三个 research worker 为 `DISABLED`。该响应不代表平台整体就绪。
- `127.0.0.1:4207` 当前没有监听。此前生命周期检查因 research programme pins 校验失败返回 BLOCKED；未绕过该管理流程或替换其运行目录。
- 没有可用的真实管理员/心理专业人员登录会话，因此任务、目录、CAT、来源目录等受保护 API 的真实用户端到端验收为 NOT_RUN。健康端点是本轮唯一直接读取并记录的后端页面数据。

## 截图索引

| 页面 | 桌面 | 窄屏/平板 |
|---|---|---|
| 管理员测评任务 | [admin-tasks-1440.png](../../10_frontend/output/playwright/2026-10-20-admin-specialist/admin-tasks-1440.png) | [375](../../10_frontend/output/playwright/2026-10-20-admin-specialist/admin-tasks-375.png) · [768](../../10_frontend/output/playwright/2026-10-20-admin-specialist/admin-tasks-768.png) |
| 管理员运营事务 | [admin-audit-1440.png](../../10_frontend/output/playwright/2026-10-20-admin-specialist/admin-audit-1440.png) | — |
| 管理员系统状态 | [admin-settings-1440.png](../../10_frontend/output/playwright/2026-10-20-admin-specialist/admin-settings-1440.png) | — |
| 心理专业人员概览 | [specialist-overview-1440.png](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-overview-1440.png) | — |
| 心理专业资料 | [specialist-resources-1440.png](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-resources-1440.png) · [详情](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-resources-detail-1440.png) | — |
| CAT 实验室 | [specialist-cat-1440.png](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-cat-1440.png) · [研究管理](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-research-management-1440.png) | [375](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-cat-375.png) |
| 心理专业工作事项 | [specialist-tasks-1440.png](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-tasks-1440.png) | [375](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-tasks-375.png) · [768](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-tasks-768.png) · [1024](../../10_frontend/output/playwright/2026-10-20-admin-specialist/specialist-tasks-1024.png) |

## 工程检查

| 检查 | 结果 | 证据/范围 |
|---|---|---|
| TypeScript | PASS | `npm run typecheck` |
| Production build | PASS | `VITE_API_MODE=real`、`VITE_API_BASE_URL=http://127.0.0.1:8117` 下 `npm run build` |
| 本轮改动文件 ESLint | PASS | 管理员/专业页面、共享 workspace 组件、测试和合成概览数据定向 lint |
| 定向单测 | PASS | 10 个相关文件，74/74；任务发布关键用例 3/3，另 12 个用例按过滤器跳过 |
| 全仓单测 | PARTIAL | 43 个文件通过、7 个文件失败；319 项中 286 通过、33 失败，并有 13 个未处理异常。失败集中于登录/路由、既有学生与教师范围、反馈/研究输出复核及 `school-workflows` 中未注入 Router 的旧用例；jsdom 还报告 Canvas/ECharts 未实现 |
| 全仓 ESLint | PARTIAL | 36 errors、62 warnings；本轮改动文件定向 lint 为 0 errors。全仓错误来自未修改的启动脚本、App、学生和教师文件 |
| Playwright E2E | PARTIAL | 11 项中 4 failed、7 skipped；活动用例在旧演示登录选择器或页面定位处超时，和当前登录页面不匹配。定向浏览器截图与 Tab 键盘切换检查已完成 |
| Git whitespace | PASS | `git diff --check`；只有 Windows CRLF 提示 |

## Git 记录

- 修改前基线：`03d329b7f74d4494baa35e05cc06d5983759cb3e`，工作分支 `xiajiadi/admin-specialist-frontend-20261020`。
- 学生端与普通教师端既有实现来自该基线，本轮未改写其页面；改动集中于管理员、心理专业人员、共享工作区控件、受影响测试和相关依赖。
- 本文初稿提交后补录代码提交 SHA 与推送结果。只推送本轮命名开发分支，不强推、不部署生产，也不改动默认或受控分支。
- 本地生成的 `.school-dependency-preparation-state.json`、`.school-deps-*.npmrc`、`.playwright-cli/` 和 Playwright 临时报告不纳入版本控制。

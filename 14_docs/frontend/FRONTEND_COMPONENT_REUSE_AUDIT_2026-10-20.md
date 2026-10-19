# PsyNova 前端组件复用审计

日期：2026-10-20

范围：管理员工作区、心理专业人员工作区和本轮保留的管理员目录/概览改动。

## 资源和许可证核验

- Designeer 的 OpenSourceUI 资源页用于定位组件：[Designeer / OpenSourceUI](https://designeer.xyz/resources/opensourceui)。
- 原始代码库为 [bidyut10/opensourceui](https://github.com/bidyut10/opensourceui)，审阅版本固定在 commit [`892f486fdf0d46a44b21ddf3fa32a41a3a71173a`](https://github.com/bidyut10/opensourceui/tree/892f486fdf0d46a44b21ddf3fa32a41a3a71173a)，许可证为 MIT，版权归 Bidyut Kundu（2026）。该库以 React/Next.js、TypeScript 和 Tailwind CSS 为主。
- 除下表注明的文件夹堆叠布局适配外，OpenSourceUI 内容仅作视觉和信息组织参考，没有复制其 JSX、演示数据或品牌素材。堆叠文件夹的版权和 MIT 文本保存在 `10_frontend/src/components/admin/THIRD_PARTY_NOTICES.md`。
- `reka-ui@2.10.4`（MIT）在本轮开始前已是项目依赖。本轮未为组件参考新增依赖。管理员目录既有 CSV/XLSX 工作使用的 `read-excel-file` 与 `xls-reader` 是保留的账号导入需求，不属于 OpenSourceUI 复用。

## 采用记录

| Component | Source | Discovery | License | Original Stack | Reuse Mode | Dependencies | PsyNova File / Used By | Accessibility | Verification |
|---|---|---|---|---|---|---|---|---|---|
| Stacked Folder Card | [OpenSourceUI Stacked Folder Card](https://opensourceui.in/components/stacked-folder-card) | [Designeer OpenSourceUI](https://designeer.xyz/resources/opensourceui) | MIT；本地保留版权声明 | React / Next.js / TypeScript / Tailwind | 仅适配堆叠层级与位置布局；动画和 Vue 交互在本地实现 | 无新增 | `10_frontend/src/components/admin/AdminWorkspaceFolder.vue`；管理员概览工作区 | 本地按钮交互与减少动态效果样式；没有将原 React 组件带入 Vue 页面 | 管理员概览浏览器截图与当前分支 ESLint / Build |
| Tasks Table | [OpenSourceUI Tasks Table](https://opensourceui.in/components/tasks-table) | [Designeer OpenSourceUI](https://designeer.xyz/resources/opensourceui) | MIT 来源；未复制代码 | React / Next.js / TypeScript / Tailwind | 票据密度、分组和次级信息的视觉参考 | 无新增 | `10_frontend/src/components/school/AdminSchoolOperations.vue`；`/admin/tasks` | 页面使用本地表单控件与按钮；操作响应真实服务结果 | 管理员任务页截图；任务发布定向测试 |
| Search Input | [OpenSourceUI Search Input](https://opensourceui.in/components/search-input) | [Designeer OpenSourceUI](https://designeer.xyz/resources/opensourceui) | MIT 来源；未复制代码 | React / Next.js / TypeScript / Tailwind | 搜索框尺寸、图标和工具栏间距参考 | 无新增 | 管理员任务/目录与专业资料已有搜索输入 | 原生输入框保留键盘输入；筛选范围由现有页面说明 | 1440px 与窄屏页面截图 |
| Segmented Toggle | [OpenSourceUI Segmented Toggle Button](https://opensourceui.in/components/segmented-toggle-button) | [Designeer OpenSourceUI](https://designeer.xyz/resources/opensourceui) | MIT 来源；未复制代码 | React / Next.js / TypeScript / Tailwind | 选中态和分段控件视觉参考；基础切换交给 ReKa Tabs | 无新增 | `WorkspaceTabs.vue`；管理员运营、心理专业工作事项和 CAT 工作区 | ReKa Tabs 提供 tablist 语义与键盘导航；测试检查选中和 panel 关系 | `workspace-tabs.spec.ts`；浏览器 ArrowLeft 切换检查 |
| Resource Links Panel | [OpenSourceUI Resource Links Panel](https://opensourceui.in/components/resource-links-panel) | [Designeer OpenSourceUI](https://designeer.xyz/resources/opensourceui) | MIT 来源；未复制代码 | React / Next.js / TypeScript / Tailwind | 来源目录的信息密度、列表选择和主从布局参考 | 无新增 | `10_frontend/src/components/school/SchoolResearchSourceCatalog.vue`；`/specialist/resources` | 选择控件保持键盘可达；不渲染受保护来源片段 | 来源列表/详情截图；受限 API 错误状态截图 |
| Tabs | [Reka UI Tabs](https://reka-ui.com/docs/components/tabs) | 任务书指定 ReKa 原语 | MIT；依赖已存在 | Vue 3 primitives | 直接组合 `TabsRoot/List/Trigger/Content/Indicator`，本地封装为应用级组件 | `reka-ui@2.10.4`（既有） | `10_frontend/src/components/workspace/WorkspaceTabs.vue`；`/admin/audit`、`/specialist/tasks`、`/specialist/cat` | 自动激活、方向键导航、正确 tab/panel 关联；遵循减少动态效果 | 组件单测；真实浏览器键盘切换；生产构建 |
| Dialog primitives / detail sheet | [Reka UI Dialog](https://reka-ui.com/docs/components/dialog) | 任务书指定 ReKa 原语 | MIT；依赖已存在 | Vue 3 primitives | 直接组合 Dialog 原语，本地样式化为详情 Sheet | `reka-ui@2.10.4`（既有） | `10_frontend/src/components/workspace/WorkspaceDetailSheet.vue`；管理员任务详情 | 标题/描述、关闭名称、Esc 与焦点管理由 ReKa 提供 | Sheet 组件单测；生产构建 |

## 未引入的候选组件

日期选择、Resizable、Data Table、Accordion、Kanban 等没有作为额外组件库引入：当前接口与页面未形成足以证明这些控件收益的需求，且没有必要为了外观增加 React/Motion/Recharts 依赖。任务发布仍等待已有服务端校验和提交结果；工作事项切换仍由各自业务组件处理，不合并服务端状态机。

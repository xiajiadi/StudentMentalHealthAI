# Open Source / Design Reference Audit

访问日期：2026-09-05（Asia/Shanghai）  
范围：只审计本轮前端设计与工程参考；没有复制第三方源代码、品牌、资源或完整页面。

## 结论

本轮采用的不是某个模板的整套外观，而是一组受控决策：StyleKit Fixed Sidebar 的固定侧栏 / off-canvas 语法，Kiaalap 的教育工作区信息架构，StyleKit Fluent 的局部交互原则，shadcn-vue + Reka UI 的 open-code / headless 原语边界，Lucide 与 ECharts 的图标和图表基础。Vben、PureAdmin、Soybean、Taste、Impeccable、UI UX Pro Max 和 DESIGN.md 资料用于方法或工程对照。

许可证只在页面或仓库明确可核实时记录；“未独立确认”不视为许可结论。

## 逐项记录

| # | URL | 类型 / 版本或修订 | 许可证 | 实际检查 | 采用 | 明确不采用 / 备注 |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | https://www.stylekit.top/zh/styles/sidebar-fixed | 设计页面；版本未标明 | 未独立确认 | 中文路径未直接展开，保留为必查 URL；用同页英文路径交叉核对 | 固定侧栏、约 256px、内容优先、移动 off-canvas 的设计方向 | 不复制页面代码或品牌 |
| 2 | https://www.stylekit.top/styles/sidebar-fixed/showcase | Showcase；版本未标明 | 未独立确认 | 本次直接打开超时 / 失败，未将其当作完整证据 | 仅作为待复核的 showcase 入口记录 | 不声称完成 showcase 全量检查 |
| 3 | https://colorlib.com/polygon/kiaalap/index.html | 在线教育后台示例；页面版本未标明 | 页面未独立确认 | 已检查导航、学生列表、KPI、图表、详情分组 | 教育工作区 IA、列表 / 详情 / 趋势分组 | 不复制 Bootstrap 模板、品牌或 CSS |
| 4 | https://github.com/puikinsh/kiaalap | GitHub 仓库；页面显示 Bootstrap 5 / Vite 7 | MIT（仓库页面） | 已检查 README、功能范围和许可证信息 | 作为 Kiaalap IA 的仓库佐证 | 不作为本项目基座 |
| 5 | https://www.stylekit.top/styles/fluent-design/showcase | 设计 showcase；版本未标明 | 未独立确认 | 已检查 Light / Depth / Motion / Material / Scale 及 Acrylic 说明 | 焦点、选择、进度、遮罩和局部层级 | 不采用全站 acrylic、blur、玻璃侧栏或玻璃表格 |
| 6 | https://github.com/Leonxlnx/taste-skill | Skill；当前仓库页 | MIT（仓库页面） | 已检查 DESIGN_VARIANCE、MOTION_INTENSITY、VISUAL_DENSITY 拨盘 | 在 `DESIGN.md` 中记录角色拨盘 | 不把拨盘当作产品能力或视觉证据 |
| 7 | https://github.com/pbakaus/impeccable | 设计质量 skill；当前仓库页 | MIT（仓库页面） | 已检查 critique / audit / polish / harden 命令和 detector 方法 | 作为本轮人工设计审计的检查框架 | 未安装 CLI；不声称执行了其自动 detector |
| 8 | https://github.com/shadcn-ui/ui | React open-code 组件项目；当前仓库页 | MIT（仓库页面） | 已检查 Open Source / Open Code / 可定制组件库哲学 | 采用 open-code、项目令牌优先的边界 | 不把 React 实现直接引入 Vue |
| 9 | https://www.shadcn-vue.com/ | Vue 组件站点；当前站点 | 站点未独立确认 | 已检查 foundation / open-code 定位 | 采用 shadcn-vue 作为 Vue 侧组织参考 | 不使用默认主题覆盖项目设计基线 |
| 10 | https://www.shadcn-vue.com/docs | Vue 文档；当前站点 | 站点未独立确认 | 已检查 Dialog、Drawer、RadioGroup 等组件文档入口 | 作为组件边界和 API 设计参考 | 不自制成熟交互原语 |
| 11 | https://github.com/unovue/shadcn-vue | GitHub Vue port；当前仓库页 | MIT（仓库页面） | 已检查仓库定位与许可证 | 采用 shadcn-vue 2.8.2 | 不复制仓库组件源码到本项目 |
| 12 | https://reka-ui.com/ | 无样式可访问 primitives；当前站点 | 站点未独立确认 | 已检查 unstyled / accessible / customizable 定位和 Tailwind 示例 | Dialog、RadioGroup 原语边界 | 不让 Reka 默认样式成为品牌系统 |
| 13 | https://github.com/unovue/reka-ui | GitHub 仓库；当前仓库页 | MIT（仓库页面） | 已检查仓库定位和生态关系 | 采用 Reka UI 2.10.4 | 不复制内部实现 |
| 14 | https://github.com/apache/echarts | 图表库；当前仓库页 | Apache-2.0（仓库页面） | 已检查 Apache ECharts 定位与许可证 | 采用 ECharts 6.1.0；仅做结构占位和合成趋势 | 不将图表解读为临床结论 |
| 15 | https://github.com/lucide-icons/lucide | 图标库；当前仓库页 | ISC（仓库页面） | 已检查图标库定位与许可证 | 采用 `@lucide/vue` 1.41.0 | 不使用 emoji 系统图标 |
| 16 | https://github.com/nextlevelbuilder/ui-ux-pro-max-skill | 设计系统 skill；当前仓库页 | MIT（仓库页面） | 已检查 master / override 设计系统持久化建议 | 采用设计系统持久化、响应式和无障碍检查意识 | 不把推荐结果当作本项目批准的产品决策 |
| 17 | https://www.uupm.cc/ | UI UX Pro Max 站点；当前站点 | 站点未独立确认 | 已记录为与 #16 配套的入口 | 作为方法入口记录 | 不直接采用站点生成的品牌方案 |
| 18 | https://github.com/VoltAgent/awesome-design-md | DESIGN.md 资料索引；当前仓库页 | MIT（仓库页面） | 已检查 DESIGN.md 作为 agent-readable source of truth 的论点 | 形成根 `DESIGN.md` | 不复制索引内容或第三方规则全文 |
| 19 | https://github.com/vbenjs/vue-vben-admin | Vue 管理后台；当前仓库页 | MIT（仓库页面） | 已检查 Vue3、Shadcn UI、Vite、TypeScript、monorepo 和功能定位 | 侧栏、权限 / 路由和工程组织参考 | 不作为基座，不带入完整 Admin 壳 |
| 20 | https://github.com/pure-admin/vue-pure-admin | Vue 管理后台；当前仓库页 | MIT（仓库页面） | 已检查 Vue3、Vite、TypeScript、Pinia、Tailwind 与 Element Plus 组合 | 轻量后台组织、响应式和质量门参考 | 不让 Element Plus 成为本项目主视觉系统 |
| 21 | https://github.com/soybeanjs/soybean-admin | Vue 管理后台；当前仓库页 | MIT（仓库页面） | 已检查 Vue3、Vite、TypeScript、Pinia、Naive UI、UnoCSS 和路由组织 | 主题、路由和信息架构参考 | 不让 Naive UI 成为本项目主视觉系统 |

## 版本与归因说明

- 本轮使用的实际 npm 版本记录在 `10_frontend/FRONTEND_TECHNICAL_DECISION_V1.md`。
- 没有可靠的 tag / commit 需要锁定的参考实现；因此每项使用访问日期和页面当前内容作为审计快照，而不是虚构修订号。
- Kiaalap 的仓库页面明确包含 MIT 信息；shadcn-vue、Reka UI、ECharts、Lucide 以及工程参考仓库的许可证结论以各自页面在本次审计时展示的内容为依据。
- 参考页面只影响信息架构、交互原则、组件边界和检查方法；没有第三方代码进入 `10_frontend/src/`。

# Frontend Round 1 Acceptance

日期：2026-09-05  
范围：`10_frontend/` 以及明确授权的 `DESIGN.md`、`14_docs/ui/`、研究和验收报告。  
结论类型：合成数据边界内的前端工程验收，不是生产发布、临床效度或真实后端集成验收。

## 1. Conclusion

**PARTIAL PASS。** Round 1 前端垂直切片和工程质量门通过：登录 → 学生首页 → CAT Focus Mode → 学生结果 → 教师工作区 → 复核队列 → 复核详情可运行，单元 / E2E / 类型 / lint / 构建 / 根合同检查均有可复现证据。生产认证、真实 API adapter、完整 Parent / Marketing / 复杂 Admin 和自动化 WCAG 扫描仍待后续授权与实现。

## 2. Scope

已实现仅限 `10_frontend/` 和授权设计文档。未修改 backend、database、CAT、knowledge pipeline、RAG、LLM Runtime、Safety 规则或冻结根合同。

## 3. Runtime / Toolchain

Node 24.15.0、npm 12.0.2、Vue 3.5.42、TypeScript 5.9.3、Vite 8.2.2、Pinia 4.0.3、Vue Router 5.3.1、Tailwind CSS 4.3.3、shadcn-vue 2.8.2、Reka UI 2.10.4、`@lucide/vue` 1.41.0、ECharts 6.1.0、Vitest 5.0.0、Vue Test Utils 2.5.0、Playwright 1.63.0、vue-tsc 3.3.11。

## 4. Frozen Frontend Decisions

已落实 CALM INSTITUTIONAL EDUCATION UI、语义令牌、约 256px 桌面侧栏、移动 off-canvas、学生轻顶栏、CAT 独立 Focus Layout、Meaning → Data → Action → Evidence 结果顺序、Lucide 图标、ECharts 必要图表和 typed mock adapter 边界。详细基线见根 `DESIGN.md` 与 `FRONTEND_TECHNICAL_DECISION_V1.md`。

## 5. Open-source References Actually Inspected

21 个必查 URL 已逐项登记在 `10_frontend/research/OPEN_SOURCE_REFERENCE_AUDIT.md`，包括实际打开限制。StyleKit 中文路径未直接展开，Fixed Sidebar showcase 本次超时；对应英文规范页已交叉核对。没有复制第三方代码或完整外观。

## 6. Design System

颜色、字体、间距、圆角、边框、阴影、动效、图标、导航、图表、状态、Do / Don't 和角色拨盘已写入 `DESIGN.md`。原始颜色集中在 `src/styles/tokens.css`；普通页面未使用紫蓝 AI 渐变、霓虹、全站玻璃、emoji 系统图标或大面积卡片套卡片。

## 7. Implemented Role Surfaces

已实现：登录、学生首页、CAT、学生结果、教师概览、教师学生列表、教师详情、复核队列、复核详情和 404。路由守卫限制角色访问，布局按角色分离。

## 8. Student Home

状态：PASS（合成 mock）。首页采用意义优先顺序：下一步、最近结果、支持入口、最近记录；含 loading、首次 empty、服务 error。没有学生不可见的 theta、SE、IRT、模型评分、向量相似度或原始风险标签。

## 9. CAT Focus Mode

状态：PASS（合成 mock）。无侧栏、AI widget、风险徽章、倒计时、统计面板和游戏化元素；RadioGroup 支持键盘语义；选择不会自动提交；离开需确认；保存失败和会话不可用有恢复路径；不承诺固定总题数，使用 `can_complete` 返回驱动完成动作。

## 10. Student Result

状态：PASS（合成 mock）。页面顺序为 Meaning → Data → Action → Evidence；图表明确“合成占位、非诊断”；引用保持 adapter 顺序，缺失元数据不猜测；引用不可用和部分结果有专门状态。

## 11. Teacher / Reviewer Workspace

状态：PASS（合成 mock）。教师概览、学生列表、学生详情和复核员工作区使用固定侧栏 / 响应式抽屉；桌面侧栏约 256px；内容密度按角色拨盘区分。教师详情显示教育支持摘要，不替代诊断或 Safety 决策。

## 12. Review Queue

状态：PASS（合成 mock）。支持状态 / 优先级筛选、加载、空队列、筛选无结果和可恢复错误。队列项展示抽象进入原因、状态、更新时间和详情入口，不以红色卡片代替工作流。

## 13. Review Detail

状态：PASS（合成 mock）。详情包含安全状态、最小元数据、流程时间线、审核依据和通过 / 退回动作。提交前有 Dialog 确认，已处理状态不保留误导性的普通生成入口。

## 14. Safety Workflow UI

状态：PASS（前端呈现边界）。高优先级案例显示“普通生成已暂停，等待人工复核”，主路径进入人工复核；本轮没有监护人 / 紧急通知，也没有在前端实现 Safety 分类或规则。

## 15. Responsive Evidence

状态：PASS（页面证据）。在 375、768、1024、1440 四档生成 28 张实际截图；Playwright 对每个代表性页面检查页面级横向溢出。证据目录：`10_frontend/reports/artifacts/visual/`。

## 16. Accessibility Evidence

状态：PARTIAL PASS。已实现语义 heading、label、button / link、RadioGroup、Dialog、移动抽屉、可见焦点、reduced motion、文字化图表替代和非颜色单独状态；浏览器垂直切片覆盖键盘可识别控件。尚未运行 axe、NVDA / VoiceOver 或完整 WCAG 审计，不能把本轮结果表述为完整无障碍合规。

## 17. Test Evidence

Vitest：3 个 test files、9 个 tests 通过。Playwright：3 个 E2E tests 通过，其中包含完整垂直切片、错误 / 网络失败提示和四档视觉截图 / 横向溢出检查。结果 JSON：`10_frontend/reports/artifacts/playwright-results.json`。

## 18. Type/Lint Evidence

`npm run typecheck`：PASS。`npm run lint`：PASS。检查范围是前端配置、源码和测试文件。

## 19. Build Evidence

`npm run build`：PASS。实际使用 Vite 8.2.2 完成 `vue-tsc --noEmit` 和生产构建，输出写入本地 `10_frontend/dist/`；本项不是发布包或部署验收。

## 20. Root Contract Evidence

`powershell -NoProfile -ExecutionPolicy Bypass -File .\00_architecture\tests\run_contract_checks.ps1`：PASS，13 tests、0 failures，OpenAPI 文档检查通过。该检查证明根合同和 fixture 当前有效，不证明真实前端 API 已接通。

## 21. Synthetic Data Confirmation

状态：PASS。mock fixtures 使用合成账号、合成学生标识、合成案例和已授权合成知识片段，并在界面显示本地演示 / 合成说明。未使用真实学生数据、真实身份或真实临床记录。

## 22. Frozen Contract Confirmation

状态：PASS。未修改根 `CONTRACTS.md`、OpenAPI、后端、数据库、CAT、RAG、LLM Runtime 或 Safety 文件。前端只建立本地 typed adapter；任何未来破坏性合同需求都应先记录 `PROPOSED_CONTRACT_CHANGE`。

## 23. Known Limitations

- 当前认证、权限和数据请求是内存态 mock，不代表生产安全边界；
- npm 安装时报告 7 个 moderate audit advisories，未执行未经授权的自动修复；
- 构建输出和浏览器缓存是本地验证产物，不应进入公共仓库；
- 本次没有完整 axe / 屏幕阅读器 / 真机测试；
- `StyleKit Fixed Sidebar` 的中文路径与 showcase 入口存在本次访问限制，审计已如实记录。

## 24. Deferred Items

真实 API adapter 与认证、生产权限 / 会话过期、完整教师分析矩阵、Parent / Marketing / 复杂 Admin、真实通知、真实后端错误 envelope 集成、生产数据脱敏、axe 与屏幕阅读器门禁、跨浏览器视觉回归、发布链路和签名。

## 25. Round 2 Recommendations

先接入根合同对应的真实 adapter，并用契约 fixture 做 API 集成测试；再补登录会话、权限过期、并发复核和真实错误恢复。接入真实引用后重跑引用排序与缺失元数据检查；同时增加 axe + NVDA / VoiceOver 走查和跨 Chromium / Edge 视觉基线。Parent 只有在权限、沟通文案和人工审核边界明确后再单独立项。

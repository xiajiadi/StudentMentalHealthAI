# Frontend Design Audit

日期：2026-09-05  
审计对象：`10_frontend/` Round 1 视觉与交互基线  
审计方式：实际运行页面、Playwright 页面截图、源码令牌检查和人工逐图检查。截图不是生产数据，也不替代完整 WCAG 或真实后端验收。

## 1. 结论

结论：前端视觉基线可进入 Round 1 验收，工程垂直切片已形成一致的学生、教师和复核员表面。主要剩余项是生产后端 / 认证接入、完整无障碍自动化扫描和延期角色表面，不是本轮视觉方向缺失。

## 2. 实际截图证据

每个视口均生成 7 个页面截图，共 28 个 PNG：

```text
10_frontend/reports/artifacts/visual/{375,768,1024,1440}/
  login.png
  student-home.png
  cat-focus.png
  student-result.png
  teacher-overview.png
  review-queue.png
  review-detail.png
```

截图由 `e2e/visual-artifacts.spec.ts` 在 `reducedMotion: reduce` 下生成，代表性页面均等待关键标题 / 状态可见后再保存。

## 3. 检查结果

| 检查项 | 结果 | 证据与说明 |
| --- | --- | --- |
| CALM INSTITUTIONAL EDUCATION UI | PASS | 画布、白色内容面、克制边框、蓝色动作、青色支持状态和少量琥珀 / 红色工作流状态一致 |
| 学生首页不做 ERP KPI 仪表盘 | PASS | meaning-first、下一步、支持入口和最近记录；没有教师侧 KPI 网格 |
| CAT Focus Mode | PASS | 无侧栏、无 AI widget、无风险徽章、无倒计时、无游戏化；一题一页 |
| 结果顺序 | PASS | Meaning → Data → Action → Evidence；图表为合成占位并有边界说明 |
| 教师固定侧栏 | PASS | 桌面约 256px；当前导航有稳定锚点；平板 / 移动转 off-canvas |
| 复核安全工作流 | PASS | “普通生成已暂停，等待人工复核”与人工通过 / 退回动作可见；没有普通生成 CTA |
| 图标系统 | PASS | 使用 `@lucide/vue`，没有 emoji 系统图标 |
| 颜色令牌 | PASS | CSS 原始颜色集中在 `src/styles/tokens.css`；组件使用语义变量 |
| 动效 | PASS | 过渡短、无 bounce / elastic / spring overshoot；截图使用 reduced motion |
| 页面级横向溢出 | PASS | Playwright 对 375、768、1024、1440 下页面 `scrollWidth` 与 viewport 做断言 |
| Loading / empty / error / partial | PASS | mock adapter 提供首页、队列、结果、CAT、登录和详情的代表性分支 |
| Humanizer | PASS | 本轮新增可见文案按“具体、短句、说明发生了什么和下一步”人工复核 |
| Vale | NOT RUN | 未发现项目 Vale 配置；因此不声称 Vale 通过，也未引入一次性写作工具链 |

## 4. 逐表面观察

### 登录

1440px 使用左右分区，左侧建立产品身份，右侧保持表单专注；375px 自然改为上下结构。账号、密码、身份选择、密码可见性和错误提示均有明确标签。

### 学生首页与结果

学生首页先给“现在可以做什么”，结果页先给“为什么会看到这些建议”。结果页的合成雷达图与文字边界并列，依据按返回顺序显示，长摘录在移动端换行。

### CAT

题目面板在 1440px 保持可读宽度，在 375px 仍保留足够的选项点击区域。选择不自动提交，离开触发确认；首屏不出现固定总题数或内部测量字段。

### 教师与复核员

两类工作区共享壳，但密度和导航目的不同。教师页面以合成流程趋势和学生入口为主；复核页面以状态、时间线、依据和安全动作优先。移动端表格转为堆叠信息，详情保持单列可读。

## 5. 仍需在下一轮验证的事项

- 用真实浏览器辅助技术做 NVDA / VoiceOver 走查，并接入 axe 或等价自动化扫描；
- 对真实 API 错误 envelope、权限过期和并发更新做集成测试；
- 在真实后端数据接入后重新核对长文本、空字段和引用排序；
- 如果引入新角色或新图表，先更新根 `DESIGN.md` 和对应页面说明。

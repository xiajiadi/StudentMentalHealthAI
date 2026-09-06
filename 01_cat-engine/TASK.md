# 01_cat-engine：自适应测评引擎

## CAT Round 1：CAT V0.1 Engineering Baseline

公共 Contract：`v0.1.0 FROZEN`。本轮全部题库、参数、响应和结果均为
`DEMO / ENGINEERING USE ONLY`，并明确标记 `NOT FOR PSYCHOLOGICAL
INTERPRETATION`。本轮不得决定正式量表、人群、因子结构、风险阈值或心理学
解释规则；不得修改冻结 Contract。

状态枚举：`TODO`、`IN_PROGRESS`、`DONE`、`BLOCKED`。

| ID | Checklist | 状态 |
| --- | --- | --- |
| CAT-R1-01 | 阅读 Contract 和治理文件 | DONE |
| CAT-R1-02 | 创建 `CAT_TECHNICAL_DECISION_V1.md` | DONE |
| CAT-R1-03 | 建立 domain model | DONE |
| CAT-R1-04 | 建立 `CATProvider` Interface | DONE |
| CAT-R1-05 | 建立 Synthetic Item Bank | DONE |
| CAT-R1-06 | 验证 adaptivetesting 当前 API 和环境兼容 | DONE |
| CAT-R1-07 | 实现 `AdaptiveTestingProvider` PoC | DONE |
| CAT-R1-08 | 实现 Session State Machine | DONE |
| CAT-R1-09 | 实现 CAT Trace | DONE |
| CAT-R1-10 | 实现 stopping orchestration | DONE |
| CAT-R1-11 | 实现 `assessment.v1` mapper | DONE |
| CAT-R1-12 | 实现 Simulation Framework | DONE |
| CAT-R1-13 | 运行 `N >= 1000` simulation | DONE |
| CAT-R1-14 | 建立 Reference Validation 状态 | DONE |
| CAT-R1-15 | 完整测试 | DONE |
| CAT-R1-16 | 生成 Round 1 验收报告 | DONE |

### 本轮工程边界

- Online runtime 只读取版本化、不可变、`published` 的题库；不在线校准题目参数。
- Provider-specific 类型只能存在于 Provider adapter 内部。
- CAT 不负责诊断、咨询、RAG、LLM、建议、风险最终定义或危机判断。
- 缺失响应必须区分 `answered`、`skipped`、`timeout`、`invalid`、`not_presented`，不得转为 0 分。
- 所有随机实验支持固定 seed；所有 Session、Trace 和 Simulation 结果可追踪。

## 职责

- 根据已批准的题库和测评模型执行自适应选题；
- 实现经确认的能力估计、题目选择和停止规则；
- 提供可复现的 CAT 状态更新和模拟器；
- 记录题目、估计、标准误和引擎版本；
- 通过接口输出可供适配器组装的 Assessment Result 数据。

## 输入

- 02_item-bank 输出的已审核题目和参数；
- 逐题响应事件；
- 已确认的测评模型、先验、停止和曝光策略配置；
- 合成受试者和模拟响应配置；
- CONTRACTS.md 中 Assessment Schema 的字段约束。

## 输出

- 测评状态、已答题摘要、各维度估计值和标准误；
- 题目选择与停止原因；
- CAT 引擎版本和题库版本；
- 符合 assessment.v1 的结果，或明确的技术性未就绪错误；
- 模拟器的 RMSE、Bias、平均题数和收敛摘要。

## 禁止事项

- 不自行选择量表、维度、人口范围、临床解释或风险阈值；
- 不把 theta 或分数直接解释成诊断；
- 不接入 RAG、LLM、Prompt 或用户页面；
- 不在日志中保存姓名、学号、原始自由文本或完整逐题敏感回答；
- 不能伪造风险等级；风险必须来自已批准的规则集或由上层安全模块完成。

## 接口

- 题库读取：消费 Item Bank 的标准题目集合；
- 状态更新：response event -> CAT state；
- 选题：state + available items -> next item；
- 估计：state + response -> dimension estimate；
- 完成：CAT state + approved risk result + provenance -> assessment.v1；
- 失败：返回稳定的输入无效、题库不可用、参数缺失或无法收敛错误码。

## 验收标准

- 选题、估计和停止逻辑可用固定随机种子复现；
- 题库缺字段、参数非法、维度未知时拒绝运行；
- 能运行合成模拟，并产出 RMSE、Bias、平均题数等指标；
- 不满足停止条件时不会提前标记 completed；
- 输出字段符合 assessment.v1，且 provenance 完整；
- 高风险状态不会被 CAT Engine 单独放行生成个性化建议。

## 交付物

- CAT 核心实现及单元测试；
- 模型、选题、估计和停止策略说明；
- 合成模拟器与样例配置；
- Assessment 输出样例；
- 指标报告、已知限制和待确认的心理学决策。

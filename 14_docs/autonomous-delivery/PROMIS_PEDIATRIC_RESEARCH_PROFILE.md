# PROMIS Pediatric Anxiety 8-item research profile candidate

核查日期：2026-10-14。状态：独立研究候选，未进入学校在线题库或启用。研究 loader 已支持这一份固定 profile/manifest 哈希的 v3 五类别候选，Root 运行研究测试 86 项通过；在线 CAT 未改。原始 profile 中的 loader_compatibility 是生成时的历史记录，原文件及哈希保持不变。0013 仓储现已明确支持已发表参数来源：在新隔离 K3319 保存了加密候选，原文回读哈希一致，fit/calibration 为空，保存真实 crosswalk 哈希。原始否定发布状态与长维度说明保持在原文，仅数据库安全投影采用稳定维度 ID 和规范否定状态。证据见 K/logs/native-research-profile-59b3e817de0341718eec182dcb90c1b6.json；不是专业批准或已接通学生测评 API。

## Profile

外部目录：`D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1`。

- `profile.json`：`psynova.research-profile.v3`，instrument family `PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET`；`research_only=true`、`publication_status=not_approved`、`human_curated=false`、`psychological_interpretation_allowed=false`。
- 八项为公开 child-self-report Anxiety 字段，英文题面与 past-7-days 提示按 codebook 原文保留。响应标签依次为 `Never / Almost Never / Sometimes / Often / Almost Always`。Profile 明确记录 `1=Never, 2=Almost Never, 3=Sometimes, 4=Often, 5=Almost Always`，再映射 engine index `0–4`；source blank 变为 `NA`，拒答 `-1` 与系统缺失在原 CSV 中无法区分。没有反向计分、翻译、个人分数、theta、临床界值或危机阈值。
- 参数取 Irwin et al. 2010 Table 5 已发表 Pediatric Anxiety v1.0 bank GRM，`a` 与四个 `b` 只保留论文公布的两位小数。论文以 North Carolina 子样本为参考并将 theta 定为均值 0、方差 1；参数校准总样本 1,529 名 8–17 岁儿童，来自 NC/TX 公立学校与门诊/专科门诊。HealthMeasures 手册说明 v1.0/v1.1/v2.0 参数校准一致，v1.1 8b 与 v2.0 8a item-set 相同但类别分值不同。GenPop v3.0 不兼容此参数集。
- 这是 v2.0 Short Form 8a 的**题项集合**与旧 v1.0 bank 参数对应候选。2010 校准论文的问卷分为两个测试表单，每个含 9 个 anxiety 候选题项；2020 GenPop 论文提及 10-item anxiety measure，而本次公开 codebook 响应文件有上述八项。故本 profile 不证明 GenPop 的每一行明确按名为 8a 的表单施测，也不代表完整 10 项数据或经验证的 CAT。
- `candidate_cat_config.min_items=max_items=8` 只用于完整八题子集覆盖的工程参考，不是批准的 CAT 配置或停止规则。未使用 958 行重拟合参数，也没有建立校准/验证拆分。

## Response artifacts

源文件来自 PROMIS Pediatric General Population Survey，Harvard Dataverse DOI `10.7910/DVN/UXH6DH` V2，记录标记 CC0-1.0。响应来源是美国 KnowledgePanel/GfK caregiver/child general-population panel，child self-report 年龄 8–17；不是学校样本，也不代表中国高中人群。数据集许可与 PROMIS 题目/数字施测许可分开处理。

| 外部文件 | 行数 | 内容 | SHA-256 |
|---|---:|---|---|
| `responses_numeric_1_5.csv` | 1,005 | 八个题项列；值为 codebook 1–5，47 条部分响应的缺项为 `NA` | `b00e87fc4e0335a941d92b09195943deec92e21a53f3101576941e2dab54f6fc` |
| `complete_observed_800.csv` | 800 | 从 958 条八项完整 source rows 中以固定 seed `2026101403` 无放回抽取；输出仅有八项，没有行号或 ID | `7c723fbdb2590a24cc3fa33adb70c8affb323e3688ce3f0477620bd6507d7f32` |

800 条是工程覆盖样本，不是新校准或验证样本；其余 158 条完整行仍保留在 1,005 行全量矩阵中，47 条部分行也保留。抽样 membership 由随机种子和完整行顺序复现；没有输出行号、个体 response hash、人口字段、proxy 项、权重或派生 theta。

Profile SHA-256：`a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3`；manifest SHA-256：`984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524`。构建清单 `manifest.json` 记录源/中间/输出文件级哈希、数量和 seed；`build_profile.py` 可验证源矩阵 SHA 后重建数值版、800 行覆盖子集、profile 和 manifest；抽样用 CPython 3.14.6 `random.Random(2026101403).sample`，manifest 记录算法运行时。这里只使用原始公开 response-only 矩阵，不重新读取含其他字段的临时源文件。

## Rights and limits

2026-10-14 独立研究回放：实际公开观察 800 条完成 6,400 次作答，每例中途签名恢复，800 次恢复全部通过；原始 1–5 类别严格校验，没有补值。结果仅聚合存于外部 `research-runs/promis-observed800-coverage-20261013T205037Z/summary.json`，SHA `0b38fbb9daea9109338e9b92be7d6470a588dd2d7514880342d37f799cdaf677`。相关 adapter 文件 SHA 前后一致，Root 已独立复核；整组 CPU 会话耗时约 290.34 秒不代表学校在线吞吐。第一轮因无关 Git HEAD 变更标记失败并保留，第二轮单独记录 Git、严格检查实际加载代码和资源哈希，完成通过。未写出个人分数或作答记录。

HealthMeasures 当前网站说明，非商业用户进行单次、限时研究时，可将未修改的英文 PROMIS measure 编入数字平台，无需权限或费用；日常/常规教育测量、其他用途、商业用途和翻译适用不同许可要求。本地 profile 仅作隔离研究 staging，不构成学校部署、商业使用或推广授权。后续如要真实施测，须单独核实项目是否符合其“单次、限时研究”条件并满足数据与机构要求。此处不作法律或专业批准决定。

本 profile 不允许诊断、个体心理解释、学校决策、临床处置或跨文化效度声明；公开美国数据与旧版参数不能证明中国高中效度。不得将其直接导入现有在线题库或视为 `human_curated` 内容。

来源： [Irwin et al. 2010, Table 5](https://pmc.ncbi.nlm.nih.gov/articles/PMC3158603/)；[Carle et al. 2020, PROMIS pediatric GenPop study](https://pmc.ncbi.nlm.nih.gov/articles/PMC8005418/)；[HealthMeasures Anxiety Scoring Manual](https://healthmeasures.net/wp-content/uploads/2026/05/PROMIS-Anxiety-Scoring-Manual_08Sept2023.pdf)；[HealthMeasures electronic administration guidance](https://www.healthmeasures.net/explore-measurement-systems/promis/obtain-administer-measures)；[HealthMeasures fees and licensing](https://healthmeasures.net/services/fees/)。

## GRM 参数斜率常数与量尺核对（2026-10-14）

外部计算核对：`D:\Dev\datasets\psynova-public-research\staging\promis-grm-metric-review-20261014-r1\metric-review.json`（SHA-256 `4cfdebdf109a5f9d51f0dc335f571bac63a78e9a7ef5ebb422ec8971587a6e9f`），可由同目录 `metric_check.py` 重算。它只读取已发布参数 crosswalk 和官方公开查表，不读取响应行、不计算任何个体分数。

**斜率结论：当前 `logistic(a × (θ−b))` 不应再乘 1.7 或 1.702。** Irwin et al. 原始儿童 Anxiety 校准文说明采用 Samejima GRM 与 MULTILOG，Table 5 给出 `a`、`b1..b4`，并将参考组 NC 子样本的 anxiety theta 定为均值 0、方差 1。PROMIS 的另一篇 GRM 方法论文明确说明 MULTILOG 不使用额外 D scaling；PROMIS EAP 方法论文所列 GRM 公式也直接写成 `logistic(1 × a × (θ−b))`。所以此处是 **D=1/no extra multiplier**；源类别码 v1 0–4 与 v2 1–5 的偏移只是标签索引不同，不要求缩放 theta 或 `a`。PROMIS 官方 EAP 说明将 T-score 定义为 `50+10θ`。

另以八题 crosswalk 的两位小数参数复算 PROMIS EAP raw-sum lookup，并与 HealthMeasures 2023 Pediatric v2.0 Anxiety 8a 官方表逐分比较。采用其公开的 `θ=-4..4`、0.1 步长、标准正态先验及 EAP lookup 规则时：

- D=1：平均绝对 T 差 `0.026`，RMSE `0.031`，最大绝对差 `0.053`（raw sum 15）。
- D=1.7：平均绝对差 `1.043`，最大差 `2.015`；D=1.702：平均绝对差 `1.045`，最大差 `2.019`。

这支持不做 D 换算，但不证明参数可精确复现原版 CAT 分值：Table 5 只发布两位小数，而官方表可能使用未四舍五入的内部参数。故该 profile 仍只能作研究候选；不要宣称精确原尺度 CAT 估计、上线评分或心理解释。参数、profile 和产品代码均未改动。

来源：[Irwin et al. 2010, GRM/MULTILOG 与 Table 5](https://pmc.ncbi.nlm.nih.gov/articles/PMC3158603/)；[Teresi et al. 2009, MULTILOG 的 D scaling 说明](https://pmc.ncbi.nlm.nih.gov/articles/PMC2844669/)；[PROMIS EAP 方法与公式](https://link.springer.com/article/10.1186/s41687-022-00464-9)；[HealthMeasures 2023 Anxiety Manual, v2.0 8a lookup](https://www.healthmeasures.net/images/PROMIS/manuals/Scoring_Manual_Only/PROMIS_Anxiety_Scoring_Manual_08Sept2023.pdf)。此环境未取得上述论文/PDF 原始二进制文件，因此 metric manifest 没有伪报来源文件 hash；它绑定了本地参数 crosswalk 与 profile 的 SHA-256。

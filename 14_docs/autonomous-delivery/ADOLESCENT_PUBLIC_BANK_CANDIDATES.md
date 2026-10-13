# 青少年 PROMIS 公开题库与作答数据来源核查

核查日期：2026-10-14。目标是为 800 人高中合成情境寻找有人群年龄依据、可复核许可、真实题目文本、GRM 参数和/或匿名化作答矩阵的来源。这里的“可用”仅指公开来源和工程研究候选，不代表学校适用性、量表效度或专业批准。

## 结论

现有证据支持一条分阶段路线：

1. 若需要一套已发表 GRM 参数并能对应校准作答矩阵，PROMIS 1 Pediatric Supplement 是最完整的公开研究候选。Dataverse 标记 CC0，文件不受限，但记录启用了 guestbook 表单；本次只检查元数据，没有提交表单或下载数据。
2. 若优先取得可公开下载的儿童作答矩阵，PROMIS Pediatric General Population Survey 是较易复核的外部对照来源。Dataverse 记录 CC0，数据文件不受限且没有 guestbook；它包含儿童 self-report 的焦虑和抑郁条目列及派生 theta，但其数据集不是新的完整参数校准发布。
3. 当前更适合的 PROMIS Pediatric GenPop v3 焦虑和抑郁校准已发表，但参数需向 HealthMeasures 申请，论文所述 Dataverse 数据发布在本次官方目录查询中尚未找到可确认记录。因此现在不能把 v3 的完整参数和观察矩阵称为已公开取得。

三个来源都是英文美国样本。PROMIS Pediatric self-report 的年龄范围是 8–17 岁；它不能直接证明中国高中生、18 岁学生或特定学校人群的测量有效性。800 人合成场景不应被描述为真实高中校准或验证。

## 候选对照

| 候选 | 人群与真实观察数据 | 题目及 GRM 参数 | 许可 / 获取状态 | 对 800 高中情境的用途边界 |
|---|---|---|---|---|
| **PROMIS 1 Pediatric Supplement**，Harvard Dataverse DOI [10.7910/DVN/IBWSUD](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/IBWSUD) | Dataverse 描述为儿童 5–17 岁，包含一般人群、慢性病样本及 child/parent-proxy 数据。原始 anxiety/depressive-symptom v1.0 论文报告其分析样本 `n=1,529`，来自公立学校与医院门诊/专科诊所；儿童 self-report 目标年龄 8–17 岁。文件 DDI 有 7,423 行、486 个变量，包含 child age 和心理条目字段；此总行数不是 1,529 人焦虑/抑郁校准样本数，不能混为一谈。 | v1.0 原始校准论文报告 GRM 参数，焦虑与抑郁条目分别列出 discrimination `a` 与 4 个 thresholds `b1..b4`（五级作答）；参数和 item stems 可在论文表格中复核。Dataverse 有实际 tabular calibration data、item guide 和 codebook。 | Dataverse 标记 CC0-1.0；文件 `restricted=false`、`fileAccessRequest=false`，但 dataset 有 `guestbookId=110`，须经过 Dataverse guestbook 流程。本次未提交 guestbook、未下载数据文件。PROMIS item-text 权利另受 HealthMeasures 条件约束。 | 最接近“真实作答矩阵 + 已发表 GRM 参数”的完整研究候选，可用于受许可约束的旧版 v1.0 工程复现。它混合疾病与一般样本、儿童与 proxy，年代较早；不能直接作为当前 v3 或中国高中题库。 |
| **PROMIS Pediatric General Population Survey**，Harvard Dataverse DOI [10.7910/DVN/UXH6DH](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/UXH6DH) | 2014 年 GfK/KnowledgePanel 调查，用于 pediatric PROMIS 年龄常模；使用概率面板并加入 opt-in 样本。相关论文报告 Sample 1 有 5,206 caregiver 与 4,005 名 8–17 岁儿童，焦虑等量表分块抽样，每个 domain 约 1,000 名儿童。公开 DDI 对应文件有 5,206 行、946 个变量，并确认 anxiety、depressive-symptom item response 列以及派生 score/theta 字段。 | 有真实问卷反应和派生 theta。相关常模论文使用先前发表的 PROMIS 参数估 theta；此数据集本身没有提供一套新的完整 GRM item-parameter 校准发布。不要把 theta 或 score 列当成 `a/b` 参数。 | Dataverse 标记 CC0-1.0；tabular 文件 `restricted=false`、`fileAccessRequest=false`，dataset 无 guestbook。本次只取 DDI 与 dataset metadata，未下载或查看作答行。PROMIS item-text 使用仍遵 HealthMeasures 条款。 | 可作为带真实年龄范围的公开外部 response/score 对照候选，或作许可确认后的方法复现；其按短表分块、美国一般人口加 opt-in 的设计不等于高中样本，也不替代题库校准。 |
| **PROMIS Pediatric GenPop v3 anxiety / depressive symptoms**，2025 年重标定论文 [DOI 10.1016/j.apro.2025.100200](https://doi.org/10.1016/j.apro.2025.100200) | 论文报告 2021 年概率在线面板的 504 名美国儿童，年龄 8–17 岁，包含 anxiety、depressive symptoms 等五个 pediatric banks。 | 采用 GRM 重新校准；论文说明参数可为研究用途申请，但未将参数表作为公开下载附件。论文称原始数据将公开存入 HealthMeasures Dataverse；本次用论文 DOI/题名及官方 Dataverse API 搜索，没有找到可确认的对应新数据记录。 | 当前 v3 measure 可从 HealthMeasures measure library 查阅；校准参数需申请，完整匿名 response matrix 的公开记录尚未确认。本次未联系作者或 HealthMeasures、未下载数据。 | 是更贴近当前版本的人群/校准路线；`n=504` 小于 800，且当前参数与数据尚未形成已公开取得的完整包。适合作为申请/等待发布路线，不可当作已拿到的 bank 或 matrix。 |

## 使用许可和工程入口

- HealthMeasures 当前说明：英文静态表单纸笔使用通常免费；未修改英文题目的非商业研究型电子管理（例如队列或横断面研究）可免许可费。超出该研究范围的数字测量、商业使用或翻译有单独许可要求。对于学校平台是否符合研究型非商业范围，本次不作法律/许可判断；也不把非商业演示自动视为已获授权。
- PROMIS Assessment Center API 适用于 CAT 与集成评分，但 HealthMeasures 当前费用页列出单机构 API 年费 `$6,000`。因此它不是本地 800 合成演示的“已免费现成来源”。本次未申请或使用 API。
- PROMIS 1 Supplement 数据许可 CC0 不会自动授予 PROMIS 条目在任意电子产品中的所有用途；数据许可与测量工具许可应分别遵守。中国高中部署还涉及未改变原题的翻译许可和人群适配问题，本次没有取得中文题目或授权。
- HealthMeasures 将其 Dataverse 描述为 de-identified 数据集库；这不等于本次独立证明了不可重识别的匿名性。本次只读 DDI/目录元数据，没有检查个体记录，也没有做重识别风险评估。取得数据后须另行检查文件内容、行级字段与适用的研究数据保护条件。
- HealthMeasures 建议按可用最高版本选择量表；其 2024 Pediatric scoring manual 明确 v3 GenPop 分数与 v1/v2 量尺不可直接比较。不要将旧 v1 `a/b` 参数与 v3 题目、题号或类别码拼接。

## 来源与可复核证据

### 原始校准 / 参数

- PROMIS Pediatric v1 anxiety 与 depressive-symptoms GRM 研究：[Irwin et al., 2010, PubMed Central](https://pmc.ncbi.nlm.nih.gov/articles/PMC3158603/)。论文报告目标项目 8–17 岁；其分析 `n=1,529` 招募于学校与门诊；表格列出 v1.0 最终题目 `a` 和阈值参数。
- 原始 Pediatric calibration supplement：[Harvard Dataverse DOI 10.7910/DVN/IBWSUD](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/IBWSUD)。本次只读取 dataset/file metadata 与 DDI；D 盘来源元数据记录 API / DDI 哈希及行、变量计数。

### 公开儿童作答矩阵 / 外部参照

- PROMIS 儿童常模研究：[Carle et al., 2020, PubMed Central](https://pmc.ncbi.nlm.nih.gov/articles/PMC8005418/)。论文报告 GfK KnowledgePanel 样本和 8–17 岁儿童 self-report 样本量；短表分块抽样，焦虑等单域样本约 1,000 人，而非全部 4,005 名儿童均回答同一 domain。
- 对应公开 Dataverse 文件：[PROMIS Pediatric General Population Survey, DOI 10.7910/DVN/UXH6DH](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/UXH6DH)。有 CC0、文件 unrestricted/no file request 元数据；本次未取 response payload。

### 当前 GenPop v3 与许可

- v3 重标定研究：[Lai et al., 2025](https://doi.org/10.1016/j.apro.2025.100200)。论文报告 504 名 8–17 岁儿童、GRM、参数按研究申请，并称数据计划公开存入 Dataverse。公开匹配记录未检出，状态记为“未确认可获取”。
- HealthMeasures：[Measure Development / Calibration Samples](https://healthmeasures.net/promis-basics/measure-development/)、[Measure Library](https://healthmeasures.net/measure-library/)、[Research Tools / Dataverse](https://healthmeasures.net/resources/research-tools/)、[Steps to License](https://healthmeasures.net/implement/steps-to-license/) 和 [Fees](https://healthmeasures.net/services/fees/)。许可与价格取自官网页面；版本/费用会变，实施前需重查。

## 外部元数据产物

D 盘 [candidate-source-metadata.json](D:/Dev/datasets/psynova-public-research/staging/adolescent-public-bank-review-20261014-r1/candidate-source-metadata.json) 只保存公开 Dataset API 元数据、DDI 摘要计数与哈希。未下载响应表、未存储个人响应、未记录 theta 值、未提交 guestbook、未执行付费或受控访问。

## 推荐与停止条件

- **优先研究源路线：**先将 v1 Pediatric Supplement 定位为“已发表参数 + 真实校准矩阵”的研究复现候选，正式数据使用前通过 Dataverse guestbook；只在非商业研究且英文题目不变的许可条件成立时考虑电子管理。真实项目适用、翻译、专业认可及高中效度仍须另行确认。
- **公开外部矩阵路线：**General Population Survey 可用于响应结构的外部复核，但不要从常模 theta 或分数反推/冒充公开 GRM 参数。
- **当前版本路线：**若要采用 v3 GenPop，应先取得其参数及明确许可，再确认 Dataverse 里确有相应原始 response file；在这些条件满足前，v3 不是可直接训练/载入的资源。

本次不把任何成人 SAPA 或 NHANES 数据用于高中测量校准，也没有修改既有 profile、在线题库、服务或数据库。未取得任何心理量表批准或真实高中效度证据。

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

## PROMIS GenPop 原始焦虑响应获取（2026-10-14）

按本轮限定获取了该公开记录的 child self-report Anxiety 原始题项列，数据文件保留在 Git 外部研究 staging，不进入账户档案或产品题库。官方 Dataverse DOI 记录的当前版本为 V2（2021-07-30），许可标记 CC0-1.0，数据文件 unrestricted、无 file-access request，dataset 无 guestbook。原始文件的官方 MD5 `c9b9f7f99a8cab82321d42638fc4d210` 与下载文件一致；SHA-256 为 `993a388937dda48078f52d37691fd7571b2460d33b8e49566f6702a6c4659903`。获取只走 Dataverse 的公开 original-file endpoint，未登录、未提交 guestbook、未付费。

外部产物目录：`D:\Dev\datasets\psynova-public-research\staging\promis-pediatric-genpop2014-anxiety-response-only-20261014-r1`。响应文件为 `data/anxiety-child-response-only.csv`，SHA-256 `c833b0614e74d40aca54b64fcbb5d8983a83638d66d9e7da642147fe9603834a`；清单 `response-only-manifest.json` 保存数据源版本、许可、哈希、逐题编码、筛选和聚合计数。其 8 列为 `Q227BR1`, `Q2230R1`, `Q3150BR2`, `Q5044R1`, `Q2220R2`, `Q3459BR1`, `Q713R1`, `Q3462R1`，仅保留英文原始选项文字和空值，没有写入任何 ID、proxy 条目、人口变量、权重或 theta。

Codebook 将 `AGE` 标注为 “What is your age?”，值标签 1–10 对应 8–17；original CSV 以 `age` 列直接呈现标签 `8`–`17`。5,206 行源记录中，3,973 行年龄在 8–17；1,201 行年龄空缺、32 行拒答而排除。八个焦虑项的非空类别都严格属于 codebook 明列的 `Never / Almost Never / Sometimes / Often / Almost Always`。筛选后 1,005 行至少有一项作答，958 行八项均非空；逐项类别与空值数在外部 manifest 中。原 CSV 将拒答码 `-1` 与系统缺失都呈现为空，因此不能区分，输出一律保留为空，没有推断拒答类型，也没有按缺失筛除个案以凑数。

这些题面与 PROMIS Pediatric Anxiety Short Form 8a 的八项题集一致；HealthMeasures 手册说明 Pediatric Anxiety v1.0/v1.1/v2.0 校准一致，但 GenPop v3.0 量尺不可直接与旧版本比较。该项目论文描述 anxiety domain 采用短表分组抽样，并在方法中提及 10-item anxiety measure，而公开 codebook 中可识别的 child self-report anxiety 列为上述八项。因此本次仅确认 item-set 相符；没有足够来源证据证明每一行在该调查中被明确按名为 8a 的版本施测，也不把 958 条声称为完整 10 项、参数校准或已发表常模样本。未评分、未重新拟合参数、未计算 theta、未做诊断或效度判断。

数据许可与题目权利分开处理：Dataverse 对数据标记 CC0-1.0；HealthMeasures 的非商业电子研究条件另行适用。本产物只保留未翻译英文原题与反应类别，不构成学校管理、商业管理或量表使用授权；不代表中国高中人群验证或专业批准。暂存输入原 CSV 含有本次排除的其他字段；本地策略拒绝删除尝试，因此原件仅留在上述 Git 外部 `temporary` 目录，未尝试绕过策略，未打印行内容。

来源： [Dataverse 数据记录](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/UXH6DH)；[Carle et al., 2020 原文](https://pmc.ncbi.nlm.nih.gov/articles/PMC8005418/)；[Irwin et al., 2010 pediatric item calibration paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC3158603/)；[HealthMeasures Anxiety Scoring Manual](https://healthmeasures.net/wp-content/uploads/2026/05/PROMIS-Anxiety-Scoring-Manual_08Sept2023.pdf)。

补充：本机策略拒绝清理尝试后，外部 `temporary` 目录同时保留已验证的 original CSV 与一份未用于处理的默认 Dataverse tab 响应文件；两者都在 Git 工作树外，未绕过策略删除。
提取器：外部 `scripts/prepare_response_only.py`（SHA-256 `5d28c541ca8120e3459866b0de336cc429e2638be8cbbc168fb9446fa1e6a6ba`）；执行 `python D:\Dev\datasets\psynova-public-research\staging\promis-pediatric-genpop2014-anxiety-response-only-20261014-r1\scripts\prepare_response_only.py` 可按原始文件校验和重建 CSV，并只打印聚合计数。

## PROMIS Anxiety 8a item参数逐题交叉核对（2026-10-14）

新增外部产物：`D:\Dev\datasets\psynova-public-research\staging\promis-anxiety-irwin2010-parameter-crosswalk-20261014-r1\parameter-crosswalk.json`，SHA-256 `2176b6cbf7498d8ef912f2902a22c31cb7b229ac82d988d54567cfe615c9066c`。其中逐项记录 codebook ID/stem、Irwin et al. 2010 Table 5 行定位、参数版本、GRM `a` 与 `b1..b4`、类别映射和来源文件哈希。基于 public codebook 八个 child self-report Anxiety 字段，八项均与 Table 5 的参数条目词句对应（8/8；统一移除共同的“过去 7 天”前缀并忽略末尾标点差异；其中 Q3459BR1 的 codebook stem 没有句点，论文行有句点），无反向计分；参数本身来自论文，不是用前述 958 条重拟合或从 theta 反推。

论文说明 Table 5 是 Pediatric Anxiety item calibration；`a` 为区分度，四个 `b` 为五类别 GRM 阈值，参考 North Carolina 人群的 theta 标准化为均值 0、方差 1。这些 `b` 是模型类别阈值，不是临床界值。HealthMeasures 官方手册说明 pediatric Anxiety v1.0/v1.1/v2.0 校准相同，v1.1 8b 与 v2.0 8a 使用同一组条目，但原始响应编码分别为 0–4 和 1–5；GenPop v3.0 与旧版本不可直接比较。来源数据以英文类别标签存储，codebook 标签 1–5 映射到相同类别顺序；交叉表没有将响应转换为整数或产生任何分数。

可供后续隔离研究回放的方向是：将题集标识为 Pediatric Anxiety v2.0 Short Form 8a item-set，引用 Irwin 2010 v1.0 bank 的逐项 GRM 参数，并保留源响应文字类别；若实现层必须用整数类别，另设经审核的显式类别索引映射。这里仅建立文献参数与来源题项的对应，不是可上线题库、得分器或批准使用的 profile。

施测证据仍有限：Carle 2020 的常模论文描述 anxiety 为 10-item measure，而 public codebook 可识别的 child anxiety 响应列为上述八项。故“8/8匹配”只表示题项与 Table 5/v2.0 8a item-set 对应，不证明该数据集每条记录按名为 8a 的表单施测，也不补成完整 10 项响应。前一产物中 958 是八列完整数，不应称为论文参数的校准样本数。

哈希与来源定位：codebook SHA-256 `00344836cabd71ca2ab247dedd04b5a2b759b574874dd3296db06699d132f786`；source response-only CSV SHA-256 `c833b0614e74d40aca54b64fcbb5d8983a83638d66d9e7da642147fe9603834a`；题项 crosswalk 文件 SHA 在外部目录及清单中记录。论文参数读取自 PMC 正文的 Table 5（DOI `10.1007/s11136-010-9619-3`）；该环境未能取得论文二进制文件，因此未声明论文文件哈希。题目文本和表单的再使用权仍单独受 HealthMeasures 条款约束。

来源：[Irwin et al. 2010, Table 5](https://pmc.ncbi.nlm.nih.gov/articles/PMC3158603/)；[HealthMeasures PROMIS Anxiety Scoring Manual](https://healthmeasures.net/wp-content/uploads/2026/05/PROMIS-Anxiety-Scoring-Manual_08Sept2023.pdf)；[Carle et al. 2020 pediatric GenPop study](https://pmc.ncbi.nlm.nih.gov/articles/PMC8005418/)。

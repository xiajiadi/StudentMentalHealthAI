# 公开 CAT 与量表资源候选

**核查日期：2026-10-13**  
**用途：**为隔离工程验证筛选真实题目、校准/参数来源及响应数据候选。资源公开或论文开放获取，只说明可进一步核查；不构成高中适用性、测量学有效性、伦理/法律依据或学校生产批准。目标人群是高中生；优先使用儿少样本证据。本文不包含、也未下载任何逐行响应数据。

## 建议优先级

优先核查 PROMIS Pediatric Anxiety 与 Depressive Symptoms：HealthMeasures 将 Pediatric 自陈量表定位于 8–17 岁；官方目录列出 Anxiety CAT v2.0（15 题）和 Depressive Symptoms CAT v2.0（14 题）。可用 Harvard Dataverse 的 PROMIS 1 Pediatric Supplement 作为真实校准响应数据候选，但先审阅代码本和字段，确认隐私、同意和适用样本；另有 2025 瑞典研究直接报告 GRM 参数和 CAT 分析补充材料，可作独立研究参数参照，不能与官方美国版本或其他语言版本混用。现阶段没有确认到可直接下载且获准集成到本校 CAT 的官方美国参数包。

| 候选 | 题目 / 样本年龄与人群 | 参数、响应和可获取状态 | 授权及适用边界 |
|---|---|---|---|
| **PROMIS Pediatric Anxiety / Depressive Symptoms CAT** | [官方儿少领域目录](https://healthmeasures.net/promis-basics/promis-domains/pediatric-domains/)列出自陈年龄 8–17；Anxiety CAT v2.0 为 15 题，Depressive Symptoms CAT v2.0 为 14 题。适龄上覆盖高中生中未满 18 岁者。 | 目录和[官方评分服务/API说明](https://healthmeasures.net/implement/scoring/calculate-scores/)可用于确认测量版本/实现路径；本次未找到可直接下载的官方美国独立 GRM 参数包。官方服务说明不等于参数文件许可。 | 官方条款称 PROMIS 受版权保护，单次研究/教育使用不等于可向第三方分发；嵌入专有数字系统（包括 CAT、App、网站）需书面批准，且不得擅自翻译、改写或衍生。[HealthMeasures 使用条款](https://healthmeasures.net/wp-content/uploads/2026/06/Terms-of-Use_HM_approved_1-12-17-Updated-Copyright-Notices.pdf)。先由 Controller/权利方厘清校内隔离原型适用条款；不复制题目进入产品或公开夹具。 |
| **PROMIS 1 Pediatric Supplement（Harvard Dataverse）** | [Dataverse 记录](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/IBWSUD)描述 PROMIS 儿科量表校准数据，5–17 岁儿童，包含一般人群和慢性病样本，并有家长代理配对。 | 元数据列出公开 `.tab` 响应文件（7,423 行、486 变量）及代码本等文件；数据集标 CC0 1.0。文件实际字段、逐行身份风险和可筛选的高中自陈子样本本次**未核验**，没有下载文件或响应行。 | CC0 数据许可不证明隐私安全、原始同意范围或可用于学校个案；须先仅审元数据/代码本，做字段最小化、年龄与自陈过滤，并由 Controller 核准隔离用途。若仍无法确认字段安全，则不导入。可作为“有望直接取得的真实响应资料”候选，不标记为已安全可用。 |
| **瑞典 PROMIS Pediatric Anxiety / Depressive Symptoms 校准研究** | Blomqvist 等，2025，样本 n=928，12–20 岁，来自初高中及儿童青少年精神科；研究明确年龄跨越高中与成人边界。[Springer 论文](https://link.springer.com/article/10.1007/s11136-025-03898-y)。 | 论文用 GRM 并进行 post-hoc CAT，报告条目拟合/区分度/阈值；文章补充材料包含条目参数估计及 Stocking–Lord 转换常数。补充材料可从论文页获取。原始响应数据仅说明可向通讯作者合理请求，故不是公开行级响应集。 | 论文为 CC BY 4.0，但论文许可不自动许可 PROMIS 题目/数字系统集成。它是瑞典语参数和 12–20 岁混合样本证据；文章报告少数项目存在瑞典语与美国版本 DIF。不得把瑞典参数直接当作美国/中文高中常模或已批准学校参数。 |
| **DASS-21 公开题目与计分资料** | [UNSW DASS 下载页](https://dass.psy.unsw.edu.au/down.htm)提供 DASS 问卷；该版本常见于成人/一般研究。此下载页本身不建立高中年龄效度。 | 可取得题目/计分说明；本次未找到官方校准 CAT 参数包或响应数据集。 | UNSW FAQ 称问卷可下载和复制，但不得修改或营利销售；量表材料许可与研究数据/论文许可分别判断。[DASS FAQ](https://www.dass.psy.unsw.edu.au/DASSFAQ.htm)。没有高中验证时不能直接作为高中 CAT。 |
| **DASS-21 GRM/CAT 论文（方法学参照）** | Kraska 等，2023；临床/非临床成人样本（校准 n=580、验证 n=248，平均年龄约 51 岁）。[JMIR 论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC10337454/)。 | 论文报告 GRM，并用 10,000 个从正态 theta 生成的模拟个体做 CAT；不是 10,000 条真实响应。论文含补充材料入口，但本次未核验附件是否提供完整可复用参数表；未确认公开原始响应行。 | 适合复现成人量表 CAT 方法或工程流程，不适合作为高中人群参数或高中效度依据。CC BY 论文许可不等同于 DASS 题目、数据或量表派生用途授权。 |
| **PHQ-A / PHQ Screeners 官方资料** | [官方 PHQ 手册](https://www.phqscreeners.com/images/sites/g/files/g10016261/f/201412/instructions.pdf)列有 PHQ-A（青少年版）；其余 PHQ-9 等版本不能因名称相近而替代 PHQ-A。 | 手册给题目版本与传统计分背景；PHQ-A 的诊断计分算法在手册称可申请获取。本次未发现 PHQ-A 的公开 GRM/CAT 参数包或响应行数据。 | [PHQ Screeners 官网](https://www.phqscreeners.com/)称问卷属于公有领域/可复制，但题目开放不代表存在校准参数或 CAT 授权；须逐个区分版本、计分算法和适用年龄。当前仅作儿少题目候选，不是 CAT 数据源。 |

## 获取状态与官方许可措辞核对

- **Harvard Dataverse**：公开 API 元数据已保存至 `D:\Dev\datasets\psynova-public-research\staging\promis-pediatric\dataverse-metadata.json`（已剔除联系邮箱）。记录为 PROMIS 1 Pediatric Supplement v1、CC0 1.0，响应文件元数据为 4,141,929 字节。尝试按普通文件 API 获取 12,939,236 字节 `.doc` 代码本和 26,579 字节 item-name guide 时，两次均收到 `You may not download this file without the required Guestbook response for guestbookID 110.`；未填写 Guestbook、未下载响应行。因此**无法核查字段或确认能否安全筛出 responses + 粗年龄组**，也没有把该集标成可用数据。文章称其美国比较子样本为 >12 岁且两个 bank 至少各答 4 题，n=1,510，均龄 14.26；这只是论文样本说明，不意味着该子集文件可公开直接取得。原始数据下载仍受 Harvard Guestbook 门槛限制。
- **公开参数附件已取得**：Springer 文章的 [Supplementary Table 文件](https://static-content.springer.com/esm/art%3A10.1007%2Fs11136-025-03898-y/MediaObjects/11136_2025_3898_MOESM1_ESM.docx)已直接下载到 `D:\Dev\datasets\psynova-public-research\staging\promis-pediatric\swedish-open-supplement\11136_2025_3898_MOESM1_ESM.docx`（37,543 bytes；SHA-256 `D7CBE765D4BE123B9BE0549D28B95F972FF5E141D0A8E4D017B38FFA896622B1`）。它含 Anxiety 与 Depressive Symptoms 的四张补充表：Stocking–Lord 常数及瑞典参数列 `a, b1–b4`。研究样本 n=928（学校 637、CAP 291），年龄 12–20；所研究的是 PROMIS Pediatric Item Bank v2.0 Anxiety 15 项、Depressive Symptoms 14 项。附件实际有 13 条 Anxiety 参数行、14 条 Depressive Symptoms 行；未查明少掉的两条 Anxiety 参数如何与题目/混合参数方案对齐，故该附件**不能单独当完整可运行题库**。论文的 CAT 混合方案描述为多数项目用美国参数，仅语言 DIF 项用 Stocking–Lord 转换的瑞典参数；美国参数并未随附件完整给出。公开响应数据并未附上，文章称可按合理请求获取；本轮没有联系作者。
- **HealthMeasures 授权文字存在范围差异**：HealthMeasures 的 [Pricing for Software Applications 页面](https://www.healthmeasures.net/implement-healthmeasures/pricing-for-software-applications)标注“Last updated on 9/30/2024”：多数未改动的英文量表，非商业用户用于 RCT、队列、病例对照或横断面等 research 的电子实施可免许可费；HEAP 对该类研究为 optional。页面同时说明，PROMIS CAT 的 AC API 需要按使用目的、服务器数量和语言报价的年度许可。当前可取的 [Terms of Use PDF](https://healthmeasures.net/wp-content/uploads/2026/06/Terms-of-Use_HM_approved_1-12-17-Updated-Copyright-Notices.pdf)则概括要求在专有数字系统（包括 CAT、App、网站）中集成量表先取得书面许可。两者措辞范围不完全一致；本轮只记录，不作法律解释或替权利方消歧。研究免许可文字仅覆盖符合定义的非商业机构、未改动英文项目和明确研究设计；普通校园运营、例行测量、质量评估、产品化 CAT/AC API 不能直接套用该例外。当前隔离工程验证不是已批准的受试者研究，未据此复制或电子施测 PROMIS 题目。

## 对象与授权不可混为一谈

- **题目文本**：量表题目自身可能受版权或特定使用条款约束。开放获取论文、公开量表页或公共领域声明都不能推导出可任意改写、嵌入或分发。
- **参数/校准结果**：论文附表中的参数可按论文许可阅读和引用；是否能重用参数实现 CAT，还需核对量表版本、补充材料许可和量表权利条款。瑞典 PROMIS 参数不得替代美国版参数。
- **响应数据**：Dataverse 的 CC0 标识仅描述数据集许可，不代替字段级隐私审查、知情同意范围核查及目标人群筛选。研究论文写着“数据可按请求获取”也不是公开下载许可。
- **工程/专业边界**：公开真实数据用于隔离工程验证，不等于正式高中测量工具批准、专业解释授权、学生反馈发布或学校部署许可。L1/L2/L3 发布仍按项目既有专业复核边界执行。

## 给 Controller 的可执行核查顺序

1. 先审 Dataverse 记录及代码本（不下载响应文件），确认字段定义、直接标识符/准标识符、父母代理记录、量表版本和高中年龄自陈筛选是否可安全执行；不满足则停止使用该响应集。
2. 对可确认的儿少自陈子集仅在隔离环境使用最小字段；保留原始许可和来源元数据，不纳入公开 fixture，不上传第三方评分服务。
3. 单独记录 PROMIS 官方版本参数是否有可合法取得的实现渠道；将瑞典论文补充参数只用于经批准的可复现实验，不与美国/中文版本拼接。
4. DASS/PHQ 只作为候选题目或成人方法比较；未有高中校准和专业判断前，不加入高中正式 CAT 路由。
5. 研究来源只作为三层 RAG 的候选引文。入库前另行核对来源真实性、出版元数据、许可、适用人群及可支持的陈述范围；RAG 命中不能代替专业审批。

## 本轮来源核查方法

用 Consensus 检索并调取 PROMIS 儿少校准/CAT 与 DASS CAT 论文记录；用 Exa 读取 Springer 论文、HealthMeasures 使用条款和 PHQ 手册；用 Firecrawl 读取 HealthMeasures 儿科目录和 Harvard Dataverse 元数据；用 UNSW 官方 DASS 页面核对问卷下载入口。以上是公开页面元数据/论文内容核查，没有下载受限文件、响应行数据，没有接受新网站协议，也没有联系作者或机构。

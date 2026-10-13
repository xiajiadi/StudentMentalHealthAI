# NHANES P_DPQ public-use response extract

**核查与提取日期：2026-10-14**
**范围：**CDC/NCHS 官方公开发布的 NHANES 2017–March 2020 pre-pandemic P_DPQ 成人答卷；只用于隔离研究数据工程，不进入产品、冻结题库、正式评估或学校个案工作流。

## 来源、版本与访问范围

官方 [P_DPQ codebook](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DPQ.htm) 将其描述为九项 Depression Screener/PHQ 问卷，并说明 2017–2018 与 2019–March 2020 的数据合并为 pre-pandemic 文件，数据可公开获取。官方 [Questionnaire Data 页面](https://wwwn.cdc.gov/nchs/nhanes/search/datapage.aspx?Component=Questionnaire)列出对应的 `P_DPQ` XPT 数据文件（2021-06）。文件目标年龄为 18–150；12–17 岁 P_DPQY_R 仅可通过 NCHS Research Data Center 获取，本次没有尝试访问受限 youth 数据。

CDC/NCHS [Data Release and Access Policy](https://www.cdc.gov/nchs/data/nhanes/nhanes_release_policy.pdf) 将 public-use release 与非公开、需协议或研究提案访问的数据区分。[CDC Agency Materials 指引](https://www.cdc.gov/other/agencymaterials.html)说明网站内容多数为 public domain，但存在承包方/第三方等例外，并要求来源署名、非背书声明和不改变实质内容。NCHS 的[引用指引](https://www.cdc.gov/nchs/products/citations.htm)建议引用 public-use data file。本次未发现 P_DPQ 文件单独标注的 CC0/CC BY 许可证，因此记录为 **官方 public-use access**，不声称无条件转发或再许可；衍生 CSV 留在隔离研究 staging，不纳入产品或对外分发。输出只保留原数值响应与缺失状态，不复制 PHQ 题目文本、不改写或重编码答案。

## 编码与适用边界

导出字段仅为 `DPQ010`–`DPQ090` 九项。官方 codebook 定义 `0–3` 为过去两周频率（not at all、several days、more than half the days、nearly every day），`7` 为 refused、`9` 为 don't know，`.` 为 missing。导出保持 `7`、`9` 与空值互不混淆；没有插补、总分、严重程度阈值、临床结论或风险标签。

`DPQ090` 的问题回顾过去两周中“better off dead or of hurting yourself”想法。非零仅代表这一条自报项目的频率编码，不是当前危机状态、临床 gold label 或人工复核结论。该成人 NHANES 样本不建立高中生/青少年适用性或校准依据。数据文件合并了不同采集阶段，官方提示总体估计需要特定样本权重；本提取不含权重、设计变量、年龄、人口统计或其它变量，不能用于声称全国代表性估计。

## 已完成的最小化提取

- 官方 XPT 在内存中下载及解析，未把原始含 `SEQN` 文件写入磁盘；提取器只向分析表读取九个白名单响应列。输出行顺序随机化，不保留随机种子或原始行映射。
- 8,965 行，9 个字段。其中 8,276 行九题均为有效 `0–3` 响应；各题 `0/1/2/3/7/9/missing` 的完整聚合计数在 manifest 中，各字段 counts 总计与行数一致。该完整答卷计数仅为数据工程聚合，不是临床标签或质量判断。
- 原始来源 SHA-256：`b20ee66082eaea3d6d05c2699c142e9c49cf7737587364a477b82351cb8b9866`（791,280 bytes）。
- Response-only CSV SHA-256：`1a050397dc420e8eb685a43a5a7b481bb3ff61c38e3b5f4d6fb00988a15a2091`。
- 解析环境：Python 3.12.13、pandas 3.0.6、pyreadstat 1.3.6，位于既有隔离 `research-env`；依赖未安装到全局 Python 或产品运行环境。核对该隔离环境中 girth 0.8.0、numpy 1.26.4、scipy 1.13.1 仍为原版本。

当前 CSV 已固定为上述 SHA-256，可据此复核此份产物；由于输出行随机化时没有保存 seed 或行映射，重新执行提取不保证逐字节复现同一行顺序。manifest 的 `rerun_bitwise_reproducible=false` 明确记录这一点；不保留任何能映回来源行的信息。

产物保存在 `D:\Dev\datasets\psynova-public-research\staging\nhanes-dpq\`：

- `P_DPQ_response_only.csv`：仅九列匿名化顺序的 0–3、7、9、空值响应；没有 `SEQN`、`DPQ100`、人口统计字段或行级映射。
- `P_DPQ_response_only_manifest.json`：来源 URL、codebook、来源/输出哈希、访问与授权边界、转换白名单、各题类别/缺失聚合数、局限和工具版本。

这项工程提取没有生成心理测量参数或评分解释，也不构成专业量表审批、青少年效度、危机判断或生产使用授权。

# IPIP 与公开匿名人格响应资源清单

更新时间：2026-10-13。用途限定为隔离开发研究；本文件记录来源、权限、获取和字段治理，不构成量表批准、测量学结论或学校代表性证据。

## 选择与当前结果

当前实际取得 SAPA 项目的 Harvard Dataverse v3.0 数据。其数据集许可为 CC0 1.0，官方保留了 IPIP100 标记、逐题文本及 1–6 序位响应；原始 CSV 经官方校验值验证后，只导出与 IPIP 官方 100 题键逐字匹配的 99 个响应列。`q_1483` 的来源措辞与官方键不完全相同，明确排除；未用语义相似项代替。没有反向计分、插补、完整案例筛选、得分或参数估计。

样本是 SAPA 项目 2010-08-18 至 2013-12-08 的自选在线参与者，不是学校、高中或大学代表性样本，也不是临床或诊断样本。该响应数据只可用于隔离研究与工程演练；未经独立测量学审查，不可声称已经校准、形成有效量表或用于操作性 CAT。

## 来源比较

| 来源 | 一手证据与许可 | 内容/隐私/限制 | 本次处理 |
|---|---|---|---|
| IPIP 官方题目与键 | [IPIP 官网](https://ipip.ori.org/)说明公开量表项目可复制、修改、翻译和使用；[计分说明](https://ipip.ori.org/newScoringInstructions.htm)、[Big Five 100 键](https://ipip.ori.org/newBigFive5broadKey.htm)。 | 官方键含五个 20 题域及正反向标记；方向对应键，不等于本响应数据的 1–6 评分转换规则。 | 已保存官方题目/键 HTML 和精确匹配映射；无 99/100 补题。 |
| SAPA / Harvard Dataverse | [数据集 DOI](https://doi.org/10.7910/DVN/C40K1U)，v3.0，David M. Condon、William Revelle，CC0 1.0；[SAPA SPI](https://www.sapa-project.org/research/SPI/)、[Dataverse API 文件元数据](https://dataverse.harvard.edu/api/files/11003923)。 | 来源代码本记载 128,464 人、373 个 temperament items 以及 `RID`、`gender`、`age` 三个非题目字段；响应类别 1–6，缺失广泛且有计划性。在线自选样本，不得改称学生/大学代表样本。 | 已获原始 CSV；只导出 99 个严格键匹配响应列及单独题目 crosswalk，人口统计和来源 ID 未输出。见下方哈希及缺失分布。 |
| OpenPsychometrics / IPIP-FFM 2018 | [官方原始数据页](https://openpsychometrics.org/_rawdata/)提供公开下载与研究用途说明；[About](https://openpsychometrics.org/about/)说明匿名数据与研究使用征询。 | 官方页报告 50 题、1,015,342 记录并提供 codebook。页面上的研究同意/匿名说明未找到明确的再分发许可；未下载包内 codebook，外部代码本摘录提示可能含时间、国家/地理/IP 重复计数等风险字段，仍须用官方包内 codebook 复核。不能仅凭“匿名”视为可再分发许可。IPIP 官方 [norms/data 页面](https://ipip.ori.org/newNorms.htm)还明确警告不要使用 2014 `BIG5` 19,719 条旧包，因标签/方向及计分问题。 | 未下载响应数据；旧 2014 BIG5 明确排除。2018 包不是当前主来源。 |
| Johnson / PsychArchives IPIP-NEO | [PsychArchives 主记录](https://www.psycharchives.org/en/item/e42a4531-1daa-4f3d-aef4-58f085c77cd8)，DOI [10.23668/psycharchives.2448](https://doi.org/10.23668/psycharchives.2448)，记录标注 CC BY 4.0、Public Use Level 0；文件名 `Kajonius_Johnson_2019_SUPPL.zip`，页面列 300 题数据。IPIP 的 [300/120 对比页](https://ipip.ori.org/IPIP300-120ComparisonTable.htm)与 [120 项题目页](https://ipip.ori.org/30facetneo-pi-ritems.htm)作题目参考。 | PsychArchives 页面报告大型成人/在线数据集；不代表临床、学校或大学学生。 | 实测官方 bitstream HEAD 返回 HTTP 502（Azure Application Gateway），未取得/未缓存 ZIP；不可把候选或页面样本量写成已导入数据。 |

## SAPA 文件、完整性与处理

来源文件：`sapaTempData373items18aug2010thru08dec2013.csv`，Dataverse file ID `11003923`，original format `text/csv`，原始大小 `141,414,305` bytes；官方 API 元数据提供 MD5 `8e34f3f2cb9a7f3098d1b96f3251889e`。2026-10-13 实际下载原始格式的大小及 MD5 与元数据相符，SHA-256 为 `34f0ab46c9203888de5db4d4d068add4635aec252b0464780e9f295f3f6377ab`。

Dataverse [官方 Data Access API 文档](https://guides.dataverse.org/en/latest/api/dataaccess.html)说明表格默认提供 archival tab-delimited 形式，`format=original` 返回保存的原始形式。我们分别下载了默认 TSV 和 `?format=original` CSV：TSV 57,642,257 bytes 的本地 MD5 为 `f4268ac1fc29a12b0fe4aaa6aba1b507`；原始 CSV MD5 则与 API checksum 一致。两份不同表示没有混用；实际响应导出从校验通过的 original CSV 生成。

已写入隔离 staging 的产物：

- `D:\Dev\datasets\psynova-public-research\staging\sapa-ipip100-response-only.csv`：128,464 行、99 列，17,234,275 bytes，SHA-256 `4c151783eb5c8cbe125b91dfad425c08fa04015af9d52dca543fb2a8a8b9f4f9`。仅包含 1–6 响应或空值。
- `D:\Dev\datasets\psynova-public-research\staging\sapa-ipip100-item-crosswalk.tsv`：99 条来源 item ID / 原题 / IPIP100 代码 / 域 / 官方键方向映射；唯一未匹配 `q_1483` 排除，没有替代。
- `D:\Dev\datasets\psynova-public-research\staging\sapa-ipip100-source-manifest.json`：来源版本、许可、SHA/大小、题目字段、每题 missing count、未输出字段、item response 数分布及输出哈希。

其他实际保存的小型一手题目/代码本文件（SHA-256）：

| 文件 | 大小 bytes | SHA-256 |
|---|---:|---|
| ipip-50-questionnaire.html | 50,306 | 489d66de7a643d13e620ad2907285639f12e0bc083fbb4e68dc54128373e6f5a |
| ipip-50-scoring-key.html | 18,088 | 8577862772802903db4330c5a2178bd3948894fe86b82909865bb9b5f17411f9 |
| ipip-neo-300-facet-scoring-key.html | 51,708 | f377956f942163dca42a7d1df266bb3ed2988d662cf487c21e4dbfb9f3abb15d |
| johnson-ipipneo-120-items.html | 17,649 | a0e491cc737a1d3f0fbc864d64bbc7c283fa696c64c05dab5c639ced4fc14512 |
| johnson-ipipneo-300-120-item-count-key-balance.html | 366,806 | a8d4c6051715a4e619f1a339f310c1419e33b4af58a4241731130fe93906548d |
| sapa-background-demographic-codebook.txt | 1,124 | 5ab1f6535ccab1969cd42a1d8fd0b0275ca98d653e41033b142971b2a44a29ab |
| sapa-dataverse-metadata.json | 8,630 | 7b5ce10bcc8fa88bf036edcdc70a50a3f2cac2c7716c5ab23d0d49acafc14d50 |
| sapa-ItemInfo373.tab | 31,949 | 9d3c176998fe78051529d907646af6989c70438ed01882ce271e51c8fac79c72 |

严格输入列：Dataverse schema 的 376 列由 373 个题目列及 `RID`、`gender`、`age` 组成；导出只保留 99 个逐字匹配 official key 的响应列。其余 274 题目列及三个非题目列全部丢弃；不保存 RID、性别、年龄、行级哈希、地理/IP/时间字段或来源人口数据。响应缺失保持空单元格，无插补、无 complete-case 筛选。

99 题答题数总体分布（仅聚合人数）：0–9 题 6,068；10–19 题 38,978；20–29 题 5,926；30–39 题 560；40–49 题 47,299；50–59 题 29,594；60–69 题 39；70 题以上 0。min/median/max 为 0/49/66。逐题有效暴露数范围 44,207–47,591，median 45,043。随机子集与计划性缺失真实存在；后续分析须保留 missing，不能为凑样本做完整案例筛选或捏造作答。

## 可复现获取与 response-only 生成

以下命令只写入隔离 `staging` 目录。官方原始 CSV 请求可能较慢，可用 `--continue-at -` 续传。运行转换前必须先检查大小及官方 MD5：

```powershell
$stage = 'D:\Dev\datasets\psynova-public-research\staging'
$raw = Join-Path $stage '_work\sapa-original-format.tmp'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $raw) | Out-Null
curl.exe --fail --location --silent --show-error --max-time 900 --continue-at - `
  --output $raw 'https://dataverse.harvard.edu/api/access/datafile/11003923?format=original'
if ($LASTEXITCODE -ne 0) { throw 'Dataverse original-format download failed' }
if ((Get-Item -LiteralPath $raw).Length -ne 141414305) { throw 'Original file size mismatch' }
if ((Get-FileHash -LiteralPath $raw -Algorithm MD5).Hash -ine '8e34f3f2cb9a7f3098d1b96f3251889e') { throw 'Official Dataverse checksum mismatch' }
```

本次已运行 staging 转换脚本 `build_sapa_response_only.py`，以 `sapa-ItemInfo373.tab` 与官方 Big Five key 建立 99 题 exact-key allowlist，验证 376 字段架构、1–6 作答域及 128,464 行，再仅写响应矩阵、题目 crosswalk 和 JSON source manifest。脚本没有抽样；后续抽样由 `01_cat-engine/src/cat_engine/research/import_responses.py` 执行时须传入响应列、空值策略、source SHA-256、CC0/来源人群、seed、calibration 与 evaluation 数，并输出互斥样本。不要提交原始 CSV、临时下载、缓存或行级答卷。

## 尚未确认

PsychArchives 300 题 ZIP 当前官方 bitstream 仍返回 HTTP 502，因此没有真实取得。OpenPsych 2018 数据页公开，但该数据未明确采用再分发许可，且需要包内 codebook 与字段逐项复核；本次没有下载。SAPA 99 题响应矩阵虽已隔离，但未执行 CAT/GRM 参数校准、heldout 回放或测量学验证。

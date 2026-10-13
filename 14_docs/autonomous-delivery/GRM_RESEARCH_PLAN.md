# SAPA/IPIP GRM 隔离研究计划与单域 pilot

日期：2026-10-14。状态：`RESEARCH_CROSSCHECK_REVIEW_REQUESTED`。仅隔离研究，不改在线参数、项目运行时数学、已冻结 bank 或生产状态。

## 已批准的最小模型范围

Controller 决定采用成熟实现 mirt 作为五个官方 broad domains 各自的一维 GRM MML 研究基线，GIRTH 只保留为数值交叉参照，不作为产品依赖。这是五个独立的一维拟合，不是五维 MIRT，也不等于心理测量学批准。Extraversion 交叉核验与其余四域的拟合均已完成，仍待 Controller 研究审阅。

- 输入：来源许可 CC0 1.0，SAPA 2010–2013 原始 CSV 经 Dataverse official API checksum/size 核验。Controller 已用现有 response importer 无放回随机抽样并分离得到 `D:\Dev\datasets\psynova-public-research\derived\sapa-ipip99-20261013-v1`：10,000 calibration、800 evaluation、seed `20261013`，从 128,464 × 99 response-only 源数据分离；空值保留，split manifest 保存 source SHA256 和输出哈希。
- 测量键：99 个与 [IPIP 官方 100 题键](https://ipip.ori.org/newBigFive5broadKey.htm)措辞完全匹配的列。`q_1483` 没有精确匹配，剔除；未猜测语义等价题。Extraversion 有 20 条 exact-key item。
- 类别：source codebook 定义 `1..6` 从 Very Inaccurate 到 Very Accurate。正向键保持原值；官方反向键按 Controller 选择的 `7 - response` 翻转 1↔6、2↔5、3↔4。只变换观测值，missing sentinel 永远不变。
- 缺失：空格映射到 GIRTH 的 `INVALID_RESPONSE=-99999`。不插补，不以全量 complete-case 筛人。按 item likelihood 对 NA 作边际省略；这要求后续把题目随机投放/缺失机制可忽略性作为单独假设核验。

## GIRTH 源码确认与环境

隔离研究环境：`D:\Dev\datasets\psynova-public-research\research-env`，Python 3.12.13、`girth==0.8.0`、`numpy==1.26.4`、`scipy==1.13.1`。创建命令：

```powershell
uv venv --python 'D:\Dev\pythons\cpython-3.12.13-windows-x86_64-none\python.exe' 'D:\Dev\datasets\psynova-public-research\research-env'
uv pip install --python 'D:\Dev\datasets\psynova-public-research\research-env\Scripts\python.exe' 'girth==0.8.0' 'numpy==1.26.4' 'scipy==1.13.1'
```

GIRTH wheel 是 MIT，但 PyPI 显示 0.8.0 于 2021-11-11 发布并标记 Alpha；不作为稳定产品依赖。固定 SciPy 1.13.1 是为了规避官方仓库仍可见的 SciPy 1.14+ `scipy.stats.mvn.mvnun` 移除问题（多维初始值路径相关）。此 venv 完全在 D 盘，没有改项目 `.venv`、全局 Python、CUDA/GPU 或运行服务。

对已安装 wheel 的源码已直接核验：

1. `girth.utilities.utils.tag_missing_data` 把非 1–6 的单元改成 `INVALID_RESPONSE=-99999`。
2. `condition_polytomous_response` 生成 `valid_response_mask`，只在有效观测上重新编码类别。
3. `grm_mml` 把 `invalid_response_mask` 传入逐题 GRM likelihood；`_graded_partial_integral` 对缺失项赋值 `1.0`。因此该题对这个人的乘积似然贡献为 1，不计分、不估补值、不删除整个人；这是单维 GRM MML 实际实现，不是从 README 中 2PL 示例推断。
4. 多维 GRM 入口也把同样 mask 传给 `_graded_partial_integral_md`，其中 missing 项同样设 likelihood 为 1.0；然而目前没有用多维源码运行研究拟合。

GIRTH 对一维 GRM MML 和缺失掩码有实际实现，但 2021 Alpha 版本的算法/错误报告仍需谨慎。其 `grm_mml` 返回值没有显式 `converged` 字段；函数源循环按 `max(abs(discrimination_t - discrimination_t-1)) < 1e-3` break，若达到 `max_iteration` 则直接返回。因此 pilot 使用 trace 观察实际循环次数与最后差值，不能把普通返回当成已收敛。

## Extraversion 单域 pilot 结果

运行脚本：`D:\Dev\datasets\psynova-public-research\staging\_work\run_grm_pilot.py`。参数：20 items × 10,000 calibration participants（10 个 positive-key、10 个 reverse-key；按 pilot artifact 的 item map 计数），quadrature=41、LUT enabled、standard-normal latent prior、固定分布、100 iteration upper bound；仅记录聚合诊断与 item-level 参数，不保存/输出个人能力估计或原始响应行。

- 观察到收敛：第 5 次循环停止，最大 discrimination 变化 `0.0002323028`（低于 `1e-3`）。
- 本域至少答 1 题的参与者 9,788/10,000；212 个全域空记录保留在输入矩阵。每题有效观测数 3,393–3,746；20 题均观察到完整 1–6 类别。
- 全部 100 个阈值为有限数且逐题有序；区分度 min/median/max 为 0.7416 / 1.8896 / 2.5831。
- GIRTH 发出 4 个 `invalid value encountered in log` 警告，来自优化过程的 `-sum(log(item-pattern likelihood))`。虽然拟合返回有限、递增阈值且按源停止差值达到收敛条件，这些候选参数 likelihood 下溢警告必须保留并由 Controller 审核，不得压制。
- 此设置下 AIC/BIC null 与 final 相同，不可用于模型比较：当 `estimate_distribution=False`，GIRTH `LatentPDF.n_points=3`，GRM MML 传入最终模型的 penalty 参数 `k=n_points-3=0`。pilot 不以此声称拟合优度。

诊断及仅含 item 参数的结果：`D:\Dev\datasets\psynova-public-research\derived\sapa-ipip99-20261013-v1\grm-pilot-extraversion.json`，SHA-256 `d13de4dbf7b4f009bd86a9e63d429a08e7eaddddecdd0fdf8c58ab4c3bf77396`。未运行 evaluation 样本 replay；Extraversion 的 mirt 交叉核验见下文。

## mirt 一维研究基线：四个剩余域

Controller 批准后，以 mirt 1.47 对 Agreeableness、Conscientiousness、Emotional Stability、Intellect / Imagination 分别拟合。每域使用 10,000 条 response-only calibration 输入、exact-key 子集、1..6 类别、`7 - response` 反向计分、Gaussian N(0,1)、graded GRM、EM、41 个 quadrature points、最多 1,000 cycles、`SE=FALSE`。mirt 使用全部至少包含一项作答的行；全空记录保留在输入文件，但作为无信息模式不参与似然。没有插补或 complete-case 筛人。

| 域 | 题数（正向 / 反向） | 使用行 / 全空 | EM迭代 | 自由参数 | 收敛 | 有限且有序阈值 | logLik | AIC | BIC |
|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| Agreeableness | 20（14 / 6） | 9,891 / 109 | 68 | 120 | true | 100/100；20/20题有序 | -100327.1899 | 200894.3797 | 201758.3054 |
| Conscientiousness | 19（11 / 8） | 9,830 / 170 | 63 | 114 | true | 95/95；19/19题有序 | -102544.9697 | 205317.9395 | 206137.9636 |
| Emotional Stability | 20（5 / 15） | 9,757 / 243 | 70 | 120 | true | 100/100；20/20题有序 | -108100.5689 | 216441.1378 | 217303.4266 |
| Intellect / Imagination | 20（13 / 7） | 9,849 / 151 | 45 | 120 | true | 100/100；20/20题有序 | -101094.2552 | 202428.5104 | 203291.9254 |

四域每一题都观察到全部六个类别，区分度和阈值均有限。AIC 按 `-2 × logLik + 2k`，BIC 按 `-2 × logLik + log(N_used) × k`；以逐域实际估计行数复算，均与 mirt 输出一致。每次拟合保留 mirt 警告 `data contains response patterns with only NAs`；输入中的全空行数与估计中作为无信息模式排除的行数逐域一致。

另外按 mirt `residuals(type="LD")` 输出 item-pair standardized Cramér's V 的绝对值聚合摘要。源码为每一题对使用 `table(data[, i], data[, j], useNA="no")`，按 pairwise 可观测回答计算；没有全局删除含缺失者。每域的 171 或 190 个可能题对均得到有限值：Agreeableness 的中位数/P95/最大值为 0.1062/0.1859/0.2291；Conscientiousness 为 0.1065/0.1547/0.2803；Emotional Stability 为 0.1202/0.1758/0.3271；Intellect / Imagination 为 0.1084/0.1527/0.2489。这些仅是描述性残差摘要，不设切点、不作单维假设通过/不通过判断。

`itemfit(..., fit_stats="S_X2")` 未计算：mirt 1.47 官方文档说明此检验不能用于含缺失响应的数据，需要多重插补或删行；本研究未采用这两种处理。因此未报告 S-X² 或替代 item-fit 结果。LD 输出仅保留摘要，不保存 pair matrix、person scores 或作答行。

逐域 item 参数、类别频数、缺失计数、收敛、AIC/BIC、警告及 LD 聚合见 `D:\Dev\datasets\psynova-public-research\R-runtime\mirt-crosscheck\domains-20261014-final\` 与 `mirt-remaining-domains-20261014-final.json`；重现脚本为 `run_mirt_remaining_domains.R`（将 `PSYNOVA_MIRT_RUN_ID` 设为新的唯一 run id，防止覆盖既有结果）。Extraversion 单域 GIRTH/mirt 对照单独见 `mirt-extraversion.json`。没有拟合 800 evaluation split、没有估算或保存个人能力/分数，没有形成 norms、心理解释、CAT item-bank readiness 或五维模型结论。

## 与在线 CAT provider 的边界

本地 [`adaptivetesting_provider.py`](../../01_cat-engine/src/cat_engine/providers/adaptivetesting_provider.py) 当前把能力值存成标量 `theta: float`，item 区分度装载为 `float(item.parameters["a"])`，阈值为一个一维 `b` 列表；选择信息量时只给当前标量 `ability`。Item 文档存在 `dimension`，但该 adapter 并没有多维 theta 或向量 discrimination 输入。`CATConfig` 仍选择单个 `GRM`/`GPCM`，因此现有 provider 实际是单维接口。不要把五个 domain 的独立标量结果包装成一个在线五维 bank；本任务没有改该 provider、math、published bank 或 backend。

## 后续方法路线与限制

- 当前待办是 Controller 审阅 GIRTH pilot 的 4 个数值下溢 warning 与 mirt 五个一维模型的估计、缺失及 LD 汇总，再决定后续研究。800 独立 evaluation replay 尚未运行；assessment/evaluation 的正式 acceptance 仍由 Controller 和专业人员分别决策。
- mirt 1.47 用于隔离的一维研究基线；GIRTH 0.8.0 只作为 Extraversion 数值交叉参照，不作为项目或产品依赖。五维 GRM、五域联立结构、旋转/识别、估计及缺失随机假设仍未研究。GIRTH README 提醒超过 3 factors 的多维 MML 计算可能很慢；本轮不运行五维模型。
- rig v0.11.0 Windows user-mode 路线仍阻断：官方源码中的 `sc_add()` 先运行 `sc_clean_registry()`，随后在没有默认版本时 `set_default_if_none()` 调 `sc_set_default()`；`src/windows/registry.rs::update_registry_default()` 会写 `HKCU\SOFTWARE\R-core\R` 和 `R64` 的 `Current Version`/`InstallPath`。自定义 `RIG_BINARY_DIR` 只避免 PATH 写入，不能抑制注册表路径；没有运行 `rig add`、`default`、`script-assoc` 或 Rtools。
- 已改走获准的官方文件提取路线，没有执行 R 安装器：CRAN `R-4.6.1-win.exe`（91,749,976 bytes）的本地 MD5 `7907f3a20ec8ec88cd0da279024b8e27` 与官方 sidecar 匹配，SHA-256 为 `C5424C40CD70EF85765A55D2FF96BB602B5F30ED536938FF004F14DB5DB3C2DF`，Authenticode `Valid`（Martyn Plummer）。官方 `innoextract` Windows 1.9 ZIP SHA-256 `6989342c9b026a00a72a38f23b62a8e6a22cc5de69805cf47d68ac2fec993065` 与项目官网 `SHA256SUMS` 匹配；其网站另提供 OpenPGP 签名，本机未安装 GPG，因此没有声称独立验证该签名。该 2020 binary 自报支持至 6.0.5，而当前 R installer 数据版本为 6.1.0；实际 `--test` 完整校验通过，随后解包并运行成功。CRAN FAQ 说明基本 R 安装可从磁盘/USB 位置运行且 R 运行时不使用注册表。
- 隔离 R 根为 `D:\Dev\datasets\psynova-public-research\R-runtime\extracted\app`，`R_HOME`、`R_USER`、`R_LIBS_USER`、`TMPDIR` 均显式设在 D 盘。`Rscript --vanilla` 实际报告 R 4.6.1 UCRT、`x86_64-w64-mingw32`、正确 D 盘 `.libPaths()`；运行前后只读检查的 `HKCU\SOFTWARE\R-core\R` / `R64` 项均不存在。没有改 PATH、注册表、文件关联或系统 R。mirt 1.47 与 63 个直接/传递 CRAN Windows binary 依赖安装到隔离的 D 盘私有库；安装日志显示 64 个包的 MD5 sums checked，`package-lock.csv` 保存包版本、Built 和 CRAN 4.6 binary repo。
- 完成一个同输入 Extraversion 数值交叉核验：10,000 calibration × 20 exact-key items，10 reverse + 10 positive；类别按 `7 - response` 反向计分，NA 保留。`mirt` 使用一维 graded GRM、Gaussian N(0,1)、EM、41 quadrature points、最多 1000 cycles、无 SE。输入 9,788 人至少答一题；212 个全 NA 记录保留在输入，mirt 报警告 `data contains response patterns with only NAs`，模型实际使用全部 9,788 个至少有一题作答的记录，只将 212 个无信息全空记录排除。未做 complete-case 筛选或插补。90 次迭代收敛，耗时 4.1 秒，120 个自由参数；log likelihood `-107419.4430`。GIRTH pilot 未存 LL；从已核验源码公式 `AIC=2*(k-LL)` 派生其 LL 为 `-107435.2398`（固定分布时 `k=n_points-3=0`），两者差 `15.7968`。item discrimination / threshold 相关分别 `0.999969` / `0.999937`，MAE `0.02946` / `0.03480`。mirt 警告和对照指标见 `D:\Dev\datasets\psynova-public-research\R-runtime\mirt-crosscheck\mirt-extraversion.json`；脚本、package lock 在同目录。此结果仅是相同输入上的研究数值交叉核验，不能据此批准参数、CAT bank、临床或学校适用性；不含个人能力估计或作答行。
- Extraversion 交叉核验与四个域的拟合均为研究数值参照，不代表模型获准使用。Controller 后续决定是否另行授权 evaluation split replay；本轮没有拟合该 split、EAP/能力分数或五维模型，也未改在线 provider、冻结 math 或 published bank。

## 一手技术来源

- GIRTH repository/API/README（支持项、一/多维 GRM MML、缺失标记说明、>3 因子的计算提示、MIT）：[GitHub](https://github.com/eribean/girth)；[PyPI 0.8.0](https://pypi.org/project/girth/0.8.0/)。
- 已安装代码路径：`research-env\Lib\site-packages\girth\utilities\utils.py`、`utilities\polytomous_utils.py`、`unidimensional\polytomous\grm_mml.py`、`unidimensional\polytomous\partial_integrals_poly.py`、`multidimensional\multidimensional_mml_methods.py`、`multidimensional\partial_integral_md.py`。
- SciPy 1.14+ 的 `mvn.mvnun` 兼容 issue：[GIRTH issue #150](https://github.com/eribean/girth/issues/150)。
- `mirt` graded/multidimensional/EM/MHRM/NA：[mirt 官方 API](https://philchalmers.github.io/mirt/docs/reference/mirt.html)、[项目说明](https://github.com/philchalmers/mirt)；R package license 为 GPL-3-or-later。
- R Windows 安装格式、注册表和可移动基本安装依据：[CRAN R for Windows 下载](https://cran.r-project.org/bin/windows/base/)、[R for Windows FAQ](https://cran.r-project.org/bin/windows/base/rw-FAQ.html)。安装器未执行；仅在 D 盘文件提取。`innoextract` 来源、适用范围、不会执行 installer scripts/checks 的说明：[项目官网](https://constexpr.org/innoextract/)、[官方 1.9 Windows binary index 与 SHA256SUMS](https://constexpr.org/innoextract/files/innoextract-1.9/)。
- Windows 隔离 R 安装/目录变量：[rig user/admin guide](https://rig.r-lib.org/admin-vs-user-mode.html)、[rig config](https://rig.r-lib.org/reference/config.html)、[Posit rig 0.11.0 Windows 目录说明](https://opensource.posit.co/blog/2026-10-09_rig-0-11-0-part-one/)。rig v0.11.0 source evidence: [`src/windows/mod.rs`](https://github.com/r-lib/rig/blob/v0.11.0/src/windows/mod.rs) (`sc_add`, `sc_set_default`), [`src/windows/registry.rs`](https://github.com/r-lib/rig/blob/v0.11.0/src/windows/registry.rs) (`sc_clean_registry`, `update_registry_default`), [`src/common.rs`](https://github.com/r-lib/rig/blob/v0.11.0/src/common.rs) (`set_default_if_none`). Official release hash/signature/help captures are in `D:\Dev\tools\psynova-research-rig\release-verification.json` and `help-*.txt`.

## 原始来源临时文件清理

已生成的 response-only 矩阵和题目映射不含 respondent IDs 或人口字段。原始 Dataverse original CSV 与转换 TSV 目前仍在 `staging\_work` 临时目录；对这两个本任务下载的确切临时文件调用 `Remove-Item -LiteralPath` 被执行策略拒绝。未尝试替代删除机制，也未删除其他文件；最终交付前仍需清理这两份原始文件。

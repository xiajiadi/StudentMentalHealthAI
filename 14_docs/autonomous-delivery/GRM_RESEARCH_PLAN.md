# SAPA/IPIP GRM 隔离研究计划与单域 pilot

日期：2026-10-13。状态：`RESEARCH_PILOT_REVIEW_REQUESTED`。仅隔离研究，不改在线参数、项目运行时数学、已冻结 bank 或生产状态。

## 已批准的最小模型范围

Controller 决定先将 IPIP 官方五个 broad domains 各自作为一维 GRM MML 研究基线；它不是五维 MIRT，也不等于心理测量学批准。先做一个 domain pilot 后再由 Controller 审阅，当前只完成 Extraversion pilot，没有批量运行其余四域。

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

诊断及仅含 item 参数的结果：`D:\Dev\datasets\psynova-public-research\derived\sapa-ipip99-20261013-v1\grm-pilot-extraversion.json`，SHA-256 `d13de4dbf7b4f009bd86a9e63d429a08e7eaddddecdd0fdf8c58ab4c3bf77396`。未运行 evaluation 样本 replay；未拟合其他四域。

## 与在线 CAT provider 的边界

本地 [`adaptivetesting_provider.py`](../../01_cat-engine/src/cat_engine/providers/adaptivetesting_provider.py) 当前把能力值存成标量 `theta: float`，item 区分度装载为 `float(item.parameters["a"])`，阈值为一个一维 `b` 列表；选择信息量时只给当前标量 `ability`。Item 文档存在 `dimension`，但该 adapter 并没有多维 theta 或向量 discrimination 输入。`CATConfig` 仍选择单个 `GRM`/`GPCM`，因此现有 provider 实际是单维接口。不要把五个 domain 的独立标量结果包装成一个在线五维 bank；本任务没有改该 provider、math、published bank 或 backend。

## 后续方法路线与限制

- 对已选的一维 baseline：Controller 先审阅此 pilot 与 4 个数值下溢 warning，再决定是否继续其他四域的 10k calibration fits。后续应逐域输出 convergence、每题类别频数/阈值顺序、缺失暴露、item fit，以及 800 独立 evaluation 回放；assessment/evaluation 的正式 acceptance 仍由 Controller 和专业人员分别决策。
- 如需真正的五维 GRM，优先另行验证 R [`mirt`](https://philchalmers.github.io/mirt/docs/reference/mirt.html)：官方文档有 graded item type、EM/MHRM 及 `NA` 编码；五维模型结构、旋转/识别、估计和缺失随机假设应先指定。主机当前未找到 `Rscript`，没有安装 R/mirt。GIRTH README 也提醒超过 3 factors 的多维 MML 非常耗时；当前轮不跑五维模型。
- 已下载并核验官方 rig v0.11.0 Windows x86_64 ZIP（8,572,796 bytes，GitHub release asset API `digest=sha256:81218ebc88d24f100686106542ac487fa9b2755f905539b450e0eb87a5364f9d`），ZIP 解压后 `rig.exe` Authenticode `Valid`；工具位于 `D:\Dev\tools\psynova-research-rig`。已读取 `rig --help`、`rig add --help`、`rig config --help`、`rig system dirs --help` 和发布 tag 对应官方源码。虽然 user mode 支持 `RIG_R_INSTALL_DIR`、自定义 `RIG_BINARY_DIR`（文档称避免 PATH 更新）以及自定义下载目录，但 v0.11.0 的 Windows `sc_add()` 明确先调用 `sc_clean_registry()`，之后无默认版本时 `set_default_if_none()` 调用 `sc_set_default()`；`src/windows/registry.rs::update_registry_default()` 会在 `HKCU\SOFTWARE\R-core\R` 和 `R64` 写 `Current Version`/`InstallPath`。源码还在增加 R 前清理当前安装模式 hive 的 registry entries。尽管这些是 per-user HKCU 操作而无需 admin，仍违反本任务明确的零注册表修改约束。因此我**在下载或执行任何 R 安装器前停止**，没有运行 `rig add`、`default`、`script-assoc`、Rtools 或 mirt 安装；没有修改 PATH、注册表、系统文件关联或 Positron。`rig system dirs --user` 只读输出了默认 C 路径；随后核对没有创建的 C config/log/R 目录。没有 `Rscript.exe`；未安装 R/mirt，未做数值对照。
- 本轮 `mirt` 路线只作为将来技术选项，不被 GIRTH pilot 替代或视为已验证。批量前由 Controller 明确模型、使用的样本分层与模型比较方案。

## 一手技术来源

- GIRTH repository/API/README（支持项、一/多维 GRM MML、缺失标记说明、>3 因子的计算提示、MIT）：[GitHub](https://github.com/eribean/girth)；[PyPI 0.8.0](https://pypi.org/project/girth/0.8.0/)。
- 已安装代码路径：`research-env\Lib\site-packages\girth\utilities\utils.py`、`utilities\polytomous_utils.py`、`unidimensional\polytomous\grm_mml.py`、`unidimensional\polytomous\partial_integrals_poly.py`、`multidimensional\multidimensional_mml_methods.py`、`multidimensional\partial_integral_md.py`。
- SciPy 1.14+ 的 `mvn.mvnun` 兼容 issue：[GIRTH issue #150](https://github.com/eribean/girth/issues/150)。
- `mirt` graded/multidimensional/EM/MHRM/NA：[mirt 官方 API](https://philchalmers.github.io/mirt/docs/reference/mirt.html)、[项目说明](https://github.com/philchalmers/mirt)；R package license 为 GPL-3-or-later。
- Windows 隔离 R 安装/目录变量：[rig user/admin guide](https://rig.r-lib.org/admin-vs-user-mode.html)、[rig config](https://rig.r-lib.org/reference/config.html)、[Posit rig 0.11.0 Windows 目录说明](https://opensource.posit.co/blog/2026-10-09_rig-0-11-0-part-one/)。rig v0.11.0 source evidence: [`src/windows/mod.rs`](https://github.com/r-lib/rig/blob/v0.11.0/src/windows/mod.rs) (`sc_add`, `sc_set_default`), [`src/windows/registry.rs`](https://github.com/r-lib/rig/blob/v0.11.0/src/windows/registry.rs) (`sc_clean_registry`, `update_registry_default`), [`src/common.rs`](https://github.com/r-lib/rig/blob/v0.11.0/src/common.rs) (`set_default_if_none`). Official release hash/signature/help captures are in `D:\Dev\tools\psynova-research-rig\release-verification.json` and `help-*.txt`.

## 原始来源临时文件清理

已生成的 response-only 矩阵和题目映射不含 respondent IDs 或人口字段。原始 Dataverse original CSV 与转换 TSV 目前仍在 `staging\_work` 临时目录；对这两个本任务下载的确切临时文件调用 `Remove-Item -LiteralPath` 被执行策略拒绝。未尝试替代删除机制，也未删除其他文件；最终交付前仍需清理这两份原始文件。

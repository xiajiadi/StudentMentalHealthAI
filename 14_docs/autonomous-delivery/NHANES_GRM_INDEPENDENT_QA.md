# NHANES P_DPQ GRM 独立数值 QA

**核查日期：2026-10-14**
**范围：只读检查来源、拆分、mirt 参数元数据及独立高斯积分。**不构成 Controller 验收、量表审批、临床/危机解释或学校适用性结论。

## 结果

- 外部证据 JSON：`D:\Dev\datasets\psynova-public-research\qa\nhanes-grm-independent-qa-20261014.json`；SHA-256：`a4e9ed820191057ee119ecd474e8257b7bea666aa10e3e3d50eb9981d2d37c7c`。
- 上游 response-only CSV 为 8,965 行、9 个固定字段；其 SHA-256 与上游 manifest、split manifest 和 run manifest 中记载的哈希一致。来源值只含 `0–3`、`7`、`9` 和空值；逐项来源聚合频数与原始 manifest 相符。
- 划分为 seed `20261014` 下无放回 reservoir sampling，再 shuffle；校准 6,000 行，评估 800 行。实际计数复核为校准 5,529 条完整、22 条部分缺失、449 条全缺失；评估 745 条完整、1 条部分缺失、54 条全缺失。两份拆分类别计数及缺失单元格计数均与 split manifest 一致。拆分导入将来源的 7（拒答）、9（不知道）和原空值合并为 NA，未插补或以完整答卷替换评估样本。
- 除检查 importer 的来源记录号断言外，我用相同的 hash 匹配 response-only 源文件、seed、missing codes 和拆分尺寸在内存中重放当前 importer；重放出的校准和评估行序列分别与现有 6,000/800 行 CSV 完全一致，6,800 个临时来源行号唯一且交集为 0。行号只在内存用于核对，未写入产物。response-only 源本身不含 NHANES SEQN，不能、也没有恢复任何个人身份映射。
- mirt 1.47 拟合使用 9 个题目、单因子 graded response、Gaussian `N(0,1)`、41 quadrature points、EM，76 次迭代收敛，36 个自由参数。逐题校准类别频数与 CSV 重新计算完全相同；9 题均有 `0–3` 四类支持。参数均为有限正区分度、有限且严格递增阈值；R 拟合脚本将 0–3 calibration 列直接转换为 `y`，没有反向键转换（`fit_nhanes_dp_q_grm.R:45-56`），参数元数据中也没有反向键字段。DPQ090 的校准类别 2、3 计数分别为 38、27，支持较稀疏。
- 从导出参数独立计算 `P(Y≥k)=logistic(a(θ−b_k))` 的相邻累计概率差；类别概率和误差最大 `2.22e-16`。使用稳定 log-domain 公式和 log-sum-exp 作标准正态 Gauss–Hermite 积分。校准 marginal log-likelihood 与 mirt 报告值 `-30361.645410` 的差：41 点 `+0.498569`，81 点 `-0.004246`，121 点 `+0.000314`，161 点 `+0.000281`，201 点 `+0.000280`。独立 Hermite 节点规则不保证与 mirt 内部 41 点规则相同；161/201 点校准 LL 相差约 `0.0000014`，可见高阶积分收敛到接近 mirt 报告值。
- 没有用评估集拟合参数。独立 held-out marginal log-likelihood：41 点 `-3981.022646`，81 点 `-3981.032241`，121 点 `-3981.032850`，161 点 `-3981.032853`，201 点 `-3981.032851`；评估 800 行中 746 行非全缺失、54 行全缺失，全缺失记录按空观测 likelihood=1 计入固定分母，未生成个体估计。

## 哈希与来源

独立报告复核通过 response-only CSV、upstream source manifest、split manifest、calibration/evaluation CSV、fit summary、fit R 脚本、response importer、汇总审核脚本、CRAN package lock 和 D 盘 isolated Rscript 二进制的 SHA-256。详情见上述 JSON。fit 使用既有隔离 R 4.6.1 / mirt 1.47 产物；独立积分使用隔离 Python 3.12.13 / NumPy 1.26.4 / SciPy 1.13.1；本次没有重新拟合或启动 R 服务。

官方 [NCHS P_DPQ codebook](https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/2017/DataFiles/P_DPQ.htm) 说明公共文件只含 18 岁及以上成人，并将题目目标范围列为 18–150 岁；目标范围不等于本次样本的实际年龄范围，response-only 文件没有年龄。12–17 岁 youth 文件受 RDC 获取范围约束，本 QA 未访问。该样本不是高中生、青少年、大学生或学校样本，也没有人口统计变量和调查权重；不得据此声称青少年效度、美国人口常模或危机识别能力。来源页没有识别到数据集专属 CC 许可，仍仅限隔离研究和署名，未授权逐行再分发。

## 边界

独立 QA 只保存哈希、模型/拆分聚合、逐题类别聚合和 likelihood 数值；没有输出作答行、题目正文、个体 theta、个体得分或标识。原始 7/9/空值在 split 层已合并为 NA，拆分后的数据不再含区分这些来源缺失类型所需的信息。结果仅说明数值流程可复核，不证明测量学有效性、临床意义、个体危机状态或学校应用适配性；评估 LL 不是独立人群验证。

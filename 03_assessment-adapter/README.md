# D3-2 Assessment Interpretation Adapter

本模块把已经完成的 `assessment.v1` 作为只读输入，按一个明确版本的
`InterpretationPolicyPack` 返回角色中立的结构化状态。它只做输入校验、精确策略选择和
确定性状态判断，不重新计算 CAT 测量结果，也不生成解释性自然语言。

## 范围和边界

当前实现覆盖：

- 完成的 `assessment.v1` 只读校验；
- `InterpretationRequest`、`TrustedInterpretationContext`、`InterpretationPolicyPack`、
  `InterpretationResult` 等模块内类型；
- 本地版本化 JSON policy registry；
- 精确的 policy id、policy version、policy hash、instrument、population 和 trusted mode
  选择；
- 明确的 `MEASUREMENT_ONLY`、`READY_FOR_RENDERING` 和 abstain 状态；
- 模块自己的 `interpretation_result.v1` schema、fixture 和确定性测试。

CAT 仍然是 `theta`、`se`、题目/停止证据和测量计算的唯一权威。本模块可以读取这些字段
来完成输入结构校验，但不会重新计算、舍入、分箱、生成区间或把它们写入 public result、
claim 或 audit。

本模块不调用 CAT、Safety、RAG、Prompt Engine、Backend、Database、LLM、网络服务或 D2
新提交的 14 个来源/58 个 fragment。`03_assessment-adapter` 仍然是模块内边界；本实现
不会修改冻结 Root Contract。

## 输入

`assessment` 必须是完整的、已完成的 `assessment.v1` 映射，包含冻结 schema 要求的
instrument、population、dimension、risk、provenance 和 timestamp 字段。输入会被深拷贝，
原对象不会被修改。缺字段、额外字段、错误类型、未完成状态或高风险不变量错误都会返回
`ABSTAIN_INPUT_INVALID`。

输入无效时，public result 只保留已经符合冻结 `ASSESS_...` 和 `SUBJ_...` 格式的匿名
标识；姓名、手机号样式或其他原始字符串不会被投影到结果中。

请求还必须带一个 `PolicyReference`：

```python
from assessment_adapter import InterpretationRequest, PolicyReference

request = InterpretationRequest(
    assessment=assessment,
    policy_ref=PolicyReference(
        policy_id="POLICY_assessment_synthetic_measurement_only",
        policy_version="1.0.0",
        policy_hash="sha256:...",
    ),
    request_id="REQ_demo_001",
    trace_id="TRACE_demo_001",
)
```

也可以直接传入三个 policy identity 字段；它们会被规范化为同一个
`PolicyReference`，重复字段不一致时拒绝。

## Trusted context

公共 `interpret` API 只接受 `TrustedInterpretationContext`，不能用普通 `dict` 自行声明
`REAL_USER`、人群、Safety 状态或运行模式。上下文包含 execution mode、assessment
population、context identity/version、Safety action 和审计 request/trace identity。

私有 `_build_trusted_interpretation_context` 仅作为受控 integration seam 和测试构造器，
要求完整字段并逐项校验。它是同一 Python 进程内的 capability-like 边界，不是针对能够导入
私有名称、改写内存或绕过 API 的恶意代码的加密安全边界。

## Policy registry 和 hash

随模块提交的
[`interpretation_policy_registry.v1.json`](assets/interpretation_policy_registry.v1.json)
只有一个 shipped policy。policy 对象必须绑定：

- policy id、policy version、effective version 和 policy hash；
- instrument id/version、人群和显式 allowed modes；
- synthetic-only 标记、engineering/controller scope；
- psychology review status、review decision identity、evidence refs；
- typed construct policies、allowed claim codes、forbidden claim codes 和 limitations。

policy hash 是把 JSON 解析后移除顶层 `policy_hash`，再以
`sort_keys=True`、`ensure_ascii=False`、`separators=(",", ":")` 序列化 UTF-8，计算 SHA-256，
并以 `sha256:` 前缀保存。registry 会拒绝重复 JSON key、重复 policy id/version、缺失或
无效 policy、hash 不匹配和 wildcard/latest/default 选择。调用方提供的 identity 必须和
registry 中的一条记录完全相同；模块不会选择 latest、default、first match 或 generic
fallback。

当前 shipped policy 精确绑定：

- instrument：`CURRENT_SYNTHETIC_GRM` / `synthetic_item_bank.v1 / demo.v1`；
- population：`SYNTHETIC_STUDENT_DEMO`；
- mode：`SYNTHETIC_DEMO`；
- psychology status：`REVISIONS_REQUIRED`；审计 detail 保留
  `RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK`；
- construct metadata 不提供心理学高低分含义、cutoff 或旧四域语义。

因此 shipped policy 只返回 `MEASUREMENT_ONLY`，限制代码为
`SYNTHETIC_ONLY`、`NOT_DIAGNOSTIC`、`NO_VALIDATED_CUTOFF`、`NO_CLINICAL_INFERENCE` 和
`NO_CRISIS_INFERENCE`。它不声称心理测量已获批准或具备临床解释能力。

## API 和结果

典型调用如下。生产或集成代码应从受控上游取得 trusted context；下面的私有构造器只用于
合成夹具和本模块测试。

```python
from assessment_adapter import interpret, load_shipped_registry
from assessment_adapter.adapter import _build_trusted_interpretation_context

context = _build_trusted_interpretation_context({
    "execution_mode": "SYNTHETIC_DEMO",
    "assessment_population": "SYNTHETIC_STUDENT_DEMO",
    "context_id": "CTX_demo_001",
    "context_version": "1.0.0",
    "safety_action": "PROCEED",
    "request_id": "REQ_demo_001",
    "trace_id": "TRACE_demo_001",
})
result = interpret(request, context, load_shipped_registry())
payload = result.to_dict()
```

`payload` 符合本模块的
[`interpretation_result.v1.schema.json`](schemas/interpretation_result.v1.schema.json)，包含
schema version、status、reason codes、assessment/instrument identity、policy identity、
typed claims、typed limitations 和 trusted audit identity。输出是 canonical、role-neutral
结构；学生、教师和家长的呈现属于 D3-3。adapter 对 policy registry 的 allowed claim
codes 和 construct claim codes 使用同一组全局禁用语义码校验，诊断、障碍、临床严重度、
自杀/自伤、危机风险、治疗、Level 1–5、cutoff、score/band、theta、SE、interval 和
precision-as-risk 等别名即使出现在测试 policy 中也会 fail closed。

状态包括：

- `MEASUREMENT_ONLY`：当前 shipped synthetic-only policy 的唯一正常结果；
- `READY_FOR_RENDERING`：只允许测试内的 `SYNTHETIC_TEST_ONLY` 中性 policy；测试 policy
  不在 shipped registry；
- `ABSTAIN_POLICY_MISSING`、`ABSTAIN_POLICY_MISMATCH`、
  `ABSTAIN_POLICY_HASH_MISMATCH`；
- `ABSTAIN_INSTRUMENT_MISMATCH`、`ABSTAIN_VERSION_MISMATCH`、
  `ABSTAIN_POPULATION_MISMATCH`、`ABSTAIN_CONSTRUCT_UNAPPROVED`；
- `ABSTAIN_REAL_USER_BLOCKED`、`ABSTAIN_SAFETY_BYPASS`、`ABSTAIN_MODE_NOT_ALLOWED` 和
  `ABSTAIN_INPUT_INVALID`。

可信 Safety action 为 `CRISIS_ROUTE`、`REVIEW_REQUIRED` 或 `BLOCK` 时，三种状态都会单独
返回 `ABSTAIN_SAFETY_BYPASS`。原 action 只作为 trusted audit context 保留，adapter 不会
修改或重新生成 Safety 决定。

## Mode、人群和审核状态

policy 可以显式允许 `SYNTHETIC_DEMO` 或 `RESEARCH_ONLY`；`REAL_USER` 无论 policy 如何
声明都被阻断。当前 policy 只允许 `SYNTHETIC_DEMO`，生产交付仍暂停。大学新生及 17–19
岁方向仍需要既有伦理、知情同意、隐私和未成年人门槛；本模块不会替这些门槛做决定。

## 验证

在 worktree 根目录运行：

```powershell
$env:PYTHONPATH = "$PWD\03_assessment-adapter\src"
python -m pytest -q -p no:cacheprovider 03_assessment-adapter\tests
python -m ruff check 03_assessment-adapter\src 03_assessment-adapter\tests
python -m pyright --project 03_assessment-adapter\pyrightconfig.json
python -m compileall -q 03_assessment-adapter\src
```

D3-2 工程检查通过不等于 psychology approval、psychometric validity、real-pilot readiness、
clinical validity 或 production readiness。D3-3 Role Projection、D3-4 Backend Integration
均未在本模块实现。

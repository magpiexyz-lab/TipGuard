# LLM-Driven Workflow Reliability Framework

> 一份通用框架，让任何 Claude Code (LLM-driven) 项目中，每个"我做完了 step X"的声明都由 LLM 控制不了的东西来背书。

---

## 灵魂（一句话）

**把 "step X done" 从 LLM 的自我声明，改写为 disk 状态的 pure function 投影，并在 LLM 必经路径（Write/Edit/Bash）上同步验证之。**

---

## 真正的新颖性：威胁模型

所有传统系统（Make / Bazel / Airflow / K8s / GHA）假设 **actor 诚实**，只是会犯错。本框架假设 **actor 会主动绕过**。

这一个假设差异，让所有"借鉴成熟系统"都要重审：

| 传统智慧 | 在 LLM 场景为什么不适用 |
|---|---|
| Make 的 mtime 检查 | LLM 可 `touch` 文件、可写新内容但回退语义 |
| Terraform 的 state file 权威 | LLM 可改 state file 伪造进度 |
| GitHub Actions 的 self-reported step status | 这正是要 escape 的东西 |
| MapReduce 的 trusted worker 假设 | LLM 就是 worker，不可信 |
| PR review 的 reviewer-is-trusted | LLM 项目里没有 "trusted reviewer" |

这是范式差异，不只是工具差异。框架的所有设计选择都从"actor untrusted"反推。

---

## 5 公理

| # | 公理 | 一句话 |
|---|---|---|
| A1 | **信任最小化** | LLM 输出是 unverified claim，不是 evidence |
| A2 | **可观测性** | Evidence = LLM 无法伪造的 disk 副作用（含原子可见性） |
| A3 | **状态可推导 > 被维护** | Truth = pure function(disk)，禁止 LLM 维护的进度表 |
| A4 | **物理必要性 > 仪式** | 验证挂在 LLM 必经路径上（Write/Edit/Bash），不挂在仪式上 |
| A5 | **失败显式 > 沉默** | 见证缺失必须 block，不默认 pass |

**衍生约束**（从 A1 + A2 推出，值得显式）：
Validator 必须是 deterministic pure function（disk → bool）。**任何在 validator 里调 LLM 的设计，A1 立刻破产**。

---

## 3 原语

| 原语 | 定义 | 它解决什么 |
|---|---|---|
| **Artifact** | 一个 path，其存在 + 内容 schema 构成 "step done" 的 evidence | A1 + A2（物理 evidence） |
| **Guard** | 声明式 spec：`{produces, requires, check, prose?}` 给一个 path 标记前置 + 验证方式 | A3（spec 是 disk → bool 的 declarative form） |
| **Trigger** | hook 点，在 LLM 必经路径上同步调用 check。`pre / post / stop` 是同一个原语的三时刻 | A4 + A5（挂物理必经 + 失败即 block） |

**关键说明**：
- `Interceptor` 和 `Finalizer` 本质同一原语，只是触发时刻不同
- `Contract` 不是独立原语，是 Guard 在 yaml 里的字面量形式
- `step` 在 framework 层面不存在 — 只有 Artifact 和它的 Guard

---

## 4 文件

```
steps.yaml              ← THE source of truth（执行流声明）
tools/check_*.py        ← validator（git-tracked，LLM 不能 Edit）
gate.sh                 ← PreToolUse Write|Edit|Bash hook
audit.sh                ← PostToolUse + Stop hook
```

**词汇表**：`produces` / `requires` / `check` / `prose` / `pass record`。

没有 step / state / phase / stage / kind / completed_states / advance / next。

---

## `steps.yaml` schema

```yaml
skill: <skill-name>
steps:
  - id: <human-readable-name>      # 用于 prose 引用、tools/eligible 索引
    produces: <path or glob>       # 产物路径（可以是 glob 如 "findings-*.json"）
    requires: [<path>, ...]        # 前置 artifact（必须存在 AND 有 pass record）
    check: tools/check_<id>.py     # validator 路径
    prose: |                       # 可选：内联 LLM 指令
      指令...
    # 或外链：
    prose: prose/<id>.md
```

3 个必填字段（`id` / `produces` / `check`），2 个可选字段（`requires` / `prose`）。

---

## 执行模型

### Main agent 看到的

1. 读 `steps.yaml`
2. `eligible = {step : step.requires 全部有 pass record AND step.produces 还没 pass record}`
3. eligible 集大小：
   - **0**: skill 完成 或 卡住（被前置 fail 阻塞）
   - **1**: 读它的 prose，执行（可能 spawn subagent）
   - **多个**: 并行 — 各自读自己的 prose
4. 执行 → framework 在 Write 时 gate / 写完 audit + 写 pass record
5. 回到 2

**无 NEXT 指针，无 advance-state，无 LLM 维护进度。eligible 集是 disk 的函数。**

### Framework 看到的

```
LLM 想 Write X
   ↓
PreToolUse → gate.sh
   ├─ X 是 trust root?           → DENY (exit 2)
   ├─ X 匹配某 step.produces?    → 检查该 step.requires 全部有 pass record
   │                                 → 缺则 DENY (exit 2)
   └─ allow                       → 写盘真发生
   ↓
PostToolUse → audit.sh post
   ├─ X 匹配某 step.produces?    → 跑 check_X.py
   │                                 → 过则写 pass record（含 hash chain）
   │                                 → 不过则 stderr 报错（LLM 看到自然重写）
   ↓
（LLM 任务结束）
   ↓
Stop → audit.sh stop
   └─ Reconciliation：扫所有 step，缺产物 / 缺 pass record / hash 漂移 → 写 routine-failures.jsonl
```

### 并行的自然涌现

并行不是 schema feature，而是"多个 step 共享同一 requires"的自然结果：

```yaml
- id: bull
  produces: bull.md
  requires: [probe.json]
  check: tools/check_bull.py

- id: bear
  produces: bear.md
  requires: [probe.json]      # 同 requires
  check: tools/check_bear.py

- id: historian
  produces: historian.md
  requires: [probe.json]      # 同 requires
  check: tools/check_historian.py
```

3 个 step 共享 requires → eligible 集同时含 3 个 → main agent 同 Task 调用并行 spawn 3 个 subagent。

子 agent 在自己的 session 写各自的 `.md`，hook 自动在子 session 触发（因为共享项目根的 `settings.json`），无需任何 coordinator。partial-write race 由 "pass record 才算完成" 自然防止。

---

## 关键设计决策

### ❌ 显式拒绝的复杂度（全部是 accidental，不影响 LLM 产出质量）

| 拒绝的 | 替代方案 | 拒绝理由 |
|---|---|---|
| retry budget / cumulative_spawn_count | fail-fast，失败即 abort | 隐藏信号、引入新 gaming 面、违反 A3 |
| sealing window / sentinel 文件 | produces 是天然 immutable | pass record 写入即冻结，sentinel 多余 |
| `when:` 条件 step | push 进 validator 的早 exit | framework 不该懂表达式语言 |
| `advance-state.sh` 仪式 | pass record 自动维护 | 违反 A4（LLM 可跳过仪式） |
| `completed_states[]` LLM 维护 | state = pure function(disk) | 违反 A3 |
| `NEXT:` 指针 | `tools/eligible.py` 求解 | 指针漂移 + 流程分散 |
| step name 当 framework 主键 | path 是查询主键，id 给人看 | 框架内不需要昵称 |
| `kind: critic`（LLM-as-judge gate） | critic 写数据，gate 不挂 verdict | 违反 A1 |
| mode 切换（单 skill 多 DAG） | 拆 N 个独立 skill | 简化心智模型 |

### ✅ 必须保留的设计

| 保留的 | 防御什么 |
|---|---|
| Pass record 含 `artifact_sha256` + `validator_sha256` + `session_id` | Replay 攻击（改 validator 让其永远 pass） |
| `requires` 检查"前置 pass record 存在"，不是"文件存在" | Partial-write race（LLM 写一半被下游误读） |
| `gate.sh` 注册 Bash matcher | LLM 用 `bash -c "cat > X"` / `python -c "open(...).write"` 绕过 Write |
| 信任根保护（`tools/check_*` / `steps.yaml` / 两个 hook） | LLM 直接改 validator / steps.yaml |
| `audit.sh stop` reconciliation | LLM 中途 `rm pass_record` |
| 并行 = 共享 requires（无特殊 schema） | 自然涌现，无 schema 膨胀 |

---

## 3 个 essential pattern（零扩展可表达）

### ① 迭代搜索 → 索引化 produces + 收敛 check

```yaml
- id: findings
  produces: "findings-*.json"     # glob
  requires: [plan.md]
  check: tools/check_findings.py  # 验证 N monotonic + has new issues

- id: converged
  produces: converged.json
  requires: ["findings-*.json"]
  check: tools/check_converged.py # 验"上一轮无新 finding = 收敛"
```

LLM 在 prose 里跑 while-loop："跑 findings-N 直到 check_converged 通过"。迭代是 prose 的事，验证是 framework 的事 — 各司其职。

### ② LLM-as-judge → critic 写数据而非 gate verdict

```yaml
- id: critique
  produces: critique.json
  requires: [bull.md, bear.md]
  check: tools/check_critique.py
  # validator 只验结构：必有 issues 数组，每条有 path/severity/description
  # 完全不验 issues 是否"对"

- id: scorecard
  produces: scorecard.yaml
  requires: [critique.json]       # 结构性事实（critique.json 存在）
  check: tools/check_scorecard.py
  # 下游 gate 挂结构事实，不挂 critique.verdict 字段
```

Critic 的 verdict 字段是数据，下游 prose 决定要不要 act on it（"如果 critic 标 fail，LLM 修后再 rerun"）。Gate 只挂结构性事实：Lighthouse 分、a11y violation 数、tsc 出错数等。

### ③ 用户审批 → 用户写的文件作 artifact

```yaml
- id: approval
  produces: approval/decision.md
  requires: [analysis.md]
  check: tools/check_user_approval.py
  prose: |
    STOP. 让用户在 approval/decision.md 写 "APPROVE" 或 "REJECT" 后再继续。
```

`gate.sh` 自动保护 `approval/*` 路径不被 LLM 写（可加规则）。用户写文件后，LLM 下次进入 skill，framework 看到 `approval/decision.md` + pass record 存在，自动放行下游。

---

## 漏洞防御

### 漏洞 #1：Validator 篡改 replay 攻击

**症状**：LLM 改 `tools/check_*.py` 让它永远 return 0 → 老 pass record 仍合法 → 永久绕过。

**双重防御**：
1. **第一防线**：`gate.sh` 在 `tools/check_*` 等"信任根"文件被 Write|Edit 时直接 exit 2
2. **第二防线**（Nix-style hash chain）：pass record 含 `validator_sha256`，Stop hook 重算所有 hash，任一不匹配 → invalidate pass record + 报警

### 漏洞 #2：Bash 绕过 Write hook

**症状**：LLM 用 `bash -c "cat > X <<EOF"` / `python -c "open('X','w').write(...)"` / `sed -i` / `git checkout` 绕过 Write tool。

**修复**：`gate.sh` 注册 Bash matcher，正则识别：
- `> path` / `>> path`（重定向）
- `tee path` / `tee -a path`
- `sed -i.*path`
- `python.*-c.*open\(.*write`
- `git checkout.*--.*path`
- `cp` / `mv` / `rsync` 到 produces 路径

命中 + 目标路径有 guard → exit 2。

### 漏洞 #3：Reconciliation 缺失

**症状**：LLM 在两次 Write 之间 `rm -rf .runs/.pass-records/X`，framework 不感知。

**修复**：`audit.sh stop` 做完整 sweep：
- 扫所有 `steps.yaml` 中的 produces 路径
- 缺 pass record 的写 `journal/routine-failures.jsonl`
- Hash 不匹配的 invalidate 并报警

### 漏洞 #4：并发 session 误读 pass record

**症状**：Session A 跑 ticker FOO，Session B 跑 BAR，共享 `.runs/.pass-records/`。

**修复**：pass record 含 `session_id`（从 `CLAUDE_SESSION_ID` env 或随机 UUID），下游 grep 用 session_id 过滤；路径作 key 用 scope-aware hash（含 ticker / date 等 scope key）。

---

## 完整参考实现（~250 行，纯 stdlib + PyYAML）

### `steps.yaml`（示例，5 场景全覆盖）

```yaml
skill: example
steps:
  # (a) 线性
  - id: plan
    produces: plan.md
    requires: []
    check: tools/check_plan.py

  - id: analysis
    produces: analysis.md
    requires: [plan.md]
    check: tools/check_analysis.py

  # (b) 并行 sibling
  - id: bull
    produces: bull.md
    requires: [probe.json]
    check: tools/check_bull.py

  - id: bear
    produces: bear.md
    requires: [probe.json]
    check: tools/check_bear.py

  # (c) 迭代搜索
  - id: findings
    produces: "findings-*.json"
    requires: [plan.md]
    check: tools/check_findings.py

  - id: converged
    produces: converged.json
    requires: ["findings-*.json"]
    check: tools/check_converged.py

  # (d) 用户审批
  - id: approval
    produces: approval/decision.md
    requires: [analysis.md]
    check: tools/check_user_approval.py
    prose: "STOP. 让用户写 approval/decision.md 含 APPROVE/REJECT 后再继续。"

  # (e) Critic 写数据
  - id: critique
    produces: critique.json
    requires: [bull.md, bear.md]
    check: tools/check_critique.py     # 只验 schema

  - id: scorecard
    produces: scorecard.yaml
    requires: [critique.json]          # 结构事实
    check: tools/check_scorecard.py
```

### `tools/lookup.py`（给路径找 step）

```python
#!/usr/bin/env python3
import sys, json, fnmatch, yaml

target = sys.argv[1]
data = yaml.safe_load(open("steps.yaml"))

for step in data["steps"]:
    p = step["produces"]
    if isinstance(p, list):
        for pp in p:
            if target == pp or (any(c in pp for c in "*?[") and fnmatch.fnmatch(target, pp)):
                print(json.dumps(step)); sys.exit(0)
    else:
        if target == p or (any(c in p for c in "*?[") and fnmatch.fnmatch(target, p)):
            print(json.dumps(step)); sys.exit(0)
sys.exit(1)  # no guard for this path
```

### `tools/eligible.py`（main agent 查下一步该干啥）

```python
#!/usr/bin/env python3
import sys, json, glob, hashlib, pathlib, yaml

PASS_DIR = pathlib.Path(".runs/.pass-records")

def pass_path(p):
    return PASS_DIR / f"{hashlib.sha1(p.encode()).hexdigest()}.json"

def has_pass(p):
    if any(c in p for c in "*?["):
        return any(pass_path(m).exists() for m in glob.glob(p))
    return pass_path(p).exists()

data = yaml.safe_load(open("steps.yaml"))
eligible = []
for step in data["steps"]:
    produces = step["produces"] if isinstance(step["produces"], list) else [step["produces"]]
    if all(has_pass(p) for p in produces): continue  # 已完成
    if all(has_pass(r) for r in step.get("requires", [])):
        eligible.append({
            "id": step["id"],
            "produces": step["produces"],
            "prose": step.get("prose", ""),
        })
print(json.dumps(eligible, indent=2))
```

### `tools/check_requires.py`（验前置 pass record）

```python
#!/usr/bin/env python3
import sys, glob, hashlib, pathlib

PASS_DIR = pathlib.Path(".runs/.pass-records")
def pass_path(p): return PASS_DIR / f"{hashlib.sha1(p.encode()).hexdigest()}.json"

failures = []
for req in sys.argv[1:]:
    if any(c in req for c in "*?["):
        matches = glob.glob(req)
        if not matches:
            failures.append(f"glob '{req}' no match")
        elif not any(pass_path(m).exists() for m in matches):
            failures.append(f"glob '{req}' matched {len(matches)} files, none with pass record")
    else:
        if not pathlib.Path(req).exists():
            failures.append(f"'{req}' missing")
        elif not pass_path(req).exists():
            failures.append(f"'{req}' exists but no pass record")

if failures:
    sys.stderr.write("REQUIRES FAILED:\n" + "\n".join(f"  - {m}" for m in failures) + "\n")
    sys.exit(2)
```

### `tools/write_pass_record.py`（原子写 + hash chain）

```python
#!/usr/bin/env python3
import sys, json, hashlib, pathlib, os, tempfile, datetime

PASS_DIR = pathlib.Path(".runs/.pass-records")
produces, check_tool = sys.argv[1], sys.argv[2]
p = pathlib.Path(produces)

artifact_sha = hashlib.sha256(p.read_bytes()).hexdigest()
validator_sha = hashlib.sha256(pathlib.Path(check_tool).read_bytes()).hexdigest()

PASS_DIR.mkdir(parents=True, exist_ok=True)
target = PASS_DIR / f"{hashlib.sha1(produces.encode()).hexdigest()}.json"

record = {
    "path": produces,
    "check": check_tool,
    "artifact_sha256": artifact_sha,        # 防 LLM 改产物后 replay
    "validator_sha256": validator_sha,      # 防 LLM 改 validator 后 replay
    "session_id": os.environ.get("CLAUDE_SESSION_ID", "unknown"),
    "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
}

fd, tmp = tempfile.mkstemp(dir=PASS_DIR, prefix=".tmp-")
with os.fdopen(fd, "w") as f: json.dump(record, f, indent=2)
os.replace(tmp, target)  # 原子 rename
```

### `tools/reconcile.py`（Stop hook 调用）

```python
#!/usr/bin/env python3
import sys, json, glob, hashlib, pathlib, datetime, yaml

PASS_DIR = pathlib.Path(".runs/.pass-records")
FAIL_LOG = pathlib.Path("journal/routine-failures.jsonl")
FAIL_LOG.parent.mkdir(parents=True, exist_ok=True)

def pass_path(p): return PASS_DIR / f"{hashlib.sha1(p.encode()).hexdigest()}.json"

issues = []
data = yaml.safe_load(open("steps.yaml"))
for step in data["steps"]:
    produces = step["produces"] if isinstance(step["produces"], list) else [step["produces"]]
    for p in produces:
        files = glob.glob(p) if any(c in p for c in "*?[") else ([p] if pathlib.Path(p).exists() else [])
        for f in files:
            rec_path = pass_path(f)
            if not rec_path.exists():
                issues.append({"path": f, "issue": "artifact_exists_no_pass_record"})
                continue
            rec = json.loads(rec_path.read_text())
            actual_sha = hashlib.sha256(pathlib.Path(f).read_bytes()).hexdigest()
            if actual_sha != rec.get("artifact_sha256"):
                issues.append({"path": f, "issue": "artifact_hash_drift"})
            validator_path = pathlib.Path(rec.get("check", ""))
            if validator_path.exists():
                v_sha = hashlib.sha256(validator_path.read_bytes()).hexdigest()
                if v_sha != rec.get("validator_sha256"):
                    issues.append({"path": f, "issue": "validator_hash_drift"})

if issues:
    with FAIL_LOG.open("a") as f:
        for i in issues:
            f.write(json.dumps({
                **i,
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "kind": "reconcile",
            }) + "\n")
    sys.stderr.write(f"RECONCILE: {len(issues)} drift(s) logged to {FAIL_LOG}\n")
```

### `gate.sh`（PreToolUse Write|Edit|Bash）

```bash
#!/usr/bin/env bash
set -euo pipefail
INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // ""')

# 抽取目标路径
TARGET=""
case "$TOOL" in
  Write|Edit)
    TARGET=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
    ;;
  Bash)
    CMD=$(echo "$INPUT" | jq -r '.tool_input.command // ""')
    # 检测常见 Bash-bypass 模式
    TARGET=$(echo "$CMD" | grep -oE '(> |>> |tee |sed -i.*|cp .* |mv .* |git checkout.* -- )[^ ;|&]+' \
             | sed -E 's/^(> |>> |tee |sed -i\S* |cp \S+ |mv \S+ |git checkout\S* -- )//' | head -1 || true)
    # Python heredoc / write 检测
    if echo "$CMD" | grep -qE "python\S* -c .*open\(.*['\"]w"; then
      TARGET=$(echo "$CMD" | grep -oE "open\(['\"][^'\"]+" | head -1 | sed "s/^open(['\"]//")
    fi
    ;;
  *) exit 0 ;;
esac
[[ -z "$TARGET" ]] && exit 0

# 信任根保护
case "$TARGET" in
  tools/check_*|tools/lookup.py|tools/eligible.py|tools/check_requires.py|tools/write_pass_record.py|tools/reconcile.py|steps.yaml|gate.sh|audit.sh)
    echo "BLOCKED: '$TARGET' is trust root, LLM cannot modify" >&2
    echo "If a check is wrong, operator must edit outside this session" >&2
    exit 2 ;;
esac

# 查 step
ENTRY=$(python3 tools/lookup.py "$TARGET" 2>/dev/null) || exit 0

# 检查 requires
REQS=$(echo "$ENTRY" | jq -r '.requires[]?' | tr '\n' ' ')
if [[ -n "$REQS" ]]; then
  if ! python3 tools/check_requires.py $REQS; then
    PROSE=$(echo "$ENTRY" | jq -r '.prose // ""')
    echo "BLOCKED: writing '$TARGET' — prior steps incomplete" >&2
    [[ -n "$PROSE" ]] && echo "Hint: $PROSE" >&2
    exit 2
  fi
fi
exit 0
```

### `audit.sh`（PostToolUse + Stop）

```bash
#!/usr/bin/env bash
set -uo pipefail
MODE="${1:-post}"

if [[ "$MODE" == "post" ]]; then
  INPUT=$(cat)
  TARGET=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
  [[ -z "$TARGET" || ! -f "$TARGET" ]] && exit 0

  ENTRY=$(python3 tools/lookup.py "$TARGET" 2>/dev/null) || exit 0
  CHECK=$(echo "$ENTRY" | jq -r '.check')

  if python3 "$CHECK" "$TARGET" 1>&2; then
    python3 tools/write_pass_record.py "$TARGET" "$CHECK"
  else
    echo "AUDIT FAIL: $TARGET did not pass $CHECK (no pass record written)" >&2
    # 不 exit 2 — Write 已发生，只报告，让 LLM 看到错重写
  fi
  exit 0
fi

if [[ "$MODE" == "stop" ]]; then
  python3 tools/reconcile.py
  exit 0
fi

echo "Unknown audit mode: $MODE" >&2; exit 1
```

### `.claude/settings.json`（hook 注册）

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|Bash",
        "hooks": [{ "type": "command", "command": "bash gate.sh" }]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{ "type": "command", "command": "bash audit.sh post" }]
      }
    ],
    "Stop": [
      {
        "hooks": [{ "type": "command", "command": "bash audit.sh stop" }]
      }
    ]
  }
}
```

### `tools/check_template.py`（validator 模板，copy 后改）

```python
#!/usr/bin/env python3
# COPY 这个文件到 tools/check_<step_id>.py 后修改
#
# 设计原则：
# - validator 只读取自己的 artifact，不读 sibling 文件
# - 任何跨文件依赖应该 declare 在 steps.yaml 的 requires
# - 失败 exit 2 + stderr 写明 actionable error
# - 绝对不在这里调 LLM
import sys, pathlib

def fail(msg: str):
    sys.stderr.write(f"CHECK FAILED: {msg}\n"); sys.exit(2)

def main():
    if len(sys.argv) != 2:
        fail("usage: check_<step>.py <artifact-path>")
    p = pathlib.Path(sys.argv[1])
    if not p.exists():
        fail(f"artifact '{p}' does not exist")
    text = p.read_text(encoding="utf-8")

    # --- 示例 assertions（替换为真实业务规则）---
    if len(text.strip()) < 50:
        fail(f"artifact '{p}' suspiciously short ({len(text)} chars)")
    if "TODO" in text or "FIXME" in text:
        fail(f"artifact '{p}' contains TODO/FIXME placeholders")
    # 若 artifact 是 YAML/JSON，用 schema validator：
    # import yaml; data = yaml.safe_load(text)
    # if "required_key" not in data: fail("missing required_key")
    # ---

if __name__ == "__main__":
    main()
```

---

## 30 分钟落地

### Phase 0 — 自评（5 min）

每个 skill 打分（0-10 各项）：

| 维度 | 0 分 | 5 分 | 10 分 |
|---|---|---|---|
| Step 边界清晰 | step 数量飘 | 有编号 step | 编号 + 固定 produces |
| Produces 物理可见 | 只输出 prose | 写文件路径不固定 | 固定路径 + schema |
| Requires 可前置检查 | 看不出依赖 | 文档写依赖 | 机器可读 |
| Check 可程序化 | 只能人眼 | grep/jq 取值 | Pydantic/JSON Schema |
| 重跑代价 | 状态散 5+ 文件 | 有 archive 路径 | `mv {dir} {dir}.archived/` 一键 |

- 总分 **≥ 35** → 直接接入
- **25-34** → 接入前先编号化、produces 落地化
- **< 25** → 不强迁，改造或放弃

**红旗（跳过）**：
- 元层套娃（skill 本身是验证器）
- 本质验不了的（retrospective、interview）
- 单步 skill（框架是 overhead）

### Phase 1 — 安装（10 min）

```bash
# 1. 创建目录
mkdir -p tools .runs/.pass-records

# 2. 复制 4 个核心文件（见上面"完整参考实现"）
#    - steps.yaml（先空数组）
#    - tools/lookup.py / eligible.py / check_requires.py / write_pass_record.py / reconcile.py
#    - gate.sh / audit.sh
chmod +x gate.sh audit.sh

# 3. 改 .claude/settings.json，加 hooks 段（见上）

# 4. 装依赖（若没装）
pip install pyyaml  # 或 python3 -m pip install --user pyyaml
```

### Phase 2 — 第一个 step（10 min）

```bash
# 1. 在 steps.yaml 加一个 step
cat >> steps.yaml <<EOF
steps:
  - id: hello
    produces: hello.md
    check: tools/check_hello.py
EOF

# 2. 写 validator
cp tools/check_template.py tools/check_hello.py
# 编辑 tools/check_hello.py 加真实 assertion

# 3. 让 LLM 试着 Write hello.md
#    → audit.sh post 触发 → 跑 check_hello.py
#    → 过则写 .runs/.pass-records/<sha>.json
#    → 不过则 stderr 错信息，LLM 重写
```

### Phase 3 — 验证（5 min）

故意做坏事看 framework 是否拦截：

1. **跳步测试**：加一个 step `world.md` 的 `requires: [hello.md]`。直接试 Write `world.md` 而不先写 `hello.md` → gate 应 exit 2
2. **Bash 绕过测试**：用 `bash -c "echo 'fake' > hello.md"` → `gate.sh` Bash matcher 应识别
3. **信任根测试**：试 Edit `tools/check_hello.py` → gate 应 exit 2
4. **Pass record 检查**：看 `.runs/.pass-records/` 下文件 schema 含 `artifact_sha256` + `validator_sha256` + `session_id`

---

## 5 个典型陷阱

### ① LLM 用 Bash 绕开 Write hook

LLM 自然会 fallback 到 `bash -c "cat > X"`。`gate.sh` 必须注册 Bash matcher 并正则识别 `>` / `tee` / `sed -i` / `python -c open(...).write` / `cp` / `mv` / `git checkout` 等模式。**没有 Bash matcher = framework 形同虚设。**

### ② Validator 写成"安慰剂"

`if "prob_bull" in content` 不是 check，是安慰。原则：每个 validator 必须有 pass / fail 双向 fixture — 一份样本通过、一份样本被拒，且失败样本是真实漂移过的（从 git log 捞历史 bug 写 negative fixture）。

### ③ requires 漏写

Step prose 写"读 X"，但 `steps.yaml` 没列 X 进 requires → gate 不拦 → LLM 跳过 X 直接写。**原则**：每次出 bug 后问"如果当时 steps.yaml 里有这条 requires，bug 会发生吗？"不会就该补，而不是改 prompt。

### ④ Validator 里调 LLM

任何 `subprocess.run(["claude", "-p", ...])` 或调 critic API 的 validator，A1 立刻破产。Validator 只能是 deterministic Python（可以调 tsc、curl、subprocess.run 调外部 deterministic CLI，但不能调 LLM）。

### ⑤ 多 session 并发误读 pass record

多 session 跑同一 skill 不同 instance，pass record 共享 `.runs/.pass-records/`。解决：pass record 含 `session_id`，下游验证用 session 过滤；scope-aware 的 produces 路径（如 `{date}/{ticker}/`）让不同 session 自然不撞 key。

---

## 跨系统对照（为什么这套比 X 强）

| 系统 | 它解决"作弊不可能"对应的问题 | Borrow | Avoid |
|---|---|---|---|
| Make | 显式依赖图 | requires DAG | mtime-as-truth（LLM 可 touch） |
| Bazel/Nix | hash-addressed inputs + hermetic sandbox | pass record 含 sha256 | BUILD 复杂度 / store 复杂度 |
| Terraform | declarative state + plan/apply | dry-run 思路 | 单点 state file 权威 |
| GHA/GitLab CI | DAG job + idempotent step | audit.sh 幂等 | self-reported step status |
| Pre-commit | hook 跨 repo 标准化 | settings.json hook 模板 | `--no-verify` 隐式 bypass |
| Dagster | materialization = step done | pass record = materialized | 多态 task state machine |
| K8s controller | admission webhook + reconciliation loop | gate.sh + audit.sh stop sweep | etcd 复杂度 |
| PR review + CI | 机器（机械事实）+ 人（判断题）双签 | check 只验机械事实，judgment 留 critic-as-data | reviewer-is-trusted 假设 |

**最值得 borrow 的一个 idea**：Nix 的 hash chain。已纳入 pass record 含 `validator_sha256` + `artifact_sha256`，close 掉"改 validator 让其永远 pass + replay 老 pass record"的攻击面。

**真正的新颖性**：不是工具组合，是把 actor 自己放进 untrusted 区。这是 K8s/Airflow/Make 都不做的假设。

---

## 何时不该用这个框架

| 场景 | 原因 |
|---|---|
| 元层套娃 skill（verify-the-verifier） | Framework 不验证 framework |
| 本质验不了的产物（retrospective、interview、brainstorm） | Validator 写不出"对错" |
| 单步 skill | Framework 是 overhead |
| 完全交互式 chat（无 disk 落点） | 没有 artifact 可验 |
| LLM 探索性任务（产物形态不可预测） | Schema 无法预先 declare |

红旗任一命中 → 跳过框架，留 prompt + 人工 review 即可。

---

## 概念关系图

```
┌─────────────────────────────────────────────────────┐
│  Skill 作者 写              steps.yaml              │
│                            (source of truth)        │
│                                  │                  │
│                                  │ 派生              │
│                                  ▼                  │
│  Framework 内部 用    path → guard 查询              │
│                       (tools/lookup.py)             │
│                                  │                  │
│              ┌───────────────────┼───────────────┐  │
│              ▼                   ▼               ▼  │
│         gate.sh             audit.sh         eligible│
│       (PreToolUse)        (PostToolUse +    (人/LLM  │
│                              Stop)         查"下一步")│
│              │                   │                  │
│              ▼                   ▼                  │
│    ┌─────────────────────────────────────────┐     │
│    │      .runs/.pass-records/ (disk)        │     │
│    │  含 hash chain + session_id 的 pass     │     │
│    │  record = "完成"的真值                  │     │
│    └─────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────┘
```

---

## 一句话总结

> **5 公理 + 3 原语 + 4 文件 + Nix-style hash chain + Bash-bypass 防御 = 真正可移植的 LLM 可靠性框架。零新概念，核心 ~250 行，跨 repo 通用。**
>
> **把 actor 放进 untrusted 区是这套设计的真正新颖性 — 其他全部是把成熟系统中"假设 actor 诚实"的设计反过来用。**

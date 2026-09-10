#!/usr/bin/env bash
# 方案 A / 方案 B 对比验收脚本
# 用法：scripts/compare_branches.sh <branch>
# 在开发开始前固定，避免事后按结果调整标准。
set -uo pipefail
BR="${1:-$(git branch --show-current)}"
ROOT="$(git rev-parse --show-toplevel)"
VENV="$ROOT/.venv/bin/python"
WT="/tmp/acc-check-$$"
git worktree add -q "$WT" "$BR" || { echo "无法检出 $BR"; exit 1; }
cleanup() {
  cd "$ROOT" || return
  git worktree remove "$WT" --force >/dev/null 2>&1
  git worktree prune
}
trap cleanup EXIT
cd "$WT"

echo "=========== 验收：$BR ==========="

echo "--- 基线记录（方案 A / main）---"
echo "  测试 885 全绿 | primary() 12 | panel 9 | issue_triage 分支 28 | ACTION_TYPE 0"
echo

echo "[1] 回归安全：测试全绿且数量不低于 885"
"$VENV" -m pytest -p no:cacheprovider --tb=short -q > /tmp/acc-test.log 2>&1
RC=$?
N=$(grep -E "\[ *[0-9]+%\]$" /tmp/acc-test.log | sed 's/\[.*//' | tr -d ' \n' | wc -c | tr -d ' ')
[ $RC -eq 0 ] && echo "    ✓ 全绿（$N 个）" || { echo "    ✗ 有失败（退出码 $RC）"; tail -20 /tmp/acc-test.log; }
[ "$N" -ge 885 ] 2>/dev/null && echo "    ✓ 数量未倒退" || echo "    ✗ 数量低于基线 885（当前 $N）—— 检查是否删测试换绿"

echo "[2] ActionType 成为对象"
C=$(grep -c "ACTION_TYPE" app/ontology/enums.py 2>/dev/null | head -1); C=${C:-0}
[ "$C" -gt 0 ] && echo "    ✓ 已声明" || echo "    ✗ 未声明（基线为 0，方案 B 必须 >0）"

echo "[3] R1 一屏一主：primary() 调用数应显著下降并有测试锁住"
P=$(grep -o "primary(" static/operator.js 2>/dev/null | wc -l | tr -d ' ')
echo "    primary() = ${P}（基线 12）"
grep -rqE "primary|主按钮" tests/ 2>/dev/null && echo "    ✓ 存在相关测试" || echo "    ✗ 无 R1 断言测试"

echo "[4] if-chain 特征化测试（防行为漂移）"
grep -rqE "classify_task" tests/ 2>/dev/null && echo "    ✓ 存在 classify_task 测试" || echo "    ✗ 缺特征化测试 —— 工单要求先写它再动代码"

echo "[5] 兜底动作不得授予账务可用（最易被绕过的一条）"
grep -rqiE "fallback.*(accounting|账务)|不授予账务可用|record_judgement" tests/ 2>/dev/null \
  && echo "    ✓ 存在相关断言" || echo "    ✗ 无专项测试"

echo "[6] 五个通用兜底动作是否齐备"
for a in record_judgement suspend request_supplement mark_out_of_scope escalate; do
  grep -rq "$a" app/ 2>/dev/null && echo "    ✓ $a" || echo "    ✗ 缺 $a"
done

echo "[7] 兜底动作占比指标（衡量复利是否空转）"
grep -rqiE "fallback_ratio|兜底.*占比|fallback.*rate" app/ 2>/dev/null \
  && echo "    ✓ 已埋点" || echo "    ✗ 未埋点 —— 工单要求与阶段 1 同期上线"

echo
echo "=========== 需人工验收（脚本测不了）==========="
echo "  ★ 主验收：造一个系统从未见过的问题类型，不改一行代码，"
echo "    它必须出现在人工队列里并有可用动作。方案 A 此项必然为 0。"
echo "  · 完成一个决定的点击数 / 页面跳转数（两分支各跑聚贤达 1 月）"
echo "  · R2 四问必答、R3 数字可下钻、R4 完成即衔接、R5 收起而非删除"

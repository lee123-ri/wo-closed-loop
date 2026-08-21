/** 工单显示映射：状态/优先级/来源/升级 —— 全站统一 */

export const statusMap: Record<string, { label: string; tag: string }> = {
  pending: { label: "待派发", tag: "tag-gray" },
  approving: { label: "审批中", tag: "tag-blue" },
  dispatched: { label: "已派发", tag: "tag-amber" },
  executing: { label: "执行中", tag: "tag-blue" },
  verifying: { label: "待验收", tag: "tag-amber" },
  closed: { label: "已闭环", tag: "tag-green" },
  overdue: { label: "已逾期", tag: "tag-red" },
  rejected: { label: "已驳回", tag: "tag-gray" },
  judging: { label: "已回填", tag: "tag-amber" },
};

export const statusLabel = (s: string) => statusMap[s]?.label ?? s;
export const statusTag = (s: string) => statusMap[s]?.tag ?? "tag-gray";

/** TDesign 主题映射（给 t-tag theme 用） */
export const statusTheme = (s: string): string => {
  const m: Record<string, string> = {
    pending: "default", approving: "primary", dispatched: "warning",
    executing: "primary", verifying: "warning", closed: "success",
    overdue: "danger", rejected: "default",
  };
  return m[s] || "default";
};

export const priorityMap: Record<string, { label: string; tag: string }> = {
  P1: { label: "P1 紧急", tag: "tag-red" },
  P2: { label: "P2 普通", tag: "tag-amber" },
  P3: { label: "P3 低优先", tag: "tag-blue" },
};
export const priorityLabel = (p: string) => priorityMap[p]?.label ?? p;
export const priorityTag = (p: string) => priorityMap[p]?.tag ?? "tag-blue";

export const priorityTheme = (p: string): string => {
  const m: Record<string, string> = { P1: "danger", P2: "warning", P3: "primary" };
  return m[p] || "primary";
};

export const sourceMap: Record<string, { label: string; cls: string; color: string }> = {
  plan: { label: "年度计划", cls: "src-plan", color: "#2563eb" },
  alert: { label: "监视告警", cls: "src-alert", color: "#dc2626" },
  meeting: { label: "判定会", cls: "src-meeting", color: "#d97706" },
  manual: { label: "手动", cls: "src-manual", color: "#7c3aed" },
};
export const sourceLabel = (s: string) => sourceMap[s]?.label ?? s;
export const sourceTagClass = (s: string) => sourceMap[s]?.cls ?? "";

export const escLabel: Record<number, string> = { 0: "", 1: "P3 预警", 2: "P2 升级", 3: "P1 严重" };
export const escTag = (lvl: number) => (lvl >= 3 ? "tag-red" : "tag-amber");

/** 审批流步骤定义（与后端状态机一致） */
export const FLOW_STEPS = [
  "pending",
  "approving",
  "dispatched",
  "executing",
  "verifying",
  "closed",
] as const;

/** 根据当前状态计算审批流进度。
 *  alert 来源 → 3步判断流程：待回填 → 判定中 → 已闭环
 */
export function flowProgress(
  status: string,
  sourceCode?: string,
  backfillFilled?: boolean,
): { idx: number; steps: { code: string; state: "done" | "active" | "warn" | "todo" }[] } {

  // alert 来源 → 判断流程
  if (sourceCode === "alert") {
    const steps = [
      { code: "pending", label: "待回填" },
      { code: "judging", label: "已回填" },
      { code: "closed", label: "已闭环" },
    ];
    let idx: number;
    if (status === "closed") {
      idx = 2;
    } else if (status === "judging") {
      idx = 1;
    } else {
      idx = 0;
    }
    return {
      idx,
      steps: steps.map((s, i) => ({
        code: s.code,
        state: i < idx ? "done" as const
             : i === idx ? "active" as const
             : "todo" as const,
      })),
    };
  }

  // 普通工单 → 原审批流
  const FLOW_STEPS = ["pending", "approving", "dispatched", "executing", "verifying", "closed"] as const;
  let idx = FLOW_STEPS.indexOf(status as any);
  if (idx === -1) idx = status === "overdue" ? 3 : status === "rejected" ? 1 : 0;
  const steps = FLOW_STEPS.map((code, i) => {
    if (status === "rejected" && i <= 1) return { code, state: "warn" as const };
    if (i < idx) return { code, state: "done" as const };
    if (i === idx) return { code, state: status === "overdue" ? ("warn" as const) : ("active" as const) };
    return { code, state: "todo" as const };
  });
  return { idx, steps };
}

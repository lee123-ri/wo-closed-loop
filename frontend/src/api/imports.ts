import http from "./http";

export interface ParsedItem {
  title: string;
  person?: string | null;
  project?: string | null;
  priority: string;
  type?: string;
  deadline?: string;
  reason?: string;
  action?: string;
  raw?: string;
  score?: number;
  reasons?: string[];
  low_confidence?: boolean;
}

export interface ParseResult {
  engine: "llm" | "regex";
  items: ParsedItem[];
  count: number;
}

export const parseMinutes = (text: string) =>
  http.post<any, ParseResult>("/import/parse-minutes", { text });

export const importTable = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return http.post<any, { created: number; errors: string[]; total: number }>("/import/table", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const importMinutesBatch = (items: any[]) =>
  // 复用 createWorkOrder 逐条创建
  Promise.all(
    items.map((it) =>
      http.post("/work-orders", {
        title: it.title,
        reason: it.reason || it.raw || "",
        action: it.action || it.title,
        person_id: it.person_id,
        project_id: it.project_id,
        type_id: it.type_id,
        source_code: "meeting",
        priority: it.priority || "P2",
        deadline: it.deadline,
      })
    )
  );

// ── 可靠性Agent 复盘 HTML 导入 ──────────────────────────

export interface AgentHtmlWorkOrder {
  workorder_id: string;
  code: string;
  status: string;
  unmapped: string[];
  task_count?: number;
}

export interface AgentHtmlImportResult {
  created: number;
  skipped_duplicate: number;
  total: number;
  batch_key?: string;
  already_imported?: boolean;
  message?: string;
  parsed_count?: number;
  project?: string;
  trigger?: { indicator?: string; period?: string };
  results: AgentHtmlWorkOrder[];
}

/** 上传「指标异常处置SOP」复盘 HTML → 后端解析并生成待派发草稿工单 */
export const importAgentHtml = (html: string) =>
  http.post<any, AgentHtmlImportResult>("/import/agent-html", { html });

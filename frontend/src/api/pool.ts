import http from "./http";

export interface PoolItem {
  id: number;
  pool_type: string;
  source_system: string;
  source_ref?: string | null;
  title: string;
  project_name?: string | null;
  person_name?: string | null;
  deadline?: string | null;
  description?: string | null;
  metric_type?: string | null;
  metric_value?: number | null;
  threshold?: number | null;
  deviation_pct?: number | null;
  status: string;
  work_order_id?: number | null;
  skip_reason?: string | null;
  raw_data?: any;
  backfill_reason?: string | null;
  backfill_action?: string | null;
  backfilled_at?: string | null;
  created_at: string;
  work_order_code?: string | null;
}

export interface PoolListOut {
  items: PoolItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface PoolImportResult {
  imported: number;
  skipped: number;
  errors: string[];
}

export interface GenerateResult {
  generated: number;
  skipped: number;
  errors: string[];
  work_order_ids: number[];
}

export interface BackfillResult {
  work_order_id: number;
  reason?: string | null;
  action?: string | null;
  triggered_wo_id?: number | null;
  triggered_wo_code?: string | null;
  backfilled_at: string;
  // 判断Agent 结果
  verdict?: string | null;
  judgment_reasoning?: string | null;
  judgment_suggestions?: {
    title?: string | null;
    deadline?: string | null;
    person_name?: string | null;
    priority?: string | null;
    action_adjustment?: string | null;
  } | null;
  judgment_confidence?: number | null;
}

// 数据池列表
export const listPoolItems = (params?: { pool_type?: string; status?: string; page?: number; page_size?: number }) =>
  http.get<any, PoolListOut>("/pool/items", { params });

// 单条详情
export const getPoolItem = (id: number) =>
  http.get<any, PoolItem>(`/pool/items/${id}`);

// 手动录入
export const createPoolItem = (data: Partial<PoolItem>) =>
  http.post<any, PoolItem>("/pool/items", data);

// 编辑
export const updatePoolItem = (id: number, data: Partial<PoolItem>) =>
  http.patch<any, PoolItem>(`/pool/items/${id}`, data);

// 删除
export const deletePoolItem = (id: number) =>
  http.delete(`/pool/items/${id}`);

// CSV 上传
export const uploadPoolCSV = (pool_type: string, file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return http.post<any, PoolImportResult>(`/pool/upload?pool_type=${pool_type}`, fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

// 批量生成工单
export const generateFromPool = (pool_ids: number[]) =>
  http.post<any, GenerateResult>("/pool/generate", { pool_ids });

// 一键生成全部
export const generateAllFromPool = (pool_type?: string) =>
  http.post<any, GenerateResult>("/pool/generate-all", null, { params: { pool_type } });

// AI表格同步
export const syncAITable = (base_id?: string, table_id?: string, pool_type?: string) =>
  http.post<any, PoolImportResult>("/pool/sync-aitable", null, { params: { base_id, table_id, pool_type } });

// 一键全链路同步：AITable→数据池→生成工单 + 钉盘「工单版」xlsx→工单
export interface FullSyncResult {
  aitable: { anomaly_synced: number; non_eam_synced: number };
  pool_generated: number;
  drive_imported: number;
  drive_files: number;
  errors: string[];
}
export const syncFull = () =>
  http.post<any, FullSyncResult>("/pool/sync-full", null);

// 回填
export const backfillWO = (wo_id: number, data: {
  reason?: string; action?: string; trigger_new_wo?: boolean;
  new_wo_title?: string; new_wo_deadline?: string; new_wo_person_name?: string;
  accept_judgment?: boolean; override_judgment?: boolean;
}) =>
  http.post<any, BackfillResult>(`/work-orders/${wo_id}/backfill`, data);

// 查看回填
export const getBackfill = (wo_id: number) =>
  http.get<any, BackfillResult>(`/work-orders/${wo_id}/backfill`);

// 判断Agent 导出
export const exportJudgment = (wo_id: number) =>
  http.get(`/work-orders/${wo_id}/export-judgment`, { responseType: "blob" });

// 判断Agent 导入
export const importJudgment = (wo_id: number, data: any) =>
  http.post<any, any>(`/work-orders/${wo_id}/import-judgment`, data);

// 人员看板
export const getPersonDashboard = (user_id: number) =>
  http.get<any, any>(`/dashboard/person/${user_id}`);

// 工单日历
export const getCalendar = (year: number, month: number, person_id?: number, project_id?: number) =>
  http.get<any, any>("/dashboard/calendar", { params: { year, month, person_id, project_id } });

// 趋势数据
export const getTrends = (months?: number) =>
  http.get<any, any>("/dashboard/trends", { params: { months } });
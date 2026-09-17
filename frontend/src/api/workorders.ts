import http from "./http";

export interface WorkOrder {
  id: number;
  code: string;
  title: string;
  reason: string | null;
  action: string | null;
  conclusion: string | null;
  status: string;
  priority: string;
  source_code: string;
  metric_type: string | null;
  alert_phase: string | null;
  measure_progress: {
    closed: number;
    total: number;
    measures: { id: number; code: string; status: string; title: string }[];
  } | null;
  occurrences: {
    id: number;
    occurred_at: string | null;
    metric_type: string | null;
    indicator_type: string | null;
    note: string | null;
  }[] | null;
  project_id: number | null;
  project_name: string | null;
  region: string | null;
  person_id: number | null;
  person_name: string | null;
  approver_id: number | null;
  approver_name: string | null;
  type_id: number | null;
  type_name: string | null;
  created_date: string;
  planned_start_date: string | null;
  deadline: string | null;
  completed_date: string | null;
  oa_id: string | null;
  escalation_level: number;
  overdue_days: number;
  duration_days: number | null;
  is_overdue: boolean;
  // 判断Agent
  judgment_status: string | null;
  judgment_result: any | null;
  // 回填增强
  triggered_wo_title: string | null;
  triggered_wo_deadline: string | null;
  triggered_wo_person_name: string | null;
  triggered_wo_tasks: any | null;
}

export interface WorkOrderList {
  items: WorkOrder[];
  total: number;
  page: number;
  page_size: number;
  project_options?: { id: number; name: string; region?: string | null }[];
}

export interface StatusLog {
  id: number;
  from_status: string | null;
  to_status: string;
  operator_name: string | null;
  note: string | null;
  created_at: string;
}

export const listWorkOrders = (params: Record<string, any> = {}) =>
  http.get<any, WorkOrderList>("/work-orders", { params });

export const listClosedOrders = (params: Record<string, any> = {}) =>
  http.get<any, WorkOrderList>("/work-orders/closed/list", { params });

export const getWorkOrder = (id: number) => http.get<any, WorkOrder>(`/work-orders/${id}`);

export const getStatusLogs = (id: number) => http.get<any, StatusLog[]>(`/work-orders/${id}/status-logs`);

export const createWorkOrder = (data: any) => http.post<any, WorkOrder>("/work-orders", data);

export const updateWorkOrder = (id: number, data: any) => http.patch<any, WorkOrder>(`/work-orders/${id}`, data);

export const updateWorkOrderBasic = (id: number, data: any) => http.patch<any, WorkOrder>(`/work-orders/${id}/basic`, data);

export const deleteWorkOrder = (id: number) => http.delete<any, { deleted: boolean; code: string }>(`/work-orders/${id}`);

export const transitionWorkOrder = (id: number, action: string) =>
  http.post<any, WorkOrder>(`/work-orders/${id}/transition`, null, { params: { action } });

export interface RedispatchMeasure {
  title: string;
  person_name?: string | null;
  type_id?: number | null;
  planned_start_date?: string | null;
  deadline?: string | null;
  reason?: string | null;
  action?: string | null;
  priority?: string | null;
}
export const redispatchMeasures = (id: number, measures: RedispatchMeasure[]) =>
  http.post<any, WorkOrder>(`/work-orders/${id}/redispatch`, { measures });

export interface SimilarHost {
  id: number;
  code: string;
  title: string;
  alert_phase: string | null;
  measure_progress: { closed: number; total: number; measures: { id: number; code: string; status: string; title: string }[] };
}
export const getSimilarHosts = (id: number) =>
  http.get<any, { items: SimilarHost[] }>(`/work-orders/${id}/similar`);

export const reuseMeasures = (id: number, measure_ids: number[]) =>
  http.post<any, WorkOrder>(`/work-orders/${id}/reuse`, { measure_ids });

export const mergeHost = (id: number, target_host_id: number) =>
  http.post<any, WorkOrder>(`/work-orders/${id}/merge`, { target_host_id });

export const syncOaWorkOrder = (id: number) => http.post<any, any>(`/dingtalk/oa/sync/${id}`);

export const getWorkOrderAttachments = (id: number) => http.get<any, any[]>(`/work-orders/${id}/attachments`);

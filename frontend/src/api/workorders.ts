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
  project_id: number | null;
  project_name: string | null;
  person_id: number | null;
  person_name: string | null;
  approver_id: number | null;
  approver_name: string | null;
  type_id: number | null;
  type_name: string | null;
  created_date: string;
  deadline: string | null;
  completed_date: string | null;
  oa_id: string | null;
  escalation_level: number;
  overdue_days: number;
  duration_days: number | null;
  is_overdue: boolean;
}

export interface WorkOrderList {
  items: WorkOrder[];
  total: number;
  page: number;
  page_size: number;
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

export const transitionWorkOrder = (id: number, action: string) =>
  http.post<any, WorkOrder>(`/work-orders/${id}/transition`, null, { params: { action } });

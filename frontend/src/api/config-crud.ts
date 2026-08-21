import http from "./http";

// 优先级规则
export const addPriorityRuleApi = (data: { pattern: string; label: string; priority: string }) =>
  http.post<any, any>("/config/priority-rules", data);
export const delPriorityRuleApi = (id: number) => http.delete<any, void>(`/config/priority-rules/${id}`);
export const updatePriorityRuleApi = (id: number, data: { pattern?: string; label?: string; priority?: string; enabled?: boolean }) =>
  http.patch<any, any>(`/config/priority-rules/${id}`, data);

// SLA
export const updateSla = (id: number, data: { deadline_days?: number; warn_before_hours?: number; escalate_hours?: number }) =>
  http.patch<any, any>(`/config/sla/${id}`, data);

// 工单类型
export const getWoTypesFull = () => http.get<any, any[]>("/config/work-order-types-full");
export const addWoType = (data: any) => http.post<any, any>("/config/work-order-types", data);
export const updateWoType = (id: number, data: any) => http.patch<any, any>(`/config/work-order-types/${id}`, data);
export const delWoType = (id: number) => http.delete<any, void>(`/config/work-order-types/${id}`);

// 来源/状态
export const addConfigDef = (data: { category: string; code: string; name: string; color?: string }) =>
  http.post<any, any>("/config/config-definitions", data);
export const updateConfigDef = (id: number, data: { name?: string; color?: string }) =>
  http.patch<any, any>(`/config/config-definitions/${id}`, data);
export const delConfigDef = (id: number) => http.delete<any, void>(`/config/config-definitions/${id}`);

// 审批流
export const updateApprovalFlow = (id: number, data: { name?: string; nodes?: any[]; escalation?: any }) =>
  http.patch<any, any>(`/config/approval-flows/${id}`, data);
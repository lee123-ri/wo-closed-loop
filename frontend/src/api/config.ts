import http from "./http";

export interface ConfigItem {
  id: number;
  category: string;
  code: string;
  name: string;
  color: string | null;
  sort_order: number;
  extra: any;
}

export const getStatuses = () => http.get<any, ConfigItem[]>("/config/statuses");
// 工单类型（统一口径：来源/工单类型/异常大类三合一，10 内置 + 后台新增）
export const getWoTypes = () => http.get<any, ConfigItem[]>("/config/work-order-types");
export const addWorkOrderType = (data: { name: string; default_approver_name?: string | null; default_person_name?: string | null }) =>
  http.post<any, ConfigItem>("/config/work-order-types", data);
export const updateWorkOrderType = (id: number, data: { name?: string; flow?: string; default_approver_name?: string | null; default_person_name?: string | null }) =>
  http.patch<any, ConfigItem>(`/config/work-order-types/${id}`, data);
export const getWoTypesFull = () => http.get<any, any[]>("/config/work-order-types-full");
export const getProjects = () => http.get<any, any[]>("/config/projects");
export const getProjectsAll = () => http.get<any, any[]>("/config/projects/all");
export const getUsers = () => http.get<any, any[]>("/config/users");
export const getUsersAll = () => http.get<any, any[]>("/config/users/all");
export const getPriorityRules = () => http.get<any, any[]>("/config/priority-rules");
export const getSla = () => http.get<any, any[]>("/config/sla");
export const getApprovalFlows = () => http.get<any, any[]>("/config/approval-flows");
export const getPersonProjectMap = () => http.get<any, any[]>("/config/person-project-map");

// 数据范围角色：每个角色能看到哪些工单（多选取并集；admin 行锁定不可改）
export const getRoleScopes = () => http.get<any, any[]>("/config/role-scopes");
export const updateRoleScope = (roleCode: string, scopes: string[]) => http.put<any, any>(`/config/role-scopes/${roleCode}`, { scopes });

// 「暂停发单」开关：读=任意已登录；写=仅管理员
export const getSystemPause = () => http.get<any, { paused: boolean }>("/config/system-pause");
export const setSystemPause = (enabled: boolean) => http.put<any, { paused: boolean }>("/config/system-pause", { enabled });

export interface DingtalkStatus {
  app_key: boolean;
  app_secret: boolean;
  agent: boolean;
  oa_template: boolean;
  corp: boolean;
  callback_token: boolean;
  callback_aes_key: boolean;
}
export const getDingtalkStatus = () => http.get<any, DingtalkStatus>("/dingtalk/status");

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

export const getSources = () => http.get<any, ConfigItem[]>("/config/sources");
export const getStatuses = () => http.get<any, ConfigItem[]>("/config/statuses");
export const getWoTypes = () => http.get<any, ConfigItem[]>("/config/work-order-types");
export const getWoTypesFull = () => http.get<any, any[]>("/config/work-order-types-full");
export const getProjects = () => http.get<any, any[]>("/config/projects");
export const getProjectsAll = () => http.get<any, any[]>("/config/projects/all");
export const getUsers = () => http.get<any, any[]>("/config/users");
export const getUsersAll = () => http.get<any, any[]>("/config/users/all");
export const getPriorityRules = () => http.get<any, any[]>("/config/priority-rules");
export const getSla = () => http.get<any, any[]>("/config/sla");
export const getApprovalFlows = () => http.get<any, any[]>("/config/approval-flows");
export const getPersonProjectMap = () => http.get<any, any[]>("/config/person-project-map");

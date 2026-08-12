import http from "./http";

export interface DashboardStats {
  total: number;
  executing: number;
  pending_verify: number;
  overdue: number;
  closed: number;
  sla_compliance: number;
  mttr_days: number | null;
  mtta_days: number | null;
  closed_rate: number;
  aging: Record<string, number>;
  source_dist: { code: string; name: string; count: number; pct: number }[];
  overdue_items: { id: number; code: string; person: string; overdue_days: number; escalation_level: number; title: string }[];
  todo_items: { id: number; code: string; title: string; status: string; priority: string; person: string; deadline: string | null; escalation_level: number }[];
}

export const getDashboardStats = () => http.get<any, DashboardStats>("/dashboard/stats");

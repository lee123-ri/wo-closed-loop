import http from "./http";

export interface LoginUser {
  id: number;
  name: string;
  role: string;
  phone?: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  user: LoginUser;
  redirect_path?: string;
}

export interface Permissions {
  roles: string[];
  menu_groups: Record<string, Record<string, { roles: string[] }>>;
  actions: Record<string, { roles: string[] }>;
}

// 获取钉钉登录 URL
export const getDingTalkLoginUrl = (redirect_path?: string) =>
  http.get<any, { url: string }>("/auth/dingtalk/url", { params: { redirect_path } });

// 钉钉 OAuth 回调
export const dingtalkCallback = (code: string, redirect_path?: string) =>
  http.get<any, LoginResult>("/auth/dingtalk/callback", { params: { code, redirect_path } });

// 获取当前用户
export const getMe = () =>
  http.get<any, LoginUser>("/auth/me");

// 获取权限配置
export const getPermissions = () =>
  http.get<any, Permissions>("/auth/permissions");
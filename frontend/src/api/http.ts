import axios, { type AxiosInstance } from "axios";

const http: AxiosInstance = axios.create({
  baseURL: "/api",
  timeout: 30000,
});

// 请求拦截：附 JWT
http.interceptors.request.use((config) => {
  const token = localStorage.getItem("wo_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// 响应拦截：统一错误
http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("wo_token");
      if (window.location.pathname !== "/login") {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
    }
    const msg = err.response?.data?.detail || err.message || "请求失败";
    return Promise.reject(new Error(msg));
  }
);

export default http;

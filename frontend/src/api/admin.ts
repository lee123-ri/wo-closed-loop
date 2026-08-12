import http from "./http";

export const clearData = () => http.delete<any, any>("/admin/clear-data");
export const getStats = () => http.get<any, any>("/admin/stats");

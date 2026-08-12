<template>
  <div class="page">
    <div class="header"><h1>操作日志</h1><div class="meta">系统操作记录</div></div>
    <div class="card">
      <table>
        <thead><tr><th style="width:160px">时间</th><th style="width:80px">操作</th><th style="width:120px">对象</th><th>详情</th><th style="width:80px">操作人</th></tr></thead>
        <tbody>
          <tr v-for="log in logs" :key="log.id">
            <td class="time">{{ log.created_at?.slice(0,16) }}</td>
            <td><span class="tag tag-blue">{{ log.action }}</span></td>
            <td>{{ log.target }} #{{ log.target_id }}</td>
            <td class="detail">{{ log.detail }}</td>
            <td>{{ log.operator }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!logs.length" class="empty">暂无操作记录</div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from "vue";
import http from "@/api/http";
const logs = ref<any[]>([]);
onMounted(async () => { try { const r: any = await http.get("/config/audit-logs?page_size=100"); logs.value = r.items || []; } catch {} });
</script>
<style scoped>
.page .header { margin-bottom: 20px; } .header h1 { font-size: var(--fs-h1); font-weight: 700; } .meta { font-size: 12px; color: var(--muted); }
.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); overflow: auto; }
table { width: 100%; border-collapse: collapse; } th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
th { background: #f8fafc; font-weight: 600; font-size: 11px; color: var(--muted); }
.time { font-family: monospace; font-size: 12px; color: var(--muted); } .detail { color: var(--muted); font-size: 12px; max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.tag-blue { background: #eff6ff; color: var(--brand); }
.empty { text-align: center; padding: 40px; color: var(--muted); }
</style>
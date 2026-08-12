<template>
  <div class="my-page">
    <div class="header">
      <div><h1>{{ userName }} 的工单</h1><div class="meta">我的待办 · 执行中 · 逾期 · 回填</div></div>
      <div class="header-actions">
        <select v-model="currentUserId" @change="load">
          <option :value="user.id" v-for="user in users" :key="user.id">{{ user.name }}</option>
        </select>
      </div>
    </div>

    <!-- 统计卡片 -->
    <div class="stats-row" v-if="stats">
      <div class="stat-card" @click="filterStatus = ''">
        <div class="num">{{ stats.total }}</div>
        <div class="lbl">全部工单</div>
      </div>
      <div class="stat-card warn" @click="filterStatus = 'overdue'">
        <div class="num">{{ stats.overdue }}</div>
        <div class="lbl">已逾期</div>
      </div>
      <div class="stat-card primary" @click="filterStatus = 'executing'">
        <div class="num">{{ stats.executing }}</div>
        <div class="lbl">执行中</div>
      </div>
      <div class="stat-card amber" @click="filterStatus = 'verifying'">
        <div class="num">{{ stats.verifying }}</div>
        <div class="lbl">待验收</div>
      </div>
      <div class="stat-card blue" @click="filterStatus = 'pending'">
        <div class="num">{{ stats.pending }}</div>
        <div class="lbl">待处理</div>
      </div>
      <div class="stat-card" @click="filterStatus = 'need_backfill'">
        <div class="num">{{ stats.need_backfill }}</div>
        <div class="lbl">待回填</div>
      </div>
    </div>

    <!-- 待处理列表 -->
    <div class="card">
      <div class="card-hd">
        <h3>工单列表</h3>
        <span class="count">共 {{ items.length }} 条</span>
      </div>
      <table v-if="items.length">
        <thead>
          <tr>
            <th style="width:100px">编号</th>
            <th>标题</th>
            <th style="width:70px">优先级</th>
            <th style="width:70px">状态</th>
            <th style="width:90px">截止日期</th>
            <th style="width:60px">回填</th>
            <th style="width:60px">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in filteredItems" :key="item.id" :class="{ overdue: item.status === 'overdue' }">
            <td class="code">{{ item.code }}</td>
            <td class="title-cell">
              <div class="title">{{ item.title }}</div>
            </td>
            <td><span class="tag" :class="priorityTag(item.priority)">{{ priorityLabel(item.priority) }}</span></td>
            <td><span class="tag" :class="statusTag(item.status)">{{ statusLabel(item.status) }}</span></td>
            <td :class="{ 'text-red': item.status === 'overdue' }">
              {{ item.deadline }}
              <span v-if="item.overdue_days" class="overdue-badge">+{{ item.overdue_days }}天</span>
            </td>
            <td>
              <span v-if="item.backfill_status === 'filled'" class="done">已填</span>
              <span v-else-if="item.status === 'executing' || item.status === 'dispatched'" class="pending">待填</span>
              <span v-else class="na">—</span>
            </td>
            <td>
              <button class="btn btn-sm btn-pri" @click="$router.push(`/work-orders/${item.id}`)">查看</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无工单</div>
    </div>

    <!-- 日历（本月） -->
    <div class="card">
      <div class="card-hd">
        <h3>本月日历 · {{ currentMonthLabel }}</h3>
        <div class="cal-nav">
          <button class="btn btn-sm btn-out" @click="changeMonth(-1)">‹</button>
          <button class="btn btn-sm btn-out" @click="changeMonth(1)">›</button>
        </div>
      </div>
      <div class="mini-cal">
        <div class="cal-header">
          <div v-for="d in dayNames" :key="d" class="cal-day-name">{{ d }}</div>
        </div>
        <div class="cal-grid">
          <div v-for="(day, i) in calendarDays" :key="i" class="cal-day" :class="dayClass(day)">
            <div class="cal-date">{{ day.date }}</div>
            <div v-for="wo in day.items" :key="wo.id" class="cal-item" :class="'cal-' + wo.status">
              <span class="cal-dot"></span>
              <span class="cal-text">{{ wo.code.slice(-4) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { listPoolItems, getPersonDashboard, getCalendar } from "@/api/pool";
import { getUsers } from "@/api/config";
import { priorityLabel, priorityTag, statusLabel, statusTag } from "@/utils/wo-display";

const users = ref<any[]>([]);
const currentUserId = ref(0);
const userName = ref("我的");
const stats = ref<any>(null);
const items = ref<any[]>([]);
const filterStatus = ref("");
const calendarYear = ref(new Date().getFullYear());
const calendarMonth = ref(new Date().getMonth() + 1);
const currentMonthLabel = computed(() => `${calendarYear.value}年${calendarMonth.value}月`);
const dayNames = ["一", "二", "三", "四", "五", "六", "日"];
const calendarDays = ref<any[]>([]);

const filteredItems = computed(() => {
  if (!filterStatus.value) return items.value;
  if (filterStatus.value === "need_backfill") {
    return items.value.filter((i: any) => i.status === "executing" || i.status === "dispatched");
  }
  return items.value.filter((i: any) => i.status === filterStatus.value);
});

async function load() {
  if (!currentUserId.value) return;
  try {
    const res = await getPersonDashboard(currentUserId.value);
    userName.value = res.user.name;
    stats.value = res.stats;
    items.value = res.items;
    await loadCalendar();
  } catch (e: any) {
    console.error(e);
  }
}

async function loadCalendar() {
  try {
    const res = await getCalendar(calendarYear.value, calendarMonth.value, currentUserId.value);
    // 构建日历网格
    const days: any[] = [];
    const first = new Date(calendarYear.value, calendarMonth.value - 1, 1);
    const last = new Date(calendarYear.value, calendarMonth.value, 0);
    const startDow = first.getDay() || 7; // 1=周一, 7=周日
    // 填充空白
    for (let i = 1; i < startDow; i++) days.push({ date: "", items: [], empty: true });
    for (let d = 1; d <= last.getDate(); d++) {
      const dateStr = `${calendarYear.value}-${String(calendarMonth.value).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      const dayItems = res.items.filter((i: any) => i.deadline === dateStr);
      days.push({ date: d, items: dayItems, today: dateStr === new Date().toISOString().slice(0, 10), empty: false });
    }
    calendarDays.value = days;
  } catch (e: any) {
    console.error(e);
  }
}

function dayClass(day: any) {
  return {
    "cal-today": day.today,
    "cal-empty": day.empty,
    "cal-has-items": day.items.length > 0,
  };
}

function changeMonth(delta: number) {
  calendarMonth.value += delta;
  if (calendarMonth.value > 12) { calendarMonth.value = 1; calendarYear.value++; }
  if (calendarMonth.value < 1) { calendarMonth.value = 12; calendarYear.value--; }
  loadCalendar();
}

onMounted(async () => {
  users.value = await getUsers();
  if (users.value.length) {
    currentUserId.value = users.value[0].id;
    await load();
  }
});
</script>

<style scoped>
.my-page .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 16px; flex-wrap: wrap; }
.header h1 { font-size: var(--fs-h1); font-weight: 700; }
.meta { font-size: 12px; color: var(--muted); }
.header select { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; font-size: 13px; }

.stats-row { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 16px; }
.stat-card { background: var(--card); border-radius: var(--radius); padding: 16px; text-align: center; box-shadow: var(--shadow); cursor: pointer; }
.stat-card:hover { transform: translateY(-1px); }
.stat-card .num { font-size: 28px; font-weight: 700; }
.stat-card .lbl { font-size: 11px; color: var(--muted); margin-top: 2px; }
.stat-card.warn .num { color: var(--red); }
.stat-card.primary .num { color: var(--brand); }
.stat-card.amber .num { color: var(--amber); }
.stat-card.blue .num { color: #2563eb; }

.card { background: var(--card); border-radius: var(--radius); box-shadow: var(--shadow); margin-bottom: 16px; overflow: auto; }
.card-hd { display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.card-hd h3 { font-size: 15px; font-weight: 700; }
.count { font-size: 12px; color: var(--muted); }
.cal-nav { display: flex; gap: 4px; }

table { width: 100%; border-collapse: collapse; }
th, td { padding: 10px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); }
th { background: #f8fafc; font-weight: 600; font-size: 11px; color: var(--muted); }
tr.overdue { background: #fef2f2; }
.code { font-family: monospace; font-size: 12px; color: var(--muted); }
.title-cell .title { font-weight: 600; }
.text-red { color: var(--red); }
.overdue-badge { font-size: 11px; color: var(--red); font-weight: 600; margin-left: 4px; }
.done { color: var(--green); font-weight: 600; font-size: 12px; }
.pending { color: var(--amber); font-weight: 600; font-size: 12px; }
.na { color: var(--muted); font-size: 12px; }
.empty { text-align: center; padding: 40px; color: var(--muted); }

/* 迷你日历 */
.mini-cal { padding: 12px; }
.cal-header { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; margin-bottom: 4px; }
.cal-day-name { text-align: center; font-size: 11px; font-weight: 600; color: var(--muted); padding: 4px 0; }
.cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
.cal-day { min-height: 60px; padding: 4px; border-radius: 4px; background: #fafafa; }
.cal-empty { background: transparent; }
.cal-today { background: #eff6ff; border: 1px solid var(--brand); }
.cal-has-items { background: #f8fafc; }
.cal-date { font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 2px; }
.cal-today .cal-date { color: var(--brand); }
.cal-item { font-size: 10px; display: flex; align-items: center; gap: 3px; margin-bottom: 1px; cursor: pointer; }
.cal-item:hover { background: #e5e7eb; border-radius: 2px; }
.cal-dot { width: 4px; height: 4px; border-radius: 50%; flex-shrink: 0; }
.cal-overdue .cal-dot { background: var(--red); }
.cal-executing .cal-dot { background: var(--brand); }
.cal-verifying .cal-dot { background: var(--amber); }
.cal-pending .cal-dot { background: #9ca3af; }
.cal-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.tag { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.tag-blue { background: #eff6ff; color: var(--brand); }
.tag-green { background: #ecfdf5; color: var(--green); }
.tag-amber { background: #fffbeb; color: var(--amber); }
.tag-red { background: #fef2f2; color: var(--red); }
.tag-gray { background: #f3f4f6; color: #6b7280; }

.btn { padding: 8px 16px; border-radius: 6px; border: none; cursor: pointer; font-size: 13px; font-weight: 600; }
.btn-pri { background: var(--brand); color: #fff; }
.btn-out { background: #fff; color: #4b5563; border: 1px solid var(--border); }
.btn-sm { padding: 4px 10px; font-size: 11px; }
</style>
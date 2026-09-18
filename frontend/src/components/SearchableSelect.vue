<template>
  <div class="ss-wrap" ref="wrapRef">
    <div class="ss-input-row" @click="focusInput">
      <span v-if="selected" class="ss-chip">
        <span class="ss-avatar sm" :style="{ background: avatarColor(selected.name) }">{{ avatarChar(selected.name) }}</span>
        {{ selected.name }}
        <button class="ss-chip-x" @click.stop="clear">×</button>
      </span>
      <input
        ref="inputRef"
        v-model="query"
        :placeholder="selected ? '' : placeholder"
        @focus="open = true"
        @input="open = true"
        @keydown.down.prevent="moveDown"
        @keydown.up.prevent="moveUp"
        @keydown.enter.prevent="pickHighlighted"
        @keydown.escape="open = false"
        class="ss-input"
      />
    </div>

    <div v-if="open" class="ss-drop">
      <!-- 搜索中：平铺结果 -->
      <template v-if="query.trim()">
        <div
          v-for="(u, i) in filtered"
          :key="u.id"
          class="ss-item"
          :class="{ hl: i === idx }"
          @mousedown.prevent="pick(u)"
          @mouseenter="idx = i"
        >
          <span class="ss-avatar" :style="{ background: avatarColor(u.name) }">{{ avatarChar(u.name) }}</span>
          <span class="ss-name">{{ u.name }}</span>
          <span class="ss-meta" v-if="u.department">{{ u.department }}</span>
          <span class="ss-tag">{{ roleLabel(u.role) }}</span>
        </div>
        <div v-if="!filtered.length" class="ss-empty">无匹配结果</div>
      </template>
      <!-- 未搜索：按部门分组浏览 -->
      <template v-else>
        <div v-for="g in grouped" :key="g.dept" class="ss-group">
          <div class="ss-group-hd">{{ g.dept }} <span class="ss-count">{{ g.items.length }}</span></div>
          <div
            v-for="u in g.items"
            :key="u.id"
            class="ss-item"
            :class="{ hl: u.id === visible[idx]?.id }"
            @mousedown.prevent="pick(u)"
            @mouseenter="idx = indexOf(u)"
          >
            <span class="ss-avatar" :style="{ background: avatarColor(u.name) }">{{ avatarChar(u.name) }}</span>
            <span class="ss-name">{{ u.name }}</span>
            <span class="ss-tag">{{ roleLabel(u.role) }}</span>
          </div>
        </div>
        <div v-if="!grouped.length" class="ss-empty">暂无可选人员</div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick, onBeforeUnmount } from "vue";

interface UserOption {
  id: number;
  name: string;
  role: string;
  department?: string | null;
}

const props = defineProps<{
  modelValue: number | undefined;
  options: UserOption[];
  placeholder?: string;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", v: number | undefined): void;
}>();

const open = ref(false);
const query = ref("");
const idx = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);
const wrapRef = ref<HTMLElement | null>(null);

const selected = computed(() => props.options.find((u) => u.id === props.modelValue));

function match(u: UserOption, q: string) {
  return (
    (u.name || "").toLowerCase().includes(q) ||
    (u.department || "").toLowerCase().includes(q)
  );
}

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return props.options;
  return props.options.filter((u) => match(u, q)).slice(0, 100);
});

// 键盘导航的扁平列表：搜索时用筛选结果，否则用全量
const visible = computed(() => (query.value.trim() ? filtered.value : props.options));

const grouped = computed(() => {
  const map = new Map<string, UserOption[]>();
  for (const u of props.options) {
    const dept = u.department || "未分组";
    if (!map.has(dept)) map.set(dept, []);
    map.get(dept)!.push(u);
  }
  const entries = [...map.entries()];
  entries.sort((a, b) => (a[0] === "未分组" ? 1 : 0) - (b[0] === "未分组" ? 1 : 0));
  return entries.map(([dept, items]) => ({ dept, items }));
});

function roleLabel(r: string) {
  return (
    { admin: "管理员", approver: "审批人", executor: "责任人" }[r] || r
  );
}

function avatarChar(name: string) {
  return (name && name.trim().charAt(0)) || "?";
}

function avatarColor(name: string) {
  const colors = ["#0052d9", "#2ba471", "#e37318", "#d54941", "#7c3aed", "#0ea5e9", "#db2777", "#65a30d"];
  if (!name) return colors[0];
  let h = 0;
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return colors[h % colors.length];
}

function indexOf(u: UserOption) {
  return visible.value.findIndex((x) => x.id === u.id);
}

function focusInput() {
  inputRef.value?.focus();
}

function pick(u: UserOption) {
  emit("update:modelValue", u.id);
  query.value = "";
  idx.value = 0;
  open.value = false;
}

function clear() {
  emit("update:modelValue", undefined);
  query.value = "";
  open.value = false;
}

function moveDown() {
  if (idx.value < visible.value.length - 1) idx.value++;
}

function moveUp() {
  if (idx.value > 0) idx.value--;
}

function pickHighlighted() {
  const u = visible.value[idx.value];
  if (u) pick(u);
}

function onClick(e: MouseEvent) {
  if (wrapRef.value && !wrapRef.value.contains(e.target as Node)) {
    open.value = false;
    query.value = "";
    idx.value = 0;
  }
}

watch(open, async (v) => {
  if (v) {
    await nextTick();
    inputRef.value?.focus();
    document.addEventListener("mousedown", onClick);
  } else {
    document.removeEventListener("mousedown", onClick);
  }
});

watch(query, () => { idx.value = 0; });
onBeforeUnmount(() => document.removeEventListener("mousedown", onClick));
</script>

<style scoped>
.ss-wrap { position: relative; }
.ss-input-row {
  display: flex; align-items: center; gap: 6px;
  padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: #fff; cursor: text; min-height: 36px; flex-wrap: wrap;
}
.ss-input-row:focus-within { border-color: var(--brand); box-shadow: 0 0 0 2px rgba(37,99,235,.12); }
.ss-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 2px 8px 2px 4px; background: #eff6ff; color: var(--brand);
  border-radius: 20px; font-size: 12px; font-weight: 600;
}
.ss-chip-x { background: none; border: none; color: var(--brand); cursor: pointer; font-size: 15px; padding: 0; line-height: 1; }
.ss-input { border: none; outline: none; flex: 1; min-width: 80px; font-size: 13px; background: transparent; }

.ss-drop {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 100;
  max-height: 340px; overflow-y: auto;
  background: #fff; border: 1px solid var(--border); border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,.12);
}
.ss-group-hd {
  padding: 6px 12px; font-size: 11px; font-weight: 700; color: var(--muted);
  background: #f8fafc; border-bottom: 1px solid var(--border);
  position: sticky; top: 0;
}
.ss-count { font-weight: 500; color: #b0b6bf; margin-left: 4px; }
.ss-item {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 12px; cursor: pointer; font-size: 13px;
}
.ss-item:hover, .ss-item.hl { background: #eff6ff; }
.ss-avatar {
  width: 26px; height: 26px; border-radius: 50%; color: #fff;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 600; flex-shrink: 0;
}
.ss-avatar.sm { width: 18px; height: 18px; font-size: 10px; }
.ss-name { font-weight: 500; flex-shrink: 0; }
.ss-meta { font-size: 11px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ss-tag { margin-left: auto; font-size: 10px; color: var(--muted); background: #f3f4f6; padding: 1px 6px; border-radius: 3px; flex-shrink: 0; }
.ss-empty { padding: 16px; text-align: center; color: var(--muted); font-size: 12px; }
</style>

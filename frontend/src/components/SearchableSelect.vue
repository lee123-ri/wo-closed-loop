<template>
  <div class="ss-wrap" ref="wrapRef">
    <div class="ss-input-row" @click="open = true">
      <span v-if="selected" class="ss-chip">{{ selected.name }} <button class="ss-chip-x" @click.stop="clear">×</button></span>
      <input
        ref="inputRef"
        v-model="query"
        :placeholder="selected ? '' : placeholder"
        @focus="open = true"
        @keydown.down.prevent="moveDown"
        @keydown.up.prevent="moveUp"
        @keydown.enter.prevent="pickHighlighted"
        @keydown.escape="open = false"
        class="ss-input"
      />
    </div>
    <div v-if="open && filtered.length" class="ss-drop">
      <div
        v-for="(u, i) in filtered"
        :key="u.id"
        class="ss-item"
        :class="{ hl: i === idx }"
        @mousedown.prevent="pick(u)"
        @mouseenter="idx = i"
      >
        <span class="ss-name">{{ u.name }}</span>
        <span class="ss-tag">{{ u.role === 'approver' ? '审批人' : u.role === 'admin' ? '管理员' : '执行人' }}</span>
      </div>
    </div>
    <div v-if="open && query && !filtered.length" class="ss-drop ss-empty">无匹配结果</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch, nextTick } from "vue";

interface UserOption {
  id: number;
  name: string;
  role: string;
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

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return props.options.slice(0, 50);
  return props.options.filter((u) => u.name.toLowerCase().includes(q)).slice(0, 50);
});

function pick(u: UserOption) {
  emit("update:modelValue", u.id);
  query.value = "";
  open.value = false;
  idx.value = 0;
}

function clear() {
  emit("update:modelValue", undefined);
  query.value = "";
  open.value = false;
}

function moveDown() {
  if (idx.value < filtered.value.length - 1) idx.value++;
}

function moveUp() {
  if (idx.value > 0) idx.value--;
}

function pickHighlighted() {
  const u = filtered.value[idx.value];
  if (u) pick(u);
}

// 点击外部关闭
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
</script>

<style scoped>
.ss-wrap { position: relative; }
.ss-input-row {
  display: flex; align-items: center; gap: 4px;
  padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px;
  background: #fff; cursor: text; min-height: 36px; flex-wrap: wrap;
}
.ss-input-row:focus-within { border-color: var(--brand); box-shadow: 0 0 0 2px rgba(37,99,235,.12); }
.ss-chip {
  display: inline-flex; align-items: center; gap: 2px;
  padding: 2px 8px; background: #eff6ff; color: var(--brand);
  border-radius: 4px; font-size: 12px; font-weight: 600;
}
.ss-chip-x { background: none; border: none; color: var(--brand); cursor: pointer; font-size: 14px; padding: 0; line-height: 1; }
.ss-input { border: none; outline: none; flex: 1; min-width: 80px; font-size: 13px; background: transparent; }
.ss-drop {
  position: absolute; top: 100%; left: 0; right: 0; z-index: 100;
  max-height: 220px; overflow-y: auto;
  background: #fff; border: 1px solid var(--border); border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0,0,0,.1); margin-top: 2px;
}
.ss-item {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 10px; cursor: pointer; font-size: 13px;
}
.ss-item.hl { background: #eff6ff; }
.ss-name { font-weight: 500; }
.ss-tag { font-size: 10px; color: var(--muted); background: #f3f4f6; padding: 1px 6px; border-radius: 3px; }
.ss-empty { padding: 12px; text-align: center; color: var(--muted); font-size: 12px; }
</style>
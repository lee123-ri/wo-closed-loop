import { defineStore } from "pinia";
import { ref } from "vue";
import { getSources, getStatuses, getSla } from "@/api/config";

interface DictItem { code: string; name: string; color?: string | null; }

/**
 * 运行时业务字典：从后端 /config 读状态、来源、SLA，
 * 前端显示层据此渲染，后端可改配置自由调整；读不到时回退硬编码兜底。
 */
export const useConfigStore = defineStore("config", () => {
  const sources = ref<DictItem[]>([]);
  const statuses = ref<DictItem[]>([]);
  const sla = ref<{ priority: string; deadline_days: number }[]>([]);
  const loaded = ref(false);

  async function ensureLoaded() {
    if (loaded.value) return;
    try {
      const [src, sts, sl] = await Promise.all([getSources(), getStatuses(), getSla()]);
      sources.value = (src as any[]).map((x) => ({ code: x.code, name: x.name, color: x.color ?? null }));
      statuses.value = (sts as any[]).map((x) => ({ code: x.code, name: x.name, color: x.color ?? null }));
      sla.value = (sl as any[]).map((x) => ({ priority: x.priority, deadline_days: x.deadline_days }));
      loaded.value = true;
    } catch {
      /* 保持空，显示层走硬编码兜底 */
    }
  }

  function nameOf(list: DictItem[], code: string, fallback: string): string {
    const hit = list.find((x) => x.code === code);
    return hit?.name ?? fallback;
  }

  const statusName = (code: string, fallback: string) => nameOf(statuses.value, code, fallback);
  const sourceName = (code: string, fallback: string) => nameOf(sources.value, code, fallback);
  const slaDays = (priority: string, fallback: number): number =>
    sla.value.find((x) => x.priority === priority)?.deadline_days ?? fallback;

  return { sources, statuses, sla, loaded, ensureLoaded, statusName, sourceName, slaDays };
});
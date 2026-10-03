import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { GuiConfigValues } from "@/lib/types";

function clampInt(value: string, defaultVal: number, min: number, max: number): string {
  const n = parseInt(value, 10);
  if (isNaN(n)) return String(defaultVal);
  return String(Math.max(min, Math.min(max, n)));
}

/** 任务 ID 文本去重 + 稳定排序（与后端 _normalize_task_ids_text 一致） */
function normalizeTaskIds(value: string): string {
  const parts = value
    .split(",")
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  return Array.from(new Set(parts)).sort().join(",");
}

/** 线程数 / 总连接数上限。
    统一为 128，与后端 overwatch_drops_miner/config.py 的 validate() 对齐。
    原先前端 validate 256 / sidecar 的 _clamp_int 256 / backend/config.py 的 validate 128
    三处不一致：默认 60×3=180 能保存成功但启动时被 config.py 拒绝，
    错误文案来自深层调用，用户很难联想到「房间数 × 线程数」。 */
const MAX_THREAD_COUNT = 128;

/** 关闭链路的兜底配置快照 key（save() 成功后由 load() 清理） */
const CONFIG_STASH_KEY = "config_stash";

export const useConfigStore = defineStore("config", () => {
  const config = ref<GuiConfigValues>({
    cookie: "",
    rooms_text: "23612045",
    thread_count_text: "60",
    reconnect_delay_text: "8",
    task_ids_text: "",
    task_query_interval_text: "30",
    notify_urls_text: "",
    notify_on_task_complete: true,
    verbose: false,
    auto_claim_rewards: false,
  });

  const loading = ref(false);
  const loadError = ref("");
  let loaded = false;
  /** in-flight 去重：loaded 只在 await 兑现后才置 true，而 Vue 中子组件
      onMounted 先于父组件执行 —— ConfigForm 先发一次并挂起，App.vue 再发第二次。
      注释原先宣称「幂等」但实际并未实现。 */
  let inflight: Promise<void> | null = null;
  /** 请求序号：save() 尾部会 load() 回读确认，此时若还有另一次 load 在途，
      两次响应没有顺序保证 —— 旧请求后到就覆盖刚落盘的配置，形成静默回滚。 */
  let loadToken = 0;

  async function load() {
    const token = ++loadToken;
    loading.value = true;
    loadError.value = "";
    try {
      const next = await invoke<GuiConfigValues>("load_config");
      if (token !== loadToken) return; // 已有更新的请求，丢弃本次
      config.value = next;
      loaded = true;
      // 成功落盘后清理关闭链路的兜底快照
      try {
        localStorage.removeItem(CONFIG_STASH_KEY);
      } catch {
        /* 隐私模式/配额异常：忽略 */
      }
    } catch (e) {
      if (token === loadToken) {
        loadError.value = `${e}`;
        // 关闭链路写下的兜底快照：上次退出时 save() 失败/超时，
        // 至少把用户编辑恢复回界面，避免直接退回默认值。
        const restored = restoreFromStash();
        if (restored) {
          console.warn("load_config 失败，已从本地快照恢复上次的配置编辑");
        }
      }
      throw e;
    } finally {
      if (token === loadToken) loading.value = false;
    }
  }

  /** 幂等加载：多个组件 onMounted 竞争时只发一次 load_config */
  async function ensureLoaded() {
    if (loaded) return;
    inflight ??= load().finally(() => {
      inflight = null;
    });
    await inflight;
  }

  /** 从关闭链路的兜底快照恢复配置；成功返回 true */
  function restoreFromStash(): boolean {
    try {
      const raw = localStorage.getItem(CONFIG_STASH_KEY);
      if (!raw) return false;
      const parsed = JSON.parse(raw) as Partial<GuiConfigValues>;
      // 只接受字符串/布尔字段，避免损坏数据污染 store
      config.value = { ...config.value };
      for (const key of Object.keys(config.value) as (keyof GuiConfigValues)[]) {
        const v = parsed[key];
        if (typeof v === typeof config.value[key]) {
          (config.value as Record<string, unknown>)[key] = v;
        }
      }
      return true;
    } catch (e) {
      console.warn("恢复配置快照失败:", e);
      try {
        localStorage.removeItem(CONFIG_STASH_KEY);
      } catch {
        /* ignore */
      }
      return false;
    }
  }

  function validateConfig(): string | null {
    const rooms = config.value.rooms_text
      .split(/[,，\n\r]/)
      .map((r) => r.trim())
      .filter((r) => r.length > 0);
    if (rooms.length === 0) {
      return "房间号不能为空";
    }
    for (const room of rooms) {
      if (!/^\d+$/.test(room)) {
        return `房间号格式错误: ${room}`;
      }
      if (parseInt(room, 10) <= 0) {
        return `房间号必须大于 0: ${room}`;
      }
    }
    const threads = parseInt(config.value.thread_count_text, 10);
    if (isNaN(threads) || threads < 1 || threads > MAX_THREAD_COUNT) {
      return `线程数必须在 1-${MAX_THREAD_COUNT} 之间`;
    }
    const totalConnections = rooms.length * threads;
    if (totalConnections > MAX_THREAD_COUNT) {
      return `总连接数（房间数 × 线程数）不能超过 ${MAX_THREAD_COUNT}，当前: ${totalConnections}`;
    }
    return null;
  }

  async function save() {
    // 关闭钩子可能在 load_config 完成前触发：未加载就保存会用默认值覆盖用户配置
    if (!loaded) return;
    // 数值字段统一钳制
    config.value.thread_count_text = clampInt(config.value.thread_count_text, 60, 1, MAX_THREAD_COUNT);
    config.value.reconnect_delay_text = clampInt(config.value.reconnect_delay_text, 8, 1, 3600);
    config.value.task_query_interval_text = clampInt(config.value.task_query_interval_text, 30, 10, 3600);
    // 任务 ID 文本去重 + 排序，避免仅顺序不同的输入被判为变更
    config.value.task_ids_text = normalizeTaskIds(config.value.task_ids_text);
    // 配置验证
    const error = validateConfig();
    if (error) {
      throw new Error(error);
    }
    try {
      await invoke("save_config", { config: config.value });
    } catch (e) {
      // 让调用方（ConfigForm）能提示保存失败，而不是静默丢弃
      throw new Error(`保存配置失败: ${e}`);
    }
    // 回读确认（后端会重新钳制并返回真实落盘值）
    await load();
  }

  return { config, loading, loadError, load, ensureLoaded, save };
});

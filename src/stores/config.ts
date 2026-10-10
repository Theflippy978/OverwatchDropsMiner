import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import type { GuiConfigValues } from "@/lib/types";
import { formatIpcError } from "@/lib/ipc-error";

function clampInt(value: string, defaultVal: number, min: number, max: number): string {
  const n = parseInt(value, 10);
  if (isNaN(n)) return String(defaultVal);
  return String(Math.max(min, Math.min(max, n)));
}

/** 任务 ID 文本去重，**保留原有顺序**（落盘与回显用）。
 *
 * 绝不能排序：B站掉宝任务 ID 是不透明字符串（实测形如
 * `6ERAcwloghvp4i00`，base36、不含日期），字典序排序对它没有任何语义，
 * 只会把用户刚「自动获取」到的顺序整个打乱 —— 用户点一次「保存配置」
 * 就发现 ID 列表变了，误以为配置被换掉（实测 save_config 回读确实重排）。
 * B站页面按时长升序展示，这个顺序是有信息量的。
 *
 * 与后端 `python_sidecar/backend/utils.py` 的 `dedupe_task_ids` 同口径。
 */
export function normalizeTaskIds(value: string): string {
  const parts = value
    .split(",")
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  return Array.from(new Set(parts)).join(",");
}

/** 任务 ID 的指纹规范形：去重 + 排序，仅用于判断「是不是同一批任务」。
 *
 * 顺序不参与身份判定：`a,b` 改成 `b,a` 指向同一批任务，若按原文比较会被
 * 误判成换了任务，连带把「已领奖记账」清空 → 重复领取。
 * 只有这里允许排序。与后端 `utils.normalize_task_ids` 同口径。
 */
export function taskIdsFingerprint(value: string): string {
  return normalizeTaskIds(value)
    .split(",")
    .filter((p) => p.length > 0)
    .sort()
    .join(",");
}

/** 线程数 / 总连接数上限（用户决策值 256）。
 *  四处必须同源，改一处必须同步其余三处：
 *    ① 本常量
 *    ② `python_sidecar/backend/config.py` 的 `MAX_TOTAL_CONNECTIONS`
 *    ③ `python_sidecar/main.py` 的 `MAX_THREAD_COUNT`（由 ② 直接 import，不重复定义）
 *    ④ `ConfigForm.vue` 里线程数输入框的 `max` 属性
 *  历史上这四处出现过 128/256 不一致，后果是「前端允许填 256、保存也成功，
 *  启动时才被 config.validate() 拒」，错误文案来自深层调用，用户无法关联因果
 *  （默认 60 线程 × 3 房间 = 180，正好落在 128 与 256 之间，最易触发）。 */
const MAX_THREAD_COUNT = 256;

/** 关闭链路的兜底配置快照 key（save() 成功后由 load() 清理） */
const CONFIG_STASH_KEY = "config_stash";

/**
 * 配置已落盘，但落盘的任务 ID 集合与用户提交的不一致。
 *
 * 单独一个类型而不是普通 Error：调用方需要区分「保存失败」与
 * 「保存成功但内容被改动」——后者不是错误，只是一个必须让用户知道的
 * 事实（否则用户会以为配置被换了，且无法判断该填哪一批）。
 */
export class TaskIdsAlteredError extends Error {
  constructor(
    readonly submitted: string,
    readonly saved: string
  ) {
    super("任务 ID 已被后端改写");
    this.name = "TaskIdsAlteredError";
  }
}

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
        // 用 formatIpcError 而不是裸 `${e}`：此前这一处连业务前缀都没有，
        // 用户看到的是一句来自 Rust 的原始错误（含命令名与超时秒数）。
        loadError.value = formatIpcError(e, "加载配置失败");
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

  /**
   * 保存配置。
   *
   * 用 save_config **自己的回包**（落盘后的真实值）更新本地 store，
   * 不再走「save → 再发一次 load_config 回读」的两趟往返：两次调用之间
   * 后端任何一次归一化/钳制都会静默改掉用户刚填的内容。
   *
   * `!loaded` 时不能静默 return：那会让「保存配置」按钮永远显示「配置已保存」
   * 而实际什么都没写。抛错让调用方能提示用户。
   */
  async function save() {
    // 关闭钩子可能在 load_config 完成前触发：未加载就保存会用默认值覆盖用户配置
    if (!loaded) {
      throw new Error("配置尚未加载完成，请稍候重试");
    }
    // 数值字段统一钳制
    config.value.thread_count_text = clampInt(config.value.thread_count_text, 60, 1, MAX_THREAD_COUNT);
    config.value.reconnect_delay_text = clampInt(config.value.reconnect_delay_text, 8, 1, 3600);
    config.value.task_query_interval_text = clampInt(config.value.task_query_interval_text, 30, 10, 3600);
    // 任务 ID 去重（保序，见 normalizeTaskIds 的注释）
    config.value.task_ids_text = normalizeTaskIds(config.value.task_ids_text);
    // 配置验证
    const error = validateConfig();
    if (error) {
      throw new Error(error);
    }
    const submittedTaskIds = taskIdsFingerprint(config.value.task_ids_text);
    let saved: GuiConfigValues;
    try {
      saved = await invoke<GuiConfigValues>("save_config", { config: config.value });
    } catch (e) {
      // 让调用方（ConfigForm）能提示保存失败，而不是静默丢弃。
      // 用 formatIpcError 剥离 Rust 内部措辞，只给用户可理解的说明。
      throw new Error(formatIpcError(e, "保存配置失败"));
    }
    config.value = saved;
    loaded = true;
    // 成功落盘后清理关闭链路的兜底快照
    try {
      localStorage.removeItem(CONFIG_STASH_KEY);
    } catch {
      /* 隐私模式/配额异常：忽略 */
    }
    // 任务 ID 集合被后端改动过：必须说清楚，否则用户会以为配置被换掉了。
    // 不抛错（配置确实已落盘），只把差异带出去给 UI 提示。
    if (taskIdsFingerprint(saved.task_ids_text) !== submittedTaskIds) {
      throw new TaskIdsAlteredError(submittedTaskIds, saved.task_ids_text);
    }
  }

  /**
   * 即时切换详细日志级别（勾选即生效，不必等「保存配置」）。
   *
   * 此前唯一的生效路径是 save_config：复选框能勾上、能显示成「已勾选」，
   * 但日志级别没变，用户必须再点一次保存才知道有没有生效 —— 可视状态与
   * 实际行为脱节，比没有这个开关更误导。
   *
   * 与 save() 里的 verbose 是两条独立但同向的路径：勾选立刻生效（内存），
   * 保存负责落盘（重启后仍生效）。
   */
  async function setVerbose(verbose: boolean) {
    config.value.verbose = verbose;
    await invoke("set_verbose", { verbose });
  }

  return { config, loading, loadError, load, ensureLoaded, save, setVerbose };
});

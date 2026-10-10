import { defineStore } from "pinia";
import { ref, computed } from "vue";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { LogEntry } from "@/lib/types";

export interface StoredLog extends LogEntry {
  seq: number;
}

export const useLogsStore = defineStore("logs", () => {
  const logs = ref<StoredLog[]>([]);
  const maxLogs = 5000;
  const filterAccountId = ref<string | null>(null);
  let unlisten: UnlistenFn | null = null;
  let initialized = false;
  let nextSeq = 0;
  const buffer: StoredLog[] = [];
  let flushTimer: number | null = null;

  const filteredLogs = computed(() => {
    if (!filterAccountId.value) return logs.value;
    return logs.value.filter((l) => l.account_id === filterAccountId.value);
  });

  /**
   * 最后一条日志的序号（单调递增，永不重复、永不回退）。
   *
   * 供「新日志到达」这类副作用监听使用 —— **不能监听 logs.length**：
   * 到达 maxLogs 之后每批是「push N 条 + splice 掉 N 条」，length 恒为 5000，
   * 依赖它的 watcher 永远不会再触发（实测：灌满 5000 条后再追加 5000 条，
   * 监听 length 的 watcher 触发 0 次）。LogViewer 的自动滚动正是这样
   * 在长时间运行后永久失效的。
   *
   * 空列表返回 -1：clear() 之后值会从正数变回 -1，watcher 触发一次；
   * 那次是无害的（scrollHeight 归零，滚动位置本就是 0），
   * 且 LogViewer 里另有长度判断兜住。
   */
  const lastSeq = computed(() =>
    logs.value.length > 0 ? logs.value[logs.value.length - 1].seq : -1
  );

  function flush() {
    flushTimer = null;
    if (buffer.length === 0) return;
    // 必须逐条 push：push(...buffer) 展开成实参会撞 V8 的参数上限
    // （约 65k~125k），超限抛 RangeError 且整批日志丢失。
    // 本项目量级可触及：房间数 × 线程数 ≤ 128 条连接，verbose 打开后
    // 每条连接都产日志，而合并窗口只有 120ms。
    for (const entry of buffer) {
      logs.value.push(entry);
    }
    buffer.length = 0;
    const overflow = logs.value.length - maxLogs;
    if (overflow > 0) {
      logs.value.splice(0, overflow);
    }
  }

  function addLog(entry: LogEntry) {
    buffer.push({ ...entry, seq: nextSeq++ });
    if (flushTimer === null) {
      flushTimer = window.setTimeout(flush, 120);
    }
  }

  function clear() {
    buffer.length = 0;
    if (flushTimer !== null) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    logs.value = [];
  }

  function clearByAccount(accountId: string) {
    // 只清该账号：缓冲区里其它账号的日志要保留，不能被连带丢弃
    if (buffer.length > 0) {
      const kept = buffer.filter((l) => l.account_id !== accountId);
      buffer.length = 0;
      buffer.push(...kept);
      if (kept.length > 0 && flushTimer === null) {
        flushTimer = window.setTimeout(flush, 120);
      }
    }
    logs.value = logs.value.filter((l) => l.account_id !== accountId);
  }

  function setFilter(accountId: string | null) {
    filterAccountId.value = accountId;
  }

  async function initListeners() {
    if (initialized) return;
    initialized = true;
    try {
      unlisten = await listen<LogEntry>("log-entry", (event) => {
        addLog(event.payload);
      });
    } catch (e) {
      initialized = false;
      console.error("注册日志监听失败:", e);
    }
  }

  function dispose() {
    if (unlisten) {
      unlisten();
      unlisten = null;
    }
    initialized = false;
    clear();
  }

  return { logs, filteredLogs, lastSeq, filterAccountId, addLog, clear, clearByAccount, setFilter, initListeners, dispose };
});

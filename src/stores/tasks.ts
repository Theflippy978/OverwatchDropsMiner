import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { useConfigStore } from "@/stores/config";

interface Reward {
  name: string;
  icon: string;
  count: number;
}

interface CheckPoint {
  sid: string;
  alias: string;
  status: number;
  is_completed: boolean;
  cur_value: number;
  limit_value: number;
  award_name: string;
  award_count: number;
}

interface TaskItem {
  task_id: string;
  title: string;
  progress: number;
  target: number;
  status: string;
  rewards: Reward[];
  check_points: CheckPoint[];
}

interface AccountTasks {
  tasks: TaskItem[];
  text: string;
  error: string;
  cur: number;
  limit: number;
  /** 已成功领取（或服务端已领取）的具体奖励任务 ID（check_point.sid 维度） */
  handledIds: Set<string>;
  /** 已下发领取、等待结果的 ID，避免同一 ID 被重复下发 */
  pendingIds: Set<string>;
  refreshing: boolean;
  refreshQueued: boolean;
  claiming: boolean;
  claimQueued: boolean;
}

/** 具体奖励任务（check_point.sid 优先，缺失时回落到 task_id） */
interface ClaimUnit {
  id: string;
  /** 服务端已领取（check_point.status === 6） */
  claimed: boolean;
  /** 已完成、可领取 */
  completed: boolean;
}

/**
 * 把任务列表摊平成“具体奖励任务 ID”维度。
 * 与原始 Qt 实现的 classify_auto_claim_task_ids 对齐：
 * 有 check_points 时按 sid 分类，否则回落到任务级 task_id。
 */
function collectClaimUnits(tasks: TaskItem[]): ClaimUnit[] {
  const units: ClaimUnit[] = [];
  for (const task of tasks) {
    const concrete = (task.check_points ?? [])
      .map((point) => ({ id: (point.sid ?? "").trim(), point }))
      .filter((entry) => entry.id.length > 0);
    if (concrete.length > 0) {
      for (const { id, point } of concrete) {
        units.push({ id, claimed: point.status === 6, completed: !!point.is_completed });
      }
      continue;
    }
    const fallbackId = (task.task_id ?? "").trim();
    if (fallbackId) {
      units.push({
        id: fallbackId,
        claimed: task.status === "已领取",
        completed: task.status === "已完成",
      });
    }
  }
  return units;
}

export const useTasksStore = defineStore("tasks", () => {
  const configStore = useConfigStore();
  const accountTasksMap = ref<Record<string, AccountTasks>>({});

  function getAccountTasks(accountId: string): AccountTasks {
    if (!accountTasksMap.value[accountId]) {
      accountTasksMap.value = {
        ...accountTasksMap.value,
        [accountId]: {
          tasks: [],
          text: "",
          error: "",
          cur: 0,
          limit: 0,
          handledIds: new Set(),
          pendingIds: new Set(),
          refreshing: false,
          refreshQueued: false,
          claiming: false,
          claimQueued: false,
        },
      };
    }
    return accountTasksMap.value[accountId];
  }

  async function refreshTasks(accountId: string, manual = true) {
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.refreshing) {
      accountTasks.refreshQueued = true;
      if (manual) {
        accountTasks.text = "已有刷新进行中，已排队下一次刷新...";
      }
      return;
    }
    accountTasks.refreshing = true;
    accountTasks.error = "";
    try {
      const result = await invoke<{ tasks: TaskItem[]; text: string }>(
        "refresh_tasks",
        { accountId }
      );
      accountTasks.tasks = result.tasks;
      accountTasks.text = result.text;
      if (result.tasks.length > 0) {
        const best = result.tasks.reduce((a, b) => (a.target > b.target ? a : b));
        accountTasks.cur = best.progress;
        accountTasks.limit = best.target;
      }

      // 按 sid 维度重算 handled/pending（对齐原项目 difference_update(incomplete)）
      const units = collectClaimUnits(result.tasks ?? []);
      const incomplete = new Set<string>();
      const completed = new Set<string>();
      for (const unit of units) {
        if (unit.claimed) continue;
        if (unit.completed) completed.add(unit.id);
        else incomplete.add(unit.id);
      }
      accountTasks.handledIds = new Set(
        [...accountTasks.handledIds].filter((id) => !incomplete.has(id))
      );
      // 已不再“完成待领取”的 ID 出队，避免 pending 永久占位
      accountTasks.pendingIds = new Set(
        [...accountTasks.pendingIds].filter((id) => completed.has(id))
      );

      maybeAutoClaim(accountId);
    } catch (e) {
      accountTasks.error = `刷新任务失败: ${e}`;
    } finally {
      accountTasks.refreshing = false;
      if (accountTasks.refreshQueued) {
        accountTasks.refreshQueued = false;
        void refreshTasks(accountId, manual);
      }
    }
  }

  function maybeAutoClaim(accountId: string) {
    if (!configStore.config.auto_claim_rewards) return;
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.claiming) return;

    const toClaim = collectClaimUnits(accountTasks.tasks ?? [])
      .filter((unit) => unit.completed)
      .map((unit) => unit.id)
      .filter(
        (id) => !accountTasks.handledIds.has(id) && !accountTasks.pendingIds.has(id)
      );
    if (toClaim.length === 0) return;

    // 先入队 pending，再下发，保证同一 ID 不会在一个周期内被重复下发
    accountTasks.pendingIds = new Set([...accountTasks.pendingIds, ...toClaim]);
    accountTasks.text = "检测到任务完成，正在自动领取奖励...";
    void claimRewards(accountId, true);
  }

  async function claimRewards(accountId: string, automatic = false) {
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.claiming) {
      accountTasks.claimQueued = true;
      return;
    }
    accountTasks.claiming = true;
    accountTasks.error = "";
    // 本次下发涉及的具体奖励任务 ID（用于结果回来后出队）
    const requested = new Set(accountTasks.pendingIds);
    try {
      const result = await invoke<{
        success: boolean;
        results: Array<{
          task_id: string;
          reward_name: string;
          success: boolean;
          skipped: boolean;
          message: string;
        }>;
        text: string;
      }>("claim_rewards", { accountId });

      const newHandled = new Set(accountTasks.handledIds);
      for (const item of result.results) {
        const id = (item.task_id ?? "").trim();
        if (!id) continue;
        requested.add(id);
        if (item.success || item.skipped) {
          newHandled.add(id);
        }
      }
      accountTasks.handledIds = newHandled;
      // 已下发的 ID 一律出队（对齐原项目 pending.difference_update(auto_task_ids)）
      accountTasks.pendingIds = new Set(
        [...accountTasks.pendingIds].filter((id) => !requested.has(id))
      );
      accountTasks.text = (automatic ? "自动领取\n" : "") + result.text;
      if (result.results.length > 0) {
        await refreshTasks(accountId, false);
      }
    } catch (e) {
      // 失败时同样出队，交给下一次刷新重试（与原项目一致）
      accountTasks.pendingIds = new Set(
        [...accountTasks.pendingIds].filter((id) => !requested.has(id))
      );
      accountTasks.error = `${automatic ? "自动领取" : "领取奖励"}失败: ${e}`;
    } finally {
      accountTasks.claiming = false;
      if (accountTasks.claimQueued) {
        accountTasks.claimQueued = false;
        void claimRewards(accountId, automatic);
      }
    }
  }

  function clearAccountTasks(accountId: string) {
    delete accountTasksMap.value[accountId];
  }

  return {
    accountTasksMap,
    getAccountTasks,
    refreshTasks,
    claimRewards,
    clearAccountTasks,
  };
});

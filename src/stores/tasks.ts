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
  handledIds: Set<string>;
  pendingIds: Set<string>;
  refreshing: boolean;
  refreshQueued: boolean;
  claiming: boolean;
  claimQueued: boolean;
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
    if (!accountTasks.claiming) {
      const pendingClaim = accountTasks.tasks.some(
        (t) => t.status === "已完成" && !accountTasks.handledIds.has(t.task_id.trim())
      );
      if (pendingClaim) {
        accountTasks.text = "检测到任务完成，正在自动领取奖励...";
        void claimRewards(accountId, true);
      }
    }
  }

  async function claimRewards(accountId: string, automatic = false) {
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.claiming) {
      accountTasks.claimQueued = true;
      return;
    }
    accountTasks.claiming = true;
    accountTasks.error = "";
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
        if ((item.success || item.skipped) && item.task_id.trim()) {
          newHandled.add(item.task_id.trim());
        }
      }
      accountTasks.handledIds = newHandled;
      accountTasks.text = (automatic ? "自动领取\n" : "") + result.text;
      if (result.results.length > 0) {
        await refreshTasks(accountId, false);
      }
    } catch (e) {
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

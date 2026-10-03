import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { useConfigStore } from "@/stores/config";
import type { TaskItem } from "@/lib/types";

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
  /** 排队的那次刷新是否来自手动点击（累积意图，防自动刷新吞掉手动刷新） */
  queuedManual: boolean;
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
  /** 已删除账号的 id：防止删除后在途的 refreshTasks/claimRewards 回来时
      通过 getAccountTasks 为已删除账号重建条目（既无人驱动刷新也无人再删，
      每次删账号累加一份泄漏） */
  const deletedIds = new Set<string>();

  function createAccountTasks(): AccountTasks {
    return {
      tasks: [],
      text: "",
      error: "",
      cur: 0,
      limit: 0,
      handledIds: new Set(),
      pendingIds: new Set(),
      refreshing: false,
      refreshQueued: false,
      queuedManual: false,
      claiming: false,
      claimQueued: false,
    };
  }

  function getAccountTasks(accountId: string): AccountTasks {
    if (!accountTasksMap.value[accountId]) {
      accountTasksMap.value = {
        ...accountTasksMap.value,
        [accountId]: createAccountTasks(),
      };
    }
    return accountTasksMap.value[accountId];
  }

  /** 纯读取：不在渲染期写响应式状态。
      computed getter 里调用 getAccountTasks 会在求值过程中整体替换
      accountTasksMap.value，把自己重新置脏，并连带失效其它订阅该 map 的
      渲染 effect（"Maximum recursive updates exceeded" 前兆）。 */
  function peekAccountTasks(accountId: string): AccountTasks | undefined {
    return accountTasksMap.value[accountId];
  }

  async function refreshTasks(accountId: string, manual = true) {
    if (deletedIds.has(accountId)) return;
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.refreshing) {
      // 排队时累积「手动」意图：refreshQueued 只是布尔，若自动刷新在途
      // 而用户点了手动刷新，重跑会退化成 manual=false，
      // 「已有刷新进行中」提示永不出现，UI 表现为点了没反应。
      accountTasks.refreshQueued = true;
      if (manual) {
        accountTasks.queuedManual = true;
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
      // 账号在请求在途期间被删除：丢弃结果，不要重建条目
      if (deletedIds.has(accountId)) return;
      if (result.tasks.length === 0) {
        // 空列表时清零，避免出现「任务列表空 + 进度条显示上次进度」的矛盾态
        accountTasks.cur = 0;
        accountTasks.limit = 0;
      } else {
        const best = result.tasks.reduce((a, b) => (a.target > b.target ? a : b));
        accountTasks.cur = best.progress;
        accountTasks.limit = best.target;
      }

      // 按 sid 维度重算 handled/pending（对齐原项目 difference_update(incomplete)）
      const units = collectClaimUnits(result.tasks ?? []);
      const incomplete = new Set<string>();
      const completed = new Set<string>();
      const claimed = new Set<string>();
      for (const unit of units) {
        // 同一 sid 可能出现在多个任务里（其一已完成、其一已领取）。
        // 三档互斥：claimed 最高优先，其次 completed，最后 incomplete。
        // 若同一 id 同时进 completed 与 incomplete，
        // 后续用 incomplete 剔除 handledIds 会把已领过的奖励重新变成可领。
        if (unit.claimed) claimed.add(unit.id);
        else if (unit.completed) completed.add(unit.id);
        else incomplete.add(unit.id);
      }
      // 已领取同样应退出「完成待领取」集合，避免 pending 永久占位
      for (const id of claimed) completed.delete(id);
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
        const rerunManual = accountTasks.queuedManual;
        accountTasks.queuedManual = false;
        void refreshTasks(accountId, rerunManual);
      }
    }
  }

  function maybeAutoClaim(accountId: string) {
    if (!configStore.config.auto_claim_rewards) return;
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.claiming) return;

    // 关键：必须同时排除 claimed。
    // 后端 models.py:48 的 is_completed 把 status===6（已领取）也算作完成，
    // 所以已领取的奖励同时满足 claimed 与 completed；若只过滤 completed，
    // 冷启动时 handledIds 为空，会对全部历史已领奖励下发一次无效 claim。
    // 上游原项目 classify_auto_claim_task_ids 用 status==6 优先归入 claimed，正是为此。
    const toClaim = collectClaimUnits(accountTasks.tasks ?? [])
      .filter((unit) => unit.completed && !unit.claimed)
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
    if (deletedIds.has(accountId)) return;
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
      // 先解除 claiming 再做嵌套刷新：否则 refreshTasks 内部的
      // maybeAutoClaim 会被「本轮正在领取」挡住，本轮新完成的任务
      // 要多等一个轮询周期（最短 10s）才被领取。
      accountTasks.claiming = false;
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
    deletedIds.add(accountId);
    const next = { ...accountTasksMap.value };
    delete next[accountId];
    accountTasksMap.value = next;
  }

  /** 账号重新被添加时清掉删除标记（同一 id 再次出现是合法复用） */
  function reviveAccountTasks(accountId: string) {
    deletedIds.delete(accountId);
  }

  return {
    accountTasksMap,
    getAccountTasks,
    peekAccountTasks,
    refreshTasks,
    claimRewards,
    clearAccountTasks,
    reviveAccountTasks,
  };
});

import { defineStore } from "pinia";
import { ref } from "vue";
import { invoke } from "@tauri-apps/api/core";
import { useConfigStore, taskIdsFingerprint } from "@/stores/config";
import { TASK_STATUS_CLAIMED } from "@/lib/types";
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
  /** 本轮（含排队轮）真正结束时 resolve。调用方靠它保证后续同步跑在新数据上 */
  refreshSettled: Promise<void> | null;
  claiming: boolean;
  claimQueued: boolean;
  /**
   * 上次重算记账时所用的任务 ID 集合（已归一化）。
   *
   * 掉宝任务 ID **每日不变、只有进度归零**。所以「昨天领过的 sid」
   * 今天会以同一个 id 再次出现，而服务端此时尚未把 status 置为已领取，
   * 于是今天完成的任务被 `handledIds.has(id)` 判成已处理 → 当天不再自动领取。
   * 指纹变了就说明换了一批任务，此时旧的记账全部作废。
   */
  taskIdsKey: string;
}

/** 具体奖励任务（check_point.sid 优先，缺失时回落到 task_id） */
interface ClaimUnit {
  id: string;
  /** 服务端已领取（TASK_STATUS_CLAIMED） */
  claimed: boolean;
  /** 已完成、可领取 */
  completed: boolean;
}

/**
 * 把任务列表摊平成“具体奖励任务 ID”维度。
 * 有 check_points 时按每个检查点的 sid 分类，否则回落到任务级 task_id ——
 * 领取的最小粒度是检查点而不是任务。
 */
function collectClaimUnits(tasks: TaskItem[]): ClaimUnit[] {
  const units: ClaimUnit[] = [];
  for (const task of tasks) {
    const concrete = (task.check_points ?? [])
      .map((point) => ({ id: (point.sid ?? "").trim(), point }))
      .filter((entry) => entry.id.length > 0);
    if (concrete.length > 0) {
      for (const { id, point } of concrete) {
        units.push({
          id,
          claimed: point.status === TASK_STATUS_CLAIMED,
          completed: !!point.is_completed,
        });
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
      refreshSettled: null,
      claiming: false,
      claimQueued: false,
      taskIdsKey: "",
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

  /**
   * 执行一轮刷新。settle 由调用方传入，且**整条链（本轮 + 全部排队轮）共用
   * 同一个 settle**：只有链上最后一轮结束时才兑现。
   *
   * 不能每轮都新建一个 promise 覆盖 accountTasks.refreshSettled —— 排队方
   * await 的是它进入时读到的那个旧 promise，而旧 promise 的 resolve 只在
   * 「没有排队轮」的分支里被调用。一旦出现排队轮，先前的等待方就永远挂住，
   * TaskProgress.handleRefresh 里 await 之后的 fetchStatus 永不执行。
   */
  async function runRound(accountId: string, settle: () => void): Promise<void> {
    const accountTasks = getAccountTasks(accountId);
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

      // 任务 ID 指纹比对。必须在 handledIds 重算**之前**，且两个集合一起清：
      // 昨日残留的 pendingIds 会把新任务挡在 toClaim 之外。
      // 必须是「清空后重算」而非「合并」—— 合并的话昨日 id 依然在集合里，
      // 今天完成时仍被判为已处理，等于没修。
      // 用 taskIdsFingerprint（去重+排序）而非展示用的去重函数：顺序不参与
      // 「是不是同一批任务」的判定，`a,b` 改成 `b,a` 不该清空记账。
      const currentKey = taskIdsFingerprint(configStore.config.task_ids_text);
      if (accountTasks.taskIdsKey !== currentKey) {
        accountTasks.taskIdsKey = currentKey;
        accountTasks.handledIds = new Set();
        accountTasks.pendingIds = new Set();
      }

      // 按 sid 维度重算 handled/pending：进行中的检查点要退出「已处理」，
      // 否则周期任务重置后当天不会再自动领取。
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
        // 必须 await 并传递同一个 settle：不 await 会让调用方在数据仍旧时
        // 醒来，不传递则排队轮的结束信号无法回到最初的等待方。
        await runRound(accountId, settle);
      } else {
        settle();
      }
    }
  }

  /**
   * 刷新任务进度。返回的 Promise 在**本轮（含全部排队轮）真正结束**后才 resolve。
   *
   * 必须返回可等待的完成信号：调用方（TaskProgress.handleRefresh）拿到结果后
   * 紧接着要拉一次 get_account_status 来同步顶部四字段与掉宝进度条。
   * 原实现「已在刷新就直接 return」，于是那次同步跑在**旧数据**上 ——
   * 用户点手动刷新，看到的仍是刷新前的进度。
   */
  async function refreshTasks(accountId: string, manual = true): Promise<void> {
    if (deletedIds.has(accountId)) return;
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.refreshing) {
      // 排队时若来自手动点击，给出可见反馈；refreshQueued 是布尔，
      // 连点多次与一次等价，重跑只会有一次。
      accountTasks.refreshQueued = true;
      if (manual) {
        accountTasks.text = "已有刷新进行中，已排队下一次刷新...";
      }
      // 等当前这条链的结束信号；由链上最后一轮兑现。
      await accountTasks.refreshSettled;
      return;
    }
    let settle!: () => void;
    accountTasks.refreshSettled = new Promise<void>((resolve) => {
      settle = resolve;
    });
    await runRound(accountId, settle);
  }

  function maybeAutoClaim(accountId: string) {
    if (!configStore.config.auto_claim_rewards) return;
    const accountTasks = getAccountTasks(accountId);
    if (accountTasks.claiming) return;

    // 关键：必须同时排除 claimed。
    // 后端 client_parts/models.py 的 is_completed 把 status===6（已领取）也算作完成，
    // 所以已领取的奖励同时满足 claimed 与 completed；若只过滤 completed，
    // 冷启动时 handledIds 为空，会对全部历史已领奖励下发一次无效 claim。
    // collectClaimUnits 用 claimed 优先于 completed 的三档分类，正是为此。
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
      // 只排队一次：领取一轮动辄十几秒，用户会连点。claimQueued 是布尔，
      // 连点 N 次与点 1 次等价 —— 否则 N 次点击排成 N 轮领取，
      // 每轮都重新下发一遍 request，多账号时足以压垮 sidecar。
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
          /** B站任务状态，领取成功为 TASK_STATUS_CLAIMED。
              sidecar 不缓存检查点状态，随后的 refresh_tasks 拿回来的仍是
              TASK_STATUS_COMPLETED，UI 要显示「已领取」只能靠这里。 */
          status: number;
          message: string;
        }>;
        text: string;
      }>("claim_rewards", { accountId });

      // handledIds 是「本会话已领取」的权威集合，与 refreshTasks 里的
      // 服务端字段取并集而非互相覆盖：B站接口对已领检查点仍可能返回 3，
      // 若每次刷新都以服务端为准，本地刚领取成功的事实立刻被抹掉。
      const newHandled = new Set(accountTasks.handledIds);
      for (const item of result.results) {
        const id = (item.task_id ?? "").trim();
        if (!id) continue;
        requested.add(id);
        if (item.status === TASK_STATUS_CLAIMED || item.success || item.skipped) {
          newHandled.add(id);
        }
      }
      accountTasks.handledIds = newHandled;
      // 已下发的 ID 一律出队：它们要么已成功、要么已记入 handledIds，
      // 留着会让 pendingIds 永久占位、挡住后续重试。
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

/** 挂宝进度卡「该显示哪些任务」的**纯逻辑**（零 import、无 DOM 依赖）。
 *
 *  为什么单独一个文件：与 `nav-geometry.ts` 同一个理由 —— Node 22.6+ 能直接
 *  `import` `.ts`（类型剥离），只要本文件不 import 任何东西，外部 `.mjs`
 *  脚本就能**加载真代码**来断言。判据若留在 `TaskProgress.vue` 里，
 *  脚本就只能把它复刻一遍再测 —— 那测的是复刻品，真代码改坏了它照样绿。
 *
 *  因此本文件**必须保持零 import**：连类型也不要 import，
 *  下面两个 interface 只声明本文件用到的字段（结构类型，
 *  `lib/types.ts` 的 TaskItem / CheckPoint 天然满足），
 *  这样调用方照常传真实对象，而本文件仍然可被 Node 直接加载。
 */

/** 时长任务标题正则：与后端 `browser/task_presenter.py` 的 DURATION_TASK_RE 同源。
 *  后端用宽松前缀 ^(.+?)\d+分钟$，此处必须同样宽松，
 *  否则「累计观看60分钟」这类标题后端会成组、前端当普通任务，两边形态不一致。 */
export const DURATION_TASK_RE = /^.+?\d+分钟$/;

export interface ViewCheckpoint {
  alias: string;
  cur_value: number;
  limit_value: number;
}

export interface ViewTask {
  title: string;
  progress: number;
  target: number;
  check_points: ViewCheckpoint[];
}

/** 检查点明细是否值得单独展示（与后端 _has_meaningful_checkpoints 同一口径）。
 *
 *  多个检查点必然值得展示。只有一个时，若它的别名与两个数值都与任务本身相同，
 *  那它就是任务行的一面镜子 —— 再列一行只会把同一个数字复读一遍。
 *  实测「计时器」任务正是这种单检查点全等情况。 */
export function hasMeaningfulCheckPoints(task: ViewTask): boolean {
  const cps = task.check_points;
  if (!cps || cps.length === 0) return false;
  if (cps.length > 1) return true;
  const cp = cps[0];
  return (
    cp.alias !== task.title ||
    cp.cur_value !== task.progress ||
    cp.limit_value !== task.target
  );
}

/** 本活动里「该显示」的任务列表。
 *
 *  两类被排除：
 *  ① 标题匹配 DURATION_TASK_RE 的阶梯任务 —— 它们被聚合成时长组，
 *     由另一条渲染分支消费，列在这里会重复出现。
 *  ② **同一指标的汇总视图**：B 站在阶梯任务之外还并列给一个总目标任务
 *     （实测标题「计时器」，只带一个与任务自身全等的镜像检查点，
 *     progress/target 与阶梯任务同为 0/600）。它表达的是同一件事，
 *     单独成卡会让用户以为要多挂一个任务，还白占一张卡的高度。
 *
 *  判据用结构而不是标题词。⚠ 这里有个踩过的坑：阶梯的「60分钟」在
 *  **check_point 别名**上，任务标题只是「观看直播」，所以 DURATION_TASK_RE
 *  对这两个任务都不命中 —— 早先一版拿「target 命中时长组某一档」当判据，
 *  而时长组恒为空集，过滤完全失效（用户实测「计时器还在」）。
 *
 *  ② 的三条判据必须同时成立才隐藏：本任务无有意义检查点、
 *  另有一个任务有有意义检查点、两者 progress 与 target 都相同。
 *  缺任何一条都不隐藏，所以「两个恰好同进度的独立任务」不会同时被藏 ——
 *  只有"汇总视图 vs 明细任务"这种组合才满足。
 *
 *  隐藏只影响展示，不影响领取：后端 receive_all_mission_rewards 走
 *  normalize_task_ids 的全量 task_ids，不读这个列表。
 *
 *  泛型让调用方拿回自己传进来的类型（`TaskItem[]` 而不是 `ViewTask[]`），
 *  否则模板里 `v-for` 出来的字段会被收窄成 interface 里声明的那几个。 */
export function visibleTasks<T extends ViewTask>(tasks: T[]): T[] {
  const detailed = tasks.filter(
    (t) => !DURATION_TASK_RE.test(t.title) && hasMeaningfulCheckPoints(t),
  );
  return tasks.filter((task) => {
    if (DURATION_TASK_RE.test(task.title)) return false;
    if (hasMeaningfulCheckPoints(task)) return true;
    return !detailed.some(
      (d) => d !== task && d.progress === task.progress && d.target === task.target,
    );
  });
}

/**
 * 等宽文字进度条，与后端 `browser/task_presenter.py` 的 `_progress_bar` 同口径。
 *
 * 为什么后端已经有纯文本进度（`format_task_progress` 的输出）还要在前端再画一份：
 * 后端那份只存在于 `refresh_tasks` 响应的 `text` 字段里，而 UI 早已改成结构化
 * 胶囊渲染、不再展示那段纯文本。两份并存时**必须口径一致**，否则用户会看到
 * 同一个任务在两处的百分比/格数对不上。所以宽度与填充算法都对齐后端常量
 * `BAR_WIDTH = 20`，改一侧必须改另一侧。
 */

/** 与后端 `browser/task_presenter.BAR_WIDTH` 同源 */
export const BAR_WIDTH = 20;

/**
 * 生成进度条的两段文本，供模板分别上色。
 *
 * 返回两段而不是整串：整串只能单色，而「已填充」与「未填充」的区分
 * 是这个控件唯一的视觉信息。
 *
 * **两端必须带方括号**（`[####------]`），与后端
 * `browser/task_presenter.py` 的 `"[" + "#" * filled + "-" * rest + "]"` 逐字对齐。
 * 方括号不只是装饰：没有它时满格进度条的 `#` 会紧贴右边的 `60/60`，
 * 读起来像一串连续字符；有了它才有明确边界，用户能一眼看出「这是一条进度条，
 * 而且已经到头」。
 */
export function textProgressBar(
  percent: number,
  width: number = BAR_WIDTH
): { filled: string; empty: string; percent: number } {
  // 必须**截断**而不是四舍五入：后端 browser/task_presenter.py 的
  // `_progress_percent` 用 int()（截断），TaskProgress.percentOf /
  // percentOfCheckpoint 用 Math.floor（同为截断）。三处口径必须一致，
  // 否则 999/1000 会显示成「100%」并画满整条，而任务其实尚未完成。
  //
  // 当前调用方传入的已经是 floor 过的整数，所以 Math.round 在这里恰好
  // 是恒等运算、看不出差异 —— 但那是巧合，不是契约。写成 floor 让
  // 「直接传小数」的新调用方也得到正确结果，与本函数开头的同口径声明一致。
  const safe = Math.max(0, Math.min(100, Math.floor(percent)));
  const filledCount = Math.floor((width * safe) / 100);
  return {
    filled: "#".repeat(filledCount),
    empty: "-".repeat(width - filledCount),
    percent: safe,
  };
}
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
  const safe = Math.max(0, Math.min(100, Math.round(percent)));
  const filledCount = Math.floor((width * safe) / 100);
  return {
    filled: "#".repeat(filledCount),
    empty: "-".repeat(width - filledCount),
    percent: safe,
  };
}

/**
 * 进度条的完整文本（含两端方括号）。
 *
 * 单独给出而不是让调用方自己拼：方括号一旦漏在某处，两端口径就又不一致了，
 * 而这种不一致在界面上表现为「有的行有括号有的没有」，极难定位。
 */
export function textProgressBarText(
  percent: number,
  width: number = BAR_WIDTH
): string {
  const { filled, empty } = textProgressBar(percent, width);
  return `[${filled}${empty}]`;
}
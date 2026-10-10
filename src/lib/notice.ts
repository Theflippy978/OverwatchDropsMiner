import { onUnmounted, ref } from "vue";

/**
 * 行内提示的自动消失时长。
 *
 * 3 秒的来历：够读完一句「配置已保存，但任务 ID 与提交的不一致，已按后端实际
 * 落盘的值填回：xxx」这种最长的提示，又不至于让用户以为程序没响应。
 */
export const NOTICE_AUTO_HIDE_MS = 3000;

/**
 * 错误提示的自动消失时长。
 *
 * 比成功提示长得多（10s），理由是两者的「错过成本」不对称：
 *   * 成功提示晚几秒消失没有代价，用户已经知道操作成功了；
 *   * 错误提示一旦消失就**再也查不到** —— 本项目没有 toast 历史面板，
 *     也没有把行内错误写进日志，用户若此刻正在看浏览器（挂宝场景的常态），
 *     回来时只看到「什么都没发生过」，无从判断刚才那步到底成没成。
 *
 * 仍会自动消失而不是常驻：常驻的失败提示会把配置卡下方的说明行与
 * 后续内容一直往下挤，且用户下次操作时它会被新提示顶掉 ——
 * 那种「看起来还在、其实已经过期」的状态比消失更误导。
 */
export const ERROR_NOTICE_AUTO_HIDE_MS = 10000;

/**
 * 页面级行内提示：3 秒后自动消失。
 *
 * 为什么需要它：此前 8 处提示（保存/导入/导出结果、测试通知结果、自动获取失败、
 * 详细日志切换失败、任务刷新失败、领取前置校验、状态查询连续失败、启动/停止失败）
 * 全是裸 `ref`，只在「下一次同类操作」时才被覆盖或清空。成功提示「配置已保存」
 * 会一直挂在配置卡底部，把用户真正关心的错误挤到下面去；失败提示则和配置的
 * 提示混在同一处分不清。用户要求「显示 3 秒后就自动关闭，不要一直显示在这里」。
 *
 * **只用于页面级行内提示，弹窗内的错误一律不用它**：
 * `ConfirmDialog` / `QrLoginDialog` / `UpdateDialog` / 添加·重命名·捕获三个
 * Dialog / `InputContextMenu` 打开时有全屏遮罩吃掉指针事件，提示自动消失后
 * 用户既看不到结果也点不掉按钮，只会认为程序卡死（`AccountList.vue` 里
 * `addError` / `renameError` / `captureError` / `removeError` 的注释同此）。
 */
export function useTimedNotice(delayMs: number = NOTICE_AUTO_HIDE_MS) {
  const text = ref("");
  const isError = ref(false);
  let timer: number | null = null;

  function clear() {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    text.value = "";
    // isError 必须一并复位：它是「当前这条提示是不是错误」的状态，
    // 提示已清空却留着 true 会让后续任何读它的逻辑拿到过期结论
    // （例如「先 clear 再按条件 show」的写法会继承上一次的错误态）。
    isError.value = false;
  }

  /**
   * 显示一条提示并重置倒计时。
   *
   * 重置而不是叠加：`ConfigForm` 里保存与测试通知共用同一条反馈位，
   * 连点两下「保存配置」时若各自起一个定时器，先那条的定时器会在
   * 3 秒后把后一条的提示一起清掉。
   *
   * 错误提示的停留时长单独放宽到 ERROR_NOTICE_AUTO_HIDE_MS（见其注释）：
   * 调用方传进来的 delayMs 仍是「成功提示」的时长，取两者较大值，
   * 这样既不会把显式传了更长时长的调用方压回去，也不会让错误提示
   * 沿用 3 秒这种「来不及读」的时长。
   */
  function show(message: string, error = false) {
    if (timer !== null) clearTimeout(timer);
    text.value = message;
    isError.value = error;
    const holdMs = error ? Math.max(delayMs, ERROR_NOTICE_AUTO_HIDE_MS) : delayMs;
    timer = window.setTimeout(() => {
      timer = null;
      text.value = "";
      isError.value = false;
    }, holdMs);
  }

  // 组件卸载时清掉未触发的定时器：否则会对已卸载组件的 ref 写值，
  // 在 devtools 的定时器列表里也会留一条悬挂记录。
  onUnmounted(clear);

  return { text, isError, show, clear };
}
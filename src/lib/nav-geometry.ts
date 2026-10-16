/** 方向键区域导航的**纯逻辑**（零 import、无 DOM 依赖）。
 *
 *  为什么单独拆出来：本项目没有 JS 测试运行器，而 Node 22.6+ 能直接
 *  `import` `.ts`（类型剥离）—— 只要这个模块不 import 任何东西，
 *  外部的 `.mjs` 脚本就能**加载真代码**来断言。
 *  反过来，若模块带了 DOM 依赖，脚本就只能把逻辑**复刻一遍**再测 ——
 *  那测的是复刻品，真代码改坏了它照样绿。
 *
 *  因此本文件**必须保持零 import**。DOM 相关的胶水全在 `region-nav.ts`。
 */

/** 一个停靠点相对视口的矩形（只取判定需要的四个边）。 */
export interface StopBox {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

/** 输入类控件的 `type` —— 除这些以外，`<input>` 都按「文本录入」对待，
 *  方向键保持原生（含用户点名要保住的 `number`）。 */
const NON_TEXT_INPUT_TYPES = new Set([
  "button",
  "submit",
  "reset",
  "checkbox",
  "radio",
  "file",
  "image",
  "color",
  "range",
]);

/** 焦点是否落在「方向键必须保持原生」的控件上。
 *
 *  依据用户确认的设计原话：
 *  「焦点在输入框内时保持原生行为、不跨区；number 输入框（线程数 / 重连延迟 /
 *    查询间隔）的 ↑/↓ 仍用于增减数值，文本光标 ←/→ 正常；
 *    只有焦点在按钮 / 复选项 / 账号行上时才跨区。」
 *
 *  所以 `input[type=number]` **必须**算文本录入 —— 它正是用户点名要保住的三个控件。
 *  而 `type=checkbox/radio` 这类按钮型 input 不算（reka 的 Checkbox 渲染成
 *  `button[role=checkbox]`，本来也走不到这里），它们应当参与导航。
 */
export function isTextEntry(
  tagName: string,
  inputType: string | null,
  isContentEditable: boolean,
): boolean {
  const tag = tagName.toUpperCase();
  if (tag === "TEXTAREA") return true;
  // select 的 ↑/↓ 是切换选项，也是原生行为，不能抢
  if (tag === "SELECT") return true;
  if (isContentEditable) return true;
  if (tag !== "INPUT") return false;
  return !NON_TEXT_INPUT_TYPES.has((inputType ?? "text").toLowerCase());
}

/** 竖直方向的重叠高度（可为负 = 不相交）。 */
function overlapY(a: StopBox, b: StopBox): number {
  return Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
}

/** 两个停靠点是否属于**同一行**。
 *
 *  判据用「重叠高度 ≥ 较矮那个的一半」而不是绝对像素：行高随字号与 DPI 变
 *  （本项目吃过「computed style 全绿但像素是错的」那一刀），比例判据不依赖具体像素。
 *
 *  0.5 的来历：一行里同时有 32px 输入框、20px 标签、28px 按钮时，两两重叠都在
 *  20px 以上（占较矮者 70%+）；而**相邻两行之间是负重叠**（行间有 gap）。
 *  0.5 离两侧都远，不会在临界处抖动。 */
export function sameRow(a: StopBox, b: StopBox): boolean {
  const shorter = Math.min(a.bottom - a.top, b.bottom - b.top);
  if (shorter <= 0) return false;
  return overlapY(a, b) >= shorter * 0.5;
}

/** 按 **DOM 顺序**把停靠点分组成行。
 *
 *  只与「上一行的最后一个」比较，不与所有已见行比较：DOM 顺序在本项目里就是
 *  视觉顺序（左→右、上→下）。跨行比较会把「上一行最后一个」与「下一行第一个」
 *  在元素较高时误判成同行。
 *
 *  返回值是**索引**分组，不是元素分组 —— 纯逻辑不碰 DOM。 */
export function groupIntoRows(boxes: StopBox[]): number[][] {
  const rows: number[][] = [];
  for (let i = 0; i < boxes.length; i++) {
    const last = rows[rows.length - 1];
    const prevIdx = last?.[last.length - 1];
    if (last && prevIdx !== undefined && sameRow(boxes[prevIdx], boxes[i])) {
      last.push(i);
    } else {
      rows.push([i]);
    }
  }
  return rows;
}

/** 停靠点落在第几行（找不到返回 -1）。 */
export function rowIndexOf(rows: number[][], index: number): number {
  return rows.findIndex((row) => row.includes(index));
}

/** ↑/↓ 的目标：**相邻行**里水平方向最接近当前停靠点的那个。
 *
 *  已到首行（向上）或末行（向下）时返回 `null` —— 调用方据此**跨区**。
 *  「到区域边缘后再按一次才跨区」正是靠这个 null 实现的：到边缘那一次返回 null，
 *  于是同一次按键就完成了跨区。
 *
 *  刻意**不做列记忆**（回到本行时仍落在原列）：那需要额外状态，而本项目的行宽
 *  差异不大，按「水平中心最近」选已经足够可预测。这是有意简化，不是遗漏。 */
export function verticalTarget(
  boxes: StopBox[],
  rows: number[][],
  current: number,
  dir: 1 | -1,
): number | null {
  const rowIdx = rowIndexOf(rows, current);
  if (rowIdx < 0) return null;
  const nextRow = rows[rowIdx + dir];
  if (!nextRow || nextRow.length === 0) return null;

  const from = boxes[current];
  const centerX = (from.left + from.right) / 2;
  let best = nextRow[0];
  let bestDist = Number.POSITIVE_INFINITY;
  for (const idx of nextRow) {
    const box = boxes[idx];
    const dist = Math.abs((box.left + box.right) / 2 - centerX);
    if (dist < bestDist) {
      bestDist = dist;
      best = idx;
    }
  }
  return best;
}

/** ←/→ 的目标：**当前行内**前后移动；到该行首/末返回 `null`。
 *
 *  返回 null 时调用方**不跨区**（用户确认的是「到边界停住」）——
 *  横向没有「相邻区域」的概念，硬要跨只会跳到左边那栏或右边那栏，违反直觉。 */
export function horizontalTarget(
  rows: number[][],
  current: number,
  dir: 1 | -1,
): number | null {
  const rowIdx = rowIndexOf(rows, current);
  if (rowIdx < 0) return null;
  const row = rows[rowIdx];
  const col = row.indexOf(current) + dir;
  if (col < 0 || col >= row.length) return null;
  return row[col];
}

/** 区域链的顺序：显式 `order` 升序优先，未标注的排在最后并保持原有（DOM）顺序。
 *
 *  用稳定排序 + 原索引兜底：未标注 order 的区域不会因为排序实现而随机换位。 */
export function orderRegionIds(
  entries: { id: string; order: number | null }[],
): string[] {
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((a, b) => {
      const ao = a.entry.order ?? Number.MAX_SAFE_INTEGER;
      const bo = b.entry.order ?? Number.MAX_SAFE_INTEGER;
      if (ao !== bo) return ao - bo;
      return a.index - b.index;
    })
    .map((item) => item.entry.id);
}

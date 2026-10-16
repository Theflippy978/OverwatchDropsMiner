/** reka-ui Select 的空 value 哨兵串。
 *
 *  **这是本项目唯一解释「Select 为什么不能收空串」的地方**，其余使用点
 *  只写自己那一侧的后果，不复述这里的原理。
 *
 *  背景：reka-ui 的 SelectItem 在**渲染期**就拒绝空字符串 value ——
 *  空串被它留作「清空选择并显示 placeholder」的语义。传空串的报错是
 *  `A <SelectItem /> must have a value prop that is not an empty string.`，
 *  且是一打开就抛，不是选中时才抛（本项目 2026-10-13 因此整个日志卡报错）。
 *
 *  所以封装层把空串归一成这个哨兵串，且**两侧必须同时做**：
 *    * SelectItem.vue 用它替换自己注册的 value；
 *    * Select.vue 用它替换 Root 的 modelValue。
 *  只做一侧的故障形态是「不报错但对勾永远不出来」——reka 按 value 严格
 *  比对，Item 注册的是哨兵串、Root 存的是空串，两者永不相等。
 *
 *  真实取值（账号 id 等）是 uuid hex，不可能等于这个串，所以互转是双射。
 *
 *  判据：三处必须同时成立 —— Item 归一化、Root 归一化、出口反归一
 *  （见下面 denormalizeSelectValue），且哨兵字面量只在这里定义一次。 */
export const EMPTY_VALUE_SENTINEL = "__reka_empty__";

/** 把调用方给的值归一成 reka 能接受的形式（空串 → 哨兵串）。
 *
 *  用泛型而不是 `unknown`：调用方给的通常是 `string`，而归一化不改变类型
 *  （哨兵串也是 string）。返回 unknown 会让 reka 的 AcceptableValue
 *  约束报 TS2322。 */
export function normalizeSelectValue<T>(value: T): T {
  return value === "" ? (EMPTY_VALUE_SENTINEL as T) : value;
}

/** 把 reka 回传的值还原成调用方给的形式（哨兵串 → 空串）。
 *
 *  **必须在封装层的出口做，不许让调用方自己判**：reka 回传的 value 全部来自
 *  已注册的 Item，而注册时已经归一过了，所以哨兵串一定会漏到外面。
 *  漏出去的故障形态不报错、不抛异常，只是调用方拿到一个谁都不认识的字符串
 *  并把它当成真实取值存进状态 —— 日志卡当时选「全部账号」会把日志整块筛空
 *  （筛选条件变成一个不可能等于任何账号 id 的串），界面看起来像「没有日志」。
 *  调用方各自判等于把同一个坑复制 N 遍，所以这里统一收口。 */
export function denormalizeSelectValue<T>(value: T): T {
  return value === EMPTY_VALUE_SENTINEL ? ("" as T) : value;
}

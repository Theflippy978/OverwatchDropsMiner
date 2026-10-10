/**
 * IPC 异常的统一格式化。
 *
 * 为什么需要它：store 层此前一律用模板串直接拼接原始异常
 * （`error.value = `加载账号失败: ${e}``），而 `e` 来自 Rust 的
 * `Result<_, String>`，内容是**给开发者看的**：
 *
 *   sidecar 命令 get_accounts 超时（30s 未响应）
 *
 * 用户看到的是这种中英混杂的内部措辞，既不知道发生了什么、
 * 也不知道该做什么。而同一个 `${e}` 在别处又可能是本地
 * `throw new Error(...)`，渲染出来带 `Error: ` 前缀 —— 格式也会漂移。
 *
 * 原则是**映射而非丢弃**：原始串一律继续 console.error（并进日志面板），
 * 保证排障信息不丢；只把展示给用户的措辞换成能理解的说明。
 * 这与「错误提示必须保留失败原因，否则无诊断价值」不冲突 ——
 * 后者反对的是「换成一句泛化文案后什么都不留」。
 */

/** 已知的 Rust 侧错误文案 → 面向用户的说明。
 *  只映射**确定性**的模式：匹配不到时原样返回（剥离 Error: 前缀），
 *  宁可露出内部措辞，也不要编一个可能误导的泛化说法。 */
const FRIENDLY_RULES: Array<{ pattern: RegExp; message: string }> = [
  {
    pattern: /sidecar 命令 .+ 超时/,
    message: "后台服务响应超时，请稍后重试",
  },
  {
    pattern: /sidecar (未启动|未运行|已退出)|not running|failed to connect/i,
    message: "后台服务未就绪，请重启程序",
  },
  {
    pattern: /配置尚未加载完成/,
    message: "配置尚未加载完成，请稍候重试",
  },
];

/**
 * 把任意异常转成面向用户的一句话。
 *
 * @param error 捕获到的异常（Tauri 的 invoke 拒绝给的是 string，
 *              本地 throw 给的是 Error）
 * @param context 可选的动作前缀，如「加载账号失败」。
 *                不传则只返回原因本身。
 */
export function formatIpcError(error: unknown, context?: string): string {
  // 原始串必须留在控制台：映射后的文案是给用户的，不是给排障的
  console.error("[IPC]", error);

  const raw = error instanceof Error ? error.message : String(error ?? "");
  const trimmed = raw.replace(/^Error:\s*/, "").trim();
  const friendly =
    FRIENDLY_RULES.find((rule) => rule.pattern.test(trimmed))?.message ?? trimmed;

  return context ? `${context}：${friendly}` : friendly;
}

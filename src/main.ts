import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import "./style.css";
import { useLogsStore } from "@/stores/logs";

const app = createApp(App);
app.use(createPinia());

/**
 * 渲染期异常必须让用户看得见。
 *
 * Vue 默认只 console.error：组件渲染/生命周期抛异常时该子树渲染中断、
 * 界面出现局部空白，而用户看不到任何提示，也想不到去看 devtools。
 * 本项目有大量模板内计算（TaskProgress 的聚合/过滤/进度串、
 * LogViewer 的结构化分段），这类异常并非不可能。
 *
 * 写进日志面板即可复用现成的展示通道 —— 不新造 toast，
 * 也不需要额外的错误状态管理。
 *
 * 在 handler **内部**调用 useLogsStore()（而非模块顶层）：
 * 此时 createPinia 已安装，且 logsStore 尚未 initListeners 也不影响
 * —— addLog 只是往 buffer 里推，flush 由定时器驱动。
 */
app.config.errorHandler = (err, _instance, info) => {
  console.error("[Vue]", info, err);
  try {
    useLogsStore().addLog({
      timestamp: new Date().toISOString(),
      account_id: null,
      level: "error",
      message: `界面异常（${info}）：${err instanceof Error ? err.message : String(err)}`,
    });
  } catch {
    /* 日志 store 尚未就绪时忽略 —— 绝不能因为「处理错误」再抛错 */
  }
};

/**
 * 未处理的 Promise 拒绝同样要留痕。
 *
 * 项目里有多处 `void someAsync()` 的调用（fire-and-forget 是刻意的），
 * 一旦其中某个抛错，默认只会有一条 console 警告，用户与后续排障者
 * 都无从得知。
 */
window.addEventListener("unhandledrejection", (event) => {
  console.error("[unhandledrejection]", event.reason);
  try {
    const reason = event.reason;
    useLogsStore().addLog({
      timestamp: new Date().toISOString(),
      account_id: null,
      level: "error",
      message: `未处理的异步异常：${reason instanceof Error ? reason.message : String(reason)}`,
    });
  } catch {
    /* 同上 */
  }
});

app.mount("#app");

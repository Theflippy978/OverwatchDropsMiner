export interface Account {
  id: string;
  remark: string;
  running: boolean;
}

// 注：原此处有一个 MinerConfig 接口（sidecar 端 config.json 的契约镜像），
// 2026-10-02 删除：全 src/ 无任何 import，Rust 侧同名结构体也已删除。
// 两处维护同一份线格式而无人消费，是纯粹的腐化源。

export interface GuiConfigValues {
  cookie: string;
  rooms_text: string;
  thread_count_text: string;
  reconnect_delay_text: string;
  task_ids_text: string;
  task_query_interval_text: string;
  notify_urls_text: string;
  notify_on_task_complete: boolean;
  verbose: boolean;
  auto_claim_rewards: boolean;
}

export interface AccountStatus {
  account_id: string;
  running: boolean;
  watch_time_seconds: number;
  /** 后端格式化的状态行（与原 Qt 项目一致） */
  status_line: string;
  /** B 站掉宝进度数值（后端 progress 键） */
  progress: ProgressValues | null;
  /** 任务级进度对象（当前后端无数据，保留字段兼容） */
  task_progress: TaskProgress | null;
  /** Cookie 失效自动停止（true 时表示因登录失效而停止）。
      后端 serde 虽标 default，但序列化时总会写出该键，故为必填。 */
  login_invalidated: boolean;
}

export interface ProgressValues {
  cur: number;
  limit: number;
  percent: number;
}

/**
 * B站检查点与任务的 status 取值。镜像
 * python_sidecar/backend/constants.py，改动必须两侧同步。
 *
 * 收集在模块顶层而非散落各处：此前 6 这个字面量出现在 4 个文件里，
 * 任何一处漏改都会让「已完成」与「已领取」的判定漂移，且不会报错。
 */
export const TASK_STATUS_PENDING = 0;
export const TASK_STATUS_COMPLETED = 3;
export const TASK_STATUS_CLAIMED = 6;
/** 已完成或已领取。is_completed 为 true 不代表未领取，判定待领必须
     同时排除 TASK_STATUS_CLAIMED。 */
export const TASK_STATUS_DONE: ReadonlySet<number> = new Set([
  TASK_STATUS_COMPLETED,
  TASK_STATUS_CLAIMED,
]);

export interface CheckPoint {
  sid: string;
  alias: string;
  status: number;
  /** 后端按 TASK_STATUS_DONE 判定，即 status 为 3 或 6 都为 true，
      所以它不代表未领取。 */
  is_completed: boolean;
  cur_value: number;
  limit_value: number;
  award_name: string;
  award_count: number;
}

export interface TaskProgress {
  task_id: string;
  title: string;
  progress: number;
  target: number;
  status: string;
  rewards: Reward[];
  /** 后端序列化时总会写出该键（commands.rs 的 #[serde(default)] 只作用于
      反序列化），故不是可选。 */
  check_points: CheckPoint[];
}

export type TaskItem = TaskProgress;

export interface Reward {
  name: string;
  icon: string;
  count: number;
}

export interface LogEntry {
  timestamp: string;
  account_id: string | null;
  level: "info" | "warning" | "error" | "debug";
  message: string;
}

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

export interface CheckPoint {
  sid: string;
  alias: string;
  status: number;
  /** 注意：后端 models.py:48 的 status in (3, 6) 含「已领取」，
      所以 is_completed 为 true 不代表未领取，判定待领必须同时排除
      status === 6。 */
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

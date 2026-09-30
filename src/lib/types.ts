export interface Account {
  id: string;
  remark: string;
  running: boolean;
}

export interface MinerConfig {
  cookie: string;
  room_ids: number[];
  thread_count: number;
  reconnect_delay_seconds: number;
  task_ids: string[];
  task_query_interval_seconds: number;
  notify_urls: string[];
  notify_on_task_complete: boolean;
  auto_claim_rewards: boolean;
  verbose: boolean;
}

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
  /** Cookie 失效自动停止（true 时表示因登录失效而停止） */
  login_invalidated?: boolean;
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
  check_points?: CheckPoint[];
}

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

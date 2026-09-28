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
  task_progress: TaskProgress | null;
}

export interface TaskProgress {
  task_id: string;
  title: string;
  progress: number;
  target: number;
  status: string;
  rewards: Reward[];
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

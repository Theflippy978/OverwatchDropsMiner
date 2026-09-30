use serde::{Deserialize, Serialize};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::io::{BufRead, BufReader, Write};
use std::sync::Mutex;
use std::sync::Arc;
use tauri::Emitter;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Account {
    pub id: String,
    pub remark: String,
    pub running: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AccountStatus {
    pub account_id: String,
    pub running: bool,
    pub watch_time_seconds: u64,
    pub status_line: String,
    pub task_progress: Option<TaskProgress>,
    pub progress: Option<ProgressValues>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ProgressValues {
    pub cur: f64,
    pub limit: f64,
    pub percent: i32,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TaskProgress {
    pub task_id: String,
    pub title: String,
    pub progress: f64,
    pub target: f64,
    pub status: String,
    pub rewards: Vec<Reward>,
    #[serde(default)]
    pub check_points: Vec<CheckPoint>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CheckPoint {
    pub sid: String,
    pub alias: String,
    pub status: i32,
    pub is_completed: bool,
    pub cur_value: f64,
    pub limit_value: f64,
    pub award_name: String,
    pub award_count: i32,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Reward {
    pub name: String,
    pub icon: String,
    pub count: i32,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct QrChallenge {
    pub qr_url: String,
    pub qr_key: String,
    pub qr_image: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct QrPollResult {
    pub status: String,
    pub cookie: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RefreshTasksResult {
    pub tasks: Vec<TaskProgress>,
    pub text: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ClaimRewardItem {
    pub task_id: String,
    pub reward_name: String,
    pub success: bool,
    pub skipped: bool,
    pub message: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ClaimRewardsResult {
    pub success: bool,
    pub results: Vec<ClaimRewardItem>,
    pub text: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TaskGroup {
    pub label: String,
    pub task_ids: Vec<String>,
    pub active: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FetchRoomIdResult {
    pub room_id: i64,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FetchTaskIdsResult {
    pub room_id: i64,
    pub groups: Vec<TaskGroup>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct FetchTaskIdsMode2Result {
    #[serde(default)]
    pub room_id: Option<i64>,
    pub groups: Vec<TaskGroup>,
}

#[derive(Debug, Serialize, Deserialize)]
#[allow(dead_code)]
pub struct MinerConfig {
    pub cookie: String,
    pub room_ids: Vec<i64>,
    pub thread_count: i32,
    pub reconnect_delay_seconds: i32,
    pub task_ids: Vec<String>,
    pub task_query_interval_seconds: i32,
    pub notify_urls: Vec<String>,
    pub notify_on_task_complete: bool,
    pub auto_claim_rewards: bool,
    pub verbose: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct GuiConfigValues {
    pub cookie: String,
    pub rooms_text: String,
    pub thread_count_text: String,
    pub reconnect_delay_text: String,
    pub task_ids_text: String,
    pub task_query_interval_text: String,
    pub notify_urls_text: String,
    pub notify_on_task_complete: bool,
    pub verbose: bool,
    pub auto_claim_rewards: bool,
}

// Python sidecar 进程管理
// stdin/reader 必须跨 call 复用：每次新建 BufReader 会把预读缓冲里的
// 后续行（响应或事件）一并丢弃，导致命令响应错位。
struct SidecarProcess {
    #[allow(dead_code)]
    process: Child,
    stdin: ChildStdin,
    reader: BufReader<ChildStdout>,
}

pub struct SidecarManager {
    child: Arc<Mutex<Option<SidecarProcess>>>,
    app_handle: tauri::AppHandle,
}

impl SidecarManager {
    pub fn new(app_handle: tauri::AppHandle) -> Self {
        SidecarManager {
            child: Arc::new(Mutex::new(None)),
            app_handle,
        }
    }
    
    pub fn start(&self) -> Result<(), String> {
        let mut child = self.child.lock().unwrap();
        if child.is_some() {
            return Ok(()); // 已经在运行
        }
        
        // 修正路径：Tauri 的 current_dir() 是 src-tauri，需要回到项目根目录
        let sidecar_path = std::env::current_dir()
            .map_err(|e| e.to_string())?
            .parent()
            .ok_or("无法获取项目根目录")?
            .join("python_sidecar");
        
        let python_exe = std::env::var("PYTHON_EXE").unwrap_or_else(|_| "python".to_string());
        
        let mut process = Command::new(&python_exe)
            .arg(sidecar_path.join("main.py"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| format!("启动 Python sidecar 失败: {}", e))?;
        
        let stdin = process.stdin.take().ok_or("无法获取 sidecar stdin")?;
        let stdout = process.stdout.take().ok_or("无法获取 sidecar stdout")?;
        
        *child = Some(SidecarProcess {
            process,
            stdin,
            reader: BufReader::new(stdout),
        });
        Ok(())
    }
    
    pub fn call(&self, command: &str, params: serde_json::Value) -> Result<serde_json::Value, String> {
        self.start()?;
        
        let mut guard = self.child.lock().unwrap();
        let proc = guard.as_mut().ok_or("Sidecar 未运行")?;
        
        let request = serde_json::json!({
            "command": command,
            "params": params,
        });
        
        writeln!(proc.stdin, "{}", request)
            .map_err(|e| format!("写入 sidecar 失败: {}", e))?;
        
        // 循环读取：跳过事件行（转发到前端），只把真正的响应返回给命令调用方
        loop {
            let mut line = String::new();
            let read = proc
                .reader
                .read_line(&mut line)
                .map_err(|e| format!("读取 sidecar 失败: {}", e))?;
            if read == 0 {
                return Err("sidecar 进程已退出".to_string());
            }
            
            let trimmed = line.trim();
            if trimmed.is_empty() {
                continue;
            }
            
            let value: serde_json::Value = serde_json::from_str(trimmed)
                .map_err(|e| format!("解析 sidecar 响应失败: {}", e))?;
            
            if value.get("type").and_then(|v| v.as_str()) == Some("event") {
                let event_name = value
                    .get("event")
                    .and_then(|v| v.as_str())
                    .unwrap_or("sidecar-event");
                let data = value.get("data").cloned().unwrap_or(serde_json::Value::Null);
                if let Err(e) = self.app_handle.emit(event_name, &data) {
                    eprintln!("转发 sidecar 事件失败: {}", e);
                }
                continue;
            }
            
            if let Some(error) = value.get("error") {
                return Err(error.as_str().unwrap_or("未知错误").to_string());
            }
            
            return Ok(value);
        }
    }
}

#[tauri::command]
pub async fn get_accounts(sidecar: tauri::State<'_, SidecarManager>) -> Result<Vec<Account>, String> {
    let resp = sidecar.call("get_accounts", serde_json::json!({}))?;
    let accounts = resp.get("accounts")
        .and_then(|v| v.as_array())
        .ok_or("无效的响应")?;
    
    let result: Vec<Account> = accounts.iter()
        .map(|a| Account {
            id: a.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            remark: a.get("remark").and_then(|v| v.as_str()).unwrap_or("").to_string(),
            running: a.get("running").and_then(|v| v.as_bool()).unwrap_or(false),
        })
        .collect();
    
    Ok(result)
}

#[tauri::command]
pub async fn add_account(cookie: String, sidecar: tauri::State<'_, SidecarManager>) -> Result<Account, String> {
    let resp = sidecar.call("add_account", serde_json::json!({ "cookie": cookie }))?;
    
    Ok(Account {
        id: resp.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        remark: resp.get("remark").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        running: false,
    })
}

#[tauri::command]
pub async fn remove_account(account_id: String, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("remove_account", serde_json::json!({ "account_id": account_id }))?;
    Ok(())
}

#[tauri::command]
pub async fn rename_account(
    account_id: String,
    remark: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<Account, String> {
    let resp = sidecar.call("rename_account", serde_json::json!({
        "account_id": account_id,
        "remark": remark,
    }))?;

    Ok(Account {
        id: resp.get("id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        remark: resp.get("remark").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        running: resp.get("running").and_then(|v| v.as_bool()).unwrap_or(false),
    })
}

#[tauri::command]
pub async fn start_miner(account_id: String, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("start_miner", serde_json::json!({
        "account_id": account_id,
    }))?;
    Ok(())
}

#[tauri::command]
pub async fn stop_miner(account_id: String, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("stop_miner", serde_json::json!({ "account_id": account_id }))?;
    Ok(())
}

#[tauri::command]
pub async fn get_account_status(account_id: String, sidecar: tauri::State<'_, SidecarManager>) -> Result<AccountStatus, String> {
    let resp = sidecar.call("get_account_status", serde_json::json!({ "account_id": account_id }))?;

    let progress = resp.get("progress").and_then(|v| {
        Some(ProgressValues {
            cur: v.get("cur").and_then(|x| x.as_f64()).unwrap_or(0.0),
            limit: v.get("limit").and_then(|x| x.as_f64()).unwrap_or(0.0),
            percent: v.get("percent").and_then(|x| x.as_i64()).unwrap_or(0) as i32,
        })
    });

    Ok(AccountStatus {
        account_id: resp.get("account_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        running: resp.get("running").and_then(|v| v.as_bool()).unwrap_or(false),
        watch_time_seconds: resp.get("watch_time_seconds").and_then(|v| v.as_u64()).unwrap_or(0),
        status_line: resp.get("status_line").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        task_progress: None,
        progress,
    })
}

#[tauri::command]
pub async fn save_config(config: GuiConfigValues, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("save_config", serde_json::json!({ "config": config }))?;
    Ok(())
}

#[tauri::command]
pub async fn load_config(sidecar: tauri::State<'_, SidecarManager>) -> Result<GuiConfigValues, String> {
    let resp = sidecar.call("load_config", serde_json::json!({}))?;
    
    Ok(GuiConfigValues {
        cookie: resp.get("cookie").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        rooms_text: resp.get("rooms_text").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        thread_count_text: resp.get("thread_count_text").and_then(|v| v.as_str()).unwrap_or("60").to_string(),
        reconnect_delay_text: resp.get("reconnect_delay_text").and_then(|v| v.as_str()).unwrap_or("8").to_string(),
        task_ids_text: resp.get("task_ids_text").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        task_query_interval_text: resp.get("task_query_interval_text").and_then(|v| v.as_str()).unwrap_or("30").to_string(),
        notify_urls_text: resp.get("notify_urls_text").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        notify_on_task_complete: resp.get("notify_on_task_complete").and_then(|v| v.as_bool()).unwrap_or(true),
        verbose: resp.get("verbose").and_then(|v| v.as_bool()).unwrap_or(false),
        auto_claim_rewards: resp.get("auto_claim_rewards").and_then(|v| v.as_bool()).unwrap_or(false),
    })
}

#[tauri::command]
pub async fn qr_login(sidecar: tauri::State<'_, SidecarManager>) -> Result<QrChallenge, String> {
    let resp = sidecar.call("qr_login", serde_json::json!({}))?;
    serde_json::from_value(resp).map_err(|e| format!("解析二维码响应失败: {}", e))
}

#[tauri::command]
pub async fn qr_poll(
    qr_key: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<QrPollResult, String> {
    let resp = sidecar.call("qr_poll", serde_json::json!({ "qr_key": qr_key }))?;
    Ok(QrPollResult {
        status: resp
            .get("status")
            .and_then(|v| v.as_str())
            .unwrap_or("unscanned")
            .to_string(),
        cookie: resp
            .get("cookie")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
    })
}

#[tauri::command]
pub async fn qr_cancel(sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("qr_cancel", serde_json::json!({}))?;
    Ok(())
}

#[tauri::command]
pub async fn browser_capture(
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<String, String> {
    let resp = sidecar.call("browser_capture", serde_json::json!({ "browser": browser }))?;
    Ok(resp.get("cookie").and_then(|v| v.as_str()).unwrap_or("").to_string())
}

#[tauri::command]
pub async fn send_notification(
    title: String,
    body: String,
    sidecar: tauri::State<'_, SidecarManager>
) -> Result<bool, String> {
    let resp = sidecar.call("send_notification", serde_json::json!({
        "title": title,
        "body": body,
    }))?;
    Ok(resp.get("success").and_then(|v| v.as_bool()).unwrap_or(false))
}

#[tauri::command]
pub async fn claim_rewards(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<ClaimRewardsResult, String> {
    let resp = sidecar.call("claim_rewards", serde_json::json!({ "account_id": account_id }))?;
    let results = resp
        .get("results")
        .cloned()
        .map(serde_json::from_value)
        .transpose()
        .map_err(|e| format!("解析领取结果失败: {}", e))?
        .unwrap_or_default();

    Ok(ClaimRewardsResult {
        success: resp.get("success").and_then(|v| v.as_bool()).unwrap_or(false),
        results,
        text: resp
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
    })
}

#[tauri::command]
pub async fn refresh_tasks(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<RefreshTasksResult, String> {
    let resp = sidecar.call("refresh_tasks", serde_json::json!({ "account_id": account_id }))?;
    let tasks = resp
        .get("tasks")
        .cloned()
        .map(serde_json::from_value)
        .transpose()
        .map_err(|e| format!("解析任务进度失败: {}", e))?
        .unwrap_or_default();

    Ok(RefreshTasksResult {
        tasks,
        text: resp
            .get("text")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
    })
}

#[tauri::command]
pub async fn auto_fetch_room_id(
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<FetchRoomIdResult, String> {
    let resp = sidecar.call("auto_fetch_room_id", serde_json::json!({ "browser": browser }))?;
    serde_json::from_value(resp).map_err(|e| format!("解析房间号失败: {}", e))
}

#[tauri::command]
pub async fn auto_fetch_task_ids(
    room_id: i64,
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<FetchTaskIdsResult, String> {
    let resp = sidecar.call(
        "auto_fetch_task_ids",
        serde_json::json!({ "room_id": room_id, "browser": browser }),
    )?;
    serde_json::from_value(resp).map_err(|e| format!("解析任务组失败: {}", e))
}

#[tauri::command]
pub async fn auto_fetch_task_ids_mode2(
    room_id: Option<i64>,
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<FetchTaskIdsMode2Result, String> {
    let resp = sidecar.call(
        "auto_fetch_task_ids_mode2",
        serde_json::json!({ "room_id": room_id, "browser": browser }),
    )?;
    serde_json::from_value(resp).map_err(|e| format!("解析任务组失败: {}", e))
}

#[tauri::command]
pub async fn export_config(
    path: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<String, String> {
    let resp = sidecar.call("export_config", serde_json::json!({ "path": path }))?;
    Ok(resp.get("path").and_then(|v| v.as_str()).unwrap_or("").to_string())
}

#[tauri::command]
pub async fn import_config(
    path: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<GuiConfigValues, String> {
    let resp = sidecar.call("import_config", serde_json::json!({ "path": path }))?;
    serde_json::from_value(resp).map_err(|e| format!("解析配置失败: {}", e))
}

#[tauri::command]
pub async fn sync_config_to_miners(
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<(), String> {
    sidecar.call("sync_config_to_miners", serde_json::json!({}))?;
    Ok(())
}

#[tauri::command]
pub async fn shutdown(sidecar: tauri::State<'_, SidecarManager>) -> Result<ShutdownResult, String> {
    let resp = sidecar.call("shutdown", serde_json::json!({}))?;
    Ok(ShutdownResult {
        closed: resp.get("closed").and_then(|v| v.as_bool()).unwrap_or(false),
    })
}

#[derive(Debug, Serialize, Deserialize)]
pub struct ShutdownResult {
    pub closed: bool,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct UpdateCheckResult {
    pub update_available: bool,
    pub latest_version: String,
    pub release_url: String,
}

#[tauri::command]
pub async fn check_update(sidecar: tauri::State<'_, SidecarManager>) -> Result<UpdateCheckResult, String> {
    let resp = sidecar.call("check_update", serde_json::json!({}))?;
    Ok(UpdateCheckResult {
        update_available: resp.get("update_available").and_then(|v| v.as_bool()).unwrap_or(false),
        latest_version: resp.get("latest_version").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        release_url: resp.get("release_url").and_then(|v| v.as_str()).unwrap_or("").to_string(),
    })
}

#[derive(Debug, Serialize, Deserialize)]
pub struct BrowserDetection {
    pub available: Vec<String>,
    pub default: String,
    pub labels: std::collections::HashMap<String, String>,
}

#[tauri::command]
pub async fn detect_browsers(sidecar: tauri::State<'_, SidecarManager>) -> Result<BrowserDetection, String> {
    let resp = sidecar.call("detect_browsers", serde_json::json!({}))?;
    Ok(BrowserDetection {
        available: resp.get("available")
            .and_then(|v| v.as_array())
            .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default(),
        default: resp.get("default").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        labels: resp.get("labels")
            .and_then(|v| v.as_object())
            .map(|obj| {
                obj.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect()
            })
            .unwrap_or_default(),
    })
}

#[tauri::command]
pub async fn update_notify_urls(
    urls: Vec<String>,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<Vec<String>, String> {
    let resp = sidecar.call("update_notify_urls", serde_json::json!({ "urls": urls }))?;
    Ok(resp.get("urls")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().filter_map(|x| x.as_str().map(String::from)).collect())
        .unwrap_or_default())
}

#[tauri::command]
pub async fn stop_all(sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("stop_all", serde_json::json!({}))?;
    Ok(())
}






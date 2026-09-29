use serde::{Deserialize, Serialize};
use std::process::{Command, Stdio};
use std::io::{BufRead, BufReader, Write};
use std::sync::Mutex;
use std::sync::Arc;

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
    pub task_progress: Option<TaskProgress>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TaskProgress {
    pub task_id: String,
    pub title: String,
    pub progress: f64,
    pub target: f64,
    pub status: String,
    pub rewards: Vec<Reward>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Reward {
    pub name: String,
    pub icon: String,
    pub count: i32,
}

#[derive(Debug, Serialize, Deserialize)]
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
pub struct SidecarManager {
    child: Arc<Mutex<Option<std::process::Child>>>,
    #[allow(dead_code)]
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
        
        let process = Command::new(&python_exe)
            .arg(sidecar_path.join("main.py"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|e| format!("启动 Python sidecar 失败: {}", e))?;
        
        *child = Some(process);
        Ok(())
    }
    
    pub fn call(&self, command: &str, params: serde_json::Value) -> Result<serde_json::Value, String> {
        self.start()?;
        
        let mut child = self.child.lock().unwrap();
        let process = child.as_mut().ok_or("Sidecar 未运行")?;
        
        let request = serde_json::json!({
            "command": command,
            "params": params,
        });
        
        let stdin = process.stdin.as_mut().ok_or("无法写入 sidecar")?;
        writeln!(stdin, "{}", request.to_string())
            .map_err(|e| format!("写入 sidecar 失败: {}", e))?;
        
        let stdout = process.stdout.as_mut().ok_or("无法读取 sidecar")?;
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader.read_line(&mut line).map_err(|e| format!("读取 sidecar 失败: {}", e))?;
        
        let response: serde_json::Value = serde_json::from_str(&line)
            .map_err(|e| format!("解析 sidecar 响应失败: {}", e))?;
        
        if let Some(error) = response.get("error") {
            return Err(error.as_str().unwrap_or("未知错误").to_string());
        }
        
        Ok(response)
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
pub async fn start_miner(account_id: String, config: MinerConfig, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("start_miner", serde_json::json!({
        "account_id": account_id,
        "config": config,
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
    
    Ok(AccountStatus {
        account_id: resp.get("account_id").and_then(|v| v.as_str()).unwrap_or("").to_string(),
        running: resp.get("running").and_then(|v| v.as_bool()).unwrap_or(false),
        watch_time_seconds: resp.get("watch_time_seconds").and_then(|v| v.as_u64()).unwrap_or(0),
        task_progress: None,
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
pub async fn qr_login(sidecar: tauri::State<'_, SidecarManager>) -> Result<String, String> {
    let resp = sidecar.call("qr_login", serde_json::json!({}))?;
    Ok(resp.get("qr_code").and_then(|v| v.as_str()).unwrap_or("").to_string())
}

#[tauri::command]
pub async fn browser_capture(sidecar: tauri::State<'_, SidecarManager>) -> Result<String, String> {
    let resp = sidecar.call("browser_capture", serde_json::json!({}))?;
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
pub async fn claim_rewards(account_id: String, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("claim_rewards", serde_json::json!({ "account_id": account_id }))?;
    Ok(())
}

#[tauri::command]
pub async fn refresh_tasks(account_id: String, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("refresh_tasks", serde_json::json!({ "account_id": account_id }))?;
    Ok(())
}






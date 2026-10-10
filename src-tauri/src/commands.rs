use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::Emitter;

#[cfg(windows)]
use std::os::windows::io::AsRawHandle;
#[cfg(windows)]
use windows::Win32::Foundation::{CloseHandle, HANDLE};
#[cfg(windows)]
use windows::Win32::System::JobObjects::{
    AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
    SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};

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
    #[serde(default)]
    pub login_invalidated: bool,
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
    /// B站任务状态。领取成功为 6（已领取）。sidecar 不缓存检查点状态，
    /// 下次 refresh_tasks 返回的仍是 3（已完成），前端靠这个字段当场
    /// 把徽标改成「已领取」。
    pub status: i32,
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

// 注：原此处有一个 #[allow(dead_code)] 的 MinerConfig 结构体（sidecar 端
// config.json 的契约镜像），2026-10-02 删除：全 crate 无任何引用，
// GuiConfigValues 才是真正使用的配置 DTO。两处（Rust 与 TS）都维护同一份
// 线格式而无人消费，是纯粹的腐化源。

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
// 并发模型：
//   * 写 stdin 只在极短的锁内完成，锁不跨命令等待，命令之间不再互相阻塞；
//   * 每个请求带自增 id，独立 reader 线程按 id 把响应投递给对应等待者；
//   * 事件行（无 id 的 {"type":"event"}）由 reader 线程直接转发给前端；
//   * 命令等待有 300s 上限（浏览器嗅探 120s / 领奖 180s 需要较长的窗口），
//     超时后从挂起表移除，不会污染后续请求。
const CALL_TIMEOUT: Duration = Duration::from_secs(300);

/// 单个在途请求：`(进程代次, 响应投递通道)`。
///
/// 代次存在的理由见 `SidecarManager::epoch` 的注释 —— reader_loop 退出时
/// 只能清理自己那一代，否则会把新一代进程的在途请求一并判死。
type PendingEntry = (u64, Sender<Result<serde_json::Value, String>>);
/// 请求序号 → 在途请求。序号是 `SidecarManager::call` 的 `next_id` 自增值。
type PendingTable = HashMap<u64, PendingEntry>;
type PendingMap = Arc<Mutex<PendingTable>>;

struct SidecarProcess {
    process: Child,
    stdin: ChildStdin,
}

pub struct SidecarManager {
    child: Arc<Mutex<Option<SidecarProcess>>>,
    pending: PendingMap,
    next_id: Arc<AtomicU64>,
    alive: Arc<AtomicBool>,
    /// 进程代次号：每次 start() 自增。pending 表里的每一项都记下它所属的
    /// 代次，reader_loop 退出时只清理自己那一代并只在仍是当前代时才置
    /// alive=false。否则出现如下竞态：T1 读到 alive==false 尚未 reset，
    /// T2 已完成 reset+start 拉起 P2（alive=true）并写入请求 R，
    /// T1 随后执行 reset 把健康的 P2 杀掉再拉起 P3；
    /// P2 的 reader_loop 拿到 EOF 后会把 P3 的在途请求 R 全部判死。
    epoch: Arc<AtomicU64>,
    app_handle: tauri::AppHandle,
    /// KILL_ON_JOB_CLOSE 的 Job Object 句柄（存 isize：HANDLE 是裸指针
    /// newtype 不满足 Send/Sync，SidecarManager 需要）。主进程无论以何种
    /// 方式退出（正常关闭 / 任务管理器强杀 / 崩溃），该句柄被内核回收时
    /// Job 内的 sidecar 进程会被操作系统自动终止，杜绝残留。
    /// 生命周期 = 进程生命周期，**故意不 CloseHandle**，否则会提前触发
    /// KILL_ON_JOB_CLOSE 把 sidecar 杀掉。
    ///
    /// 用 Arc 包裹：克隆体必须能读到**同一个**句柄。若克隆时新建空锁，
    /// 由克隆体 spawn 出的 sidecar 就挂不上 Job Object
    /// （assign_child_to_kill_job 会静默 early-return），孤儿进程防护随之中断。
    kill_job: Arc<Mutex<Option<isize>>>,
}

/// 共享进程与通信表，让命令体能在 `spawn_blocking` 的闭包里使用。
///
/// `kill_job` 必须在克隆之间共享：async 命令都用克隆体调用 `call()` →
/// `start()`，而 start() 里的 assign_child_to_kill_job 读的是 self.kill_job。
/// 克隆体若拿不到句柄，它拉起的 sidecar 就永远进不了 Job Object —— 例如
/// sidecar 崩溃后由某个 async 命令重新拉起时，防护会静默失效。
/// 共享的是句柄值而非所有权：本进程全程不 CloseHandle，故无克隆体误释放之虞。
impl Clone for SidecarManager {
    fn clone(&self) -> Self {
        Self {
            child: self.child.clone(),
            pending: self.pending.clone(),
            next_id: self.next_id.clone(),
            alive: self.alive.clone(),
            epoch: self.epoch.clone(),
            app_handle: self.app_handle.clone(),
            kill_job: self.kill_job.clone(),
        }
    }
}

/// 把阻塞式 sidecar 调用挪到专用阻塞线程池执行。
///
/// 为什么不直接给命令加 `#[tauri::command(async)]`：该属性对**同步**函数
/// 只是把函数体包进 `async move { ... }`（见 tauri-macros 的 `body_async`），
/// 而 `ResponseTag::future()` 只是 `Ok(value.body()?)` —— 全程**没有**
/// `spawn_blocking`。结果是同步代码在首次 poll 时于 **tokio worker 线程**
/// 上执行：主线程解冻了（窗口不再「未响应」），但一个 worker 被
/// `recv_timeout(300s)` 占死。领奖 180s + 浏览器嗅探 120s 同时来就占死两个，
/// 而 tokio 默认 worker 数 = CPU 核数，核少的机器上剩余命令全部排队。
///
/// `spawn_blocking` 走 tokio 独立的阻塞池（上限 512），不占 worker。
/// 代价是每次调用一次线程调度，故只用于**确有长等待**的命令；
/// load_config 这类纯本地读仍保持同步直调。
async fn call_blocking<T, F>(task: F) -> Result<T, String>
where
    F: FnOnce() -> Result<T, String> + Send + 'static,
    T: Send + 'static,
{
    tauri::async_runtime::spawn_blocking(task)
        .await
        .map_err(|e| format!("sidecar 调用线程异常: {}", e))?
}

impl SidecarManager {
    pub fn new(app_handle: tauri::AppHandle) -> Self {
        SidecarManager {
            child: Arc::new(Mutex::new(None)),
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: Arc::new(AtomicU64::new(0)),
            alive: Arc::new(AtomicBool::new(false)),
            epoch: Arc::new(AtomicU64::new(0)),
            app_handle,
            kill_job: Arc::new(Mutex::new(Self::create_kill_job())),
        }
    }

    /// 锁中毒兜底：任一线程在持锁时 panic 会毒化 Mutex，此后所有
    /// `.lock().unwrap()` 都会 panic —— panic 发生在 Tauri 的 spawn 任务里
    /// 会导致该 IPC 请求永远拿不到响应，前端 invoke 无限挂起。
    fn lock_child(&self) -> std::sync::MutexGuard<'_, Option<SidecarProcess>> {
        self.child.lock().unwrap_or_else(|e| e.into_inner())
    }

    fn lock_pending(&self) -> std::sync::MutexGuard<'_, PendingTable> {
        self.pending.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// 与 lock_child/lock_pending 同一套中毒兜底：kill_job 被毒化后若在这里
    /// unwrap，spawn 路径会连带 panic，表现为「sidecar 起不来」而非锁问题。
    fn lock_kill_job(&self) -> std::sync::MutexGuard<'_, Option<isize>> {
        self.kill_job.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// 创建 KILL_ON_JOB_CLOSE 的 Job Object；失败返回 None（降级，不影响启动）
    #[cfg(windows)]
    fn create_kill_job() -> Option<isize> {
        unsafe {
            let job = CreateJobObjectW(None, None).ok()?;
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            if SetInformationJobObject(
                job,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const _,
                std::mem::size_of_val(&info) as u32,
            )
            .is_err()
            {
                let _ = CloseHandle(job);
                return None;
            }
            Some(job.0 as isize)
        }
    }

    #[cfg(not(windows))]
    fn create_kill_job() -> Option<isize> {
        None
    }

    /// 把刚 spawn 的 sidecar 挂进 Job；失败仅记日志（保留启动能力，双保险中的一环）
    #[cfg(windows)]
    fn assign_child_to_kill_job(&self, raw_handle: std::os::windows::raw::HANDLE) {
        let guard = self.lock_kill_job();
        let Some(job) = *guard else { return };
        unsafe {
            let job = HANDLE(job as *mut std::ffi::c_void);
            if let Err(e) = AssignProcessToJobObject(job, HANDLE(raw_handle)) {
                eprintln!("[Sidecar] sidecar 挂接 Job Object 失败: {:?}", e);
            }
        }
    }

    /// 定位 PyInstaller 打包的 sidecar EXE：先查 Tauri 资源目录（MSI 安装版），
    /// 再查主 EXE 同目录（便携/开发产物）
    fn locate_sidecar_exe(&self) -> Result<std::path::PathBuf, String> {
        use tauri::Manager;
        let resource_dir = self
            .app_handle
            .path()
            .resource_dir()
            .map_err(|e| format!("获取资源目录失败: {}", e))?;
        let sidecar_exe = resource_dir.join("python_sidecar.exe");
        if sidecar_exe.exists() {
            return Ok(sidecar_exe);
        }
        let exe_dir = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .ok_or("无法获取 EXE 目录")?
            .to_path_buf();
        let sidecar_exe = exe_dir.join("python_sidecar.exe");
        if sidecar_exe.exists() {
            return Ok(sidecar_exe);
        }
        Err("找不到 python_sidecar.exe".to_string())
    }

    pub fn start(&self) -> Result<(), String> {
        // 在锁内探测判活，磁盘 IO 与 spawn 都在锁外完成，
        // 只在最终写入时才持锁，避免把并发命令一起堵在慢操作里。
        enum Probe {
            Running,
            Absent,
            Dead,
        }
        let probe = {
            let mut child = self.lock_child();
            match child.as_mut() {
                // try_wait 判活：死进程必须当场回收，
                // 否则每个命令都要先吃一次写失败再触发 reset。
                Some(proc) => match proc.process.try_wait() {
                    Ok(Some(_)) => Probe::Dead,
                    _ => Probe::Running,
                },
                None => Probe::Absent,
            }
        };
        match probe {
            Probe::Running => return Ok(()),
            Probe::Dead => self.reset_process(),
            Probe::Absent => {}
        }

        #[cfg(windows)]
        const CREATE_NO_WINDOW: u32 = 0x08000000;

        let mut command = match self.locate_sidecar_exe() {
            Ok(sidecar_exe) => Command::new(&sidecar_exe),
            Err(e) => {
                // 开发回退：直接用 Python 跑 sidecar 源码。
                // 修正路径：Tauri 的 current_dir() 是 src-tauri，需要回到项目根目录。
                // 必须打出来：否则 release 下静默降级到系统 Python 且无任何线索。
                eprintln!("[sidecar] 未找到打包产物，改用 Python 源码回退: {}", e);
                let sidecar_path = std::env::current_dir()
                    .map_err(|e| e.to_string())?
                    .parent()
                    .ok_or("无法获取项目根目录")?
                    .join("python_sidecar");
                let python_exe =
                    std::env::var("PYTHON_EXE").unwrap_or_else(|_| "python".to_string());
                let mut cmd = Command::new(&python_exe);
                cmd.arg(sidecar_path.join("main.py"));
                cmd
            }
        };

        command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            // stdio 是 UTF-8 协议通道（见下方 writeln!），而 Windows 上 Python
            // 默认按系统区域设置取编码。中文 Windows 上实测 stdin 为
            // gbk + surrogateescape，UTF-8 字节被它解码时：
            //   "乐子"     → 静默乱码（不报错，最难发现）
            //   "古风小生" → 非法序列被兜底成 U+DCA3 代理字符
            // 代理字符一路存活到账号库 strict UTF-8 落盘才炸，报错信息里
            // 出现 \udca3 而真正的输入是正常中文，极难定位。
            // 这里显式声明，与 main.py 里的 reconfigure 构成双保险：
            // 覆盖那些不经过 main() 入口、直接运行 main.py 的场景。
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(CREATE_NO_WINDOW);
        }
        let mut process = command
            .spawn()
            .map_err(|e| format!("启动 Python sidecar 失败: {}", e))?;

        // 挂进 KILL_ON_JOB_CLOSE 的 Job：主进程被任何方式杀死时内核自动回收 sidecar
        #[cfg(windows)]
        self.assign_child_to_kill_job(process.as_raw_handle());

        // take() 失败时必须显式 kill：Child 的 Drop 只关句柄不终止子进程，
        // 否则会留下 stdio 接在管道上、永不回收的孤儿 python 进程。
        let stdin = match process.stdin.take() {
            Some(s) => s,
            None => {
                let _ = process.kill();
                let _ = process.wait();
                return Err("无法获取 sidecar stdin".to_string());
            }
        };
        let stdout = match process.stdout.take() {
            Some(s) => s,
            None => {
                let _ = process.kill();
                let _ = process.wait();
                return Err("无法获取 sidecar stdout".to_string());
            }
        };

        let epoch = self.epoch.fetch_add(1, Ordering::SeqCst) + 1;
        {
            let mut child = self.lock_child();
            *child = Some(SidecarProcess { process, stdin });
        }

        // reader 线程独占 stdout，进程退出后唤醒本代等待者
        self.alive.store(true, Ordering::SeqCst);
        let pending = Arc::clone(&self.pending);
        let alive = Arc::clone(&self.alive);
        let epoch_ref = Arc::clone(&self.epoch);
        let app_handle = self.app_handle.clone();
        thread::spawn(move || {
            reader_loop(
                BufReader::new(stdout),
                pending,
                alive,
                epoch_ref,
                epoch,
                app_handle,
            );
        });

        Ok(())
    }

    /// 丢弃已退出的 sidecar，让下一次 call() 重新拉起
    fn reset_process(&self) {
        let mut guard = self.lock_child();
        if let Some(mut proc) = guard.take() {
            let _ = proc.process.kill();
            let _ = proc.process.wait();
        }
    }

    /// 幂等强杀：无论 sidecar 是否处于优雅退出流程，确保进程被回收。
    /// Rust `Child` drop 不会杀子进程，stdin EOF 也可能被继承句柄打断，
    /// 因此关闭链路不可依赖“自动退出”，必须显式 kill。
    pub fn force_kill(&self) {
        self.alive.store(false, Ordering::SeqCst);
        self.reset_process();
        // 主动唤醒所有等待者。**不能**依赖 reader_loop 收到 EOF：
        // sidecar 可能已启动 selenium/driver 等孙进程并继承了 stdout 写句柄，
        // 此时 read_until 永不返回，pending 里的请求会阻塞到 300s 超时。
        // drain 只取走一次，与 reader_loop 的 drain 互不冲突。
        let mut map = self.lock_pending();
        for (_, (_, tx)) in map.drain() {
            let _ = tx.send(Err("sidecar 已被强制回收".to_string()));
        }
    }

    /// 关闭 sidecar：先通知 Python 侧清理（`_shutdown` 只清理不退出进程），
    /// 随后强制回收进程。sidecar 未拉起时不启动新进程。
    pub fn shutdown_sidecar(&self) -> Result<bool, String> {
        {
            let guard = self.lock_child();
            if guard.is_none() && !self.alive.load(Ordering::SeqCst) {
                return Ok(true); // 未拉起，避免 shutdown 反而创建进程
            }
        }
        // 透传 sidecar 真实返回的 closed：它会在嗅探线程 3s 内未退出时置
        // False。丢弃该值会让前端的「浏览器进程可能残留」告警成为死代码。
        let closed = match self.call("shutdown", serde_json::json!({})) {
            Ok(resp) => resp
                .get("closed")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            Err(_) => false,
        };
        self.force_kill();
        Ok(closed)
    }

    pub fn call(
        &self,
        command: &str,
        params: serde_json::Value,
    ) -> Result<serde_json::Value, String> {
        self.start()?;

        // 上一轮进程已退出：清掉残留并重启
        if !self.alive.load(Ordering::SeqCst) {
            self.reset_process();
            self.start()?;
        }

        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let epoch = self.epoch.load(Ordering::SeqCst);
        let (tx, rx) = mpsc::channel();
        self.lock_pending().insert(id, (epoch, tx));

        // 信封键是 rid 而非 id：id 是业务字段（add_account / rename_account
        // 都返回账号 id），若用 id 当信封键，Python 侧回带请求序号时会把
        // 业务 id 覆盖掉，调用方 as_str() 落空 → 「响应缺少 id 字段」。
        let request = serde_json::json!({
            "rid": id,
            "command": command,
            "params": params,
        });

        // 只在写这一行时持锁，写完立即释放
        let write_result = {
            let mut guard = self.lock_child();
            match guard.as_mut() {
                Some(proc) => writeln!(proc.stdin, "{}", request)
                    .and_then(|_| proc.stdin.flush())
                    .map_err(|e| format!("写入 sidecar 失败: {}", e)),
                None => Err("Sidecar 未运行".to_string()),
            }
        };

        if let Err(e) = write_result {
            self.lock_pending().remove(&id);
            self.reset_process();
            return Err(e);
        }

        match rx.recv_timeout(CALL_TIMEOUT) {
            Ok(result) => result,
            Err(RecvTimeoutError::Timeout) => {
                self.lock_pending().remove(&id);
                Err(format!(
                    "sidecar 命令 {} 超时（{}s 未响应）",
                    command,
                    CALL_TIMEOUT.as_secs()
                ))
            }
            Err(RecvTimeoutError::Disconnected) => {
                self.lock_pending().remove(&id);
                Err("sidecar 进程已退出".to_string())
            }
        }
    }
}

/// 独占 stdout 的读线程：事件转发前端，响应按 id 派发。
/// 用 `read_until` + `from_utf8_lossy`：无效 UTF-8 只污染单行，不会中断整个通信链路。
/// 日志安全：sidecar 的 stdout 协议通道里混着凭据（qr_poll 成功响应含完整
/// Cookie、x25Kn 请求的 query 含 HMAC 根密钥 benchmark）。凡是要打印
/// 原始协议行的诊断点都必须先过这里，否则一行 eprintln! 就能把凭据写进
/// stderr —— 而 stderr 是 Stdio::inherit()，从 cmd 启动时直接可见。
fn safe_log_line(raw: &str) -> String {
    const MAX: usize = 200;
    let mut out = raw.to_string();
    for key in [
        "cookie",
        "sessdata",
        "bili_jct",
        "csrf",
        "token",
        "benchmark",
        "access_key",
        "corpsecret",
        "secret_key",
    ] {
        out = redact_key(&out, key);
    }
    if out.chars().count() > MAX {
        let truncated: String = out.chars().take(MAX).collect();
        format!("{}…（已截断，共 {} 字节）", truncated, raw.len())
    } else {
        out
    }
}

/// 把 `key=<值>` / `"key":"<值>"` 形态里 `<值>` 换成 ***（可多次出现）。
/// 手写而非引入 regex 依赖：Rust 标准库无 regex。
/// 键之后允许 `"key" : value` 这种 JSON 形态（引号 + 可选空白 + 冒号）；
/// 值的终止符分两种：JSON 形态取到配对收尾引号（Cookie 内部的 `;` `=` 不会被
/// 误截），查询串形态取到 `&` `?` 空白等分隔符。
fn redact_key(text: &str, key: &str) -> String {
    let lower = text.to_ascii_lowercase();
    let needle = key.to_ascii_lowercase();
    let bytes = text.as_bytes();
    let mut out = String::with_capacity(text.len());
    let mut copied = 0usize;
    let mut search_from = 0usize;

    while let Some(rel) = lower[search_from..].find(&needle) {
        let key_start = search_from + rel;
        let after_key = key_start + needle.len();

        // 键边界：前一字符若是标识符字符或撇号，说明这个 key 是更长
        // token 的一部分（如 tokenize 里的 token），必须跳过。
        // 注意：前一字符是 `"` 要**接受** —— 那正是 JSON 键的开引号
        // （{"cookie": ...}），排除它会导致所有 JSON 键一个都脱敏不到。
        let prev_ok = key_start == 0
            || !matches!(lower[..key_start].chars().next_back(), Some(c)
                if c.is_alphanumeric() || c == '_' || c == '\'');
        if !prev_ok {
            search_from = after_key;
            continue;
        }

        let mut i = after_key;
        while i < bytes.len() && (bytes[i] as char).is_whitespace() {
            i += 1;
        }
        if i < bytes.len() && (bytes[i] == b'"' || bytes[i] == b'\'') {
            i += 1;
            while i < bytes.len() && (bytes[i] as char).is_whitespace() {
                i += 1;
            }
        }
        if i >= bytes.len() || (bytes[i] != b'=' && bytes[i] != b':') {
            search_from = after_key;
            continue;
        }
        let is_json = bytes[i] == b':';
        i += 1;
        while i < bytes.len() && (bytes[i] as char).is_whitespace() {
            i += 1;
        }

        let mut quoted = false;
        if is_json && i < bytes.len() && (bytes[i] == b'"' || bytes[i] == b'\'') {
            quoted = true;
            i += 1;
        }

        let value_start = i;
        let value_end = if quoted {
            let mut j = i;
            let mut escaped = false;
            while j < bytes.len() {
                if escaped {
                    escaped = false;
                } else if bytes[j] == b'\\' {
                    escaped = true;
                } else if bytes[j] == b'"' {
                    break;
                }
                j += 1;
            }
            j
        } else {
            let mut j = i;
            while j < bytes.len() {
                let c = bytes[j];
                if c == b'"'
                    || c == b'\''
                    || c == b','
                    || c == b'}'
                    || c == b'&'
                    || c == b'?'
                    || (c as char).is_whitespace()
                {
                    break;
                }
                j += 1;
            }
            j
        };

        if value_end <= value_start {
            search_from = after_key;
            continue;
        }
        out.push_str(&text[copied..value_start]);
        out.push_str("***");
        copied = value_end;
        search_from = value_end;
    }

    if copied == 0 {
        return text.to_string();
    }
    out.push_str(&text[copied..]);
    out
}

fn reader_loop(
    mut reader: BufReader<ChildStdout>,
    pending: PendingMap,
    alive: Arc<AtomicBool>,
    epoch_ref: Arc<AtomicU64>,
    my_epoch: u64,
    app_handle: tauri::AppHandle,
) {
    loop {
        let mut buf: Vec<u8> = Vec::new();
        match reader.read_until(b'\n', &mut buf) {
            Ok(0) => break, // EOF：进程退出
            Ok(_) => {}
            Err(e) => {
                eprintln!("读取 sidecar 失败: {}", e);
                break;
            }
        }

        let line = String::from_utf8_lossy(&buf);
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }

        let value: serde_json::Value = match serde_json::from_str(trimmed) {
            Ok(value) => value,
            Err(e) => {
                eprintln!(
                    "解析 sidecar 响应失败: {}（原始行已脱敏截断: {}）",
                    e,
                    safe_log_line(trimmed)
                );
                continue;
            }
        };

        // 事件行没有 id，直接转发
        if value.get("type").and_then(|v| v.as_str()) == Some("event") {
            let event_name = value
                .get("event")
                .and_then(|v| v.as_str())
                .unwrap_or("sidecar-event");
            let data = value
                .get("data")
                .cloned()
                .unwrap_or(serde_json::Value::Null);
            if let Err(e) = app_handle.emit(event_name, &data) {
                eprintln!("转发 sidecar 事件失败: {}", e);
            }
            continue;
        }

        // 先把请求序号取成 u64（Copy），再决定把 value 当成功值还是错误值。
        // 读 rid 而非 id：响应里的 id 是业务字段（账号 id），拿它当路由键
        // 会把响应派给错误的等待者，或根本派不出去。
        let id = value.get("rid").and_then(|v| v.as_u64());

        let result = match value.get("error") {
            Some(error) if !error.is_null() => {
                // 保留原始结构：若 sidecar 改成结构化错误
                // （{"error":{"code":...,"msg":...}}），as_str() 会返回 None，
                // 用户只看到「未知错误」且原始原因被永久丢弃。
                Err(match error.as_str() {
                    Some(s) => s.to_string(),
                    None => error.to_string(),
                })
            }
            _ => Ok(value),
        };

        match id {
            Some(id) => {
                let waiter = {
                    let mut map = pending.lock().unwrap_or_else(|e| e.into_inner());
                    map.remove(&id).map(|(_, tx)| tx)
                };
                match waiter {
                    Some(tx) => {
                        let _ = tx.send(result);
                    }
                    None => eprintln!("收到未知 id 的 sidecar 响应: {}", id),
                }
            }
            None => eprintln!("缺少 rid 的 sidecar 响应: {}", safe_log_line(trimmed)),
        }
    }

    // 代次保护：只有仍是当前代时才置 alive=false。
    // 若本进程已被 reset+start 取代，新进程明明活着却被误标为已死，
    // 下一条命令会再次 reset 把健康进程杀掉。
    if epoch_ref.load(Ordering::SeqCst) == my_epoch {
        alive.store(false, Ordering::SeqCst);
    }
    // 只清理本代请求：新一代的请求与本进程无关，误判死会导致
    // 调用方收到假错误「sidecar 进程已退出」而新进程稍后才真的回包。
    let mut map = pending.lock().unwrap_or_else(|e| e.into_inner());
    let dead: Vec<u64> = map
        .iter()
        .filter(|(_, (e, _))| *e == my_epoch)
        .map(|(id, _)| *id)
        .collect();
    for id in dead {
        if let Some((_, tx)) = map.remove(&id) {
            let _ = tx.send(Err("sidecar 进程已退出".to_string()));
        }
    }
}

#[tauri::command]
pub fn get_accounts(sidecar: tauri::State<'_, SidecarManager>) -> Result<Vec<Account>, String> {
    let resp = sidecar.call("get_accounts", serde_json::json!({}))?;
    let accounts = resp
        .get("accounts")
        .and_then(|v| v.as_array())
        .ok_or("无效的响应")?;

    let result: Vec<Account> = accounts
        .iter()
        // id 缺失必须硬失败，不能 unwrap_or("") 降级成空串：
        // 前端拿空 id 去比对选中态必然失配，选中会被重置到首行，
        // 而底部「备注 / 删除」按钮会指向一个不存在的账号。
        // 宁可整个列表加载失败并报错，也不要交出看似正常的错误数据。
        // remark 为空是合法的（前端会回退到 id 前 8 位），故仍用默认值。
        .map(|a| {
            Ok(Account {
                id: a
                    .get("id")
                    .and_then(|v| v.as_str())
                    .ok_or("账号响应缺少 id 字段")?
                    .to_string(),
                remark: a
                    .get("remark")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                running: a.get("running").and_then(|v| v.as_bool()).unwrap_or(false),
            })
        })
        .collect::<Result<Vec<_>, String>>()?;

    Ok(result)
}

#[tauri::command]
pub async fn add_account(
    cookie: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<Account, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call("add_account", serde_json::json!({ "cookie": cookie }))?;

        Ok(Account {
            // 理由同 get_accounts：空 id 会破坏前端选中态
            id: resp
                .get("id")
                .and_then(|v| v.as_str())
                .ok_or("添加账号响应缺少 id 字段")?
                .to_string(),
            remark: resp
                .get("remark")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
            running: false,
        })
    })
    .await
}

#[tauri::command]
pub fn remove_account(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<(), String> {
    sidecar.call(
        "remove_account",
        serde_json::json!({ "account_id": account_id }),
    )?;
    Ok(())
}

#[tauri::command]
pub fn rename_account(
    account_id: String,
    remark: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<Account, String> {
    let resp = sidecar.call(
        "rename_account",
        serde_json::json!({
            "account_id": account_id,
            "remark": remark,
        }),
    )?;

    Ok(Account {
        id: resp
            .get("id")
            .and_then(|v| v.as_str())
            .ok_or("重命名响应缺少 id 字段")?
            .to_string(),
        remark: resp
            .get("remark")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        running: resp
            .get("running")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
    })
}

/// 按给定顺序重排账号（前端拖拽排序）。
///
/// 同步命令（不是 `call_blocking`）：这个调用只做一次本地 JSON 落盘，
/// 不碰网络、不启子进程，耗时在毫秒级 —— 与 `remove_account` 同档。
/// 用 async + `call_blocking` 反而要额外占一个阻塞线程池名额。
///
/// 后端会校验 `ordered_ids` 必须是**当前账号集合的一个排列**（不缺不多），
/// 不满足就返回 Err，前端据此回滚本地顺序。
#[tauri::command]
pub fn reorder_accounts(
    ordered_ids: Vec<String>,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<(), String> {
    sidecar.call(
        "reorder_accounts",
        serde_json::json!({ "ordered_ids": ordered_ids }),
    )?;
    Ok(())
}

#[tauri::command]
pub async fn start_miner(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<(), String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        mgr.call(
            "start_miner",
            serde_json::json!({
                "account_id": account_id,
            }),
        )?;
        Ok(())
    })
    .await
}

#[tauri::command]
pub async fn stop_miner(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<(), String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        mgr.call(
            "stop_miner",
            serde_json::json!({ "account_id": account_id }),
        )?;
        Ok(())
    })
    .await
}

#[tauri::command]
pub fn get_account_status(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<AccountStatus, String> {
    let resp = sidecar.call(
        "get_account_status",
        serde_json::json!({ "account_id": account_id }),
    )?;

    let progress = resp.get("progress").and_then(|v| {
        if v.is_null() {
            return None;
        }
        Some(ProgressValues {
            cur: v.get("cur").and_then(|x| x.as_f64()).unwrap_or(0.0),
            limit: v.get("limit").and_then(|x| x.as_f64()).unwrap_or(0.0),
            // sidecar 可能返回浮点百分比，as_i64() 对 JSON 浮点会返回 None
            // 从而静默变 0（进度条显示 0%）。用 as_f64 + round 更稳。
            percent: v
                .get("percent")
                .and_then(|x| x.as_f64())
                .map(|f| f.round() as i32)
                .unwrap_or(0),
        })
    });

    // 任务级对象由 refresh_tasks 提供；sidecar 在这里预留 task_progress 键
    let task_progress = resp
        .get("task_progress")
        .cloned()
        .filter(|v| !v.is_null())
        .map(serde_json::from_value)
        .transpose()
        .map_err(|e| format!("解析任务进度失败: {}", e))?;

    Ok(AccountStatus {
        account_id: resp
            .get("account_id")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        running: resp
            .get("running")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        watch_time_seconds: resp
            .get("watch_time_seconds")
            .and_then(|v| v.as_u64())
            .unwrap_or(0),
        status_line: resp
            .get("status_line")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        task_progress,
        progress,
        login_invalidated: resp
            .get("login_invalidated")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
    })
}

/// 把 sidecar 的配置响应解析成 `GuiConfigValues`。
///
/// 严格解析：配置是唯一真值来源，前端会用返回值整体替换 Pinia 里的
/// config，并在关窗时 save() 回写。若这里用 unwrap_or 兜底，sidecar 返回
/// 结构不符（如版本不匹配返回 {}）时 GUI 会静默显示 60 线程/8 秒重连/
/// 开启通知，关窗后把用户真实配置覆盖成默认值且无任何提示。
/// 只有确实可选的字段（cookie、task_ids）才允许缺失。
fn parse_config_values(resp: &serde_json::Value) -> Result<GuiConfigValues, String> {
    let text = |key: &str, fallback: &str| -> String {
        match resp.get(key) {
            Some(serde_json::Value::String(s)) => s.clone(),
            Some(serde_json::Value::Null) | None => fallback.to_string(),
            Some(other) => other.to_string(),
        }
    };
    let boolean = |key: &str, fallback: bool| -> bool {
        match resp.get(key) {
            Some(serde_json::Value::Bool(b)) => *b,
            Some(serde_json::Value::Null) | None => fallback,
            Some(_) => fallback,
        }
    };

    if !resp.is_object() {
        return Err("sidecar 返回的配置不是对象，配置未加载".to_string());
    }

    Ok(GuiConfigValues {
        cookie: text("cookie", ""),
        rooms_text: text("rooms_text", ""),
        thread_count_text: text("thread_count_text", "60"),
        reconnect_delay_text: text("reconnect_delay_text", "8"),
        task_ids_text: text("task_ids_text", ""),
        task_query_interval_text: text("task_query_interval_text", "30"),
        notify_urls_text: text("notify_urls_text", ""),
        notify_on_task_complete: boolean("notify_on_task_complete", true),
        verbose: boolean("verbose", false),
        auto_claim_rewards: boolean("auto_claim_rewards", false),
    })
}

#[tauri::command]
pub fn save_config(
    config: GuiConfigValues,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<GuiConfigValues, String> {
    // sidecar 直接回带落盘后的真实值，前端不必再发一次 load_config。
    // 两趟往返之间任何一次后端钳制都可能静默改掉用户刚填的内容
    // （实测：自动获取到的任务 ID 点一次保存就被重排）。
    let resp = sidecar.call("save_config", serde_json::json!({ "config": config }))?;
    parse_config_values(&resp)
}

#[tauri::command]
pub fn load_config(sidecar: tauri::State<'_, SidecarManager>) -> Result<GuiConfigValues, String> {
    let resp = sidecar.call("load_config", serde_json::json!({}))?;
    parse_config_values(&resp)
}

#[tauri::command]
pub async fn qr_login(sidecar: tauri::State<'_, SidecarManager>) -> Result<QrChallenge, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call("qr_login", serde_json::json!({}))?;
        serde_json::from_value(resp).map_err(|e| format!("解析二维码响应失败: {}", e))
    })
    .await
}

#[tauri::command]
pub async fn qr_poll(
    qr_key: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<QrPollResult, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call("qr_poll", serde_json::json!({ "qr_key": qr_key }))?;
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
    })
    .await
}

#[tauri::command]
pub fn qr_cancel(sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("qr_cancel", serde_json::json!({}))?;
    Ok(())
}

#[tauri::command]
pub async fn browser_capture(
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<String, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call("browser_capture", serde_json::json!({ "browser": browser }))?;
        Ok(resp
            .get("cookie")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string())
    })
    .await
}

#[tauri::command]
pub async fn send_notification(
    title: String,
    body: String,
    notify_urls: Option<Vec<String>>,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<bool, String> {
    // 必须透传 notify_urls：缺省时 sidecar 会回落到 _config_data 里
    // 上次 save_config 落盘的 URL（该字典只在 save/import 时更新），
    // 于是「测试通知」测的不是用户输入框里刚填的内容。
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call(
            "send_notification",
            serde_json::json!({
                "title": title,
                "body": body,
                "notify_urls": notify_urls,
            }),
        )?;
        Ok(resp
            .get("success")
            .and_then(|v| v.as_bool())
            .unwrap_or(false))
    })
    .await
}

#[tauri::command]
pub async fn claim_rewards(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<ClaimRewardsResult, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call(
            "claim_rewards",
            serde_json::json!({ "account_id": account_id }),
        )?;
        let results = resp
            .get("results")
            .cloned()
            .map(serde_json::from_value)
            .transpose()
            .map_err(|e| format!("解析领取结果失败: {}", e))?
            .unwrap_or_default();

        Ok(ClaimRewardsResult {
            success: resp
                .get("success")
                .and_then(|v| v.as_bool())
                .unwrap_or(false),
            results,
            text: resp
                .get("text")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string(),
        })
    })
    .await
}

#[tauri::command]
pub async fn refresh_tasks(
    account_id: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<RefreshTasksResult, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call(
            "refresh_tasks",
            serde_json::json!({ "account_id": account_id }),
        )?;
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
    })
    .await
}

#[tauri::command]
pub async fn auto_fetch_room_id(
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<FetchRoomIdResult, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call(
            "auto_fetch_room_id",
            serde_json::json!({ "browser": browser }),
        )?;
        serde_json::from_value(resp).map_err(|e| format!("解析房间号失败: {}", e))
    })
    .await
}

#[tauri::command]
pub async fn auto_fetch_task_ids(
    room_id: i64,
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<FetchTaskIdsResult, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call(
            "auto_fetch_task_ids",
            serde_json::json!({ "room_id": room_id, "browser": browser }),
        )?;
        serde_json::from_value(resp).map_err(|e| format!("解析任务组失败: {}", e))
    })
    .await
}

#[tauri::command]
pub async fn auto_fetch_task_ids_mode2(
    room_id: Option<i64>,
    sidecar: tauri::State<'_, SidecarManager>,
    browser: Option<String>,
) -> Result<FetchTaskIdsMode2Result, String> {
    let mgr = sidecar.inner().clone();
    call_blocking(move || {
        let resp = mgr.call(
            "auto_fetch_task_ids_mode2",
            serde_json::json!({ "room_id": room_id, "browser": browser }),
        )?;
        serde_json::from_value(resp).map_err(|e| format!("解析任务组失败: {}", e))
    })
    .await
}

/// 校验配置导入/导出的路径：Rust 侧才是信任边界，IPC 参数可由 WebView
/// 任意构造（叠加 csp 收紧前的状态）。只接受绝对路径的 .json 文件，
/// 拒绝相对路径、UNC、设备路径与扩展名不符的情况。
fn validate_config_path(path: &str) -> Result<(), String> {
    let trimmed = path.trim();
    if trimmed.is_empty() {
        return Err("路径为空".to_string());
    }
    if trimmed.starts_with("\\\\") || trimmed.starts_with("//") {
        return Err("不接受网络共享路径".to_string());
    }
    // 设备路径：\\?\ 、\\.\ 、CON、NUL 等
    if trimmed.contains("\\\\?\\") || trimmed.contains("\\\\.\\") {
        return Err("不接受设备路径".to_string());
    }
    let p = std::path::Path::new(trimmed);
    if !p.is_absolute() {
        return Err("只接受绝对路径".to_string());
    }
    let ext_ok = p
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.eq_ignore_ascii_case("json"))
        .unwrap_or(false);
    if !ext_ok {
        return Err("配置文件必须是 .json 扩展名".to_string());
    }
    Ok(())
}

#[tauri::command]
pub fn export_config(
    path: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<String, String> {
    validate_config_path(&path)?;
    let resp = sidecar.call("export_config", serde_json::json!({ "path": path }))?;
    Ok(resp
        .get("path")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string())
}

#[tauri::command]
pub fn import_config(
    path: String,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<GuiConfigValues, String> {
    validate_config_path(&path)?;
    let resp = sidecar.call("import_config", serde_json::json!({ "path": path }))?;
    serde_json::from_value(resp).map_err(|e| format!("解析配置失败: {}", e))
}

#[tauri::command]
pub fn sync_config_to_miners(sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("sync_config_to_miners", serde_json::json!({}))?;
    Ok(())
}

#[tauri::command]
pub fn shutdown(sidecar: tauri::State<'_, SidecarManager>) -> Result<ShutdownResult, String> {
    // 透传 sidecar 实算的 closed（嗅探线程 3s 内未退出时为 false），
    // 硬编码 true 会让前端的残留告警成为永不可达的死代码。
    let closed = sidecar.shutdown_sidecar()?;
    Ok(ShutdownResult { closed })
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

/// 更新页 URL 白名单：opener 插件已限制 scheme 为 http/https/mailto/tel
/// （file:// 与自定义协议已被挡住），但 host 无限——被劫持的更新源
/// 仍能把用户导向钓鱼页。这里在 Rust 侧再加一道，
/// 不合规时置空，前端会退化为「仅提示版本号」而不会打开任何链接。
const RELEASE_URL_ALLOWED_PREFIXES: &[&str] = &[
    "https://github.com/",
    "https://raw.githubusercontent.com/",
    "https://api.github.com/",
];

/// `force` 供前端的手动「检查更新」按钮使用：启动时的自动检查不传，
/// 仍受 sidecar 侧的 update_channel 门禁约束（dev 包不去打扰 GitHub API）。
#[tauri::command]
pub fn check_update(
    force: Option<bool>,
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<UpdateCheckResult, String> {
    let resp = sidecar.call("check_update", serde_json::json!({ "force": force }))?;
    let raw = resp
        .get("release_url")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let safe = RELEASE_URL_ALLOWED_PREFIXES
        .iter()
        .any(|p| raw.starts_with(p));
    Ok(UpdateCheckResult {
        update_available: resp
            .get("update_available")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        latest_version: resp
            .get("latest_version")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        release_url: if safe { raw } else { String::new() },
    })
}

#[derive(Debug, Serialize, Deserialize)]
pub struct BrowserDetection {
    pub available: Vec<String>,
    pub default: String,
    pub labels: std::collections::HashMap<String, String>,
}

#[tauri::command]
pub fn detect_browsers(
    sidecar: tauri::State<'_, SidecarManager>,
) -> Result<BrowserDetection, String> {
    let resp = sidecar.call("detect_browsers", serde_json::json!({}))?;
    Ok(BrowserDetection {
        available: resp
            .get("available")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|x| x.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default(),
        default: resp
            .get("default")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        labels: resp
            .get("labels")
            .and_then(|v| v.as_object())
            .map(|obj| {
                obj.iter()
                    .filter_map(|(k, v)| v.as_str().map(|s| (k.clone(), s.to_string())))
                    .collect()
            })
            .unwrap_or_default(),
    })
}

/// 切换详细日志级别（勾选即生效，不必等「保存配置」）。
///
/// 同步直调即可：sidecar 侧只是 `logging.getLogger(...).setLevel()`，
/// 纯本地无 IO，不会占住 IPC 接收线程。
#[tauri::command]
pub fn set_verbose(verbose: bool, sidecar: tauri::State<'_, SidecarManager>) -> Result<(), String> {
    sidecar.call("set_verbose", serde_json::json!({ "verbose": verbose }))?;
    Ok(())
}

#[cfg(test)]
mod response_envelope_tests {
    use super::parse_config_values;
    use serde_json::json;

    /// 信封 rid 与业务 id 同处一个对象时，必须各自完好。
    ///
    /// 这就是 rename_account / add_account 报「响应缺少 id 字段」的根因：
    /// 两侧曾共用 `id` 作信封键，Python 侧回带请求序号时把业务 id 覆盖成数字。
    /// 回归锁：任何时候协议都不得让两者互相污染。
    #[test]
    fn envelope_rid_does_not_clobber_business_id() {
        let line = json!({
            "rid": 42u64,
            "id": "b34547f0e1a2",
            "remark": "古风小生",
            "running": false,
        });
        assert_eq!(line.get("rid").and_then(|v| v.as_u64()), Some(42));
        assert_eq!(
            line.get("id").and_then(|v| v.as_str()),
            Some("b34547f0e1a2"),
            "业务 id 必须仍是字符串"
        );
    }

    /// save_config 的回包必须能被 load_config 的解析器接受：
    /// 两者共用 parse_config_values，语义漂移会立刻在这里暴露。
    #[test]
    fn saved_config_round_trips_through_shared_parser() {
        let saved = json!({
            "rid": 7u64,
            "cookie": "",
            "rooms_text": "23612045",
            "thread_count_text": "60",
            "reconnect_delay_text": "8",
            // 保序：不得被排序打乱（B站 ID 无语义序，排序只会破坏用户看到的顺序）
            "task_ids_text": "6ERAcwloghvp4i00,6ERAcwloghvaa000",
            "task_query_interval_text": "30",
            "notify_urls_text": "",
            "notify_on_task_complete": true,
            "verbose": false,
            "auto_claim_rewards": false,
        });
        let parsed = parse_config_values(&saved).expect("回包应可解析");
        assert_eq!(parsed.task_ids_text, "6ERAcwloghvp4i00,6ERAcwloghvaa000");
        assert_eq!(parsed.rooms_text, "23612045");
    }

    #[test]
    fn rejects_non_object_config_response() {
        let bad = json!([1, 2, 3]);
        assert!(
            parse_config_values(&bad).is_err(),
            "非对象必须硬失败而不是静默兜底"
        );
    }
}

#[cfg(test)]
mod log_redaction_tests {
    use super::redact_key;
    use super::safe_log_line;

    #[test]
    fn redacts_cookie_in_json_response() {
        // qr_poll 成功响应的真实形态：cookie 里含分号与等号
        let raw = r#"{"status":"success","cookie":"SESSDATA=abc123; bili_jct=def456"}"#;
        let out = safe_log_line(raw);
        assert!(!out.contains("abc123"), "SESSDATA 值泄漏: {}", out);
        assert!(!out.contains("def456"), "bili_jct 值泄漏: {}", out);
        assert!(out.contains("cookie"), "键名应保留: {}", out);
        assert!(out.contains("***"), "值应被整体替换: {}", out);
    }

    #[test]
    fn redacts_benchmark_query_param() {
        // x25Kn 的 HMAC 根密钥走 benchmark 查询参数
        let raw =
            "GET https://api.live.bilibili.com/xlive/x25kn?benchmark=SECRET123&room=123 HTTP/1.1";
        let out = safe_log_line(raw);
        assert!(!out.contains("SECRET123"), "benchmark 根密钥泄漏: {}", out);
        assert!(out.contains("room=123"), "非敏感参数应保留: {}", out);
    }

    #[test]
    fn redacts_corpsecret() {
        let raw = r#"{"error":"企业微信 gettoken 失败: https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpsecret=TOPSECRET"}"#;
        let out = safe_log_line(raw);
        assert!(!out.contains("TOPSECRET"), "corpsecret 泄漏: {}", out);
    }

    #[test]
    fn truncates_long_lines() {
        let raw = "x".repeat(5000);
        let out = safe_log_line(&raw);
        assert!(out.contains("已截断"), "长行未标注截断");
        assert!(
            out.chars().count() < 300,
            "截断后仍过长: {}",
            out.chars().count()
        );
    }

    #[test]
    fn does_not_match_substrings_of_other_keys() {
        // tokenize 不应被当成 token
        let out = redact_key(r#"{"tokenize":"abcdef"}"#, "token");
        assert!(
            out.contains("abcdef"),
            "键边界判断错误，误伤了别的键: {}",
            out
        );
    }

    #[test]
    fn idempotent_on_already_redacted() {
        // 值用 LEAF 而非 secret（后者是键名 cookie/secret_key 的子串，
        // 会让断言产生假阳性）
        let raw = r#"{"cookie":"LEAF"}"#;
        let once = safe_log_line(raw);
        let twice = safe_log_line(&once);
        assert!(!once.contains("LEAF"), "一次脱敏后仍泄漏: {}", once);
        assert!(!twice.contains("LEAF"), "二次脱敏后仍泄漏: {}", twice);
        assert!(once.contains(r#""cookie":"***""#), "形态异常: {}", once);
    }
}

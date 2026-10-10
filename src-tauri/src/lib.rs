// Tauri 2 惯例：全部 Builder 配置集中在 lib 的 run()，bin 只做入口。
// 原先 main.rs 持有全部逻辑、lib.rs 只有 7 行残缺副本，导致移动端入口
// 下**全部命令**都不存在、dialog 插件未注册（而 capabilities 仍授予
// dialog:default），两处配置也已经开始漂移。
// （这里刻意不写死命令条数：写过「25 个」而实际一直是 26，条数随功能增删会漂移。）
pub mod commands;

use tauri::Manager;

/// AppUserModelID：影响任务栏分组与通知归属。
/// 必须与 tauri.conf.json 的 identifier / productName 保持同源语义，
/// 改产品名时容易漏改，故集中在此处。
const APP_USER_MODEL_ID: &str = "OverwatchDropsMiner.GUI.1";

pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let app_handle = app.handle().clone();
            app.manage(commands::SidecarManager::new(app_handle));
            #[cfg(windows)]
            {
                unsafe {
                    // 失败（如已被 WebView2 以 MTA 初始化）不致命，
                    // 但要留下日志——静默忽略会让 COM 相关故障无从排查。
                    let hr = windows::Win32::System::Com::CoInitializeEx(
                        None,
                        windows::Win32::System::Com::COINIT_APARTMENTTHREADED,
                    );
                    if hr.is_err() {
                        eprintln!("[tauri] CoInitializeEx 失败: {:?}", hr);
                    }
                    let app_user_model_id: Vec<u16> = APP_USER_MODEL_ID
                        .encode_utf16()
                        .chain(std::iter::once(0))
                        .collect();
                    // 进程级一次性初始化，不配对 CoUninitialize（进程即将长期运行）
                    let _ = windows::Win32::UI::Shell::SetCurrentProcessExplicitAppUserModelID(
                        windows::core::PCWSTR(app_user_model_id.as_ptr()),
                    );
                }
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_accounts,
            commands::add_account,
            commands::remove_account,
            commands::rename_account,
            commands::reorder_accounts,
            commands::start_miner,
            commands::stop_miner,
            commands::get_account_status,
            commands::save_config,
            commands::load_config,
            commands::set_verbose,
            commands::qr_login,
            commands::qr_poll,
            commands::qr_cancel,
            commands::browser_capture,
            commands::send_notification,
            commands::claim_rewards,
            commands::refresh_tasks,
            commands::auto_fetch_room_id,
            commands::auto_fetch_task_ids,
            commands::auto_fetch_task_ids_mode2,
            commands::export_config,
            commands::import_config,
            commands::sync_config_to_miners,
            commands::shutdown,
            commands::check_update,
            commands::detect_browsers,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    app.run(|app_handle, event| {
        // 兜底：ExitRequested 时强制回收 sidecar。
        // 覆盖前端超时直接 destroy、关闭流程中断等未走到 shutdown 命令的路径。
        if let tauri::RunEvent::ExitRequested { .. } = event {
            if let Some(manager) = app_handle.try_state::<commands::SidecarManager>() {
                manager.force_kill();
            }
        }
    });
}

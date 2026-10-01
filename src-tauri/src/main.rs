// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use tauri::Manager;

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let app_handle = app.handle().clone();
            app.manage(commands::SidecarManager::new(app_handle));
            #[cfg(windows)]
            {
                unsafe {
                    let _ = windows::Win32::System::Com::CoInitializeEx(
                        None,
                        windows::Win32::System::Com::COINIT_APARTMENTTHREADED,
                    );
                    let app_user_model_id: Vec<u16> = "OverwatchDropsMiner.GUI.1"
                        .encode_utf16()
                        .chain(std::iter::once(0))
                        .collect();
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
            commands::start_miner,
            commands::stop_miner,
            commands::get_account_status,
            commands::save_config,
            commands::load_config,
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

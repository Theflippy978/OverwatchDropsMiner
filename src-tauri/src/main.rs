// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let app_handle = app.handle().clone();
            app.manage(commands::SidecarManager::new(app_handle));
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
            commands::update_notify_urls,
            commands::stop_all,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}



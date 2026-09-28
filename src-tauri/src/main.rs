// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(commands::SidecarManager::new(app.handle().clone()))
        .invoke_handler(tauri::generate_handler![
            commands::get_accounts,
            commands::add_account,
            commands::remove_account,
            commands::start_miner,
            commands::stop_miner,
            commands::get_account_status,
            commands::save_config,
            commands::load_config,
            commands::qr_login,
            commands::browser_capture,
            commands::claim_rewards,
            commands::refresh_tasks,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}



// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // crate 名带 _lib 后缀是 Tauri 2 的脚手架惯例（lib name 与 bin 同名会冲突），
    // 与包名 overwatch-drops-miner 不是同一件事。
    overwatch_drops_miner_lib::run()
}

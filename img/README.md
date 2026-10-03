# img/ —— 源素材（非运行时产物）

> 这里放**源文件**，不是给程序运行时读的。删之前先看本文档。

| 文件 | 用途 | 谁引用 |
|---|---|---|
| `app.ico` | **应用图标源文件**。改图标后用 `pnpm tauri icon img/app.ico` 重新生成 `src-tauri/icons/` | README 文档说明 |
| `run.png` | README 里的运行截图 | README.md |
| `hero.svg` | README 顶部的横幅图 | README.md |

## 与 `public/app.ico` 的关系

两者内容**字节相同**（SHA256 一致）但职责不同，**都要保留**：

- `img/app.ico` —— 源文件，供 `tauri icon` 生成全套图标 + README 说明用
- `public/app.ico` —— Vite 会把 `public/` 整个复制到 `dist/`，`index.html` 的
  `<link rel="icon" href="/app.ico">` 从这里取，是**运行时**的 web favicon

删掉 `public/app.ico` 会导致网页端图标 404；删掉 `img/app.ico` 则失去图标源文件。

## 已清理的零引用文件（2026-10-02）

`public/tauri.svg`、`public/vite.svg`、`img/app.png` —— Vite/Tauri 脚手架模板
遗留，全仓库零引用。删前已用 grep 核对 `index.html` / `src/**` /
`tauri.conf.json` / `README.md`，确认无任何引用点。

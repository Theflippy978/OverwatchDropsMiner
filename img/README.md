# img/ —— 源素材（非运行时产物）

> 这里放**源文件**，不是给程序运行时读的。删之前先看本文档。

| 文件 | 用途 | 谁引用 |
|---|---|---|
| `app.ico` | **唯一的图标源文件**：exe / 任务栏 / 资源管理器 / 任务管理器 / 标题栏全部由它生成。改图标后跑 `pnpm tauri icon img/app.ico` 重新生成 `src-tauri/icons/` | `tauri.conf.json` 的 `bundle.icon`（经 `src-tauri/icons/`）与 `TitleBar.vue` |
| `run.png` | README 里的运行截图 | `README.md` |
| `hero.svg` | README 顶部的横幅图（纯 SVG，直接由 GitHub 渲染） | `README.md` |

## `hero.svg` 的维护要点

**配色取自应用自身**，改主题令牌后这里要跟着改：

| 用途 | 取值 | 来源 |
|---|---|---|
| 横幅底色 | `#FFFFFF` | 浅色主题 `--color-background` |
| 主文字 | `#0A0A0A` | 浅色主题 `--color-foreground` |
| 次要文字 | `#737373` | 浅色主题 `--color-muted-foreground` |
| 卡片/描边 | `#F5F5F5` / `#E5E5E5` | `--color-secondary` / `--color-border` |
| 进度条填充 | `#171717` | 浅色主题 `--color-primary`（对应 `bg-primary`） |
| 状态绿 | `#1B7E2A` | 浅色主题 `--color-signal-success` |
| 强调橙 | `#EF7E06` | 应用图标主色（取自 `src-tauri/icons/128x128.png`） |

**程序图标以 base64 内嵌在 `<image href="data:image/png;base64,...">` 里**，
内容是 `src-tauri/icons/128x128.png` 本身。这样做的原因：

- README 里的 SVG **不能**用相对路径引用同目录的 PNG —— GitHub 渲染 SVG 时
  不会去解析仓库内的相对资源，图会裂；
- 用 `data:` URI 内嵌是唯一既能显示**真图**、又不产生外部请求的方式；
- 换图标后要**重新注入** base64：跑 `pnpm tauri icon img/app.ico` 生成新图标集后，
  把新的 `src-tauri/icons/128x128.png` 转 base64 替换 `<image>` 的 `href`。

横幅内容需与真实界面保持一致（账号名、状态字段、检查点文案都取自实际界面），
改 UI 文案后记得同步，否则 README 展示的是不存在的界面。

## 当前图标（2026-10-06 收口为单一来源）

**只有一个图标源，全应用同源。**

| 落地位置 | 消费方 |
|---|---|
| `src-tauri/icons/` 全套（由 `tauri icon` 生成） | exe 内嵌图标资源 → 任务栏 / 资源管理器 / 任务管理器 |
| 同一套里的 `src-tauri/icons/128x128.png` | **标题栏**（`TitleBar.vue` 直接 import 这个 PNG） |

标题栏刻意**引用图标集里的那一帧**而不是另存一份副本：副本方案曾导致
「任务管理器里是 A、标题栏里是 B」，而两处不一致时没有任何机制会报错。
现在换图标只有一条路径 —— 覆盖 `img/app.ico` 再跑 `pnpm tauri icon img/app.ico`，
标题栏会自动跟随。

`pnpm tauri icon` 会额外生成 `src-tauri/icons/android/` 与 `src-tauri/icons/ios/`
两个目录。本项目只有 Windows 桌面端，这两套是纯冗余，**生成后直接删掉**
（已按此处理一次，别让它进版本库）。

## 与 `public/app.ico` 的关系

两者内容**字节相同**（SHA256 一致）但职责不同，**都要保留**：

- `img/app.ico` —— 源文件，供 `tauri icon` 生成全套图标
- `public/app.ico` —— Vite 会把 `public/` 整个复制到 `dist/`，
  `index.html` 的 `<link rel="icon" href="/app.ico">` 从这里取，是**运行时**的 web favicon

删掉 `public/app.ico` 会导致网页端图标 404；删掉 `img/app.ico` 则失去图标源文件。

## 已清理的零引用文件（2026-10-02）

`public/tauri.svg`、`public/vite.svg`、`img/app.png` —— Vite/Tauri 脚手架模板
遗留，全仓库零引用。删前已用 grep 核对 `index.html` / `src/**` /
`tauri.conf.json` / `README.md`，确认无任何引用点。
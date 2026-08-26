<p align="center">
  <img src="img\hero.svg" width="100%" alt="守望先锋直播掉宝助手 - 专为守望先锋直播掉宝设计的自动化挂机工具">
</p>
<div style="text-align: center; font-size: 40px;"><img src="img\app.png" style="zoom:4%;" /> 守望先锋直播挂宝助手</div>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-GPL%20v3-blue.svg" alt="License: GPL v3"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python 3.10+"></a>
  <a href="https://wiki.qt.io/Qt_for_Python"><img src="https://img.shields.io/badge/PySide-6.5%2B-green.svg" alt="PySide6"></a>
  <a href="https://github.com/Theflippy/OverwatchDropsMiner"><img src="https://img.shields.io/badge/Platform-Windows-lightgrey.svg" alt="Platform"></a>
</p>

> 基于 [BiliBiliDropsMiner](https://github.com/mi0e/BiliBiliDropsMiner) 二次改造  
> 专为守望先锋直播掉宝设计的自动化挂机工具，支持多账号管理、扫码登录、自动领取奖励、实时日志监控。

---

## 界面预览

<p align="center">
  <img src="./img/run.png" width="100%" alt="主界面：账号列表、配置区、实时日志、任务进度">
</p>

---

## 核心功能

| 功能 | 说明 |
|------|------|
| 多账号挂机 | 同时管理多个 B 站账号，每账号独立 Cookie、独立任务进度 |
| 扫码登录 | 内置二维码登录，无需手动抓包 Cookie |
| 浏览器自动捕获 | 一键从 Edge 自动获取登录态 |
| 自动领取奖励 | 掉宝任务完成自动领取，支持 Gotify / 企业微信 / Server酱 等多渠道通知 |
| 实时进度追踪 | 基于B站服务器计时有效时间，断线自动暂停、重连续累 |
| 深色/浅色主题 | 首次启动跟随系统，支持 OLED 深色模式，一键切换 |
| 分账号日志 | 多线程日志按账号分流，界面实时显示 |
| 配置隔离 | 开发调试设置 OW_CONFIG_DIR 环境变量，完全隔离真实配置 |

---

## 使用指南

### 账号录入（三选一）

1. **扫码登录** —— 点击"扫码登录"，手机哔哩哔哩扫码授权
2. **手动粘贴** —— 复制浏览器 Cookie 粘贴入框
3. **浏览器自动捕获** —— 点击"浏览器捕获"，自动从 Chrome/Edge 读取登录态

### 启动挂机

1. 选择账号 → 填写直播间号（默认守望先锋官方直播间）
2. 设置线程数（建议 60~80，上限 128）
3. 可选：填入通知 Webhook（Gotify / 企业微信 / Server酱）
4. 点击"启动"，最小化到托盘即可后台运行

### 配置持久化

- **正常运行**：共享配置存注册表，Cookie 存 %APPDATA%\OverwatchDropsMiner\accounts.json（已本地DPAPI 加密）
- **开发调试**：设置环境变量 OW_CONFIG_DIR=<任意目录>，所有持久化重定向到该目录，绝不污染真实配置

---

## 快速开始

### 1. 下载发布版

前往 [Releases](https://github.com/Theflippy978/OverwatchDropsMiner/releases) 下载最新 OverwatchDropsMiner.exe（约 60 MB，免安装）。

### 2. 从源码运行

```bash
git clone https://github.com/Theflippy978/OverwatchDropsMiner.git
cd OverwatchDropsMiner
pip install -r requirements.txt
python build.py
```

### 3. 打包发布

```powershell
# 先杀残留进程
Get-Process OverwatchDropsMiner -ErrorAction SilentlyContinue | Stop-Process -Force

# 打包
python build.py --clean
# 产物: dist/OverwatchDropsMiner.exe
```

---

## 架构概览

```text
OverwatchDropsMiner/
├── main.py                      # 程序入口
├── build.py                     # PyInstaller 打包脚本
├── overwatch_drops_miner/       # 核心包
│   ├── gui.py                   # GUI 组装入口
│   ├── gui_parts/               # 界面组件
│   │   ├── theme.py             # 主题系统（深/浅色 QSS）
│   │   ├── main_window.py       # 主窗口
│   │   ├── account_panel.py     # 账号面板
│   │   ├── task_controller.py   # 任务控制器
│   │   └── ...
│   ├── client_parts/            # B 站 API 客户端
│   │   ├── core.py              # 核心 HTTP/签名
│   │   ├── live.py              # 直播/掉宝接口
│   │   ├── qr_login.py          # 二维码登录
│   │   └── ...
│   ├── miner.py                 # 单账号挂机逻辑
│   ├── miner_manager.py         # 多账号调度
│   ├── accounts.py              # 账号存储（DPAPI）
│   ├── config.py                # 配置模型
│   ├── paths.py                 # 路径解析/隔离
│   
├── tests/                       # pytest 测试套件（97 passed）
│   ├── run_tests.ps1            # 离屏测试脚本
│   └── ...
├── img/                         # 图标与截图
│   ├── app.ico                  # 程序图标
│   ├── run.png                  # 运行截图
│   └── ...
└── LICENSE                      # GPL v3.0
```

---

## 测试

```powershell
# 方式一：使用测试脚本（推荐）
pwsh -NoProfile -File tests/run_tests.ps1

# 方式二：直接运行
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest tests/ -q
```

> 全部测试在离屏模式运行，使用临时目录隔离，不写入真实配置。

---

## 依赖说明

| 依赖 | 用途 | 备注 |
|------|------|------|
| PySide6 | GUI 框架 | 6.5+ |
| httpx | 异步 HTTP | 替代 requests |
| qrcode | 二维码生成 | 登录用 |
| selenium | 浏览器自动化 | 可选，用于 Cookie 捕获，体积最大依赖 |
| pytest / pytest-qt | 测试框架 | 仅开发依赖 |

> 已移除原项目 colorama、apprise 等非必须依赖，代码中通过 try/except 延迟导入兜底。

---

## 免责声明

- 本工具仅供个人学习研究使用，请勿用于商业用途或大规模刷取。
- 使用即代表你同意遵守 B 站《用户协议》及相关法律法规。
- 作者不对因使用本工具导致的账号封禁、数据丢失等后果负责。
- 请合理控制挂机时长与线程数，避免给服务器造成压力。

---

## 许可证

本项目采用 GNU General Public License v3.0 开源协议。  
详见 LICENSE 文件。

---

## 致谢

- 原项目：mi0e/BiliBiliDropsMiner —— 提供了完整的 B 站掉宝自动化基础架构

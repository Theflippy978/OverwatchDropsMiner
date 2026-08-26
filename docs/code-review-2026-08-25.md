# 全项目代码审阅报告（2026-08-25）

> 状态：**待确认** —— 本报告仅列出问题与修复建议，未经逐项确认前不改任何代码。
> 分支：`fix/加减号居中与整体审阅`

## 一、审阅范围与方法

- **范围**：`overwatch_drops_miner/` 全部约 8900 行 Python（miner 核心并发层、client_parts B 站客户端层、gui/gui_parts 界面层、accounts/dpapi/notifier/config/utils/logging 等基础设施）、build.py 打包脚本、PyInstaller spec、GitHub 工作流，以及 tests/ 覆盖面评估。
- **方法**：四路并行深度静态审阅（核心并发 / client_parts / GUI / 基础设施+构建测试），跨文件调用链 grep 取证；主审对全部高危/中危结论逐一复核源码；几何类缺陷以离屏渲染像素级实验实证。
- **背景**：此前数轮已累计修复高危 5 / 中危 17 / 低危 22+ 项。本轮聚焦遗留缺陷、交互缺陷与前几轮修复不彻底之处。

## 二、本分支已修复（无需确认）

| 编号 | 位置 | 问题 | 处理 |
|---|---|---|---|
| F-1 | gui_parts/plus_minus_spinbox.py | +/− 符号用 QRect.center()（整数）定位，偶数宽高按钮真实中心在半像素处，截断使符号偏左上 0.5 逻辑像素，175%~200% DPI 下肉眼可见 | 浮点面积中心 + 抗锯齿绘制；像素质心实测偏差 (-0.50,-0.50)→(+0.00,+0.00)；新增回归测试 5 项 |

## 三、问题清单

### 高危（1 项）

#### H-1 通知 URL 误用 parse_task_ids 解析：& 参数静默截断 + task_ids= 误提取 + 配置持久化污染

- **位置（主审已复核，四路中三路独立发现）**：gui_parts/main_window.py:371、:870 将通知地址经 `parse_task_ids()` 解析；该函数会 ① 在 token 含 & 时截断取前半段（utils.py:40-41）；② 文本含 task_ids= 子串时整段替换为参数值（utils.py:30-32）。而专为此编写的 `parse_url_list()`（utils.py:47-58，注释明确不做 & 截断，tests/test_utils.py:136-146 已验证）在生产代码零调用。
- **触发与影响**：任何带 ≥2 个查询参数的通知地址（gotify://host/token?priority=8&nosound=true 等）在第一个 & 处被静默截断，鉴权参数丢失致通知 403/静默失败；启动配置与每 2 秒的运行中同步均受影响；「保存配置」把截断后的坏 URL 持久化进 config JSON，污染用户配置。
- **修复建议**：main_window.py:371、:870 两处替换为 parse_url_list 并更新 import（两处需同步，避免 _sync_config_to_miners 口径不一致引发反复重建 notifier）；补「含 & 的通知 URL 不被截断」回归测试。
- **置信度**：高（纯静态可证 + 三路交叉印证）。

### 中危（7 项）

#### Z-1 csrf/bili_jct 拼入 URL 查询串，非 2xx 时凭据随异常文本泄漏到日志与 GUI（主审已复核证据链）

- 位置：client_parts/core.py:367（room_entry_action）、:509（get_task_progress）以 {"csrf": self.bili_jct} 作 params；live_trace.py:84、:147 同样含 csrf；http.py:180-185 经 http.post(url, params=...) 进 URL。httpx 0.28.1 raise_for_status() 异常消息固定携带完整 request.url（含 query）。泄漏面：x25kn_worker.py:176-185、core.py:607、gui_parts/task_controller.py:201-202 与 :292-294（str(exc) 写入 GUI 文本与 WARNING 日志）。
- 触发与影响：任一接口返回非 2xx（风控 412/403、5xx，高并发挂机常见）即触发；bili_jct 随异常字符串落入持久化日志与界面文本，分享日志排障时外泄。SESSDATA 仅在 Cookie 头不经此路径，故定中危。
- 修复建议：http 层统一包装 raise_for_status()，捕获 HTTPStatusError 后重抛脱敏消息（剥离 query 或打码）；提供 sanitize_exception_text() 供所有 str(exc) 日志点复用。中期可将 csrf 移入请求体。
- 置信度：高。

#### Z-2 「详细日志」verbose 开关完全失效：logger 名配置错误（主审已复核）

- 位置：logging_utils.py:85 —— `logging.getLogger("overwatch_miner").setLevel(app_level)`；而全项目模块 logger 均为 getLogger(__name__) 即 overwatch_drops_miner.*（grep 确认 "overwatch_miner" 无对应层次）。root 固定 INFO（:72），包内未单独设级 → 有效级别恒 INFO。
- 影响：勾选详细日志仅格式变化，miner/x25kn_worker 等所有 LOGGER.debug 输出仍被过滤，调试功能形同虚设。
- 修复建议：改为 `logging.getLogger("overwatch_drops_miner").setLevel(app_level)`。
- 置信度：高。

#### Z-3 WatchTimeTracker 多房间共享 + pause/resume 不对称，有效观看时长长时间冻结（主审已复核）

- 位置：miner.py:122 —— 同一账号所有房间的 primary 会话共享同一 tracker 实例；x25kn_worker.py:156-157 仅在进场成功时 resume()（全项目唯一 resume 调用点），:177-178 任一失败立即 pause()；心跳成功的 else 分支（:163-172）不调用 resume。
- 触发与影响：多房间挂机时任一房间一次瞬时失败 pause 共享时钟后，其它健康房间即使持续心跳也无法恢复计时，直到自己断线重连重新 enter；GUI「本次有效观看」「预计剩余」随之长时间失真。只影响本地估算显示，不影响服务器侧进度与掉宝。
- 修复建议：心跳成功分支也调用 resume()（幂等，一行消除不对称）；更严格可按房间维护子计时器在 GUI 聚合或引用计数。
- 置信度：高。

#### Z-4 任务完成通知的去重集合跨周期永不清理，第二个周期起静默漏报（主审已复核）

- 位置：x25kn_worker.py:55（_notified_completed_ids 提升为实例字段且注释明确跨重连保留）、:227-240（key not in set 即永久去重，无任何清理路径）；models.py 带 period_type 字段说明任务存在周期语义。
- 触发与影响：单次运行跨越任务周期重置点（B 站观看类任务通常按日/周重置）：重置后的进度迁移会被快照识别并打印，但再次完成时因 key 仍在集合中被拦截，notify_on_task_complete 对第二个周期起完全失效——漏发推送通知，挖矿本身不受影响。
- 修复建议：快照比对处检测「previous 为完成态而 current 为未完成态」时 discard(key)；或检测 status 从终态回到进行中的瞬间清理对应 key。
- 置信度：机制高；周期语义中等（可抓包 totalv2 的 period_type 确证）。

#### Z-5 accounts.json 多实例并发写入竞态：确定性临时名 + last-writer-wins

- 位置：accounts.py:99-101（固定名 {name}.tmp → write_text → os.replace）；同进程有锁保护，但全仓无单实例防护（grep QLockFile/CreateMutex 为 0）。
- 触发与影响：双开程序并在两边增删账号：两进程同时写同一 .tmp 可能交错；A replace 后 B 的 os.replace 抛 FileNotFoundError（被 GUI 吞掉仅记日志）；双方内存态互相覆盖，最后保存者胜出，另一实例新增的账号凭据静默丢失。
- 修复建议：启动时 QLockFile(get_config_dir()/"app.lock") 或命名互斥量做单实例守卫；至少给 tmp 名加 pid/uuid 后缀。
- 置信度：中（代码路径确凿，双开常见，需运行时复现验证）。

#### Z-6 CI 从不运行测试：23 个测试文件无执行入口

- 位置：.github/workflows/build.yml:33-154 仅 prepare/build-windows/release 三个 job；requirements.txt 无 pytest。
- 影响：push/dispatch 均不执行测试，回归只能靠人工发现——本轮 H-1、Z-2 都属于本可被现有测试或简单断言拦截的问题；构建产物照常发布，存在「测试红着照样出正式版」的风险。
- 修复建议：新增 test job（python 3.12 + QT_QPA_PLATFORM=offscreen 跑 pytest/unittest），build-windows needs 它；补 requirements-dev.txt。
- 置信度：高。

#### Z-7 关窗时嗅探收尾 0.5 秒即放行且返回值被忽略；嗅探会话无并发守卫

- 位置：main_window.py:947-952 closeEvent 中 browser_actions.shutdown(timeout=0.5) 返回值被丢弃，无论线程是否退出都 accept();browser_actions.py:47-48、186-213 browser_sniff 启动前不检测上一嗅探是否存活、无互斥锁,_sniff_thread 被直接覆盖;browser_sniffer.py:337-362 收尾链 driver.quit() 通常超过 0.5s。
- 触发与影响：自动获取 Cookie/房间号过程中直接关窗 → daemon 线程被硬杀、finally 不执行 → msedgedriver/chromedriver 与浏览器窗口残留；连续多次触发自动获取则叠加泄漏成倍放大。
- 修复建议：closeEvent 把 join 预算提到 ≥3s 并检查返回值,超时 taskkill /T 兜底或告警；browser_sniff 入口加「已有嗅探进行中则拒绝」守卫;每会话独立 cancel Event、列表管理全部存活线程逐一 join。
- 置信度：机制层面高;实际进程残留建议运行时确认。

### 低危（14 项）

| 编号 | 位置 | 问题 | 修复方向 | 置信度 |
|---|---|---|---|---|
| D-1 | client_parts/http.py:31-65 | 对非幂等 POST 也做 ReadTimeout/RemoteProtocolError 瞬时重试，请求可能已被受理导致重复提交（领奖误报失败；x25Kn/X 重放抖动） | POST 仅对 ConnectTimeout/ConnectError 重试 | 中 |
| D-2 | client_parts/core.py:296-307,332,341-354 | get_room_owner_uid/get_live_watch_time/get_danmu_server 为死代码且绕过 parse_json_response 防御层 | 删除或改用防御解析 | 高 |
| D-3 | notifier.py:137-160 | wxwork access_token 失效（secret 更换/被踢）后缓存不清理，持续发送失败至缓存到期 | errcode 40014 时清缓存重试一次 | 高 |
| D-4 | notifier.py:216-249 | update_urls 先清空后重建非原子（daemon 线程并发 notify 可偶发丢一条）；apprise 循环整体 try/except，单条坏 URL 连累其余 apprise 通知初始化 | 先局部构建再整体换引用；逐条 add 单独容错 | 高 |
| D-5 | utils.py:173-193,196-250,398-399 | 任务解析递归无深度上限，超深嵌套页面抛 RecursionError 且部分调用点在 try 保护外 | 改显式栈迭代或兜底捕获返回空列表 | 中 |
| D-6 | gui_parts/main_window.py:618-620,523-536 | 删除运行中账号后迟到状态回调被守卫提前 return，「已运行账号数量」标签滞留旧值至下次启停 | 早退分支补 _update_running_count() | 高 |
| D-7 | dpapi.py:11,60,89 | windll 未设 use_last_error=True，GetLastError 采集点与真实错误间可能被改写，失败诊断信息失真 | WinDLL(use_last_error=True) + get_last_error() | 中 |
| D-8 | gui_parts/update_dialog.py:25-33 | 更新弹窗硬编码深色配色，浅色主题下突兀 | 删本地 QSS 继承全局主题 | 高 |
| D-9 | gui_parts/config_io.py:67-70 | save_config_data 直接 write_text 覆盖，中途崩溃留下截断 JSON 且是用户唯一导出副本 | 照 accounts 的 tmp+os.replace 模式 | 高 |
| D-10 | main_window.py:161,564 + logging_utils.py:64-82 | 每次启动账号都整表重建全局 handler，存在零 handler 瞬时窗口并对正被 close 的 handler 并发 emit | QueueLogHandler 安装一次复用，verbose 切换走轻量接口 | 中 |
| D-11 | main_window.py:292-310,697-709 | 日志刷新每 120ms 全量 join 近万行并 setPlainText，多账号+详细日志刷屏时 UI 卡顿 | 增量 appendPlainText，切账号/clear 才全量重建 | 中 |
| D-12 | miner.py:181 | run() 启动登录探测裸调 asyncio.run(_probe_login()) 无异常保护，网络抖动被降格为 "GUI worker crashed"，无法区分网抖与凭据失效 | 对齐看门狗口径：重试 1~2 次 + 明确文案 | 高 |
| D-13 | miner.py:282-286 + worker_controller.py:109-119 | 「强制停止」并无额外强制能力（force 仅收紧 join 预算），UI 文案夸大；卡死期间 has_thread 拒绝重启 | 文案改「已请求停止（加速收尾）」或实现真正中断 | 高 |
| D-14 | .github/workflows/build.yml:46-52,79,139 | workflow 输入（tag/release）直接内插 shell 双引号存在注入面（dispatch 仅协作者可用，风险有限） | env 间接引用 + tag 白名单校验 | 高 |

> 环境卫生备注：OverwatchDropsMiner.spec:4,:45 含硬编码绝对路径——.gitignore 已忽略 *.spec 不入库，仅影响本机直构，建议删除或由 build.py 相对路径生成；requirements.txt 未钉版本问题并入 J-13/T 处理。

### 建议（12 项）

| 编号 | 位置 | 内容 |
|---|---|---|
| J-1 | miner_manager.py:61-82 + worker_controller.py:39-69 | start 存在理论 TOCTOU（锁外调 controller.start，controller 自身无锁），当前被 Qt 单线程事件循环掩护；建议加锁或注释声明仅限主线程调用 |
| J-2 | client_parts/live.py:44 | int(host_item.get("wss_port", 443)) 键存 null 时裸抛 TypeError，改 or 443 写法（当前仅死代码使用） |
| J-3 | client_parts/qr_login.py:111 | Cookie 域名校验 endswith("bilibili.com") 放过 xbilibili.com 同形域，改精确匹配或 .bilibili.com 后缀 |
| J-4 | client_parts/qr_login.py:128-132 | _TRANSIENT_ERRORS 缺 httpx.ReadTimeout（与 http.py:45-50 口径不一），扫码瞬间读超时会终止整轮登录 |
| J-5 | miner.py:248-278 | finally 清理无限等待线程退出，极端 hang 死下停止永不完结、GUI 永远「运行中」（daemon 保证进程可退）；建议加累计上限超时后记录 ERROR 并放弃等待 |
| J-6 | miner_manager.py | _sessions 条目永不回收，已删除账号的 controller/tracker 常驻；可在 poll_shutdown stopped 且账号已不存在时择机清理 |
| J-7 | client_parts/core.py:414-418 | 非开播房间每轮重连打 WARNING 且不受 primary_only 节流，离线房间可能形成日志刷屏；建议首见即止或按房间限频 |
| J-8 | theme.py:374-386 | 系统主题变化无条件覆盖用户手动选择；若有意设计请在按钮 tooltip 说明，否则加手动覆盖标志 |
| J-9 | main_window.py:564 | 详细日志勾选要等下次启动账号才生效；可在 checkbox toggled 直接热切换 |
| J-10 | main_window.py:142,421,451 | _adding_accounts 只有增减从未被读取，删除或用作添加中守卫 |
| J-11 | browser_utils.py:9-13 | Edge 探测缺 %LOCALAPPDATA% 用户级 Edge 安装路径 |
| J-12 | config.py:30-33 | validate 只查下限；建议给 reconnect_delay/task_query_interval 设上限（如 ≤3600）防手滑超大值停摆看门狗 |

另（工程）：requirements.txt 全部未钉版本（httpx/PySide6/selenium/pyinstaller），上游破坏性更新会让 CI 自动产出坏包且难定位；建议在 Z-6 落地时一并钉主版本范围。

### 备注（不计入修复清单）

- B-1 utils.py:141：index-1 在 index=0 时取 position_boxes[-1]，因 blocks 为空短路无害，但属易碎写法，日后调整条件顺序会引爆，建议顺手改 max(index-1, 0)。
- B-2 accounts.json 可在 os.replace 前 fsync 临时文件，防掉电后半字节内容。
- B-3 MultiPlatformNotifier.update_urls 目前靠整体换引用实现准线程安全，建议加注释固化该约定防未来改成原地 append 引入竞态。

## 四、测试盲区清单（tests/ 覆盖面评估）

| 编号 | 盲区 | 关联缺陷 |
|---|---|---|
| T-1 | notifier.py 零覆盖：scheme 分派、gotify path_prefix/token 拆分、serverchan 回退、wecombot 双解码规避、wxwork 缓存边界、errcode/code 归一化全部无测试（可用 httpx MockTransport 补齐） | D-3、D-4 |
| T-2 | verbose→DEBUG 有效级别无断言 | Z-2 因此漏网 |
| T-3 | GUI 通知 URL 解析链路无含 & 用例（test_gui_persistence.py:58 恰好用了不带 & 的 URL） | H-1 因此漏网 |
| T-4 | update_checker 版本比较与渠道判断无直接单测 | — |
| T-5 | AccountStore 多实例/tmp 碰撞场景无测试（现有 test_accounts.py 单进程覆盖良好） | Z-5 |
| T-6 | dpapi.protect 失败抛 OSError、LocalFree 告警分支无测试（可 mock crypt32） | D-7 |

## 五、待确认清单

> 请逐项回复「修」或「跳过」，可批量（如「H-1、Z-1 到 Z-4 修，D 系全修，J 系跳过」）。确认后我在本分支逐项修复并附回归测试。测试盲区 T-1～T-3 建议随对应修复一并补齐。

| 编号 | 级别 | 一句话摘要 | 修？ |
|---|---|---|---|
| H-1 | 高危 | 通知 URL 误用 parse_task_ids，& 截断 + 配置污染（parse_url_list 已建未用） | ☐ |
| Z-1 | 中危 | csrf 走 URL 查询串 + httpx 异常携带完整 URL → 凭据泄漏到日志/GUI | ☐ |
| Z-2 | 中危 | verbose 开关失效：setLevel 打在不存在的 logger 名上 | ☐ |
| Z-3 | 中危 | 共享 tracker pause/resume 不对称，多房间时长显示冻结 | ☐ |
| Z-4 | 中危 | 任务完成通知去重集合跨周期不清理，第二周期起漏报 | ☐ |
| Z-5 | 中危 | accounts.json 双开竞态，账号凭据可能静默丢失 | ☐ |
| Z-6 | 中危 | CI 从不运行测试，回归无人拦截 | ☐ |
| Z-7 | 中危 | 关窗嗅探收尾 0.5s 放行致驱动/浏览器进程残留；嗅探无并发守卫 | ☐ |
| D-1~D-14 | 低危 | 见第三节低危表格 | ☐ |
| J-1~J-12 | 建议 | 见第三节建议表格 | ☐ |

## 六、总体印象

经过前几轮高强度修复，项目基础质量已经相当扎实：线程生命周期与停止语义、WBI/x25Kn 签名、QR 登录凭据隔离、DPAPI 原子存储、跨线程 UI 派发等关键结构均验证干净，本轮未发现崩溃级或凭据直接外泄级缺陷。最突出的模式问题是**「修复落地不彻底」**：parse_url_list 写好并有测试却没接进 GUI（H-1）、verbose 日志级别配错 logger 名（Z-2）、CI 缺少测试执行入口（Z-6）使前两者无人拦截；其次是**共享状态的语义边角**（tracker 不对称、通知去重无视周期重置）。建议优先合入 H-1/Z-2 的一行级修复并把测试接入 CI（Z-6），其余按清单排期。

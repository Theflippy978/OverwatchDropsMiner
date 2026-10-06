"""
Python Sidecar - 作为 Tauri 2 的后端服务
通过 IPC 与 Tauri 前端通信；业务逻辑在 python_sidecar.backend 中。
"""
import asyncio
import json
import logging
import math
import sys
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

# 把**仓库根**加入 Python 路径，使 `import python_sidecar.backend.*` 可解析。
# 本文件在 python_sidecar/main.py，故 parents[1] 即仓库根。
# PyInstaller 打包后本文件位于冻结的 sys._MEIPASS 根下，parent 逻辑同样成立
# （onefile 会把整个包打进去并以绝对导入方式解析）。
_project_root = Path(__file__).resolve().parents[1]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# 线程数 / 总连接数上限（用户决策值 256）。
# 必须与 python_sidecar/backend/config.py 的 MAX_TOTAL_CONNECTIONS、
# 前端 stores/config.ts 的 MAX_THREAD_COUNT、ConfigForm.vue 输入框的 max 属性同源。
# 历史上这四处出现过 128/256 不一致：前端允许填 256、保存也成功，启动时才被
# config.validate() 拒，而错误文案来自深层调用，用户无法关联因果
#（默认 60 线程 × 3 房间 = 180，正好落在 128 与 256 之间，最容易触发）。
# 改这里必须同步另外三处。
from python_sidecar.backend.config import MAX_TOTAL_CONNECTIONS as MAX_THREAD_COUNT

# 浏览器嗅探会话的用户可见等待上限（秒）。用户在弹出的浏览器里手动登录 /
# 进直播间，机器做不了，只能等；120s 是 UX 与"来不及操作"之间的折中。
# Cookie 捕获、房间号、任务ID 三种模式共用，由 _drive_sniff_session 统一使用。
SNIFF_TIMEOUT_SECONDS = 120.0

# 「自动跳转房间号」打开的起始页：守望先锋电竞 UP 主的空间页。
# 目标直播间挂在这个空间页上，从这里进直播间比从 B 站主站少好几步点击。
# 只用于 kind="room"；模式2 从已知房间号直连live.bilibili.com/{room_id}。
BROWSER_SNIFF_ROOM_START_URL = "https://space.bilibili.com/365902357/"

# 模块级 logger。此前 _add_account 等处用的是函数内的
# logging.getLogger(__name__) 局部变量，模块并无同名全局 ——
# 若别处直接写 logger.xxx() 会抛 NameError，且恰好都在 except 分支里
# （ruff F821 抓到 8 处）。异常处理路径本身再抛异常是最坏的失败模式。
logger = logging.getLogger(__name__)


async def _probe_identity(
    cookie: str, timeout: float = 30.0
) -> tuple[bool, str, str]:
    """探测 Cookie 对应的 B 站身份，最多 2 次、间隔 1 秒。

    返回 (是否有效, uname, 错误原因)。_add_account 与 _start_miner
    共用，避免同一段 tuple 解包契约在两处各写一遍。
    注意 uid 缺失时**仍会回填 uname**：调用方据此区分
    「未登录」与「已识别用户但 ID 缺失」两种错误归因。
    """
    from python_sidecar.backend.client import BilibiliClient

    last_error = ""
    last_uname = ""
    last_info_type = ""
    for attempt in range(2):
        try:
            client = BilibiliClient(cookie)
            try:
                info = await asyncio.wait_for(client.get_self_info(), timeout=timeout)
            finally:
                try:
                    await client.close()
                except Exception:
                    pass
            # get_self_info 返回 (uid | None, uname) 元组
            # （client_parts/profile.parse_self_info）
            uid, uname = info if isinstance(info, tuple) else (None, "")
            last_uname = uname or ""
            last_info_type = type(info).__name__
            if uid is None:
                last_error = "Cookie 已失效或未登录"
                # 注释写「间隔 1 秒」，但原实现只在 except 分支 sleep，
                # 最常见的失败路径（uid is None）零间隔连续打两次 /nav，
                # 既起不到重试作用也更易被风控。
                if attempt == 0:
                    await asyncio.sleep(1.0)
                continue
            return True, uname, ""
        except Exception as e:
            last_error = _safe_error(e)
            last_info_type = type(e).__name__
            if attempt == 0:
                await asyncio.sleep(1.0)
    if last_error == "Cookie 已失效或未登录" and last_uname:
        # 已识别用户但 uid 缺失：单独的错误归因，便于用户判断是协议变化
        return False, last_uname, f"已识别用户 {last_uname} 但用户 ID 缺失（{last_info_type}）"
    return False, "", last_error


def _clamp_int(value: Any, default: int, min_val: int, max_val: int) -> int:
    """把文本框里的数值钳制到合法区间；非法/空值回落到默认值"""
    try:
        return max(min_val, min(max_val, int(value)))
    except (TypeError, ValueError):
        return default


def _clean_task_ids_text(value: Any) -> str:
    """任务 ID 文本去重，**保留顺序**。

    绝不能在这里排序：B站掉宝任务 ID 是不透明字符串（实测形如
    ``6ERAcwloghvp4i00``），字典序排序对它们没有语义，却会把用户刚
    「自动获取」到的顺序整个打乱 —— 用户点一次「保存配置」就发现 ID 列表
    变了，误以为配置被换掉。实测 save_config → load_config 往返正是如此：
    集合相等、顺序被重排。

    排序只允许存在于指纹：后端 utils.task_ids_fingerprint 与前端
    config.ts 的 taskIdsFingerprint 各自排序，用于判断「是不是同一批任务」。
    """
    from python_sidecar.backend.utils import dedupe_task_ids

    return dedupe_task_ids(value)


def _safe_error(exc: BaseException) -> str:
    """把异常转成适合展示给用户的文案。

    两个必须处理的问题：
    1. ``str(TimeoutError())`` 是空串 —— 直接 f-string 进错误消息会让用户
       看到一个空白提示（`_browser_capture` 已按此显式给出文案，
       `_refresh_tasks` / `_claim_rewards` 的超时却漏修）。
    2. httpx 的异常消息常携带完整请求 URL，query 里可能含 csrf/bili_jct
       等会话凭据。仓库已有 client_parts.http.sanitize_exception_text，
       这里统一走它而不是裸 str(e)。
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "请求超时"
    try:
        from python_sidecar.backend.client_parts.http import sanitize_exception_text

        return sanitize_exception_text(exc) or type(exc).__name__
    except Exception:
        text = str(exc)
        return text if text else type(exc).__name__


class FrontendLogHandler(logging.Handler):
    """把后端日志转发为 stdout 上的 log-entry 事件（前端 LogViewer 显示）"""

    def __init__(self, sidecar: "PythonSidecar") -> None:
        super().__init__()
        self._sidecar = sidecar
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from python_sidecar.backend.account_log_context import get_current_account

            level = record.levelno
            if level >= logging.ERROR:
                level_name = "error"
            elif level >= logging.WARNING:
                level_name = "warning"
            elif level < logging.INFO:
                level_name = "debug"
            else:
                level_name = "info"

            self._sidecar._emit_event("log-entry", {
                "timestamp": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "account_id": get_current_account(),
                "level": level_name,
                "message": self.format(record),
            })
        except Exception:
            self.handleError(record)


class PythonSidecar:
    """处理来自 Tauri 的 IPC 请求"""
    
    def __init__(self):
        self.account_store = None
        self.miner_manager = None
        self._config_data = {
            "room_ids": [23612045],
            "thread_count": 60,
            "reconnect_delay_seconds": 8,
            "task_ids": [],
            "task_query_interval_seconds": 30,
            "notify_urls": [],
            "notify_on_task_complete": True,
            "auto_claim_rewards": False,
            "verbose": False,
        }
        self._event_callbacks = []
        # stdout 是 JSON 协议通道：日志线程与响应线程并发写入必须串行化
        self._stdout_lock = threading.Lock()
        # 命令协程之间、以及与轮询线程之间共享以下状态，逐个加锁
        #   _config_lock     _config_data（RLock：保存路径里会嵌套取锁）
        #   _qr_lock         扫码会话 _qr_api/_qr_key
        #   _sniff_lock      浏览器嗅探单会话守卫与线程引用
        #   _progress_lock   _progress_values 进度值缓存
        self._config_lock = threading.RLock()
        self._qr_lock = threading.Lock()
        self._sniff_lock = threading.Lock()
        self._progress_lock = threading.Lock()
        self._init_backend()
        self._qr_api: Any | None = None
        self._qr_key = ""
        # 嗅探守卫是**单会话**的：Cookie 捕获 / 房间号 / 任务ID 模式2
        # 三者共用，任一进行中时其余都必须被拒
        self._sniff_busy = False
        self._sniff_cancel_event: threading.Event | None = None
        self._sniff_thread_ref: Any | None = None
        self._progress_values: dict[str, tuple[float, float]] = {}
        self._last_running_state: dict[str, bool] = {}
        self._config_file = self._get_config_file()
        self._load_config_file()
        # 注：原 self._watch_trackers 字段已删除 —— WatchTimeTracker 迁移到
        # AccountMinerManager._sessions 后它零读写，是残留。
    
    def _init_backend(self):
        """初始化现有后端模块"""
        try:
            from python_sidecar.backend.accounts import AccountStore
            from python_sidecar.backend.miner_manager import AccountMinerManager
            
            self.account_store = AccountStore()
            self.miner_manager = AccountMinerManager(self._build_config)
            print("[Sidecar] 后端初始化成功", file=sys.stderr)
        except Exception as e:
            print(f"[Sidecar] 后端初始化失败: {e}", file=sys.stderr)
            logger.warning("命令执行失败", exc_info=True)
        finally:
            self._setup_logging(False)

    def _setup_logging(self, verbose: bool) -> None:
        """初始化/重建日志输出，并附带转发到前端的事件 handler。

        走 stderr 而非 stdout：stdout 是 JSON IPC 通道，日志混进去会让
        Rust 侧的响应解析错乱。
        """
        try:
            from python_sidecar.backend.logging_utils import setup_logging
            setup_logging(verbose=verbose, no_color=True)
            root = logging.getLogger()
            if not any(isinstance(h, FrontendLogHandler) for h in root.handlers):
                root.addHandler(FrontendLogHandler(self))
        except Exception as e:
            print(f"[Sidecar] 初始化日志失败: {e}", file=sys.stderr)

    def _apply_verbose(self, verbose: bool) -> None:
        """详细日志开关即时生效（不重建 handler，仅切换级别与格式）"""
        try:
            from python_sidecar.backend.logging_utils import apply_verbose_runtime
            apply_verbose_runtime(verbose=verbose, no_color=True)
            print(f"[Sidecar] verbose = {verbose}", file=sys.stderr)
        except Exception as e:
            print(f"[Sidecar] 切换详细日志失败: {e}", file=sys.stderr)
    
    def _get_config_file(self):
        from python_sidecar.backend.paths import get_config_dir
        config_dir = get_config_dir()
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def _load_config_file(self):
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # 兼容旧版结构化字段（room_ids 列表）与新版文本字段（rooms_text）
                    room_ids = data.get("room_ids", [])
                    if not room_ids and data.get("rooms_text"):
                        from python_sidecar.backend.utils import parse_room_ids

                        try:
                            room_ids = parse_room_ids(str(data.get("rooms_text", "")))
                        except ValueError:
                            room_ids = []
                    task_ids = data.get("task_ids", [])
                    if not task_ids and data.get("task_ids_text"):
                        from python_sidecar.backend.utils import parse_task_ids
                        task_ids = parse_task_ids(str(data.get("task_ids_text", "")))
                    notify_urls = data.get("notify_urls", [])
                    if not notify_urls and data.get("notify_urls_text"):
                        from python_sidecar.backend.utils import parse_url_list
                        notify_urls = parse_url_list(str(data.get("notify_urls_text", "")))
                    with self._config_lock:
                        self._config_data = {
                            "room_ids": room_ids,
                            # 必须钳制：_save_config 与 _import_config 都调了
                            # _clamp_int，唯独启动加载没有 —— 手改 config.json
                            # 写 "thread_count": 9999 就能绕过钳制。
                            "thread_count": _clamp_int(
                                data.get("thread_count", 60), 60, 1, MAX_THREAD_COUNT
                            ),
                            "reconnect_delay_seconds": _clamp_int(
                                data.get("reconnect_delay_seconds", 8), 8, 1, 3600
                            ),
                            "task_ids": task_ids,
                            "task_query_interval_seconds": _clamp_int(
                                data.get("task_query_interval_seconds", 30), 30, 10, 3600
                            ),
                            "notify_urls": notify_urls,
                            "notify_on_task_complete": bool(
                                data.get("notify_on_task_complete", True)
                            ),
                            "auto_claim_rewards": bool(data.get("auto_claim_rewards", False)),
                            "verbose": bool(data.get("verbose", False)),
                        }
                        verbose = self._config_data["verbose"]
                    self._apply_verbose(verbose)
                    print(f"[Sidecar] 配置已加载: {self._config_file}", file=sys.stderr)
        except Exception as e:
            print(f"[Sidecar] 加载配置文件失败: {e}", file=sys.stderr)

    def _save_config_file(self):
        try:
            from python_sidecar.backend.browser.config_io import build_config_payload
            from python_sidecar.backend.config import MinerConfig
            with self._config_lock:
                data = dict(self._config_data)
            config = MinerConfig(
                cookie="",
                room_ids=data.get("room_ids", []),
                thread_count=data.get("thread_count", 60),
                reconnect_delay_seconds=data.get("reconnect_delay_seconds", 8),
                task_ids=[],  # task_ids 不落盘（每天不同，重启后需重新获取）
                task_query_interval_seconds=data.get("task_query_interval_seconds", 30),
                notify_urls=data.get("notify_urls", []),
                notify_on_task_complete=data.get("notify_on_task_complete", True),
            )
            payload = build_config_payload(
                config,
                verbose=data.get("verbose", False),
                auto_claim_rewards=data.get("auto_claim_rewards", False),
            )
            from python_sidecar.backend.browser.config_io import save_config_data
            save_config_data(self._config_file, payload)
        except Exception as e:
            # 不再静默吞掉：调用方（_save_config）要据此判定本次保存是否真的
            # 落了盘。吞掉异常会让前端拿到一份「看起来保存成功」的回包。
            print(f"[Sidecar] 保存配置文件失败: {e}", file=sys.stderr)
            raise

    def _build_config(self, cookie: str):
        """构建 miner 配置"""
        from python_sidecar.backend.config import MinerConfig

        with self._config_lock:
            room_ids = self._config_data.get("room_ids", [])
            thread_count = self._config_data.get("thread_count", 60)
            reconnect_delay = self._config_data.get("reconnect_delay_seconds", 8)
            task_ids = self._config_data.get("task_ids", [])
            task_interval = self._config_data.get("task_query_interval_seconds", 30)
            notify_urls = self._config_data.get("notify_urls", [])
            notify_on_task_complete = self._config_data.get("notify_on_task_complete", True)

        return MinerConfig(
            cookie=cookie,
            room_ids=room_ids,
            thread_count=thread_count,
            reconnect_delay_seconds=reconnect_delay,
            task_ids=task_ids,
            task_query_interval_seconds=task_interval,
            notify_urls=notify_urls,
            notify_on_task_complete=notify_on_task_complete,
        )
    
    def add_event_callback(self, callback):
        """添加事件回调。

        保留是为测试/嵌入预留的扩展点：IPC 重构后事件已全部走 stdout，
        生产路径无调用方（_emit_event 里的遍历恒为空）。
        """
        self._event_callbacks.append(callback)
    
    def _write_line(self, text: str) -> None:
        """向 stdout 写入一行（线程安全，stdout 是 JSON 协议通道）"""
        with self._stdout_lock:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()

    @staticmethod
    def _dumps(payload: Any) -> str:
        """JSON 序列化。

        allow_nan=False 是必需的：默认 True 会输出裸 NaN / Infinity，
        那不是合法 JSON，Rust 侧 serde_json::from_str 解析失败后直接丢弃
        该行 —— 调用方的 pending waiter 永远等不到，阻塞满 300s 超时。
        可达路径：get_account_status 的 progress.cur/limit 来自
        _progress_values，其值取自 float(cur_value)，而上游 json.loads
        默认接受 NaN 字面量。
        """
        return json.dumps(payload, ensure_ascii=False, allow_nan=False)

    def _emit_event(self, event_type: str, data: dict):
        """发送事件到 Tauri：{"type": "event", "event": xxx, "data": {...}}"""
        payload = {"type": "event", "event": event_type, "data": data}
        try:
            self._write_line(self._dumps(payload))
        except Exception as e:
            print(f"[Sidecar] 事件输出失败: {e}", file=sys.stderr)
        for callback in self._event_callbacks:
            try:
                callback(payload)
            except Exception as e:
                print(f"[Sidecar] 事件回调失败: {e}", file=sys.stderr)
    
    async def handle_command(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
        """路由到对应的现有后端接口"""
        handlers = {
            "get_accounts": self._get_accounts,
            "add_account": self._add_account,
            "remove_account": self._remove_account,
            "rename_account": self._rename_account,
            "start_miner": self._start_miner,
            "stop_miner": self._stop_miner,
            "get_account_status": self._get_account_status,
            "save_config": self._save_config,
            "load_config": self._load_config,
            "set_verbose": self._set_verbose,
            "qr_login": self._qr_login,
            "qr_poll": self._qr_poll,
            "qr_cancel": self._qr_cancel,
            "browser_capture": self._browser_capture,
            "claim_rewards": self._claim_rewards,
            "refresh_tasks": self._refresh_tasks,
            "send_notification": self._send_notification,
            "auto_fetch_room_id": self._auto_fetch_room_id,
            "auto_fetch_task_ids": self._auto_fetch_task_ids,
            "auto_fetch_task_ids_mode2": self._auto_fetch_task_ids_mode2,
            "export_config": self._export_config,
            "import_config": self._import_config,
            "sync_config_to_miners": self._sync_config_to_miners,
            "shutdown": self._shutdown,
            "check_update": self._check_update,
            "detect_browsers": self._detect_browsers,
        }
        
        handler = handlers.get(command)
        if not handler:
            return {"error": f"未知命令: {command}"}
        
        try:
            return await handler(params)
        except Exception as e:
            # 注意：这里的形参名是 command（不是 serve_requests.run_request
            # 里的 request）。写错会让「handler 抛异常」这条路径自身再抛
            # NameError —— 异常处理路径连续失败是最坏的失败模式，且因为
            # 只在异常分支可达而完全没有测试覆盖（由 ruff F821 抓到）。
            logger.warning("命令处理失败，%s", command, exc_info=True)
            return {"error": _safe_error(e)}
    
    async def _get_accounts(self, params: dict) -> dict:
        """获取账号列表"""
        if not self.account_store:
            return {"accounts": []}
        
        accounts = []
        for acc in self.account_store.list_accounts():
            accounts.append({
                "id": acc.id,
                "remark": acc.remark or acc.id[:8],
                "running": self.miner_manager.is_running(acc.id) if self.miner_manager else False,
            })
        return {"accounts": accounts}
    
    async def _add_account(self, params: dict) -> dict:
        """添加账号（含 Cookie 验证与用户名获取）"""
        cookie = params.get("cookie", "")
        if not cookie:
            return {"error": "Cookie 不能为空"}

        if not self.account_store:
            return {"error": "后端未初始化"}

        # 与 _start_miner 共用 _probe_identity（消除 tuple 契约的重复实现）
        ok, uname, error = await _probe_identity(cookie, timeout=30.0)
        if not ok:
            if uname:
                return {"error": error}
            return {"error": f"无法获取用户信息，Cookie 可能已失效或未登录（{error}）"}

        # AccountStore.add 支持直接带 remark，避免 add → update 两次落盘
        # （磁盘上会短暂存在 remark="" 的中间态）
        account = self.account_store.add(cookie, remark=uname or "")
        remark = uname or account.remark or account.id[:8]

        return {"id": account.id, "remark": remark, "running": False}
    
    async def _remove_account(self, params: dict) -> dict:
        """删除账号"""
        account_id = params.get("account_id", "")
        if not account_id:
            return {"error": "账号 ID 不能为空"}

        if self.miner_manager and self.miner_manager.is_running(account_id):
            self.miner_manager.request_stop(account_id)

        # 删除不存在的账号必须报错：原实现丢弃 AccountStore.remove 的
        # bool 返回值，删任何 id 都「成功」。前端 accounts.ts 却已经把本地
        # 条目 filter 掉了，两边状态不一致且无法察觉。
        if self.account_store and not self.account_store.remove(account_id):
            return {"error": "账号不存在或已被删除"}

        # 清理进度值缓存
        with self._progress_lock:
            self._progress_values.pop(account_id, None)
        self._last_running_state.pop(account_id, None)

        return {}

    async def _rename_account(self, params: dict) -> dict:
        """重命名账号备注"""
        account_id = params.get("account_id", "")
        remark = str(params.get("remark", "")).strip()

        if not account_id:
            return {"error": "账号 ID 不能为空"}
        if not self.account_store:
            return {"error": "后端未初始化"}

        account = self.account_store.update(account_id, remark=remark)
        if account is None:
            return {"error": "账号不存在"}

        return {
            "id": account.id,
            "remark": account.remark or account.id[:8],
            "running": self.miner_manager.is_running(account.id) if self.miner_manager else False,
        }

    async def _start_miner(self, params: dict) -> dict:
        """启动 miner（只收 account_id，配置取 _config_data）"""
        account_id = params.get("account_id", "")

        if not account_id:
            return {"error": "账号 ID 不能为空"}

        if not self.miner_manager or not self.account_store:
            return {"error": "后端未初始化"}

        account = self.account_store.get(account_id)
        if not account:
            return {"error": "账号不存在"}

        if self.miner_manager.is_running(account_id):
            return {"error": "该账号已在挂宝运行中"}

        config = self._build_config(account.cookie())
        try:
            config.validate()
        except ValueError as e:
            return {"error": _safe_error(e)}

        # 启动前登录探测（最多 2 次，间隔 1 秒）。
        # 与 _add_account 共用 _probe_identity：此前两处逐行重复同一段
        # tuple 解包逻辑，修过一次 tuple/dict 契约 P0 时要改两处，
        # 将来漂移还会发生。miner.run() 内部另有一次探测（保留，
        # 它负责守卫线程启动），因此单次启动最多打 B 站 /nav 三次。
        ok, uname, probe_error = await _probe_identity(account.cookie(), timeout=10.0)
        if not ok:
            return {"error": f"启动登录检测失败，请检查网络后重试：{probe_error}"}
        print(f"[Sidecar] 启动前登录校验通过: {uname}", file=sys.stderr)

        success = self.miner_manager.start(account)
        if not success:
            # 启动失败通常是因为上次会话的线程残留，先尝试轮询回收一次
            cleanup = self.miner_manager.poll_shutdown(account_id)
            if cleanup == "stopped":
                success = self.miner_manager.start(account)
            if not success:
                # 可能是并发的同账号 start_miner：manager.start 在锁内复查后
                # 对第二个返回 False。此时 miner 其实已经在跑，
                # 报「后台尚未完全停止」会让前端抛异常且不设 running，
                # 界面显示未运行而实际在跑（要等轮询线程 ≤200ms 自愈）。
                if self.miner_manager.is_running(account_id):
                    return {}
                return {"error": "该账号后台尚未完全停止，请稍候几秒后重试"}

        self._emit_event("account-state-changed", {"account_id": account_id, "running": True})
        return {}
    
    async def _stop_miner(self, params: dict) -> dict:
        """停止 miner"""
        account_id = params.get("account_id", "")
        if not account_id:
            return {"error": "账号 ID 不能为空"}

        if not self.miner_manager:
            return {"error": "后端未初始化"}

        self.miner_manager.request_stop(account_id)
        # 注意：不在此处发 account-state-changed(false)，由轮询线程统一发送
        return {}
    
    async def _get_account_status(self, params: dict) -> dict:
        """获取账号状态"""
        account_id = params.get("account_id", "")
        if not account_id:
            return {"error": "账号 ID 不能为空"}

        running = self.miner_manager.is_running(account_id) if self.miner_manager else False
        tracker = self.miner_manager.tracker(account_id) if self.miner_manager else None

        watch_time = 0
        if tracker:
            watch_time = int(tracker.elapsed_seconds())

        # 写者是刷新命令协程，读者是本状态查询协程，故必须持锁
        with self._progress_lock:
            progress_values = self._progress_values.get(account_id, (0.0, 0.0))
        cur_value, limit_value = progress_values
        has_bili_data = bool(limit_value) or bool(cur_value)

        from python_sidecar.backend.browser.task_presenter import format_watch_status_line
        status_line = format_watch_status_line(
            running=running,
            bili_cur_minutes=cur_value if has_bili_data else None,
            local_elapsed_seconds=watch_time,
            limit_value=limit_value,
        )

        progress = None
        if limit_value > 0:
            percent = max(0, min(100, int(cur_value / limit_value * 100)))
            progress = {"cur": cur_value, "limit": limit_value, "percent": percent}

        login_invalidated = False
        if self.miner_manager:
            login_invalidated = self.miner_manager.is_login_invalidated(account_id)

        return {
            "account_id": account_id,
            "running": running,
            "watch_time_seconds": watch_time,
            "status_line": status_line,
            # progress：B 站进度数值（前端进度条用）
            # task_progress：任务级进度对象，当前无数据，保留字段兼容旧契约
            "progress": progress,
            "task_progress": None,
            "login_invalidated": login_invalidated,
        }
    
    async def _save_config(self, params: dict) -> dict:
        """保存配置（文本字段进、文本出，对齐 GuiConfigValues 契约）"""
        from python_sidecar.backend.utils import parse_room_ids, parse_task_ids, parse_url_list

        config = params.get("config", {})
        verbose = bool(config.get("verbose", False))

        rooms_text = str(config.get("rooms_text", "")).strip()
        try:
            room_ids = parse_room_ids(rooms_text) if rooms_text else []
        except ValueError as e:
            return {"error": _safe_error(e)}

        # 任务 ID 去重但**保序**：排序只属于指纹，见 _clean_task_ids_text
        task_ids_text = _clean_task_ids_text(config.get("task_ids_text", ""))
        task_ids = parse_task_ids(task_ids_text) if task_ids_text else []

        notify_urls_text = str(config.get("notify_urls_text", "")).strip()
        notify_urls = parse_url_list(notify_urls_text) if notify_urls_text else []

        thread_count = _clamp_int(config.get("thread_count_text", "60"), 60, 1, MAX_THREAD_COUNT)
        reconnect_delay = _clamp_int(config.get("reconnect_delay_text", "8"), 8, 1, 3600)
        task_interval = _clamp_int(config.get("task_query_interval_text", "30"), 30, 10, 3600)

        with self._config_lock:
            self._config_data = {
                "room_ids": room_ids,
                "thread_count": thread_count,
                "reconnect_delay_seconds": reconnect_delay,
                "task_ids": task_ids,
                "task_query_interval_seconds": task_interval,
                "notify_urls": notify_urls,
                "notify_on_task_complete": bool(config.get("notify_on_task_complete", True)),
                "auto_claim_rewards": bool(config.get("auto_claim_rewards", False)),
                "verbose": verbose,
            }
        # 勾选后必须立即生效，不能等下次启动
        self._apply_verbose(verbose)
        # 落盘失败必须让调用方知道：_save_config_file 原先吞掉一切异常只打
        # stderr，而本命令的返回值会被前端当成「已落盘的真实值」整体替换
        # Pinia 里的 config —— 那等于把一次失败的配置保存谎报成成功，
        # 用户关掉窗口后编辑全丢且毫无提示。这里改成向上抛，由 handle_command
        # 统一转成 {"error": ...}。
        self._save_config_file()
        # 直接返回落盘后的真实值，而不是让前端再发一次 load_config 回读。
        # 原实现是 save → load 两趟，且前端用回读结果整体替换本地配置：
        # 中间任何一次后端钳制/归一化都会静默改掉用户刚填的内容
        # （实测「自动获取」到的任务 ID 点一次保存就被重排，用户以为配置被换）。
        # 一趟往返 + 落盘值为唯一真值，从根上消除这个窗口。
        return await self._load_config({})

    async def _load_config(self, params: dict) -> dict:
        """加载配置（含持久化文件）"""
        with self._config_lock:
            data = dict(self._config_data)
        return {
            "cookie": "",
            "rooms_text": ",".join(str(x) for x in data.get("room_ids", [])),
            "thread_count_text": str(data.get("thread_count", 60)),
            "reconnect_delay_text": str(data.get("reconnect_delay_seconds", 8)),
            "task_ids_text": ",".join(data.get("task_ids", [])),
            "task_query_interval_text": str(data.get("task_query_interval_seconds", 30)),
            "notify_urls_text": ",".join(data.get("notify_urls", [])),
            "notify_on_task_complete": data.get("notify_on_task_complete", True),
            "verbose": data.get("verbose", False),
            "auto_claim_rewards": data.get("auto_claim_rewards", False),
        }

    async def _set_verbose(self, params: dict) -> dict:
        """即时切换详细日志级别（勾选即生效）。

        此前唯一的生效路径是 save_config，用户勾完复选框看不到任何变化，
        必须再点一次「保存配置」才知道有没有生效 —— 复选框的可视状态与
        实际行为脱节，比没有这个开关更误导。这里只改日志级别，不落盘：
        持久化仍由 save_config 负责，勾选与保存两条路都通向同一状态。
        """
        verbose = bool(params.get("verbose", False))
        self._apply_verbose(verbose)
        return {}

    async def _export_config(self, params: dict) -> dict:
        """导出配置到用户选择的 JSON 文件（含 task_ids）"""
        path = params.get("path", "")
        if not path:
            return {"error": "未指定导出路径"}
        try:
            from python_sidecar.backend.browser.config_io import build_config_payload
            from python_sidecar.backend.config import MinerConfig
            with self._config_lock:
                data = dict(self._config_data)
            config = MinerConfig(
                cookie="",
                room_ids=data.get("room_ids", []),
                thread_count=data.get("thread_count", 60),
                reconnect_delay_seconds=data.get("reconnect_delay_seconds", 8),
                task_ids=data.get("task_ids", []),  # 导出文件含 task_ids
                task_query_interval_seconds=data.get("task_query_interval_seconds", 30),
                notify_urls=data.get("notify_urls", []),
                notify_on_task_complete=data.get("notify_on_task_complete", True),
            )
            payload = build_config_payload(
                config,
                verbose=data.get("verbose", False),
                auto_claim_rewards=data.get("auto_claim_rewards", False),
            )
            from python_sidecar.backend.browser.config_io import save_config_data
            save_config_data(path, payload)
            return {"path": path}
        except Exception as e:
            return {"error": f"导出配置失败: {e}"}

    async def _import_config(self, params: dict) -> dict:
        """从 JSON 文件导入配置（校验后落地）"""
        path = params.get("path", "")
        if not path:
            return {"error": "未指定配置文件路径"}
        try:
            from python_sidecar.backend.browser.config_io import load_config_data, values_from_config_data
            data = load_config_data(path)
            values = values_from_config_data(data)
            from python_sidecar.backend.utils import parse_room_ids, parse_task_ids, parse_url_list
            room_ids = parse_room_ids(values.rooms_text) if values.rooms_text else []
            task_ids = parse_task_ids(values.task_ids_text) if values.task_ids_text else []
            notify_urls = parse_url_list(values.notify_urls_text) if values.notify_urls_text else []
            with self._config_lock:
                self._config_data = {
                    "room_ids": room_ids,
                    # 导入文件里的数值同样钳制，避免越界值直接进 miner
                    "thread_count": _clamp_int(
                        values.thread_count_text, 60, 1, MAX_THREAD_COUNT
                    ),
                    "reconnect_delay_seconds": _clamp_int(values.reconnect_delay_text, 8, 1, 3600),
                    "task_ids": task_ids,
                    "task_query_interval_seconds": _clamp_int(values.task_query_interval_text, 30, 10, 3600),
                    "notify_urls": notify_urls,
                    "notify_on_task_complete": bool(values.notify_on_task_complete),
                    "auto_claim_rewards": bool(values.auto_claim_rewards),
                    "verbose": bool(values.verbose),
                }
                verbose = bool(self._config_data.get("verbose", False))
            self._apply_verbose(verbose)
            self._save_config_file()
            return await self._load_config({})
        except Exception as e:
            return {"error": f"导入配置失败: {e}"}
    
    async def _qr_login(self, params: dict) -> dict:
        """生成登录二维码（复用原后端 QrLoginApi）"""
        try:
            from python_sidecar.backend.client_parts.qr_login import QrLoginApi

            self._qr_close()
            api = QrLoginApi()
            try:
                challenge = await asyncio.to_thread(api.generate)
            except Exception:
                api.close()
                raise

            with self._qr_lock:
                self._qr_api = api
                self._qr_key = challenge.key
            return {
                "qr_url": challenge.url,
                "qr_key": challenge.key,
                "qr_image": self._make_qr_data_url(challenge.url),
            }
        except Exception as e:
            self._qr_close()
            return {"error": f"生成二维码失败: {e}"}

    async def _qr_poll(self, params: dict) -> dict:
        """轮询扫码状态：unscanned / scanned / expired / success"""
        from python_sidecar.backend.client_parts.qr_login import QrLoginStatus

        with self._qr_lock:
            api = self._qr_api
            key = str(params.get("qr_key", "") or self._qr_key)
        if api is None or not key:
            return {"error": "二维码会话不存在，请重新生成"}

        try:
            result = await asyncio.to_thread(api.poll, key)
        except Exception as e:
            return {"error": f"查询扫码状态失败: {e}"}

        if result.status is QrLoginStatus.UNSCANNED:
            return {"status": "unscanned"}
        if result.status is QrLoginStatus.CONFIRMED_PENDING:
            return {"status": "scanned"}
        if result.status is QrLoginStatus.EXPIRED:
            self._qr_close()
            return {"status": "expired"}
        cookie = result.cookie
        self._qr_close()
        return {"status": "success", "cookie": cookie}

    async def _qr_cancel(self, params: dict) -> dict:
        """关闭扫码登录会话（对话框取消/成功后释放连接）"""
        self._qr_close()
        return {}

    def _qr_close(self) -> None:
        with self._qr_lock:
            api = self._qr_api
            self._qr_api = None
            self._qr_key = ""
        if api is not None:
            try:
                api.close()
            except Exception:
                print("[Sidecar] 关闭扫码登录连接失败", file=sys.stderr)

    @staticmethod
    def _make_qr_data_url(url: str) -> str:
        """本地生成二维码 PNG（不经过任何第三方服务）"""
        import base64
        import io

        import qrcode
        from qrcode.image.pil import PilImage

        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=4,
            border=2,
        )
        qr.add_data(url)
        qr.make(fit=True)
        image = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _resolve_task_context(self, account_id: str) -> tuple[tuple[str, list[str]] | None, str | None]:
        """取账号 Cookie 与任务 ID，返回 (context, error)"""
        if not account_id:
            return None, "账号 ID 不能为空"
        if not self.account_store:
            return None, "后端未初始化"
        account = self.account_store.get(account_id)
        if account is None:
            return None, "账号不存在"

        cookie = account.cookie().strip()
        if not cookie:
            return None, "该账号缺少 Cookie，请重新登录"

        with self._config_lock:
            task_ids = [str(t).strip() for t in self._config_data.get("task_ids", []) if str(t).strip()]
        if not task_ids:
            return None, "未填写任务 ID，请先在配置中填写"
        return (cookie, task_ids), None

    async def _refresh_tasks(self, params: dict) -> dict:
        """刷新任务进度（查询 B 站任务接口）"""
        context, error = self._resolve_task_context(str(params.get("account_id", "")))
        if error:
            return {"error": error}
        cookie, task_ids = context  # type: ignore[misc]

        from python_sidecar.backend.client import BilibiliClient
        from python_sidecar.backend.browser.task_presenter import format_task_progress

        client = BilibiliClient(cookie)
        try:
            progresses = await asyncio.wait_for(
                client.get_task_progress(task_ids), timeout=60.0
            )
        except (asyncio.TimeoutError, TimeoutError):
            # 必须显式捕获：str(TimeoutError()) 是空串，直接冒泡会让用户
            # 看到空白错误提示。与 _browser_capture 同类。
            return {"error": "查询任务进度超时（60 秒），请检查网络后重试"}
        finally:
            try:
                await client.close()
            except Exception:
                pass

        # 多任务 ID 时取目标时长最大的那个作为「整体进度」代表
        if progresses:
            try:
                best = max(progresses, key=lambda t: float(getattr(t, "limit_value", 0)))
                cur = float(getattr(best, "cur_value", 0) or 0)
                limit = float(getattr(best, "limit_value", 0) or 0)
                # NaN/inf 会在下游 int(NaN) 抛错、或经 json.dumps 产出非法
                # JSON 被 Rust 丢弃，必须在这里归零。
                if not (math.isfinite(cur) and math.isfinite(limit)):
                    cur, limit = 0.0, 0.0
                with self._progress_lock:
                    self._progress_values[str(params.get("account_id", ""))] = (cur, limit)
            except (TypeError, ValueError):
                # 原实现 pass 静默吞掉，与 NaN 链路叠加后错误信息对用户
                # 毫无意义（同一个 NaN 在这里被吞、在 _get_account_status 炸）
                logger.warning("任务进度解析失败", exc_info=True)

        return {
            "tasks": [self._serialize_task(task) for task in progresses],
            "text": format_task_progress(progresses),
        }

    async def _claim_rewards(self, params: dict) -> dict:
        """领取奖励（可领取的全部任务奖励）"""
        context, error = self._resolve_task_context(str(params.get("account_id", "")))
        if error:
            return {"error": error}
        cookie, task_ids = context  # type: ignore[misc]

        from python_sidecar.backend.client import BilibiliClient
        from python_sidecar.backend.browser.task_presenter import format_reward_claim_results

        client = BilibiliClient(cookie)
        try:
            results = await asyncio.wait_for(
                client.receive_all_mission_rewards(task_ids), timeout=180.0
            )
        except (asyncio.TimeoutError, TimeoutError):
            # 同 _refresh_tasks：180s 在多任务 ID + 限频退避场景下极易击穿，
            # 而 TimeoutError 的 str() 是空串，用户只会看到空白提示。
            return {
                "error": "领取奖励超时（180 秒），可能已部分领取，请先手动刷新确认",
                "success": False,
                "results": [],
                "text": "领取奖励超时（180 秒），可能已部分领取，请先手动刷新确认",
            }
        finally:
            try:
                await client.close()
            except Exception:
                pass

        items = [
            {
                "task_id": str(item.task_id),
                "reward_name": str(item.reward_name or item.task_name or ""),
                "success": bool(item.success),
                "skipped": bool(item.skipped),
                # status 必须透传：领奖成功时 rewards.py 构造的是
                # TASK_STATUS_CLAIMED（6），而任务进度缓存不保存检查点状态，
                # 下次 refresh_tasks 拿回来的仍是「已完成」（3）。前端只能靠
                # 这个字段当场把徽标改成「已领取」，否则用户领取成功后
                # 刷新界面又变回「已完成」。
                "status": int(getattr(item, "status", 0) or 0),
                "message": str(item.message or ""),
            }
            for item in results
        ]
        return {
            "success": bool(items) and all(i["success"] for i in items),
            "results": items,
            "text": format_reward_claim_results(results),
        }

    @staticmethod
    def _serialize_task(task: Any) -> dict:
        """TaskProgress 模型 → 前端结构（含 check_points 明细）"""
        rewards = []
        check_points = []
        for point in list(getattr(task, "check_points", None) or []):
            name = str(getattr(point, "award_name", "") or "").strip()
            if not name:
                continue
            count_raw = getattr(point, "award_count", 1)
            try:
                count = int(float(count_raw))
            except (TypeError, ValueError):
                count = 1
            rewards.append({"name": name, "icon": "", "count": max(count, 1)})

            # check_point 明细（供前端按 sid 粒度自动领取）
            sid = str(getattr(point, "sid", "") or "").strip()
            if sid:
                try:
                    cur_val = float(getattr(point, "cur_value", 0) or 0)
                except (TypeError, ValueError):
                    cur_val = 0.0
                try:
                    limit_val = float(getattr(point, "limit_value", 0) or 0)
                except (TypeError, ValueError):
                    limit_val = 0.0
                check_points.append({
                    "sid": sid,
                    "alias": str(getattr(point, "alias", "") or "").strip(),
                    "status": int(getattr(point, "status", 0) or 0),
                    "is_completed": bool(getattr(point, "is_completed", False)),
                    "cur_value": cur_val,
                    "limit_value": limit_val,
                    "award_name": name,
                    "award_count": max(count, 1),
                })

        status_code = int(getattr(task, "status", 0) or 0)
        completed = bool(getattr(task, "is_completed", False))
        if status_code == 6:
            status_text = "已领取"
        elif completed:
            status_text = "已完成"
        else:
            status_text = "进行中"

        try:
            progress = float(getattr(task, "cur_value", 0) or 0)
        except (TypeError, ValueError):
            progress = 0.0
        try:
            target = float(getattr(task, "limit_value", 0) or 0)
        except (TypeError, ValueError):
            target = 0.0

        return {
            "task_id": str(getattr(task, "task_id", "") or ""),
            "title": str(getattr(task, "task_name", "") or "未知任务"),
            "progress": progress,
            "target": target,
            "status": status_text,
            "rewards": rewards,
            "check_points": check_points,
        }

    def _acquire_sniff(self) -> bool:
        """占用浏览器嗅探单会话名额（并发命令下保证同一时刻只有一个嗅探）"""
        with self._sniff_lock:
            if self._sniff_busy:
                return False
            self._sniff_busy = True
            return True

    def _release_sniff(self) -> None:
        """释放嗅探名额并清空会话引用"""
        with self._sniff_lock:
            self._sniff_busy = False
            self._sniff_cancel_event = None
            self._sniff_thread_ref = None

    def _register_sniff(self, cancel_event: threading.Event) -> None:
        """登记新的嗅探会话（取消事件）"""
        with self._sniff_lock:
            self._sniff_cancel_event = cancel_event
            self._sniff_thread_ref = None

    def _register_sniff_thread(self, thread: threading.Thread) -> None:
        """注册嗅探线程，供 shutdown 时 join。"""
        with self._sniff_lock:
            self._sniff_thread_ref = thread

    async def _drive_sniff_session(
        self,
        *,
        action: str,
        start_kwargs: dict[str, Any],
        done: threading.Event,
        timeout_error: str,
        browser: str | None = None,
        timeout_seconds: float = SNIFF_TIMEOUT_SECONDS,
    ) -> dict[str, Any] | None:
        """驱动一次浏览器嗅探会话，直到结果就绪或超时。

        Cookie 捕获 / 房间号 / 任务ID 三种模式共用这一份生命周期骨架。此前三者各自
        抄了一遍 acquire→register→起线程→等 done→finally cancel/release，而 finally
        里 cancel/done 的顺序带着线程池踩踏的教训 —— 抄两份必然只改一处：

            acquire → register(cancel) → 起嗅探线程 → 等 done（带超时）
            → finally { cancel.set()；done.set()；release }

        调用方只提供两样东西：``start_kwargs``（透传给
        ``start_browser_sniff`` 的 kind 专属参数与回调）与 ``done`` 事件
        （嗅探线程的回调通过 set 它表示结果就绪）。

        返回值约定：
          * ``None``      —— 结果已就绪，调用方去读自己的结果容器
          * ``dict``      —— 已终止的错误（忙 / 缺依赖 / 超时 / 异常），
                             内含 ``error`` 键，调用方直接返回
        """
        if not self._acquire_sniff():
            return {"error": "已有另一个自动获取任务在运行，请稍后再试"}
        cancel_event = threading.Event()
        self._register_sniff(cancel_event)
        try:
            from python_sidecar.backend.browser.browser_sniffer import start_browser_sniff

            # 嗅探线程是阻塞 IO（起浏览器 5-15s），丢默认 executor，不阻塞事件循环
            loop = asyncio.get_event_loop()
            sniff_thread = await loop.run_in_executor(
                None,
                lambda: start_browser_sniff(
                    browser_preference=browser,
                    cancel_event=cancel_event,
                    **start_kwargs,
                ),
            )
            self._register_sniff_thread(sniff_thread)

            try:
                await asyncio.wait_for(
                    asyncio.to_thread(done.wait),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                return {"error": timeout_error}
            return None
        except ImportError as e:
            return {"error": f"缺少依赖: {e}，请安装 selenium"}
        except Exception as e:
            logger.warning("%s失败", action, exc_info=True)
            return {"error": _safe_error(e)}
        finally:
            # 必须 cancel 优先于 done：嗅探线程看到 cancel_event 会在 break 处
            # 主动 driver.quit()；反序会让回调在退出后再 set，wait() 卡死。
            # 必须 done.set()：wait_for 超时/取消后，asyncio.to_thread(event.wait)
            # 仍有一条卡在默认 executor 线程里。**绝不** join 嗅探线程
            # （cancel_event 到 break 到 driver.quit() 存在秒级延迟）：
            #   1) 每多一条这样的默认 executor 线程，进程退出前要等最多 20 秒，
            #      叠加起来会拖垮 qr_poll / 自动获取等操作；
            #   2) asyncio.run() 退出时 shutdown_default_executor() 无期限地
            #      join 这些线程，不 join 的话整个进程要等，Rust 侧强杀也卡。
            cancel_event.set()
            done.set()
            self._release_sniff()

    async def _browser_capture(self, params: dict) -> dict:
        """浏览器捕获 - 使用 Selenium + 扩展捕获 B 站 Cookie

        生命周期由 ``_drive_sniff_session`` 统一负责，本方法只提供 kind 专属的
        回调与结果解析。
        """
        from python_sidecar.backend.browser.browser_sniffer import select_login_cookies

        result_box: dict[str, Any] = {}
        done = threading.Event()

        def on_cookies(cookies: list[dict[str, Any]]) -> None:
            """Cookie 捕获回调"""
            if not done.is_set():
                filtered = select_login_cookies(cookies)
                if not filtered:
                    result_box.update(
                        {"error": "未获取到有效登录 Cookie，请确认已登录 B 站"}
                    )
                else:
                    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in filtered)
                    result_box.update({"cookie": cookie_str})
                done.set()

        def on_error(err_type: str, err_msg: str) -> None:
            """错误回调"""
            if not done.is_set():
                result_box.update({"error": f"{err_type}: {err_msg}"})
                done.set()

        error = await self._drive_sniff_session(
            action="浏览器捕获",
            start_kwargs={
                # 对齐原项目：捕获任意 B 站页面 Cookie
                "url_keyword": None,
                "hint": "正在打开浏览器捕获 B 站 Cookie...",
                "start_url": "https://www.bilibili.com/",
                "on_cookies": on_cookies,
                "on_error": on_error,
                "finish_on_any": True,
            },
            done=done,
            browser=params.get("browser"),
            timeout_error=(
                "浏览器捕获超时（120 秒未捕获到登录 Cookie），"
                "请确认浏览器已打开并完成 B 站登录"
            ),
        )
        if error is not None:
            return error
        # done 已被 set 但一个回调都没写结果 = 嗅探线程自行退出
        return dict(result_box) or {"error": "浏览器捕获被取消"}

    @staticmethod
    def _normalize_task_groups(groups: Any) -> list[dict[str, Any]]:
        """extract_bili_live_task_groups 结果 → [{label, task_ids, active}]"""
        normalized: list[dict[str, Any]] = []
        for group in groups or []:
            if not isinstance(group, dict):
                continue
            task_ids = [
                str(t).strip()
                for t in (group.get("task_ids") or [])
                if str(t).strip()
            ]
            if not task_ids:
                continue
            normalized.append({
                "label": str(group.get("label") or "").strip() or "任务组",
                "task_ids": task_ids,
                "active": bool(group.get("active")),
            })
        return normalized

    async def _auto_fetch_task_ids(self, params: dict) -> dict:
        """自动获取任务ID（模式1：纯 HTTP 抓取直播间静态页，无需浏览器）"""
        try:
            room_id = int(params.get("room_id") or 0)
        except (TypeError, ValueError):
            room_id = 0
        if room_id <= 0:
            return {"error": "请先填写房间号，或改用模式2（浏览器嗅探）"}

        from python_sidecar.backend.client_parts.task_discovery import fetch_live_task_groups

        try:
            groups = await asyncio.wait_for(
                asyncio.to_thread(fetch_live_task_groups, room_id), timeout=30.0
            )
        except Exception as e:
            logger.warning("命令执行失败", exc_info=True)
            return {"error": f"自动获取模式1失败: {type(e).__name__}（可改用模式2）"}

        normalized = self._normalize_task_groups(groups)
        if not normalized:
            return {"error": "未解析到掉宝任务分组，请改用模式2（浏览器嗅探）"}
        return {"room_id": room_id, "groups": normalized}

    async def _run_browser_sniff(self, *, kind: str, room_id: int, browser: str | None = None) -> dict:
        """浏览器嗅探会话（kind: room=房间号 / task=任务ID模式2），单会话，120s 超时

        生命周期由 ``_drive_sniff_session`` 统一负责，本方法只负责 kind 分支的
        嗅探参数与回调。
        """
        result_box: dict[str, Any] = {}
        done = threading.Event()

        def _finish(payload: dict[str, Any]) -> None:
            if not done.is_set():
                result_box.update(payload)
                done.set()

        def on_error(title: str, message: str) -> None:
            _finish({"error": f"{title}: {message}"})

        sniff_kwargs: dict[str, Any]
        if kind == "room":
            def on_room_url(captured_room_id: int) -> None:
                _finish({"room_id": int(captured_room_id)})

            sniff_kwargs = {
                "url_keyword": None,
                "hint": "已打开浏览器，请在 2 分钟内进入目标直播间",
                "on_page_url": on_room_url,
                "finish_on_any": True,
                # 起始页必须是这个 UP 主的空间页，不是 B站主站：
                # 从主站出发要用户自己一层层点到直播间，而目标直播间就挂在他
                # 的空间页上（用户指定）。sniffer 默认值是 www.bilibili.com。
                "start_url": BROWSER_SNIFF_ROOM_START_URL,
            }
        else:
            from python_sidecar.backend.browser.browser_utils import (
                extract_room_id_from_live_url,
            )
            from python_sidecar.backend.utils import extract_bili_live_task_groups

            def on_page_html(page_html: str, page_url: str) -> bool:
                found_room = extract_room_id_from_live_url(page_url)
                normalized = self._normalize_task_groups(
                    extract_bili_live_task_groups(page_html)
                )
                if not normalized:
                    return False
                payload: dict[str, Any] = {"groups": normalized}
                if found_room:
                    payload["room_id"] = int(found_room)
                _finish(payload)
                return True

            def on_network_match(payload_raw: Any) -> None:
                try:
                    payload_data = payload_raw if isinstance(payload_raw, dict) else {}
                    request_url = str(payload_data.get("url") or "")
                    page_url = str(payload_data.get("page_url") or "")
                    found_room = extract_room_id_from_live_url(page_url)
                    if found_room is None:
                        found_room = extract_room_id_from_live_url(request_url)
                    data = payload_data.get("data")
                    if not isinstance(data, dict) or data.get("code") != 0:
                        return
                    tasks = (data.get("data") or {}).get("list") or []
                    task_ids = [
                        str(t.get("task_id")).strip()
                        for t in tasks
                        if isinstance(t, dict) and t.get("task_id")
                    ]
                    if not task_ids:
                        return
                    payload = {
                        "groups": [{
                            "label": "页面任务接口捕获",
                            "task_ids": task_ids,
                            "active": True,
                        }],
                    }
                    if found_room is not None:
                        payload["room_id"] = int(found_room)
                    _finish(payload)
                except Exception:
                    return

            sniff_kwargs = {
                "url_keyword": "/x/task/totalv2",
                "hint": "已打开浏览器，请打开有当前任务的直播间并等待页面加载完成",
                "on_network_match": on_network_match,
                "on_page_html": on_page_html,
                "finish_on_any": True,
                "start_url": (
                    f"https://live.bilibili.com/{room_id}" if room_id > 0 else None
                ),
            }

        error = await self._drive_sniff_session(
            action="浏览器嗅探",
            start_kwargs={"on_error": on_error, **sniff_kwargs},
            done=done,
            browser=browser,
            timeout_error="浏览器操作超时（2 分钟）",
        )
        if error is not None:
            return error
        return dict(result_box)

    async def _auto_fetch_room_id(self, params: dict) -> dict:
        """自动获取房间号（浏览器嗅探：打开目标直播间捕获 URL）"""
        browser = params.get("browser")
        return await self._run_browser_sniff(kind="room", room_id=0, browser=browser)

    async def _auto_fetch_task_ids_mode2(self, params: dict) -> dict:
        """自动获取任务ID（模式2：嗅探任务接口/页面 HTML，可同时拿到房间号）"""
        try:
            room_id = int(params.get("room_id") or 0)
        except (TypeError, ValueError):
            room_id = 0
        browser = params.get("browser")
        return await self._run_browser_sniff(kind="task", room_id=room_id, browser=browser)

    async def _sync_config_to_miners(self, params: dict) -> dict:
        """同步当前配置到运行中的 miner"""
        if not self.miner_manager:
            return {}
        running = self.miner_manager.running_miners()
        if not running:
            return {}
        with self._config_lock:
            reconnect_delay = self._config_data.get("reconnect_delay_seconds", 8)
            task_interval = self._config_data.get("task_query_interval_seconds", 30)
            notify_on_task_complete = self._config_data.get("notify_on_task_complete", True)
            task_ids = list(self._config_data.get("task_ids", []))
            notify_urls = list(self._config_data.get("notify_urls", []))
        for miner in running:
            if reconnect_delay > 0:
                miner.config.reconnect_delay_seconds = reconnect_delay
            if task_interval > 0:
                miner.config.task_query_interval_seconds = task_interval
            miner.config.notify_on_task_complete = notify_on_task_complete
            if task_ids != miner.config.task_ids:
                # 必须逐账号复制：上游是单账号，共享 list 无害；本项目多账号
                # 并行，共用同一个 list 对象时任何原地 append / extend / sort
                # 都会同时污染所有运行中的 miner。当前全仓对这些字段只读，
                # 所以还不是现行 bug，但没有任何机制阻止后来者踩。
                # 代价是每 2s 一次、每账号两个短列表的拷贝，可忽略。
                miner.config.task_ids = list(task_ids)
            if notify_urls != miner.config.notify_urls:
                miner.update_notifier(list(notify_urls))
        return {}

    async def _detect_browsers(self, params: dict) -> dict:
        try:
            from python_sidecar.backend.browser.browser_utils import (
                available_browsers,
                detect_default_browser,
                browser_label,
            )
            available = available_browsers()
            default = detect_default_browser()
            return {
                "available": available,
                "default": default,
                "labels": {b: browser_label(b) for b in available},
            }
        except Exception as e:
            return {"error": f"检测浏览器失败: {e}"}

    def _account_poll_loop(self, stop_event: threading.Event) -> None:
        """账号轮询线程（200ms）：回收死线程、发送状态变化事件"""
        import time
        while not stop_event.is_set():
            try:
                if not self.miner_manager or not self.account_store:
                    time.sleep(0.2)
                    continue

                states = self.miner_manager.shutdown_states()
                if not states:
                    time.sleep(0.2)
                    continue

                existing_ids = {acc.id for acc in self.account_store.list_accounts()}

                for account_id, state in states.items():
                    result = self.miner_manager.poll_shutdown(account_id)
                    # 已删除账号的会话完全停止后回收
                    if result == "stopped" and account_id not in existing_ids:
                        self.miner_manager.discard_session(account_id)

                    running = state == "running"
                    if result == "stopped":
                        running = False
                    # 只在状态真正变化时推送。事件名说的是「状态变化」，无条件发
                    # 会怎样：shutdown_states() 返回所有会话（含 idle 残留），
                    # 每 200ms 一次 → 257 账号约 1285 事件/秒，每条都是一行
                    # stdout JSON + 一次跨进程 emit + 前端一次查找，纯浪费。
                    if self._last_running_state.get(account_id) == running:
                        continue
                    self._last_running_state[account_id] = running
                    self._emit_event("account-state-changed", {
                        "account_id": account_id,
                        "running": running,
                    })

                # 会话被回收后要去掉它的去重记录，否则该表只增不减
                live = set(states.keys())
                for gone in [k for k in self._last_running_state if k not in live]:
                    del self._last_running_state[gone]

            except Exception as e:
                print(f"[Sidecar] 账号轮询异常: {e}", file=sys.stderr)

            time.sleep(0.2)

    async def _check_update(self, params: dict) -> dict:
        # force 由前端手动按钮传入：启动时的自动检查不传（仍受 update_channel
        # 门禁，dev 包不去打扰 GitHub API），用户主动点才绕过。
        force = bool(params.get("force", False))
        try:
            from python_sidecar.backend.browser.update_checker import check_latest_release
            from python_sidecar.backend._version import (
                APP_VERSION,
                UPDATE_CHANNEL,
                LATEST_RELEASE_API,
                RELEASES_URL,
            )
            # 必须丢到线程里：check_latest_release 是同步 urllib（8s 超时），
            # 直接在事件循环里调会让这 8 秒内所有在途 IPC 都无法响应、
            # 扫码轮询定时器也不触发。wait_for 的 10s 略大于 urllib 的 8s，
            # 让「网络慢」表现为 None（无更新）而不是抛超时异常。
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    check_latest_release,
                    app_version=APP_VERSION,
                    update_channel=UPDATE_CHANNEL,
                    latest_release_api=LATEST_RELEASE_API,
                    releases_url=RELEASES_URL,
                    timeout=8,
                    force=force,
                ),
                timeout=10.0,
            )
            if result is None:
                return {"update_available": False}
            return {
                "update_available": True,
                "latest_version": result.latest_version,
                "release_url": result.release_url,
            }
        except (asyncio.TimeoutError, TimeoutError):
            return {"update_available": False}
        except Exception as e:
            return {"error": f"检查更新失败: {_safe_error(e)}"}

    async def _shutdown(self, params: dict) -> dict:
        """应用关闭时清理浏览器与 miner 资源"""
        closed = True
        self._qr_close()
        # 必须调 stop_all：否则 miner 线程只能靠 Rust 的 force_kill 硬杀，
        # 可能停在心跳中途。让它有机会优雅收尾。
        if self.miner_manager is not None:
            try:
                self.miner_manager.stop_all()
            except Exception:
                logger.warning("停止所有 miner 失败", exc_info=True)
                closed = False
        # 停止嗅探线程（先在锁内取引用，再在锁外等待，避免与嗅探线程释放路径互锁）
        with self._sniff_lock:
            cancel_event = self._sniff_cancel_event
            thread = self._sniff_thread_ref
            busy = self._sniff_busy
        if cancel_event is not None:
            cancel_event.set()
            if thread is not None and thread.is_alive():
                thread.join(timeout=3.0)
                if thread.is_alive():
                    print("[Sidecar] 浏览器嗅探线程未在预算时间内退出", file=sys.stderr)
                    closed = False
            elif busy and thread is None:
                # 竞态：_register_sniff 把 cancel_event 建好但 _sniff_thread_ref
                # 尚未填充（selenium 启动本身要 5-15s），此时跳过 join 就会返回
                # closed=true，而浏览器正要启动。宁可报 false 也不能谎报干净。
                print("[Sidecar] 嗅探线程正在启动，shutdown 未能确认其退出", file=sys.stderr)
                closed = False
        return {"closed": closed}

    async def _send_notification(self, params: dict) -> dict:
        """发送通知"""
        try:
            from python_sidecar.backend.notifier import MultiPlatformNotifier
            
            title = params.get("title", "通知")
            body = params.get("body", "")
            notify_urls = params.get("notify_urls")
            if notify_urls is None:
                with self._config_lock:
                    notify_urls = list(self._config_data.get("notify_urls", []))
            
            if not notify_urls:
                return {"error": "未配置通知 URL"}
            
            notifier = MultiPlatformNotifier(notify_urls)
            if not notifier.enabled:
                return {"error": "无可用的通知渠道"}

            # notify 内部对每个目标串行 httpx.post(timeout=10)，N 个 URL 最坏
            # N×10s，且原先直接跑在事件循环里 —— 期间整个 sidecar 的 IPC
            # 全部无响应。丢到线程并加 30s 总预算。
            success = await asyncio.wait_for(
                asyncio.to_thread(notifier.notify, title, body),
                timeout=30.0,
            )
            return {"success": bool(success)}

        except ImportError as e:
            return {"error": f"缺少依赖: {e}，请安装 httpx"}
        except (asyncio.TimeoutError, TimeoutError):
            return {"error": "发送通知超时（30 秒），请检查通知 URL 是否可达"}
        except Exception as e:
            # 原先 traceback.print_exc()：release 下 stderr 无效句柄，
            # 用户界面与日志都拿不到任何线索
            logger.warning("发送通知失败", exc_info=True)
            return {"error": _safe_error(e)}


async def main():
    """Sidecar 主循环 - 通过 stdin/stdout 与 Tauri 通信

    IPC 并发：慢命令（浏览器嗅探 120s、领奖 180s）不再阻塞其它命令。
    - stdin 交给独立线程阻塞读取，再用 call_soon_threadsafe 投递回事件循环；
    - 每行请求 create_task 执行，响应回带请求里的 id，供 Rust 侧路由；
    - 仍然只有一个事件循环，扫码会话的 httpx 客户端不会被跨 loop 使用。
    """
    # stdio 编码。两侧都必须显式指定，不能依赖系统区域设置：
    # Windows 上 Python 默认 stdio 为 gbk + surrogateescape（实测
    # sys.stdin.encoding == "gbk"），而 Rust 侧用 writeln! 往
    # stdin 写的是 UTF-8 字节 —— GBK 解码 UTF-8 会静默产生乱码：
    #   "乐子"    e4 b9 90 e5 ad 90  → 涔愬瓙，不抛异常，无人察觉
    #   "古风小生" e5 8f a4 e9 a3 8e … → position 4 的 0xa3 是 GBK 非法序列，
    #                                  被 surrogateescape 兜底成 U+DCA3
    # 随后 json.loads 忠实保留该代理字符，accounts.py 的 strict UTF-8 落盘
    # 便抛 UnicodeEncodeError（用户现场日志里的 \udca3 即此字符）。
    # 也就是说：中文重命名失败与账号库无关，是这条管道在解码时就已损坏。
    #
    # errors 必须显式写 "replace"：reconfigure 只改 encoding，
    # errors 会保留原值 surrogateescape —— 那样代理字符反而能写出裸字节，
    # Rust 侧按 UTF-8 解析同样失败，且错误更难定位。
    #
    # 顺序要求：reconfigure 对已被读取过的流抛 UnsupportedOperation，
    # 故必须早于 main() 里的任何 stdin 读取。
    for _stream in (sys.stdin, sys.stdout):
        try:
            if _stream is not None and hasattr(_stream, "reconfigure"):
                _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            # 嵌入式/测试场景下 stdin 可能已被读取（reconfigure 对已读流抛
            # UnsupportedOperation）或为 None，此时协议通道由调用方保证，
            # 编码兜底失败不该让 sidecar 起不来
            pass

    # stderr 兜底：release 下主进程是 GUI 子系统（main.rs 的
    # windows_subsystem = "windows"）且 sidecar 以 CREATE_NO_WINDOW 启动，
    # GetStdHandle(STD_ERROR_HANDLE) 很可能返回无效句柄，CPython 此时把
    # sys.stderr 置为 None。而 print(*, file=None) 的语义是「回落到
    # sys.stdout」—— 这些诊断行会变成非法 JSON 污染协议通道，
    # 同时真正的错误诊断（后端初始化失败、配置读写失败、嗅探未退出…）
    # 在用户界面与日志里彻底消失。改为写 devnull 至少不污染协议。
    if sys.stderr is None:
        try:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        except Exception:
            sys.stderr = open(os.devnull, "w")
    elif hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    sidecar = PythonSidecar()
    print("[Sidecar] 启动成功，等待 Tauri 连接...", file=sys.stderr)

    # 启动账号轮询线程（200ms，仅存在会话时运行）
    poll_stop = threading.Event()
    poll_thread = threading.Thread(
        target=sidecar._account_poll_loop,
        args=(poll_stop,),
        daemon=True,
        name="account-poll",
    )
    poll_thread.start()

    try:
        await serve_requests(sidecar)
    finally:
        # 主循环退出时必须 set：_account_poll_loop 的 while 只看 stop_event，
        # 不 set 它就会一直转到进程结束。join 给 1s 预算而非无限等 ——
        # 轮询里 poll_shutdown 会等 miner 线程收尾，无限 join 会把 Rust 侧
        # 的强制回收一起拖住；超时残留由 daemon=True 兜底，不阻塞进程退出。
        poll_stop.set()
        poll_thread.join(timeout=1.0)


async def serve_requests(sidecar: PythonSidecar) -> None:
    """读取 stdin、并发执行命令、按请求序号回写响应。

    - stdin 交给独立线程阻塞读取，再用 call_soon_threadsafe 投递回事件循环；
    - 每行请求 create_task 执行，响应回带请求里的 rid，供 Rust 侧路由；
    - 始终只有一个事件循环，扫码会话的 httpx 客户端不会被跨 loop 使用。
    """
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    async def run_request(request: dict) -> None:
        """执行一条命令并写出响应（带上请求 id）"""
        try:
            response = await sidecar.handle_command(
                request.get("command"), request.get("params", {})
            )
        except Exception as e:
            response = {"error": _safe_error(e)}
        # 回带请求序号，供Rust 侧把响应路由到等待中的调用。
        # 键名必须是 rid 而不是 id：id 是**业务字段**（add_account /
        # rename_account 都返回账号 id），用 id 当信封键会被下面这行覆盖掉，
        # 调用方拿到的是请求序号（数字）而非账号 id，as_str() 直接失败。
        if "rid" in request:
            response = {**response, "rid": request["rid"]}
        # 序列化必须兜底：任何 handler 返回不可序列化对象，或 stdout 已
        # broken pipe 导致 _write_line 抛异常，都会让这一行响应根本没写出去，
        # Rust 侧 rx.recv_timeout 会一直等到 300s 超时，而异常只进 asyncio
        # 的 "Task exception was never retrieved"（写 stderr，release 下
        # 不可见）。_emit_event 已有同样的 try，这里补齐一致性。
        try:
            sidecar._write_line(sidecar._dumps(response))
        except Exception as e:
            fallback = {"error": f"响应序列化/写出失败: {e}"}
            if "rid" in request:
                fallback["rid"] = request["rid"]
            try:
                # allow_nan=False 自身也可能抛（值含 NaN），最后用默认参数兜底
                sidecar._write_line(json.dumps(fallback, ensure_ascii=False))
            except Exception:
                pass

    tasks: set[asyncio.Task] = set()

    def _spawn(request: dict) -> None:
        """启动一条命令任务（保存引用，避免被垃圾回收提前取消）"""
        task = asyncio.create_task(run_request(request))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    # 曾经有个 _cleanup_tasks() 用来「防止 tasks 集合无限增长」，它是恒为空操作的死代码
    # —— 真正生效的是 _spawn 里的 add_done_callback(tasks.discard)，而 _spawn 刚创建的
    # task 尚未被调度，t.done() 必为 False，所以它永远删不到东西。已删除该函数与调用点。

    def submit(line: str) -> None:
        """（事件循环线程内）解析一行请求并立即起一个并发任务"""
        line = line.strip()
        if not line:
            return
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            sidecar._write_line(json.dumps({"error": "无效的 JSON"}, ensure_ascii=False))
            return
        if not isinstance(request, dict):
            sidecar._write_line(json.dumps({"error": "无效的请求格式"}, ensure_ascii=False))
            return
        _spawn(request)

    def reader() -> None:
        """stdin 读取线程：读到一行就投递回事件循环"""
        try:
            for raw in sys.stdin:
                loop.call_soon_threadsafe(submit, raw)
        except Exception as e:
            print(f"[Sidecar] stdin 读取线程异常: {e}", file=sys.stderr)
        finally:
            # Rust 侧关闭 stdin 即表示它要退出，主循环随之结束
            loop.call_soon_threadsafe(stop_event.set)

    threading.Thread(target=reader, daemon=True, name="stdin-reader").start()
    await stop_event.wait()

    # stdin 关闭后给进行中的命令一点时间写出响应，避免响应被截断
    pending = list(tasks)
    if pending:
        try:
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout=5.0
            )
        except asyncio.TimeoutError:
            print("[Sidecar] stdin 已关闭，仍有命令未完成，直接退出", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())






"""
Python Sidecar - 作为 Tauri 2 的后端服务
通过 IPC 与 Tauri 前端通信，复用现有 overwatch_drops_miner 后端逻辑
"""
import asyncio
import json
import logging
import sys
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))


class FrontendLogHandler(logging.Handler):
    """把后端日志转发为 stdout 上的 log-entry 事件（前端 LogViewer 显示）"""

    def __init__(self, sidecar: "PythonSidecar") -> None:
        super().__init__()
        self._sidecar = sidecar
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from overwatch_drops_miner.account_log_context import get_current_account

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
        self._config_data = {}
        self._event_callbacks = []
        # stdout 是 JSON 协议通道：日志线程与响应线程并发写入必须串行化
        self._stdout_lock = threading.Lock()
        self._init_backend()
        self._browser_capture_result: dict | None = None
        self._browser_capture_event: threading.Event | None = None
        # 扫码登录会话（跨命令保持一个 HTTP client）
        self._qr_api: Any | None = None
        self._qr_key = ""
        # 浏览器嗅探会话守卫（Cookie 捕获 / 房间号 / 任务ID 模式2 共用，单会话）
        self._sniff_busy = False
        self._config_file = self._get_config_file()
        self._load_config_file()
        self._watch_trackers: dict[str, Any] = {}
    
    def _init_backend(self):
        """初始化现有后端模块"""
        try:
            from overwatch_drops_miner.accounts import AccountStore
            from overwatch_drops_miner.miner_manager import AccountMinerManager
            
            self.account_store = AccountStore()
            self.miner_manager = AccountMinerManager(self._build_config)
            print("[Sidecar] 后端初始化成功", file=sys.stderr)
        except Exception as e:
            print(f"[Sidecar] 后端初始化失败: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
        finally:
            # 日志统一走 stderr（stdout 是 JSON IPC 通道，不能被污染）
            self._setup_logging(False)

    def _setup_logging(self, verbose: bool) -> None:
        """初始化/重建日志输出到 stderr，并附带转发到前端的事件 handler"""
        try:
            from overwatch_drops_miner.logging_utils import setup_logging
            setup_logging(verbose=verbose, no_color=True)
            root = logging.getLogger()
            if not any(isinstance(h, FrontendLogHandler) for h in root.handlers):
                root.addHandler(FrontendLogHandler(self))
        except Exception as e:
            print(f"[Sidecar] 初始化日志失败: {e}", file=sys.stderr)

    def _apply_verbose(self, verbose: bool) -> None:
        """详细日志开关即时生效（不重建 handler，仅切换级别与格式）"""
        try:
            from overwatch_drops_miner.logging_utils import apply_verbose_runtime
            apply_verbose_runtime(verbose=verbose, no_color=True)
            print(f"[Sidecar] verbose = {verbose}", file=sys.stderr)
        except Exception as e:
            print(f"[Sidecar] 切换详细日志失败: {e}", file=sys.stderr)
    
    def _get_config_file(self):
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            config_dir = Path(appdata) / "OverwatchDropsMiner"
        else:
            config_dir = Path.home() / "OverwatchDropsMiner"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "config.json"

    def _load_config_file(self):
        try:
            if self._config_file.exists():
                data = json.loads(self._config_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._config_data = {
                        "room_ids": data.get("room_ids", []),
                        "thread_count": data.get("thread_count", 60),
                        "reconnect_delay_seconds": data.get("reconnect_delay_seconds", 8),
                        "task_ids": data.get("task_ids", []),
                        "task_query_interval_seconds": data.get("task_query_interval_seconds", 30),
                        "notify_urls": data.get("notify_urls", []),
                        "notify_on_task_complete": data.get("notify_on_task_complete", True),
                        "auto_claim_rewards": data.get("auto_claim_rewards", False),
                        "verbose": data.get("verbose", False),
                    }
                    self._apply_verbose(self._config_data.get("verbose", False))
                    print(f"[Sidecar] 配置已加载: {self._config_file}", file=sys.stderr)
        except Exception as e:
            print(f"[Sidecar] 加载配置文件失败: {e}", file=sys.stderr)

    def _save_config_file(self):
        try:
            from overwatch_drops_miner.gui_parts.config_io import build_config_payload
            from overwatch_drops_miner.config import MinerConfig
            config = MinerConfig(
                cookie="",
                room_ids=self._config_data.get("room_ids", []),
                thread_count=self._config_data.get("thread_count", 60),
                reconnect_delay_seconds=self._config_data.get("reconnect_delay_seconds", 8),
                task_ids=self._config_data.get("task_ids", []),
                task_query_interval_seconds=self._config_data.get("task_query_interval_seconds", 30),
                notify_urls=self._config_data.get("notify_urls", []),
                notify_on_task_complete=self._config_data.get("notify_on_task_complete", True),
            )
            payload = build_config_payload(
                config,
                verbose=self._config_data.get("verbose", False),
                auto_claim_rewards=self._config_data.get("auto_claim_rewards", False),
            )
            from overwatch_drops_miner.gui_parts.config_io import save_config_data
            save_config_data(self._config_file, payload)
        except Exception as e:
            print(f"[Sidecar] 保存配置文件失败: {e}", file=sys.stderr)

    def _build_config(self, cookie: str):
        """构建 miner 配置"""
        from overwatch_drops_miner.config import MinerConfig
        
        room_ids = self._config_data.get("room_ids", [])
        thread_count = self._config_data.get("thread_count", 60)
        reconnect_delay = self._config_data.get("reconnect_delay_seconds", 8)
        task_ids = self._config_data.get("task_ids", [])
        task_interval = self._config_data.get("task_query_interval_seconds", 30)
        notify_urls = self._config_data.get("notify_urls", [])
        
        return MinerConfig(
            cookie=cookie,
            room_ids=room_ids,
            thread_count=thread_count,
            reconnect_delay_seconds=reconnect_delay,
            task_ids=task_ids,
            task_query_interval_seconds=task_interval,
            notify_urls=notify_urls,
        )
    
    def add_event_callback(self, callback):
        """添加事件回调"""
        self._event_callbacks.append(callback)
    
    def _write_line(self, text: str) -> None:
        """向 stdout 写入一行（线程安全，stdout 是 JSON 协议通道）"""
        with self._stdout_lock:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()

    def _emit_event(self, event_type: str, data: dict):
        """发送事件到 Tauri：{"type": "event", "event": xxx, "data": {...}}"""
        payload = {"type": "event", "event": event_type, "data": data}
        try:
            self._write_line(json.dumps(payload, ensure_ascii=False))
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
            "update_notify_urls": self._update_notify_urls,
            "stop_all": self._stop_all,
        }
        
        handler = handlers.get(command)
        if not handler:
            return {"error": f"未知命令: {command}"}
        
        try:
            return await handler(params)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
    
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

        from overwatch_drops_miner.client import BilibiliClient

        client = BilibiliClient(cookie)
        try:
            info = await asyncio.wait_for(client.get_self_info(), timeout=30.0)
        except Exception as e:
            return {"error": f"Cookie 验证失败: {e}"}
        finally:
            try:
                await client.close()
            except Exception:
                pass

        uname = str(info.get("uname", "") or "") if isinstance(info, dict) else ""
        uid = info.get("uid") if isinstance(info, dict) else None
        if not uid:
            return {"error": "无法获取用户信息，Cookie 可能已失效"}

        account = self.account_store.add(cookie)
        remark = uname or account.remark or account.id[:8]
        if uname:
            account = self.account_store.update(account.id, remark=uname)

        return {"id": account.id, "remark": remark, "running": False}
    
    async def _remove_account(self, params: dict) -> dict:
        """删除账号"""
        account_id = params.get("account_id", "")
        if not account_id:
            return {"error": "账号 ID 不能为空"}
        
        if self.miner_manager and self.miner_manager.is_running(account_id):
            self.miner_manager.request_stop(account_id)
        
        if self.account_store:
            self.account_store.remove(account_id)
        
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
        """启动 miner"""
        account_id = params.get("account_id", "")
        config = params.get("config", {})
        
        if not account_id:
            return {"error": "账号 ID 不能为空"}
        
        self._config_data = {
            "room_ids": config.get("room_ids", []),
            "thread_count": config.get("thread_count", 60),
            "reconnect_delay_seconds": config.get("reconnect_delay_seconds", 8),
            "task_ids": config.get("task_ids", []),
            "task_query_interval_seconds": config.get("task_query_interval_seconds", 30),
            "notify_urls": config.get("notify_urls", []),
        }
        
        if not self.miner_manager or not self.account_store:
            return {"error": "后端未初始化"}
        
        account = self.account_store.get(account_id)
        if not account:
            return {"error": "账号不存在"}
        
        from overwatch_drops_miner.watch_time_tracker import WatchTimeTracker
        tracker = WatchTimeTracker()
        self._watch_trackers[account_id] = tracker
        tracker.resume()

        success = self.miner_manager.start(account)
        if not success:
            return {"error": "启动失败"}
        
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
        tracker = self._watch_trackers.get(account_id)
        if tracker:
            tracker.pause()
        self._emit_event("account-state-changed", {"account_id": account_id, "running": False})
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

        from overwatch_drops_miner.gui_parts.task_presenter import format_watch_status_line
        from overwatch_drops_miner.watch_time_tracker import estimate_remaining_seconds
        status_line = format_watch_status_line(
            running=running,
            bili_cur_minutes=None,
            local_elapsed_seconds=watch_time,
        )

        return {
            "account_id": account_id,
            "running": running,
            "watch_time_seconds": watch_time,
            "status_line": status_line,
            "task_progress": None,
        }
    
    async def _save_config(self, params: dict) -> dict:
        """保存配置"""
        config = params.get("config", {})
        verbose = bool(config.get("verbose", False))
        self._config_data = {
            "room_ids": [int(x) for x in config.get("room_ids", [])],
            "thread_count": int(config.get("thread_count", 60)),
            "reconnect_delay_seconds": int(config.get("reconnect_delay_seconds", 8)),
            "task_ids": config.get("task_ids", []),
            "task_query_interval_seconds": int(config.get("task_query_interval_seconds", 30)),
            "notify_urls": config.get("notify_urls", []),
            "notify_on_task_complete": bool(config.get("notify_on_task_complete", True)),
            "auto_claim_rewards": bool(config.get("auto_claim_rewards", False)),
            "verbose": verbose,
        }
        # 详细日志开关保存后立即生效
        self._apply_verbose(verbose)
        self._save_config_file()
        return {}

    async def _load_config(self, params: dict) -> dict:
        """加载配置（含持久化文件）"""
        return {
            "cookie": "",
            "rooms_text": ",".join(str(x) for x in self._config_data.get("room_ids", [])),
            "thread_count_text": str(self._config_data.get("thread_count", 60)),
            "reconnect_delay_text": str(self._config_data.get("reconnect_delay_seconds", 8)),
            "task_ids_text": ",".join(self._config_data.get("task_ids", [])),
            "task_query_interval_text": str(self._config_data.get("task_query_interval_seconds", 30)),
            "notify_urls_text": ",".join(self._config_data.get("notify_urls", [])),
            "notify_on_task_complete": self._config_data.get("notify_on_task_complete", True),
            "verbose": self._config_data.get("verbose", False),
            "auto_claim_rewards": self._config_data.get("auto_claim_rewards", False),
        }

    async def _export_config(self, params: dict) -> dict:
        """导出配置到用户选择的 JSON 文件"""
        import tempfile
        payload = {
            "room_ids": self._config_data.get("room_ids", []),
            "thread_count": self._config_data.get("thread_count", 60),
            "reconnect_delay_seconds": self._config_data.get("reconnect_delay_seconds", 8),
            "task_ids": self._config_data.get("task_ids", []),
            "task_query_interval_seconds": self._config_data.get("task_query_interval_seconds", 30),
            "notify_urls": self._config_data.get("notify_urls", []),
            "notify_on_task_complete": self._config_data.get("notify_on_task_complete", True),
            "auto_claim_rewards": self._config_data.get("auto_claim_rewards", False),
            "verbose": self._config_data.get("verbose", False),
        }
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        try:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            return {"path": tmp.name}
        except Exception:
            tmp.close()
            raise

    async def _import_config(self, params: dict) -> dict:
        """从 JSON 文件导入配置"""
        path = params.get("path", "")
        if not path:
            return {"error": "未指定配置文件路径"}
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return {"error": "配置文件格式错误"}
            self._config_data = {
                "room_ids": data.get("room_ids", []),
                "thread_count": data.get("thread_count", 60),
                "reconnect_delay_seconds": data.get("reconnect_delay_seconds", 8),
                "task_ids": data.get("task_ids", []),
                "task_query_interval_seconds": data.get("task_query_interval_seconds", 30),
                "notify_urls": data.get("notify_urls", []),
                "notify_on_task_complete": data.get("notify_on_task_complete", True),
                "auto_claim_rewards": data.get("auto_claim_rewards", False),
                "verbose": data.get("verbose", False),
            }
            self._apply_verbose(self._config_data.get("verbose", False))
            self._save_config_file()
            return await self._load_config({})
        except Exception as e:
            return {"error": f"导入配置失败: {e}"}
    
    async def _qr_login(self, params: dict) -> dict:
        """生成登录二维码（复用原后端 QrLoginApi）"""
        try:
            from overwatch_drops_miner.client_parts.qr_login import QrLoginApi

            self._qr_close()
            api = QrLoginApi()
            try:
                challenge = await asyncio.to_thread(api.generate)
            except Exception:
                api.close()
                raise

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
        from overwatch_drops_miner.client_parts.qr_login import QrLoginStatus

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
        # QrLoginStatus.SUCCESS：Cookie 已就绪，会话结束
        cookie = result.cookie
        self._qr_close()
        return {"status": "success", "cookie": cookie}

    async def _qr_cancel(self, params: dict) -> dict:
        """关闭扫码登录会话（对话框取消/成功后释放连接）"""
        self._qr_close()
        return {}

    def _qr_close(self) -> None:
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

        from overwatch_drops_miner.client import BilibiliClient
        from overwatch_drops_miner.gui_parts.task_presenter import format_task_progress

        client = BilibiliClient(cookie)
        try:
            progresses = await asyncio.wait_for(
                client.get_task_progress(task_ids), timeout=60.0
            )
        finally:
            try:
                await client.close()
            except Exception:
                pass

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

        from overwatch_drops_miner.client import BilibiliClient
        from overwatch_drops_miner.gui_parts.task_presenter import format_reward_claim_results

        client = BilibiliClient(cookie)
        try:
            results = await asyncio.wait_for(
                client.receive_all_mission_rewards(task_ids), timeout=180.0
            )
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
        """TaskProgress 模型 → 前端结构"""
        rewards = []
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
        }

    async def _browser_capture(self, params: dict) -> dict:
        """浏览器捕获 - 使用 Selenium + 扩展捕获 B 站 Cookie"""
        if self._sniff_busy:
            return {"error": "已有一个浏览器自动获取任务在进行中，请稍候"}
        self._sniff_busy = True
        sniff_cancel = threading.Event()
        try:
            from overwatch_drops_miner.gui_parts.browser_sniffer import start_browser_sniff, select_login_cookies

            self._browser_capture_result = None
            self._browser_capture_event = threading.Event()

            def on_cookies(cookies: list[dict[str, Any]]) -> None:
                """Cookie 捕获回调"""
                filtered = select_login_cookies(cookies)
                if not filtered:
                    self._browser_capture_result = {"error": "未获取到有效登录 Cookie，请确认已登录 B 站"}
                    if self._browser_capture_event:
                        self._browser_capture_event.set()
                    return
                cookie_parts = [f"{c['name']}={c['value']}" for c in filtered]
                cookie_str = "; ".join(cookie_parts)
                self._browser_capture_result = {"cookie": cookie_str}
                if self._browser_capture_event:
                    self._browser_capture_event.set()
            
            def on_error(err_type: str, err_msg: str) -> None:
                """错误回调"""
                self._browser_capture_result = {"error": f"{err_type}: {err_msg}"}
                if self._browser_capture_event:
                    self._browser_capture_event.set()
            
            # 在线程池中运行浏览器捕获（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: start_browser_sniff(
                    url_keyword="bilibili.com",
                    hint="正在打开浏览器捕获 B 站 Cookie...",
                    start_url="https://www.bilibili.com/",
                    on_cookies=on_cookies,
                    on_error=on_error,
                    browser_preference=None,
                    finish_on_any=True,
                    cancel_event=sniff_cancel,
                )
            )
            
            # 等待捕获完成或超时（120秒）
            if self._browser_capture_event:
                await asyncio.wait_for(
                    asyncio.wrap_future(asyncio.to_thread(self._browser_capture_event.wait)),
                    timeout=120.0
                )
            
            if self._browser_capture_result:
                return self._browser_capture_result
            
            return {"error": "浏览器捕获超时或被取消"}
            
        except ImportError as e:
            return {"error": f"缺少依赖: {e}，请安装 selenium"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
        finally:
            sniff_cancel.set()
            self._sniff_busy = False
    
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

        from overwatch_drops_miner.client_parts.task_discovery import fetch_live_task_groups

        try:
            groups = await asyncio.wait_for(
                asyncio.to_thread(fetch_live_task_groups, room_id), timeout=30.0
            )
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": f"自动获取模式1失败: {type(e).__name__}（可改用模式2）"}

        normalized = self._normalize_task_groups(groups)
        if not normalized:
            return {"error": "未解析到掉宝任务分组，请改用模式2（浏览器嗅探）"}
        return {"room_id": room_id, "groups": normalized}

    async def _run_browser_sniff(self, *, kind: str, room_id: int) -> dict:
        """浏览器嗅探会话（kind: room=房间号 / task=任务ID模式2），单会话，120s 超时"""
        if self._sniff_busy:
            return {"error": "已有一个浏览器自动获取任务在进行中，请稍候"}
        self._sniff_busy = True
        cancel_event = threading.Event()
        result_box: dict[str, Any] = {}
        done = threading.Event()

        def _finish(payload: dict[str, Any]) -> None:
            if not done.is_set():
                result_box.update(payload)
                done.set()

        try:
            from overwatch_drops_miner.gui_parts.browser_sniffer import start_browser_sniff

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
                }
            else:
                from overwatch_drops_miner.gui_parts.browser_utils import (
                    extract_room_id_from_live_url,
                )
                from overwatch_drops_miner.utils import extract_bili_live_task_groups

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

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: start_browser_sniff(
                    on_error=on_error,
                    browser_preference=None,
                    cancel_event=cancel_event,
                    **sniff_kwargs,
                ),
            )

            try:
                await asyncio.wait_for(
                    asyncio.wrap_future(asyncio.to_thread(done.wait)),
                    timeout=120.0,
                )
            except asyncio.TimeoutError:
                return {"error": "浏览器捕获超时（2 分钟）"}
            return dict(result_box)
        except ImportError as e:
            return {"error": f"缺少依赖: {e}，请安装 selenium"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
        finally:
            cancel_event.set()
            self._sniff_busy = False

    async def _auto_fetch_room_id(self, params: dict) -> dict:
        """自动获取房间号（浏览器嗅探：打开目标直播间捕获 URL）"""
        return await self._run_browser_sniff(kind="room", room_id=0)

    async def _auto_fetch_task_ids_mode2(self, params: dict) -> dict:
        """自动获取任务ID（模式2：嗅探任务接口/页面 HTML，可同时拿到房间号）"""
        try:
            room_id = int(params.get("room_id") or 0)
        except (TypeError, ValueError):
            room_id = 0
        return await self._run_browser_sniff(kind="task", room_id=room_id)

    async def _sync_config_to_miners(self, params: dict) -> dict:
        """同步当前配置到运行中的 miner"""
        if not self.miner_manager:
            return {}
        running = self.miner_manager.running_miners()
        if not running:
            return {}
        reconnect_delay = self._config_data.get("reconnect_delay_seconds", 8)
        task_interval = self._config_data.get("task_query_interval_seconds", 30)
        notify_on_task_complete = self._config_data.get("notify_on_task_complete", True)
        task_ids = self._config_data.get("task_ids", [])
        notify_urls = self._config_data.get("notify_urls", [])
        for miner in running:
            if reconnect_delay > 0:
                miner.config.reconnect_delay_seconds = reconnect_delay
            if task_interval > 0:
                miner.config.task_query_interval_seconds = task_interval
            miner.config.notify_on_task_complete = notify_on_task_complete
            if task_ids != miner.config.task_ids:
                miner.config.task_ids = task_ids
            if notify_urls != miner.config.notify_urls:
                miner.update_notifier(notify_urls)
        return {}

    async def _detect_browsers(self, params: dict) -> dict:
        try:
            from overwatch_drops_miner.gui_parts.browser_utils import (
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

    async def _stop_all(self, params: dict) -> dict:
        if not self.miner_manager:
            return {"error": "后端未初始化"}
        self.miner_manager.stop_all(force=False)
        return {"success": True}

    async def _update_notify_urls(self, params: dict) -> dict:
        urls = params.get("urls", [])
        if not isinstance(urls, list):
            return {"error": "urls 必须是数组"}
        self._config_data["notify_urls"] = [str(u).strip() for u in urls if str(u).strip()]
        self._save_config_file()
        return {"success": True, "urls": self._config_data["notify_urls"]}

    async def _check_update(self, params: dict) -> dict:
        try:
            from overwatch_drops_miner.gui_parts.update_checker import check_latest_release
            from overwatch_drops_miner._version import (
                APP_VERSION,
                UPDATE_CHANNEL,
                LATEST_RELEASE_API,
                RELEASES_URL,
            )
            result = check_latest_release(
                app_version=APP_VERSION,
                update_channel=UPDATE_CHANNEL,
                latest_release_api=LATEST_RELEASE_API,
                releases_url=RELEASES_URL,
                timeout=8,
            )
            if result is None:
                return {"update_available": False}
            return {
                "update_available": True,
                "latest_version": result.latest_version,
                "release_url": result.release_url,
            }
        except Exception as e:
            return {"error": f"检查更新失败: {e}"}

    async def _shutdown(self, params: dict) -> dict:
        """应用关闭时清理浏览器资源"""
        try:
            from overwatch_drops_miner.gui_parts.browser_actions import BrowserActions
            ba = BrowserActions()
            closed = ba.shutdown(timeout=3.0)
            if not closed:
                print("[Sidecar] 浏览器嗅探线程未在预算时间内退出", file=sys.stderr)
        except Exception as e:
            print(f"[Sidecar] 关闭浏览器嗅探失败: {e}", file=sys.stderr)
        return {}

    async def _send_notification(self, params: dict) -> dict:
        """发送通知"""
        try:
            from overwatch_drops_miner.notifier import MultiPlatformNotifier
            
            title = params.get("title", "通知")
            body = params.get("body", "")
            notify_urls = params.get("notify_urls", self._config_data.get("notify_urls", []))
            
            if not notify_urls:
                return {"error": "未配置通知 URL"}
            
            notifier = MultiPlatformNotifier(notify_urls)
            if not notifier.enabled:
                return {"error": "无可用的通知渠道"}
            
            success = notifier.notify(title, body)
            return {"success": success}
            
        except ImportError as e:
            return {"error": f"缺少依赖: {e}，请安装 httpx"}
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}


async def main():
    """Sidecar 主循环 - 通过 stdin/stdout 与 Tauri 通信"""
    # 修复 stderr/stdout 中文乱码（stdout 承载 JSON 协议，必须 UTF-8）
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    sidecar = PythonSidecar()
    print("[Sidecar] 启动成功，等待 Tauri 连接...", file=sys.stderr)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
            command = request.get("command")
            params = request.get("params", {})
            response = await sidecar.handle_command(command, params)
        except json.JSONDecodeError:
            response = {"error": "无效的 JSON"}
        except Exception as e:
            response = {"error": str(e)}

        sidecar._write_line(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())






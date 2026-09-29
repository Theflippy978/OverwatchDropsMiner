"""
Python Sidecar - 作为 Tauri 2 的后端服务
通过 IPC 与 Tauri 前端通信，复用现有 overwatch_drops_miner 后端逻辑
"""
import asyncio
import json
import sys
import os
import threading
from pathlib import Path
from typing import Any

# 添加项目根目录到 Python 路径
project_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project_root))


class PythonSidecar:
    """处理来自 Tauri 的 IPC 请求"""
    
    def __init__(self):
        self.account_store = None
        self.miner_manager = None
        self._config_data = {}
        self._event_callbacks = []
        self._init_backend()
        self._browser_capture_result: dict | None = None
        self._browser_capture_event: threading.Event | None = None
    
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
    
    def _emit_event(self, event_type: str, data: dict):
        """发送事件到 Tauri"""
        event = {"type": event_type, "data": data}
        for callback in self._event_callbacks:
            try:
                callback(event)
            except Exception as e:
                print(f"[Sidecar] 事件回调失败: {e}", file=sys.stderr)
    
    async def handle_command(self, command: str, params: dict[str, Any]) -> dict[str, Any]:
        """路由到对应的现有后端接口"""
        handlers = {
            "get_accounts": self._get_accounts,
            "add_account": self._add_account,
            "remove_account": self._remove_account,
            "start_miner": self._start_miner,
            "stop_miner": self._stop_miner,
            "get_account_status": self._get_account_status,
            "save_config": self._save_config,
            "load_config": self._load_config,
            "qr_login": self._qr_login,
            "qr_poll": self._qr_poll,
            "browser_capture": self._browser_capture,
            "claim_rewards": self._claim_rewards,
            "refresh_tasks": self._refresh_tasks,
            "send_notification": self._send_notification,
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
        """添加账号"""
        cookie = params.get("cookie", "")
        if not cookie:
            return {"error": "Cookie 不能为空"}
        
        if not self.account_store:
            return {"error": "后端未初始化"}
        
        account = self.account_store.add(cookie)
        
        return {"id": account.id, "remark": account.remark, "running": False}
    
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
            watch_time = int(tracker.total_seconds())
        
        return {
            "account_id": account_id,
            "running": running,
            "watch_time_seconds": watch_time,
            "task_progress": None,
        }
    
    async def _save_config(self, params: dict) -> dict:
        """保存配置"""
        config = params.get("config", {})
        self._config_data = {
            "room_ids": [int(x) for x in config.get("room_ids", [])],
            "thread_count": int(config.get("thread_count", 60)),
            "reconnect_delay_seconds": int(config.get("reconnect_delay_seconds", 8)),
            "task_ids": config.get("task_ids", []),
            "task_query_interval_seconds": int(config.get("task_query_interval_seconds", 30)),
            "notify_urls": config.get("notify_urls", []),
        }
        return {}
    
    async def _load_config(self, params: dict) -> dict:
        """加载配置"""
        return {
            "cookie": "",
            "rooms_text": ",".join(str(x) for x in self._config_data.get("room_ids", [])),
            "thread_count_text": str(self._config_data.get("thread_count", 60)),
            "reconnect_delay_text": str(self._config_data.get("reconnect_delay_seconds", 8)),
            "task_ids_text": ",".join(self._config_data.get("task_ids", [])),
            "task_query_interval_text": str(self._config_data.get("task_query_interval_seconds", 30)),
            "notify_urls_text": ",".join(self._config_data.get("notify_urls", [])),
            "notify_on_task_complete": True,
            "verbose": False,
            "auto_claim_rewards": False,
        }
    
    async def _qr_login(self, params: dict) -> dict:
        """扫码登录"""
        return {"error": "扫码登录功能待实现"}
    
    async def _qr_poll(self, params: dict) -> dict:
        """轮询扫码状态"""
        return {"error": "扫码轮询功能待实现"}
    
    async def _browser_capture(self, params: dict) -> dict:
        """浏览器捕获 - 使用 Selenium + 扩展捕获 B 站 Cookie"""
        try:
            from overwatch_drops_miner.gui_parts.browser_sniffer import start_browser_sniff
            
            self._browser_capture_result = None
            self._browser_capture_event = threading.Event()
            
            def on_cookies(cookies: list[dict[str, Any]]) -> None:
                """Cookie 捕获回调"""
                # 构建 Cookie 字符串
                cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
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
    
    async def _claim_rewards(self, params: dict) -> dict:
        """领取奖励"""
        return {"error": "领取奖励功能待实现"}
    
    async def _refresh_tasks(self, params: dict) -> dict:
        """刷新任务"""
        return {"error": "刷新任务功能待实现"}


async def main():
    """Sidecar 主循环 - 通过 stdin/stdout 与 Tauri 通信"""
    # 修复 stderr 中文乱码
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    
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
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            print(json.dumps({"error": "无效的 JSON"}), flush=True)
        except Exception as e:
            print(json.dumps({"error": str(e)}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())






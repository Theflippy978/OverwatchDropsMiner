from __future__ import annotations

import logging
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx

# 统一脱敏入口：httpx 异常消息携带完整 URL，而本模块拼的 URL 里含
# gotify token / serverchan key / 企业微信 corpsecret 等凭据。
# 这些日志会经 python_sidecar 的 FrontendLogHandler 推给前端 LogViewer
# 明文显示，因此所有 str(exc) 日志点都必须走脱敏。
from .client_parts.http import sanitize_exception_text

LOGGER = logging.getLogger(__name__)


class _NativeNotifyTarget:
    def __init__(self, service_url: str) -> None:
        self.service_url = service_url
        self.parsed = urlparse(service_url)
        # wxwork access_token 实例级缓存：token 与获取时刻（monotonic 时钟）
        self._wxwork_access_token: str | None = None
        self._wxwork_token_fetched_at: float = 0.0

    @classmethod
    def from_url(cls, service_url: str) -> _NativeNotifyTarget | None:
        parsed = urlparse(service_url)
        if parsed.scheme in {"gotify", "gotifys", "schan", "wecombot", "wxwork"}:
            return cls(service_url)
        if (
            parsed.scheme in {"http", "https"}
            and parsed.netloc.lower() == "qyapi.weixin.qq.com"
            and parsed.path.rstrip("/") == "/cgi-bin/webhook/send"
            and parse_qs(parsed.query).get("key")
        ):
            return cls(service_url)
        return None

    def notify(self, title: str, body: str) -> bool:
        try:
            if self.parsed.scheme in {"gotify", "gotifys"}:
                return self._notify_gotify(title, body)
            if self.parsed.scheme == "schan":
                return self._notify_serverchan(title, body)
            if self.parsed.scheme == "wecombot" or self._is_wecombot_webhook():
                return self._notify_wecombot(title, body)
            if self.parsed.scheme == "wxwork":
                return self._notify_wxwork(title, body)
        except Exception as exc:
            # 必须脱敏：httpx 异常消息携带完整 URL（gotify token /
            # serverchan key / 企业微信 corpsecret 都在里面），而这条日志会经
            # FrontendLogHandler 推给前端 LogViewer 明文显示。
            LOGGER.warning("通知发送失败，%s", sanitize_exception_text(exc))
        return False

    def _notify_gotify(self, title: str, body: str) -> bool:
        path = self.parsed.path.strip("/")
        if not self.parsed.netloc or not path:
            raise ValueError("Gotify 通知 URL 缺少 host 或 token")

        path_prefix, _, token = path.rpartition("/")
        endpoint_path = f"/{path_prefix}/message" if path_prefix else "/message"
        scheme = "https" if self.parsed.scheme == "gotifys" else "http"
        endpoint = f"{scheme}://{self.parsed.netloc}{endpoint_path}"
        query = parse_qs(self.parsed.query)
        priority_value = query.get("priority", ["5"])[0].lower()
        priority = (
            int(priority_value)
            if priority_value.isdigit()
            else {"low": 1, "moderate": 4, "normal": 5, "high": 8}.get(
                priority_value,
                5,
            )
        )
        response = httpx.post(
            endpoint,
            headers={"X-Gotify-Key": unquote(token)},
            json={"title": title, "message": body, "priority": priority},
            timeout=10.0,
        )
        return self._is_success_response(response)

    def _notify_serverchan(self, title: str, body: str) -> bool:
        token = self.parsed.netloc or self.parsed.path.strip("/").split("/", 1)[0]
        if not token:
            raise ValueError("Server 酱通知 URL 缺少 SendKey")

        response = httpx.post(
            f"https://sctapi.ftqq.com/{unquote(token)}.send",
            # SCT 接口 title 上限 32 字符，超长会被服务端拒绝，发送前先截断
            data={"title": title[:32], "desp": body},
            timeout=10.0,
        )
        return self._is_success_response(response)

    def _notify_wecombot(self, title: str, body: str) -> bool:
        if self._is_wecombot_webhook():
            # parse_qs 已经对 query 做过一次 URL 解码，这里再 unquote 会造成
            # 双重解码（含 %2B 等转义的 key 会被破坏），因此直接使用原值
            key = parse_qs(self.parsed.query).get("key", [""])[0]
        else:
            # netloc/path 分支不会被 urlparse 自动解码，与 gotify/serverchan 一致手动解码
            key = unquote(
                self.parsed.netloc or self.parsed.path.strip("/").split("/", 1)[0]
            )
        if not key:
            raise ValueError("企业微信群机器人通知 URL 缺少 key")

        response = httpx.post(
            f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}",
            json={
                "msgtype": "text",
                "text": {"content": self._format_content(title, body)},
            },
            timeout=10.0,
        )
        return self._is_success_response(response)

    def _notify_wxwork(self, title: str, body: str) -> bool:
        parts = [unquote(part) for part in self.parsed.path.split("/") if part]
        if not self.parsed.netloc or len(parts) < 2:
            raise ValueError("企业微信应用通知 URL 需要 corpid/agentid/secret")

        corpid = unquote(self.parsed.netloc)
        agentid, secret = parts[0], parts[1]
        query = parse_qs(self.parsed.query)
        touser = query.get("to", query.get("touser", ["@all"]))[0]
        content = self._format_content(title, body)
        agent_id_value = int(agentid) if agentid.isdigit() else agentid

        def send(token: str) -> httpx.Response:
            return httpx.post(
                "https://qyapi.weixin.qq.com/cgi-bin/message/send",
                params={"access_token": token},
                json={
                    "touser": touser,
                    "msgtype": "text",
                    "agentid": agent_id_value,
                    "text": {"content": content},
                    "safe": 0,
                },
                timeout=10.0,
            )

        access_token = self._get_wxwork_access_token(corpid, secret)
        response = send(access_token)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict) and str(payload.get("errcode")) == "40014":
            # access_token 已失效（secret 更换/账号被踢等）：清缓存重取并
            # 重试一次，避免在缓存到期前通知持续失败。
            self._wxwork_access_token = None
            self._wxwork_token_fetched_at = 0.0
            access_token = self._get_wxwork_access_token(corpid, secret)
            response = send(access_token)
        return self._is_success_response(response)

    def _get_wxwork_access_token(self, corpid: str, secret: str) -> str:
        # access_token 有效期 7200 秒，留 300 秒安全余量，6900 秒内复用缓存，
        # 避免每次通知都额外请求一次 gettoken
        if (
            self._wxwork_access_token
            and time.monotonic() - self._wxwork_token_fetched_at < 6900.0
        ):
            return self._wxwork_access_token

        token_response = httpx.get(
            "https://qyapi.weixin.qq.com/cgi-bin/gettoken",
            params={"corpid": corpid, "corpsecret": secret},
            timeout=10.0,
        )
        # 不能用裸 raise_for_status()：httpx.HTTPStatusError 的消息固定携带
        # 完整 request.url，而 corpsecret 就在查询串里。用户只要把企业微信
        # 通知地址配错一次（应用停用 / IP 白名单变更 / corpid 敲错，都会返回
        # 4xx），密钥就经「notify() 的 LOGGER.warning」→ FrontendLogHandler
        # → log-entry 事件 → LogViewer 明文显示在 UI 上。拿到它可换取
        # access_token，以该应用身份向所有成员发消息（钓鱼 / 骚扰）。
        if token_response.status_code >= 400:
            # 只报状态码，绝不回显 URL（corpsecret 在里面）
            raise RuntimeError(
                f"企业微信 gettoken 失败: HTTP {token_response.status_code}"
            )
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            # 获取失败不写缓存，下次通知会重新尝试获取。
            # token_payload 只含 errcode/errmsg，不含密钥，可安全展示。
            raise ValueError(f"企业微信 access_token 获取失败: {token_payload}")

        self._wxwork_access_token = str(access_token)
        self._wxwork_token_fetched_at = time.monotonic()
        return self._wxwork_access_token

    def _is_wecombot_webhook(self) -> bool:
        return (
            self.parsed.scheme in {"http", "https"}
            and self.parsed.netloc.lower() == "qyapi.weixin.qq.com"
            and self.parsed.path.rstrip("/") == "/cgi-bin/webhook/send"
        )

    @staticmethod
    def _format_content(title: str, body: str) -> str:
        return f"{title}\n\n{body}" if title else body

    @staticmethod
    def _is_success_response(response: httpx.Response) -> bool:
        if not response.is_success:
            LOGGER.warning("通知发送失败，HTTP 状态码 %s", response.status_code)
            return False
        try:
            payload = response.json()
        except ValueError:
            return True

        # 归一化 errcode/code：键存在但值为 None 时回退到另一键，
        # 并兼容字符串 "0"、浮点 0.0 等形式，统一转成 int 后比较；
        # 两个键都缺失或均为 None 时保持旧行为视为成功
        # （例如 Gotify 返回不含状态码的 JSON）
        raw_code: object = None
        for key_name in ("errcode", "code"):
            if key_name in payload and payload[key_name] is not None:
                raw_code = payload[key_name]
                break

        if raw_code is None:
            return True

        try:
            # float() 中转兼容字符串 "0"、浮点 0.0 等形式后再取整
            error_code = int(float(raw_code))
        except (TypeError, ValueError):
            LOGGER.warning("通知发送失败，无法识别的状态码 %s", payload)
            return False

        if error_code != 0:
            LOGGER.warning("通知发送失败，响应 %s", payload)
            return False
        return True


class MultiPlatformNotifier:
    def __init__(self, service_urls: list[str] | None = None) -> None:
        self.service_urls: list[str] = []
        self._native_targets: list[_NativeNotifyTarget] = []
        self._apprise = None
        self._enabled = False
        self.update_urls(service_urls)

    def update_urls(self, service_urls: list[str] | None = None) -> None:
        """重建通知目标列表。

        线程安全约定（务必保持）：先在局部变量上完整构建新目标集，
        最后一次性整体替换实例字段。notify() 可能在 daemon 线程并发执行，
        整体换引用保证它读到的 _native_targets/_apprise/_enabled 永远
        自洽；切勿改成原地 append/clear（会引入竞态）。
        单条坏 URL 只跳过自身，不再连累其余通知目标。
        """
        cleaned = [url.strip() for url in (service_urls or []) if url.strip()]
        native_targets: list[_NativeNotifyTarget] = []
        apprise_urls: list[str] = []
        for url in cleaned:
            target = _NativeNotifyTarget.from_url(url)
            if target:
                native_targets.append(target)
            else:
                apprise_urls.append(url)

        apprise_app = None
        if apprise_urls:
            try:
                import apprise  # type: ignore

                app = apprise.Apprise()
                added_any = False
                for index, url in enumerate(apprise_urls, start=1):
                    try:
                        if app.add(url):
                            added_any = True
                        else:
                            # 不打印原始 URL：其中可能携带 token/key 等凭据
                            LOGGER.warning(
                                "第 %s 条通知地址无法解析，已跳过", index
                            )
                    except Exception:
                        LOGGER.warning(
                            "第 %s 条通知地址初始化失败，已跳过", index
                        )
                if added_any:
                    apprise_app = app
            except ImportError:
                LOGGER.warning(
                    "apprise 未安装，以下通知渠道将被跳过。安装方法: pip install apprise"
                )
            except Exception as exc:
                LOGGER.warning(
                    "apprise 通知组件初始化失败，%s", sanitize_exception_text(exc)
                )

        enabled = bool(native_targets) or apprise_app is not None
        self.service_urls = cleaned
        self._native_targets = native_targets
        self._apprise = apprise_app
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled and (
            bool(self._native_targets) or self._apprise is not None
        )

    def notify(self, title: str, body: str) -> bool:
        if not self.enabled:
            return False
        sent = False
        for target in self._native_targets:
            sent = target.notify(title=title, body=body) or sent
        try:
            if self._apprise is not None:
                sent = bool(self._apprise.notify(title=title, body=body)) or sent
        except Exception as exc:
            LOGGER.warning("通知发送失败，%s", sanitize_exception_text(exc))
        return sent

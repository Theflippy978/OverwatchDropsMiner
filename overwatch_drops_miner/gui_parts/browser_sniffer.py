from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterable
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Literal

from overwatch_drops_miner.client_parts.qr_login import LOGIN_COOKIE_NAMES
from overwatch_drops_miner.gui_parts.browser_utils import (
    browser_label,
    browser_try_order,
    extract_room_id_from_live_url,
    find_browser,
    find_browser_binary,
)
from overwatch_drops_miner.gui_parts.extension_builder import (
    write_chrome_extension,
    write_edge_extension,
)

SniffPayloadKind = Literal["cookies", "page", "network"]
NetworkCallback = Callable[[Any], None]
CookiesCallback = Callable[[list[dict[str, Any]]], None]
PageUrlCallback = Callable[[int], None]
PageHtmlCallback = Callable[[str, str], bool]
ErrorCallback = Callable[[str, str], None]


class SniffAbortError(RuntimeError):
    """嗅探前置条件不满足，需要直接终止本次嗅探并通知用户。"""

def classify_sniff_payload(data: dict[str, Any]) -> tuple[SniffPayloadKind, Any]:
    if data.get("type") == "__bili_cookies__":
        return "cookies", data["cookies"]
    if data.get("type") == "__bili_page__":
        return "page", data
    return "network", data


def select_login_cookies(cookies: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    has_sessdata = any(cookie.get("name") == "SESSDATA" for cookie in cookies)
    has_dedeuid = any(cookie.get("name") == "DedeUserID" for cookie in cookies)
    if not (has_sessdata and has_dedeuid):
        return None
    return [cookie for cookie in cookies if cookie.get("name") in LOGIN_COOKIE_NAMES]


def is_sniff_finished(
    enabled_done_pairs: Iterable[tuple[bool, bool]],
    *,
    finish_on_any: bool,
) -> bool:
    done_states = [done for enabled, done in enabled_done_pairs if enabled]
    if not done_states:
        return False
    return any(done_states) if finish_on_any else all(done_states)


def start_browser_sniff(
    url_keyword: str | None,
    hint: str,
    *,
    start_url: str | None = None,
    on_error: ErrorCallback,
    on_network_match: NetworkCallback | None = None,
    on_cookies: CookiesCallback | None = None,
    on_page_url: PageUrlCallback | None = None,
    on_page_html: PageHtmlCallback | None = None,
    browser_preference: str | None = None,
    finish_on_any: bool = False,
    logger: logging.Logger | None = None,
    cancel_event: threading.Event | None = None,
) -> threading.Thread:
    logger = logger or logging.getLogger(__name__)
    # 向后兼容：未传入取消事件时内部自建一个
    cancel_event = cancel_event or threading.Event()

    def _do() -> None:
        server = None
        server_thread = None
        ext_dir = None
        driver = None
        browser_type = None
        try:
            from selenium import webdriver

            need_net = bool(url_keyword and on_network_match)
            need_cookie = on_cookies is not None
            need_url = on_page_url is not None
            need_html = on_page_html is not None
            need_page = need_url or need_html

            net_captured: list[Any] = []
            cookie_captured: list[list[dict[str, Any]]] = []
            page_captured: list[dict[str, Any]] = []

            class _Handler(BaseHTTPRequestHandler):
                def do_POST(self) -> None:
                    length = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(length)
                    try:
                        data = json.loads(body)
                        kind, payload = classify_sniff_payload(data)
                        if kind == "cookies":
                            cookie_captured.append(payload)
                        elif kind == "page":
                            page_captured.append(payload)
                        else:
                            net_captured.append(payload)
                    except Exception:
                        pass
                    self.send_response(204)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()

                def do_OPTIONS(self) -> None:
                    self.send_response(204)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Access-Control-Allow-Methods", "POST")
                    self.send_header("Access-Control-Allow-Headers", "Content-Type")
                    self.end_headers()

                def log_message(self, *_args: Any) -> None:
                    pass

            server = HTTPServer(("127.0.0.1", 0), _Handler)
            port = server.server_address[1]
            server_thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
                name="bili-sniff-server",
            )
            server_thread.start()

            ext_dir = tempfile.mkdtemp(prefix="bili_sniff_")

            last_exc = None
            for browser in browser_try_order(browser_preference):
                if not find_browser(browser):
                    logger.info("未检测到 %s，跳过", browser)
                    continue
                try:
                    if browser == "edge":
                        write_edge_extension(
                            ext_dir,
                            port=port,
                            url_keyword=url_keyword,
                            need_net=need_net,
                            need_cookie=need_cookie,
                            need_page=need_page,
                        )
                        opts = webdriver.EdgeOptions()
                        browser_binary = find_browser_binary("edge")
                        if browser_binary:
                            opts.binary_location = browser_binary
                        opts.add_argument(f"--load-extension={ext_dir}")
                        driver = webdriver.Edge(options=opts)
                        browser_type = "edge"
                    else:
                        write_chrome_extension(
                            ext_dir,
                            port=server.server_address[1],
                            url_keyword=url_keyword,
                            need_net=need_net,
                            need_cookie=need_cookie,
                            need_page=need_page,
                        )
                        opts = webdriver.ChromeOptions()
                        browser_binary = find_browser_binary("chrome")
                        if browser_binary:
                            opts.binary_location = browser_binary
                        opts.enable_bidi = True
                        opts.enable_webextensions = True
                        opts.add_argument("--remote-allow-origins=*")
                        driver = webdriver.Chrome(options=opts)
                        browser_type = "chrome"
                        try:
                            driver.webextension.install(path=ext_dir)
                        except Exception as exc:
                            # 安装失败时嗅探能力实际为零，降级为与 Edge 分支一致的
                            # --load-extension 参数方式加载解压后的扩展目录
                            logger.warning(
                                "Chrome 扩展安装失败，降级为 --load-extension 参数方式加载: %s",
                                exc,
                            )
                            try:
                                driver.quit()
                            except Exception:
                                pass
                            driver = None
                            if not os.path.isfile(
                                os.path.join(ext_dir, "manifest.json")
                            ):
                                raise SniffAbortError(
                                    "Chrome 扩展安装失败，且本地扩展目录不可用，"
                                    "无法继续自动获取，请重试或检查浏览器配置。"
                                ) from exc
                            opts.add_argument(f"--load-extension={ext_dir}")
                            driver = webdriver.Chrome(options=opts)

                    break
                except SniffAbortError:
                    driver = None
                    browser_type = None
                    raise
                except Exception as exc:
                    last_exc = exc
                    driver = None
                    browser_type = None
                    logger.warning("浏览器 %s 启动失败: %s", browser, exc)

            if driver is None:
                raise RuntimeError(
                    "未找到可用浏览器（Edge/Chrome），请确认已安装并配置好 WebDriver。"
                    f"\n最后错误: {last_exc}"
                )

            driver.get(start_url or "https://www.bilibili.com/")
            logger.info("%s（浏览器: %s）", hint, browser_label(browser_type or ""))

            cookie_done = False
            net_done = False
            url_done = False
            html_done = False
            sniff_success = False
            html_attempts = 0
            last_cookie_count = 0
            for attempt in range(120):
                # 每次迭代边界响应取消请求，置位则静默退出（finally 会关闭浏览器）
                if cancel_event.is_set():
                    logger.info("嗅探操作已取消，正在退出")
                    break
                # 每 5 秒探测浏览器会话：用户手动关闭浏览器时立即失败退出，
                # 避免空转占住并发名额直到 120s 超时（后续自动获取全部被拒）
                if attempt % 5 == 0:
                    try:
                        _ = driver.current_url
                    except Exception:
                        logger.info("浏览器窗口已关闭，停止嗅探")
                        on_error("浏览器已关闭", "检测到浏览器被手动关闭，请重新发起获取")
                        break
                if need_cookie and not cookie_done and cookie_captured:
                    current_cookies = cookie_captured[-1]
                    filtered_cookies = select_login_cookies(current_cookies)
                    if filtered_cookies is not None and on_cookies is not None:
                        on_cookies(filtered_cookies)
                        cookie_done = True
                        logger.info("已检测到登入 Cookie")
                    elif len(cookie_captured) > last_cookie_count:
                        last_cookie_count = len(cookie_captured)

                if (need_url and not url_done) or (need_html and not html_done):
                    html_attempted = False
                    latest_page = None
                    while page_captured:
                        latest_page = page_captured.pop(0)
                    if latest_page:
                        cur_url = str(latest_page.get("url") or "")
                        room_id = extract_room_id_from_live_url(cur_url)

                        if (
                            room_id is not None
                            and need_url
                            and not url_done
                            and on_page_url is not None
                        ):
                            try:
                                on_page_url(room_id)
                                url_done = True
                            except Exception:
                                logger.exception("on_page_url 回调失败")

                        if (
                            room_id is not None
                            and need_html
                            and not html_done
                            and on_page_html is not None
                        ):
                            try:
                                page_html = str(latest_page.get("html") or "")
                                html_attempted = True
                                html_done = bool(on_page_html(page_html, cur_url))
                            except Exception:
                                logger.exception("页面源码回调失败")
                    if html_attempted and not html_done:
                        html_attempts += 1

                network_ready = (
                    not need_html
                    or not finish_on_any
                    or html_done
                    or html_attempts >= 3
                )
                if (
                    need_net
                    and not net_done
                    and net_captured
                    and network_ready
                    and on_network_match is not None
                ):
                    payload = net_captured.pop(0) if finish_on_any else net_captured[0]
                    try:
                        on_network_match(payload)
                        net_done = True
                    except Exception:
                        if finish_on_any:
                            logger.exception("网络响应回调失败，继续等待其他获取方式")
                        else:
                            raise

                if is_sniff_finished(
                    (
                        (need_cookie, cookie_done),
                        (need_net, net_done),
                        (need_url, url_done),
                        (need_html, html_done),
                    ),
                    finish_on_any=finish_on_any,
                ):
                    sniff_success = True
                    break

                # 等待期间也响应取消信号，避免最长 1 秒的无谓延迟
                if cancel_event.wait(1):
                    logger.info("嗅探操作已取消，正在退出")
                    break

            # 循环自然耗尽仍未捕获到内容且未被取消时，明确反馈用户而不是静默关闭浏览器
            if not sniff_success and not cancel_event.is_set():
                logger.warning("嗅探超过 2 分钟未捕获到内容，已自动关闭浏览器")
                on_error("超时", "超过 2 分钟未捕获到内容，浏览器已关闭，请重试")

        except ImportError as exc:
            on_error("依赖缺失", f"缺少依赖库，请安装后重试: {exc}\n\n")
        except SniffAbortError as exc:
            logger.error("自动获取终止: %s", exc)
            on_error("错误", str(exc))
        except Exception as exc:
            logger.exception("自动获取失败")
            on_error("错误", f"自动获取失败: {exc}")
        finally:
            if server:
                try:
                    server.shutdown()
                except Exception:
                    pass
                try:
                    server.server_close()
                except Exception:
                    pass
            if server_thread and server_thread.is_alive():
                try:
                    server_thread.join(timeout=2)
                except Exception:
                    pass
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
            if ext_dir:
                shutil.rmtree(ext_dir, ignore_errors=True)

    thread = threading.Thread(target=_do, daemon=True)
    thread.start()
    return thread

from __future__ import annotations

import json
import os


def build_page_reporter_js(port: int) -> str:
    return (
        "(function(){\n"
        "if(window.__bili_page_reporter__)return;\n"
        "window.__bili_page_reporter__=true;\n"
        "var last='';\n"
        "function sendPage(){\n"
        "  if(document.visibilityState!=='visible')return;\n"
        "  var url=window.location.href;\n"
        "  if(url.indexOf('live.bilibili.com')===-1)return;\n"
        "  var html=document.documentElement?document.documentElement.outerHTML:'';\n"
        "  var key=url+'|'+html.length;\n"
        "  if(key===last)return;\n"
        "  last=key;\n"
        "  fetch('http://127.0.0.1:"
        + str(port)
        + "/',{\n"
        "    method:'POST',\n"
        "    headers:{'Content-Type':'application/json'},\n"
        "    body:JSON.stringify({type:'__bili_page__',url:url,html:html})\n"
        "  }).catch(function(){});\n"
        "}\n"
        "sendPage();\n"
        "setInterval(sendPage,1000);\n"
        "document.addEventListener('visibilitychange',sendPage);\n"
        "window.addEventListener('load',sendPage);\n"
        "})();"
    )


def _js_keyword_literal(url_keyword: str | None) -> str:
    """把 URL 关键词转义为安全的 JS 字符串字面量，防止注入破坏脚本结构。"""
    # json.dumps 默认 ensure_ascii=True 且转义控制字符，其输出是合法的
    # JavaScript 字符串字面量（JSON 字符串语法是 JS 语法的子集）。
    return json.dumps(url_keyword or "")


# fetch/XHR 嗅探主体：主世界（MAIN world）中劫持网络响应并 postMessage 给中继。
# __KW_LITERAL__ 占位符在构建时替换为转义后的关键词字面量。
_SNIFFER_MAIN_WORLD_TEMPLATE = (
    "var kw=__KW_LITERAL__;\n"
    "var origFetch=window.fetch;\n"
    "window.fetch=async function(){\n"
    "  var resp=await origFetch.apply(this,arguments);\n"
    "  var url=(typeof arguments[0]==='string')?arguments[0]:arguments[0].url;\n"
    "  if(document.visibilityState==='visible'&&url.indexOf(kw)!==-1){\n"
    "    try{var d=await resp.clone().json();\n"
    "      window.postMessage({type:'__bili_sniff__',payload:{url:url,data:d,"
    "page_url:window.location.href}},'*');\n"
    "    }catch(e){}\n"
    "  }\n"
    "  return resp;\n"
    "};\n"
    "var origOpen=XMLHttpRequest.prototype.open;\n"
    "var origSend=XMLHttpRequest.prototype.send;\n"
    "XMLHttpRequest.prototype.open=function(m,u){\n"
    "  this.__url=u;return origOpen.apply(this,arguments);};\n"
    "XMLHttpRequest.prototype.send=function(){\n"
    "  var self=this;\n"
    "  this.addEventListener('load',function(){\n"
    "    if(document.visibilityState==='visible'&&self.__url&&"
    "self.__url.indexOf(kw)!==-1){\n"
    "      try{window.postMessage({type:'__bili_sniff__',\n"
    "        payload:{url:self.__url,data:JSON.parse(self.responseText),"
    "page_url:window.location.href}},'*');\n"
    "      }catch(e){}\n"
    "    }\n"
    "  });\n"
    "  return origSend.apply(this,arguments);\n"
    "};\n"
)


def _build_sniffer_body(url_keyword: str | None) -> str:
    """生成嗅探主体代码，替换关键词占位符为安全字面量。"""
    return _SNIFFER_MAIN_WORLD_TEMPLATE.replace(
        "__KW_LITERAL__", _js_keyword_literal(url_keyword)
    )


def _build_inject_js(url_keyword: str | None) -> str:
    """Edge 内容脚本：IIFE 包装的嗅探主体，document_start 注入主世界。"""
    return "(function(){\n" + _build_sniffer_body(url_keyword) + "})();"


def _build_relay_js(port: int) -> str:
    """隔离世界中继：接收嗅探消息并转发到本地回环端口。

    同时用作 Chrome background 动态注入的 ISOLATED world func 体。
    """
    return (
        "window.addEventListener('message',function(e){\n"
        "  if(e.data&&e.data.type==='__bili_sniff__'){\n"
        "    fetch('http://127.0.0.1:"
        + str(port)
        + "/',{\n"
        "      method:'POST',\n"
        "      headers:{'Content-Type':'application/json'},\n"
        "      body:JSON.stringify(e.data.payload)\n"
        "    }).catch(function(){});\n"
        "  }\n"
        "});"
    )


def _build_cookie_reporter_js(
    port: int,
    *,
    require_sessdata: bool,
    with_change_listener: bool,
    guard_line: str = "",
) -> str:
    """生成 Cookie 上报脚本，两端共享；差异点由参数控制以保持原行为。

    - require_sessdata: True 时仅在有 SESSDATA Cookie 时上报（Edge 行为）；
      False 时只要有任意 Cookie 即上报（Chrome 行为）。
    - with_change_listener: 是否监听 cookies.onChanged 触发即时上报。
    - guard_line: 函数体开头的守卫语句（如 NEED_COOKIE 开关）。
    """
    filter_expr = (
        "cookies.some(function(c){return c.name==='SESSDATA';})"
        if require_sessdata
        else "cookies && cookies.length > 0"
    )
    lines = ["function reportCookies(){"]
    if guard_line:
        lines.append("  " + guard_line)
    lines.extend(
        [
            "  chrome.cookies.getAll({domain:'.bilibili.com'},function(cookies){",
            "    if(!(" + filter_expr + "))return;",
            "    fetch('http://127.0.0.1:" + str(port) + "/',{",
            "      method:'POST',",
            "      headers:{'Content-Type':'application/json'},",
            "      body:JSON.stringify({type:'__bili_cookies__',cookies:cookies})",
            "    }).catch(function(){});",
            "  });",
            "}",
            "reportCookies();",
            "setInterval(reportCookies,3000);",
        ]
    )
    if with_change_listener:
        lines.extend(
            [
                "chrome.cookies.onChanged.addListener(function(changeInfo){",
                "  if(changeInfo.cookie.domain.includes('bilibili.com')){",
                "    reportCookies();",
                "  }",
                "});",
            ]
        )
    return "\n".join(lines)


def _build_chrome_background_js(
    port: int,
    url_keyword: str | None,
    *,
    need_net: bool,
    need_cookie: bool,
) -> str:
    """生成 Chrome 扩展 background service worker 脚本。

    复用共享的嗅探主体、中继与 Cookie 上报模板；仅保留 Chrome 特有的
    tabs 动态注入逻辑与能力开关。
    """
    parts: list[str] = [
        "var NEED_NET = " + ("true" if need_net else "false") + ";\n",
        "var NEED_COOKIE = " + ("true" if need_cookie else "false") + ";\n",
        "var injectedTabs = {};\n",
        "var PORT = " + str(port) + ";\n",
        "function injectTab(tabId) {\n"
        "  if (!NEED_NET || injectedTabs[tabId]) return;\n"
        "  injectedTabs[tabId] = true;\n"
        "  chrome.scripting.executeScript({\n"
        "    target: {tabId: tabId},\n"
        "    world: 'ISOLATED',\n"
        "    func: function() {\n"
        + _build_relay_js(port)
        + "\n"
        "    }\n"
        "  });\n"
        "  chrome.scripting.executeScript({\n"
        "    target: {tabId: tabId},\n"
        "    world: 'MAIN',\n"
        "    func: function() {\n"
        "      if (window.__bili_sniff_injected__) return;\n"
        "      window.__bili_sniff_injected__ = true;\n"
        + _build_sniffer_body(url_keyword)
        + "\n"
        "    }\n"
        "  });\n"
        "}\n",
    ]
    if need_net:
        parts.append(
            "chrome.tabs.onUpdated.addListener(function(tabId, changeInfo, tab) {\n"
            "  if (changeInfo.status === 'loading') {\n"
            "    delete injectedTabs[tabId];\n"
            "    return;\n"
            "  }\n"
            "  if (changeInfo.status === 'complete' && tab.url && "
            "tab.url.indexOf('bilibili.com') !== -1) {\n"
            "    injectTab(tabId);\n"
            "  }\n"
            "});\n"
            "chrome.tabs.query({url: '*://*.bilibili.com/*'}, function(tabs) {\n"
            "  tabs.forEach(function(tab) { injectTab(tab.id); });\n"
            "});\n"
        )
    parts.append(
        _build_cookie_reporter_js(
            port,
            require_sessdata=False,
            with_change_listener=True,
            guard_line="if (!NEED_COOKIE) return;",
        )
    )
    return "".join(parts)


def _write_extension_files(
    ext_dir: str,
    manifest: dict,
    files: dict[str, str],
    *,
    indent: int | None = None,
) -> None:
    """统一写出 manifest.json 与扩展脚本文件（UTF-8）。"""
    with open(os.path.join(ext_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=indent)
    for fname, content in files.items():
        with open(os.path.join(ext_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)


def write_edge_extension(
    ext_dir: str,
    *,
    port: int,
    url_keyword: str | None,
    need_net: bool,
    need_cookie: bool,
    need_page: bool,
) -> None:
    """生成 Edge（MV3）扩展目录，行为与历史版本保持完全一致。"""
    manifest: dict = {
        "manifest_version": 3,
        "name": "BiliSniff",
        "version": "1.0",
        "host_permissions": ["http://127.0.0.1/*"],
        "content_scripts": [],
    }
    files: dict[str, str] = {}

    if need_net:
        manifest["content_scripts"] += [
            {
                "matches": ["*://*.bilibili.com/*"],
                "js": ["inject.js"],
                "run_at": "document_start",
                "world": "MAIN",
            },
            {
                "matches": ["*://*.bilibili.com/*"],
                "js": ["relay.js"],
                "run_at": "document_start",
            },
        ]
        files["inject.js"] = _build_inject_js(url_keyword)
        files["relay.js"] = _build_relay_js(port)

    if need_page:
        manifest["content_scripts"].append(
            {
                "matches": ["*://*.bilibili.com/*"],
                "js": ["page.js"],
                "run_at": "document_idle",
            }
        )
        files["page.js"] = build_page_reporter_js(port)

    if need_cookie:
        manifest["permissions"] = ["cookies"]
        manifest["host_permissions"].append("*://*.bilibili.com/*")
        manifest["background"] = {"service_worker": "background.js"}
        files["background.js"] = _build_cookie_reporter_js(
            port,
            require_sessdata=True,
            with_change_listener=False,
        )

    _write_extension_files(ext_dir, manifest, files)


def write_chrome_extension(
    ext_dir: str,
    *,
    port: int,
    url_keyword: str | None,
    need_net: bool,
    need_cookie: bool,
    need_page: bool,
) -> None:
    """生成 Chrome（MV3）扩展目录，行为与历史版本保持完全一致。"""
    background_js = _build_chrome_background_js(
        port,
        url_keyword,
        need_net=need_net,
        need_cookie=need_cookie,
    )

    manifest = {
        "manifest_version": 3,
        "name": "BiliSniff",
        "version": "1.0",
        "permissions": ["scripting", "tabs", "cookies"],
        "host_permissions": [
            "http://127.0.0.1/*",
            "*://*.bilibili.com/*",
        ],
        "background": {"service_worker": "background.js"},
        "content_scripts": [],
    }

    if need_net:
        manifest["content_scripts"].append(
            {
                "matches": ["*://*.bilibili.com/*"],
                "js": ["relay.js"],
                "run_at": "document_start",
            }
        )

    if need_page:
        manifest["content_scripts"].append(
            {
                "matches": ["*://*.bilibili.com/*"],
                "js": ["page.js"],
                "run_at": "document_idle",
            }
        )

    files: dict[str, str] = {"background.js": background_js}
    if need_net:
        files["relay.js"] = _build_relay_js(port)
    if need_page:
        files["page.js"] = build_page_reporter_js(port)

    _write_extension_files(ext_dir, manifest, files, indent=2)

"""应用版本与更新渠道。

这两个值是**两条独立的轴**，不要混成一个字符串：

* ``APP_VERSION`` —— 版本号，必须是与 ``tauri.conf.json`` / ``Cargo.toml`` /
  ``package.json`` 同源的**可比较数字**（形如 ``1.2.0``）。更新检查要拿它跟
  远端 tag 做数值比较，写成一个不可比较的占位串（如 ``0.0.0+dev``）会让
  「有没有新版」这个判断失去意义 —— 任何远端 tag 都会被判成「更新」。
* ``UPDATE_CHANNEL`` —— 发布渠道，取值 ``release`` 或 ``dev``。它决定
  **自动**更新检查要不要打 GitHub API：``dev`` 不打（本地开发时没必要，
  而且未认证 API 限流 60 次/小时）。手动点「检查更新」不受它约束。

**发布打包时必须把它改成 ``release``**：留在 ``dev`` 的正式包不会自动提示
新版本，用户只能靠手动点按钮发现更新。本地开发完记得改回 ``dev``，
否则每次启动都白打一次 API。

早前的写法把「开发版」塞进版本号本身（``APP_VERSION = "0.0.0+dev"``），
后果是手动检查也被判为不可比较而直接返回，按钮成了空操作 —— 交互反馈
（菊花、3 秒提示）一切正常，但永远显示「已是最新版本」，无从察觉。
"""
APP_VERSION = "1.2.1"
UPDATE_CHANNEL = "release"
# 更新检查指向本 fork。指向上游仓库会让发布出去的程序去拉别人的 release。
REPOSITORY_URL = "https://github.com/Theflippy978/OverwatchDropsMiner"
LATEST_RELEASE_API = "https://api.github.com/repos/Theflippy978/OverwatchDropsMiner/releases/latest"
RELEASES_URL = "https://github.com/Theflippy978/OverwatchDropsMiner/releases/latest"

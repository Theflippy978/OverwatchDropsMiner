from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import httpx

from python_sidecar.backend.async_backend import ensure_anyio_asyncio_backend_ready
from python_sidecar.backend.client_parts.constants import (
    WBI_MIXIN_KEY_ENC_TAB,
)
from python_sidecar.backend.client_parts.cookies import (
    DEFAULT_USER_AGENT,
    build_cookie_state,
    build_default_headers,
    build_live_headers,
    build_mission_headers,
    generate_live_buvid,
)
from python_sidecar.backend.client_parts.http import (
    is_rate_limited_payload,
    parse_json_response,
    raise_for_status_sanitized,
    request_with_transient_retry,
    sanitize_exception_text,
    signed_get_json,
    signed_post_form_json,
    signed_post_json,
    signed_post_query_json,
)
from python_sidecar.backend.client_parts.live import (
    parse_live_room_info,
)
from python_sidecar.backend.client_parts.live_trace import (
    apply_live_trace_heartbeat_payload,
    build_live_trace_enter_params,
    build_live_trace_heartbeat_params,
    build_x25kn_signature,
    compact_json,
    hmac_by_rule,
    live_trace_session_from_enter_payload,
)
from python_sidecar.backend.client_parts.models import (
    LiveRoomInfo,
    LiveTraceSession,
    MissionRewardClaimResult,
    MissionRewardInfo,
    TaskProgress,
)
from python_sidecar.backend.client_parts.profile import (
    parse_self_info,
    validate_nav_payload,
)
from python_sidecar.backend.client_parts.rewards import (
        MISSION_RETRY_DELAYS,
        REWARD_CLAIM_BATCH_SIZE,
        REWARD_CLAIM_INTERVAL_SECONDS,
    build_reward_receive_body,
    failed_reward_claim_result,
    normalize_task_id,
    parse_mission_reward_info,
    reward_claim_result_from_payload,
    skipped_reward_claim_result,
)
from python_sidecar.backend.client_parts.task_parsing import (
    coerce_task_number,
    extract_task_indicator_values,
)
from python_sidecar.backend.client_parts.tasks import (
    normalize_task_ids,
    parse_task_progress_payload,
    resolve_reward_task_ids,
)
from python_sidecar.backend.client_parts.wbi import (
    encode_query,
    get_mixin_key,
    parse_wbi_keys_from_nav,
    sign_wbi_params,
)

LOGGER = logging.getLogger(__name__)


_coerce_task_number = coerce_task_number
_extract_task_indicator_values = extract_task_indicator_values


class BilibiliClient:
    MIXIN_KEY_ENC_TAB = WBI_MIXIN_KEY_ENC_TAB

    def __init__(self, cookie: str) -> None:
        ensure_anyio_asyncio_backend_ready()

        self.cookie_map, self.cookie_header, self.bili_jct = build_cookie_state(cookie)
        self.user_agent = DEFAULT_USER_AGENT
        self.live_buvid = self._generate_live_buvid()
        self.live_uuid = str(uuid.uuid4())
        self._wbi_cache: tuple[str, str] | None = None
        # WBI 缓存并发 miss 单飞锁：client 绑定单一事件循环，无跨循环问题
        self._wbi_lock = asyncio.Lock()
        # 离线房间告警去重：每次重连都会走 live_trace_enter，仅首见警告
        self._offline_warned_rooms: set[int] = set()

        self._http = httpx.AsyncClient(
            timeout=20.0,
            limits=httpx.Limits(max_connections=256, max_keepalive_connections=64),
            headers=build_default_headers(self.user_agent, self.cookie_header),
        )

    def update_cookie(self, cookie: str) -> None:
        self.cookie_map, self.cookie_header, self.bili_jct = build_cookie_state(
            cookie,
            fallback_buvid3=self.cookie_map.get("buvid3"),
        )
        self._http.headers["Cookie"] = self.cookie_header
        self._wbi_cache = None

    async def close(self) -> None:
        await self._http.aclose()

    async def nav(self) -> dict[str, Any]:
        url = "https://api.bilibili.com/x/web-interface/nav"
        response = await self._request_with_transient_retry(
            lambda: self._http.get(url),
            method="GET",
            url=url,
        )
        # 必须走脱敏包装而非裸 raise_for_status()：HTTPStatusError 的消息固定
        # 携带完整 request.url。当前 nav 的 URL 无 query 故不泄漏，但这是一枚
        # 地雷 —— 任何人给 nav() 加一个 params 就会静默开始泄漏，而 4 个
        # signed_* 已建立「统一包装」的正确范式，不该留例外。
        raise_for_status_sanitized(response, method="GET")
        payload = parse_json_response(response, method="GET", url=url)
        validate_nav_payload(payload)
        return payload

    async def get_self_info(self) -> tuple[int | None, str]:
        payload = await self.nav()
        return parse_self_info(payload)

    async def get_wbi_keys(self) -> tuple[str, str]:
        if self._wbi_cache is not None:
            return self._wbi_cache
        # 双检锁单飞：并发 miss 时只发起一次 nav 请求，避免冗余请求互相覆盖缓存
        async with self._wbi_lock:
            if self._wbi_cache is not None:
                return self._wbi_cache
            payload = await self.nav()
            img_key, sub_key = parse_wbi_keys_from_nav(payload)
            self._wbi_cache = (img_key, sub_key)
            return img_key, sub_key

    @classmethod
    def _get_mixin_key(cls, img_key: str, sub_key: str) -> str:
        return get_mixin_key(img_key, sub_key)

    @classmethod
    def _encode_query(cls, params: dict[str, Any]) -> str:
        return encode_query(params)

    async def sign_wbi(self, params: dict[str, Any]) -> dict[str, Any]:
        img_key, sub_key = await self.get_wbi_keys()
        return sign_wbi_params(
            params,
            img_key=img_key,
            sub_key=sub_key,
            timestamp=int(time.time()),
        )

    @staticmethod
    def _generate_live_buvid() -> str:
        return generate_live_buvid()

    @staticmethod
    def _compact_json(value: Any) -> str:
        return compact_json(value)

    def _live_headers(self, room_id: int, *, lite: bool = False) -> dict[str, str]:
        return build_live_headers(
            room_id,
            user_agent=self.user_agent,
            cookie_header=self.cookie_header,
            lite=lite,
        )

    def _mission_headers(self, task_id: str) -> dict[str, str]:
        return build_mission_headers(
            task_id,
            user_agent=self.user_agent,
            cookie_header=self.cookie_header,
        )

    @staticmethod
    def _is_rate_limited_payload(payload: dict[str, Any]) -> bool:
        return is_rate_limited_payload(payload)

    def _clear_wbi_cache(self) -> None:
        self._wbi_cache = None

    async def _request_with_transient_retry(
        self,
        request_coro,
        *,
        method: str,
        url: str,
    ) -> httpx.Response:
        return await request_with_transient_retry(
            request_coro,
            method=method,
            url=url,
            logger=LOGGER,
        )

    async def _signed_get_json(
        self,
        url: str,
        params: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        retry_on_wbi_miss: bool = True,
    ) -> dict[str, Any]:
        return await signed_get_json(
            http=self._http,
            sign_wbi=self.sign_wbi,
            clear_wbi_cache=self._clear_wbi_cache,
            logger=LOGGER,
            url=url,
            params=params,
            headers=headers,
            follow_redirects=follow_redirects,
            retry_on_wbi_miss=retry_on_wbi_miss,
        )

    async def _signed_post_json(
        self,
        url: str,
        params: dict[str, Any],
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        retry_on_wbi_miss: bool = True,
    ) -> dict[str, Any]:
        return await signed_post_json(
            http=self._http,
            sign_wbi=self.sign_wbi,
            clear_wbi_cache=self._clear_wbi_cache,
            logger=LOGGER,
            url=url,
            params=params,
            body=body,
            headers=headers,
            retry_on_wbi_miss=retry_on_wbi_miss,
        )

    async def _signed_post_query_json(
        self,
        url: str,
        params: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = False,
        retry_on_wbi_miss: bool = True,
    ) -> dict[str, Any]:
        return await signed_post_query_json(
            http=self._http,
            sign_wbi=self.sign_wbi,
            clear_wbi_cache=self._clear_wbi_cache,
            logger=LOGGER,
            url=url,
            params=params,
            headers=headers,
            follow_redirects=follow_redirects,
            retry_on_wbi_miss=retry_on_wbi_miss,
        )

    async def _signed_post_form_json(
        self,
        url: str,
        params: dict[str, Any],
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        retry_on_wbi_miss: bool = True,
    ) -> dict[str, Any]:
        return await signed_post_form_json(
            http=self._http,
            sign_wbi=self.sign_wbi,
            clear_wbi_cache=self._clear_wbi_cache,
            logger=LOGGER,
            url=url,
            params=params,
            body=body,
            headers=headers,
            retry_on_wbi_miss=retry_on_wbi_miss,
        )

    async def get_live_room_info(self, room_id: int) -> LiveRoomInfo:
        payload = await self._signed_get_json(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom",
            {
                "room_id": room_id,
                "web_location": "444.8",
            },
            headers=self._live_headers(room_id),
            retry_on_wbi_miss=True,
        )
        return parse_live_room_info(payload, room_id)

    async def room_entry_action(self, room_id: int) -> None:
        if not self.bili_jct:
            raise ValueError("cookie 缺少 bili_jct，无法上报 roomEntryAction")
        payload = await self._signed_post_json(
            "https://api.live.bilibili.com/xlive/web-room/v1/index/roomEntryAction",
            {"csrf": self.bili_jct},
            {"room_id": room_id, "platform": "pc"},
            headers=self._live_headers(room_id),
            retry_on_wbi_miss=True,
        )
        if payload.get("code") != 0:
            raise ValueError(
                f"roomEntryAction 失败 房间号：{room_id}，{payload.get('message')}"
            )

    @staticmethod
    def _hmac_by_rule(data: bytes, secret_key: str, rule: int) -> bytes:
        return hmac_by_rule(data, secret_key, rule)

    def _build_x25kn_signature(
        self,
        *,
        parent_area_id: int,
        area_id: int,
        seq_id: int,
        room_id: int,
        ets: int,
        duration: int,
        ts_ms: int,
        secret_key: str,
        secret_rule: list[int],
    ) -> str:
        return build_x25kn_signature(
            live_buvid=self.live_buvid,
            live_uuid=self.live_uuid,
            parent_area_id=parent_area_id,
            area_id=area_id,
            seq_id=seq_id,
            room_id=room_id,
            ets=ets,
            duration=duration,
            ts_ms=ts_ms,
            secret_key=secret_key,
            secret_rule=secret_rule,
        )

    async def live_trace_enter(self, room_id: int) -> LiveTraceSession:
        if not self.bili_jct:
            raise ValueError("cookie 缺少 bili_jct，无法初始化 x25Kn 心跳")

        room = await self.get_live_room_info(room_id)
        if room.live_status != 1:
            # 离线房间每次重连都会走到这里：按房间只告警一次，
            # 防止重连循环把日志刷满
            if room.room_id not in self._offline_warned_rooms:
                self._offline_warned_rooms.add(room.room_id)
                LOGGER.warning(
                    "房间号：%s 当前状态非开播 直播状态：%s，计时可能不会增长",
                    room.room_id,
                    room.live_status,
                )

        params = build_live_trace_enter_params(
            room,
            live_buvid=self.live_buvid,
            live_uuid=self.live_uuid,
            user_agent=self.user_agent,
            csrf=self.bili_jct,
            ts_ms=int(time.time() * 1000),
        )
        payload = await self._signed_post_query_json(
            "https://live-trace.bilibili.com/xlive/data-interface/v1/x25Kn/E",
            params,
            headers=self._live_headers(room.room_id, lite=True),
            retry_on_wbi_miss=True,
        )
        if payload.get("code") != 0:
            raise ValueError(
                f"x25Kn/E 失败 房间号：{room.room_id}，{payload.get('message')}"
            )
        return live_trace_session_from_enter_payload(payload, room=room)

    async def live_trace_heartbeat(self, session: LiveTraceSession) -> LiveTraceSession:
        if not self.bili_jct:
            raise ValueError("cookie 缺少 bili_jct，无法发送 x25Kn/X")
        if not session.secret_key or not session.secret_rule:
            raise ValueError("x25Kn 会话缺少 secret_key/secret_rule")

        next_seq = session.seq_id + 1
        expected_interval = max(1, int(session.heartbeat_interval))
        duration_used = expected_interval
        ts_ms = int(time.time() * 1000)
        actual_elapsed = max(1, int(ts_ms / 1000 - session.ets))
        # 回退到老版本语义：固定心跳间隔上报，避免双路径重试放大抖动。
        # actual_elapsed 仅用于失败日志定位。

        signature = self._build_x25kn_signature(
            parent_area_id=session.parent_area_id,
            area_id=session.area_id,
            seq_id=next_seq,
            room_id=session.room_id,
            ets=session.ets,
            duration=duration_used,
            ts_ms=ts_ms,
            secret_key=session.secret_key,
            secret_rule=session.secret_rule,
        )

        params = build_live_trace_heartbeat_params(
            session,
            live_buvid=self.live_buvid,
            live_uuid=self.live_uuid,
            user_agent=self.user_agent,
            csrf=self.bili_jct,
            signature=signature,
            next_seq=next_seq,
            duration=duration_used,
            ts_ms=ts_ms,
        )

        payload = await self._signed_post_query_json(
            "https://live-trace.bilibili.com/xlive/data-interface/v1/x25Kn/X",
            params,
            headers=self._live_headers(session.room_id, lite=True),
            follow_redirects=True,
            retry_on_wbi_miss=True,
        )

        if payload.get("code") != 0:
            raise ValueError(
                "x25Kn/X 失败 "
                f"房间号：{session.room_id}，{payload.get('message')} "
                f"(已用时长：{duration_used}, 期望间隔：{expected_interval}, "
                f"实际间隔：{actual_elapsed})"
            )

        return apply_live_trace_heartbeat_payload(
            session,
            payload,
            next_seq=next_seq,
        )

    async def get_task_progress(self, task_ids: list[str]) -> list[TaskProgress]:
        normalized_ids = normalize_task_ids(task_ids)
        if not normalized_ids:
            return []
        if not self.bili_jct:
            raise ValueError("cookie 缺少 bili_jct，无法查询任务进度")

        payload = await self._signed_get_json(
            "https://api.bilibili.com/x/task/totalv2",
            {
                "csrf": self.bili_jct,
                "task_ids": ",".join(normalized_ids),
                "web_location": "0.0",
            },
            headers={
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
                "User-Agent": self.user_agent,
                "Cookie": self.cookie_header,
            },
            retry_on_wbi_miss=True,
        )
        return parse_task_progress_payload(payload)

    async def get_mission_reward_info(self, task_id: str) -> MissionRewardInfo:
        normalized_id = normalize_task_id(task_id)

        payload: dict[str, Any] = {}
        for attempt, delay in enumerate(MISSION_RETRY_DELAYS, start=1):
            if delay > 0:
                await asyncio.sleep(delay)
            payload = await self._signed_get_json(
                "https://api.bilibili.com/x/activity_components/mission/info",
                {"task_id": normalized_id},
                headers=self._mission_headers(normalized_id),
                retry_on_wbi_miss=True,
            )
            if payload.get("code") == 0 or not self._is_rate_limited_payload(payload):
                break
            if attempt < len(MISSION_RETRY_DELAYS):
                LOGGER.warning(
                    "查询领奖信息触发限频 任务ID：%s 第 %s/%s 次，稍后重试",
                    normalized_id,
                    attempt,
                    len(MISSION_RETRY_DELAYS),
                )
            else:
                LOGGER.warning(
                    "查询领奖信息持续限频 任务ID：%s 第 %s/%s 次，停止重试",
                    normalized_id,
                    attempt,
                    len(MISSION_RETRY_DELAYS),
                )
        return parse_mission_reward_info(payload, normalized_id=normalized_id)

    async def receive_mission_reward(
        self, info: MissionRewardInfo
    ) -> MissionRewardClaimResult:
        skipped_result = skipped_reward_claim_result(info)
        if skipped_result is not None:
            return skipped_result

        if not self.bili_jct:
            raise ValueError("cookie 缺少 bili_jct，无法领取奖励")

        body = build_reward_receive_body(info, csrf=self.bili_jct)
        payload: dict[str, Any] = {}
        for attempt, delay in enumerate(MISSION_RETRY_DELAYS, start=1):
            if delay > 0:
                await asyncio.sleep(delay)
            payload = await self._signed_post_form_json(
                "https://api.bilibili.com/x/activity_components/mission/receive",
                {},
                body,
                headers={
                    **self._mission_headers(info.task_id),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                retry_on_wbi_miss=True,
            )
            if payload.get("code") == 0 or not self._is_rate_limited_payload(payload):
                break
            if attempt < len(MISSION_RETRY_DELAYS):
                LOGGER.warning(
                    "领取奖励触发限频 任务ID：%s 第 %s/%s 次，稍后重试",
                    info.task_id,
                    attempt,
                    len(MISSION_RETRY_DELAYS),
                )
            else:
                LOGGER.warning(
                    "领取奖励持续限频 任务ID：%s 第 %s/%s 次，停止重试",
                    info.task_id,
                    attempt,
                    len(MISSION_RETRY_DELAYS),
                )
        return reward_claim_result_from_payload(info, payload)

    async def receive_all_mission_rewards(
        self, task_ids: list[str]
    ) -> list[MissionRewardClaimResult]:
        normalized_ids = normalize_task_ids(task_ids)
        if not normalized_ids:
            return []

        try:
            progresses = await self.get_task_progress(normalized_ids)
        except Exception as exc:
            LOGGER.warning(
                "领取前查询子任务失败，将使用原任务 ID %s",
                sanitize_exception_text(exc),
            )
            reward_task_ids = resolve_reward_task_ids(normalized_ids, [])
        else:
            reward_task_ids = resolve_reward_task_ids(normalized_ids, progresses)
            if reward_task_ids != normalized_ids:
                LOGGER.info(
                    "领奖任务已展开 任务组数：%s 领奖任务数：%s",
                    len(normalized_ids),
                    len(reward_task_ids),
                )

        # 限频只作用于「发起领取请求」这一刻，不占用后面的等待时间：
        # 原实现每个子任务之间无条件 sleep(1.2s)，N 个子任务就是 N×1.2s
        # 的纯空转，与各子任务自身要等的网络时间（退避 0/1.5/3.0s +
        # WBI 签名 + 20s 超时）串行叠加，很容易顶穿 180s 预算。
        # 限频改成按批次节流：批次内并发，只保证相邻批次的起点间隔不小于
        # REWARD_CLAIM_INTERVAL_SECONDS。请求总数与节流语义都不变。
        #
        # 用局部闭包而非方法：receive_all_mission_rewards 允许以鸭子类型
        # 的假客户端被 unbound 调用（只要求有 get_mission_reward_info 与
        # receive_mission_reward），抽成 self 上的方法会在那些调用方上
        # 抛 AttributeError。
        async def claim_one(task_id: str) -> MissionRewardClaimResult:
            """领取单个子任务；异常收敛成一条失败结果，不影响同批其他任务。"""
            try:
                info = await self.get_mission_reward_info(task_id)
                return await self.receive_mission_reward(info)
            except Exception as exc:
                return failed_reward_claim_result(task_id, exc)

        results: list[MissionRewardClaimResult] = []
        total = len(reward_task_ids)
        for start in range(0, total, REWARD_CLAIM_BATCH_SIZE):
            batch = reward_task_ids[start : start + REWARD_CLAIM_BATCH_SIZE]
            results.extend(await asyncio.gather(*(claim_one(tid) for tid in batch)))
            if start + REWARD_CLAIM_BATCH_SIZE < total:
                await asyncio.sleep(REWARD_CLAIM_INTERVAL_SECONDS)
        return results

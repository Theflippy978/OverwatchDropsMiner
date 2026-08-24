from __future__ import annotations

from typing import Any

from overwatch_drops_miner.client_parts.models import (
    MissionRewardClaimResult,
    MissionRewardInfo,
)

MISSION_RETRY_DELAYS = (0.0, 1.5, 3.0)
REWARD_CLAIM_INTERVAL_SECONDS = 1.2


def normalize_task_id(task_id: str) -> str:
    normalized_id = task_id.strip()
    if not normalized_id:
        raise ValueError("task_id 不能为空")
    return normalized_id


def parse_mission_reward_info(
    payload: dict[str, Any],
    *,
    normalized_id: str,
) -> MissionRewardInfo:
    if payload.get("code") != 0:
        raise ValueError(f"查询领奖信息失败: {payload.get('message')}")

    data = payload.get("data") or {}
    reward_info = data.get("reward_info") or {}
    if "status" not in data:
        # status 缺失时不能默认按 0 处理：0 会被误判为“可领取”并触发无效领取，
        # 这里直接抛错暴露异常的返回结构
        raise ValueError(
            f"领奖信息缺少 status 字段: task_id={normalized_id}, message={payload.get('message')}"
        )
    return MissionRewardInfo(
        task_id=str(data.get("task_id") or normalized_id),
        task_name=str(data.get("task_name") or normalized_id),
        status=int(data["status"] or 0),
        message=str(data.get("message") or ""),
        act_id=str(data.get("act_id") or ""),
        act_name=str(data.get("act_name") or ""),
        reward_name=str(reward_info.get("award_name") or ""),
    )


def build_reward_receive_body(
    info: MissionRewardInfo,
    *,
    csrf: str,
) -> dict[str, Any]:
    return {
        "task_id": info.task_id,
        "activity_id": info.act_id,
        "activity_name": info.act_name,
        "task_name": info.task_name,
        "reward_name": info.reward_name,
        "gaia_vtoken": "",
        "receive_from": "missionPage",
        "csrf": csrf,
        "csrf_token": csrf,
    }


def skipped_reward_claim_result(
    info: MissionRewardInfo,
) -> MissionRewardClaimResult | None:
    if info.is_claimed:
        return MissionRewardClaimResult(
            task_id=info.task_id,
            task_name=info.task_name,
            reward_name=info.reward_name,
            status=info.status,
            message=info.message or "已领取",
            success=True,
            skipped=True,
        )
    if not info.is_claimable:
        return MissionRewardClaimResult(
            task_id=info.task_id,
            task_name=info.task_name,
            reward_name=info.reward_name,
            status=info.status,
            message=info.message or "当前状态不可领取",
            success=False,
            skipped=True,
        )
    return None


def reward_claim_result_from_payload(
    info: MissionRewardInfo,
    payload: dict[str, Any],
) -> MissionRewardClaimResult:
    code = payload.get("code")
    message = str(payload.get("message") or "")
    if code == 0:
        if not message or message == "0":
            message = "领取成功"
        return MissionRewardClaimResult(
            task_id=info.task_id,
            task_name=info.task_name,
            reward_name=info.reward_name,
            status=6,
            message=message,
            success=True,
            skipped=False,
            code=code,
        )
    return MissionRewardClaimResult(
        task_id=info.task_id,
        task_name=info.task_name,
        reward_name=info.reward_name,
        status=info.status,
        message=message or "领取失败",
        success=False,
        skipped=False,
        code=code,
    )


def failed_reward_claim_result(
    task_id: str,
    exc: Exception,
) -> MissionRewardClaimResult:
    return MissionRewardClaimResult(
        task_id=task_id,
        task_name=task_id,
        reward_name="",
        status=-1,
        message=str(exc),
        success=False,
        skipped=False,
    )


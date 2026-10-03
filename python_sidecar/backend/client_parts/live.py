from __future__ import annotations

from typing import Any

from python_sidecar.backend.client_parts.models import LiveRoomInfo


def parse_live_room_info(payload: dict[str, Any], room_id: int) -> LiveRoomInfo:
    if payload.get("code") != 0:
        raise ValueError(
            f"获取直播间信息失败 room_id={room_id}: {payload.get('message')}"
        )
    data = payload.get("data") or {}
    room_info = data.get("room_info") or {}

    real_room_id = int(room_info.get("room_id") or room_id)
    ruid = int(room_info.get("uid") or 0)
    parent_area_id = int(room_info.get("parent_area_id") or 0)
    area_id = int(room_info.get("area_id") or 0)
    live_status = int(room_info.get("live_status") or 0)

    if real_room_id <= 0 or ruid <= 0:
        raise ValueError(f"直播间信息不完整 room_id={room_id}")
    if parent_area_id <= 0 or area_id <= 0:
        raise ValueError(
            f"直播分区信息缺失 room_id={room_id} "
            f"parent_area_id={parent_area_id} area_id={area_id}"
        )
    return LiveRoomInfo(
        room_id=real_room_id,
        ruid=ruid,
        parent_area_id=parent_area_id,
        area_id=area_id,
        live_status=live_status,
    )


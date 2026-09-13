"""Usage alerts: query, acknowledge, delete."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import utcnow
from app.models import AlertRule, AlertSeverity, Device, UsageAlert
from app.schemas import AlertAck, AlertOut

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _serialize(alert: UsageAlert, device_name: str | None = None) -> AlertOut:
    payload = AlertOut.model_validate(alert, from_attributes=True)
    payload.device_name = device_name or (
        alert.device.name if alert.device is not None else None
    )
    return payload


@router.get("", response_model=list[AlertOut], summary="Alerts, newest first")
async def list_alerts(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    rule: str | None = Query(default=None, pattern="^(spike|on_too_long|household_budget|daily_energy)$"),
    severity: str | None = Query(
        default=None, pattern="^(low|medium|high|critical)$"
    ),
    acknowledged: bool | None = Query(default=None),
    device_id: int | None = Query(default=None),
    since_hours: int | None = Query(default=None, ge=1, le=24 * 30),
    session: AsyncSession = Depends(get_session),
) -> list[AlertOut]:
    stmt: Select = select(UsageAlert).order_by(UsageAlert.created_at.desc(), UsageAlert.id.desc())
    if rule:
        stmt = stmt.where(UsageAlert.rule == rule)
    if severity:
        stmt = stmt.where(UsageAlert.severity == severity)
    if acknowledged is not None:
        stmt = stmt.where(UsageAlert.acknowledged.is_(acknowledged))
    if device_id is not None:
        stmt = stmt.where(UsageAlert.device_id == device_id)
    if since_hours:
        stmt = stmt.where(UsageAlert.created_at >= utcnow() - timedelta(hours=since_hours))
    stmt = stmt.offset(offset).limit(limit)

    alerts = list((await session.execute(stmt)).scalars().all())
    if not alerts:
        return []
    names = {
        d.id: d.name
        for d in (
            await session.execute(
                select(Device).where(
                    Device.id.in_({a.device_id for a in alerts if a.device_id is not None})
                )
            )
        )
        .scalars()
        .all()
    }
    return [_serialize(a, names.get(a.device_id)) for a in alerts]


@router.get("/stats", summary="Alert counts grouped by severity and rule")
async def alert_stats(
    since_hours: int = Query(default=24, ge=1, le=24 * 30),
    session: AsyncSession = Depends(get_session),
) -> dict:
    since = utcnow() - timedelta(hours=since_hours)
    by_severity = dict(
        (await session.execute(
            select(UsageAlert.severity, func.count())
            .where(UsageAlert.created_at >= since)
            .group_by(UsageAlert.severity)
        )).all()
    )
    by_rule = dict(
        (await session.execute(
            select(UsageAlert.rule, func.count())
            .where(UsageAlert.created_at >= since)
            .group_by(UsageAlert.rule)
        )).all()
    )
    open_alerts = int(
        (await session.execute(
            select(func.count()).select_from(UsageAlert).where(UsageAlert.acknowledged.is_(False))
        )).scalar_one()
    )
    return {
        "since": since,
        "total": sum(by_severity.values()),
        "open": open_alerts,
        "by_severity": {
            sev: by_severity.get(sev, 0) for sev in [s.value for s in AlertSeverity]
        },
        "by_rule": {rule: by_rule.get(rule, 0) for rule in [r.value for r in AlertRule]},
    }


@router.patch("/{alert_id}", response_model=AlertOut, summary="Acknowledge / un-acknowledge")
async def acknowledge_alert(
    alert_id: int, payload: AlertAck, session: AsyncSession = Depends(get_session)
) -> AlertOut:
    alert = await session.get(UsageAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.acknowledged = payload.acknowledged
    alert.acknowledged_at = utcnow() if payload.acknowledged else None
    await session.commit()
    await session.refresh(alert)
    return _serialize(alert)


@router.post("/ack-all", summary="Acknowledge every open alert")
async def ack_all(session: AsyncSession = Depends(get_session)) -> dict:
    now: datetime = utcnow()
    result = await session.execute(
        select(UsageAlert).where(UsageAlert.acknowledged.is_(False))
    )
    alerts = list(result.scalars().all())
    for alert in alerts:
        alert.acknowledged = True
        alert.acknowledged_at = now
    await session.commit()
    return {"acknowledged": len(alerts)}


@router.delete("/{alert_id}", status_code=204)
async def delete_alert(alert_id: int, session: AsyncSession = Depends(get_session)) -> None:
    alert = await session.get(UsageAlert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    await session.delete(alert)
    await session.commit()


@router.delete("", summary="Clear the alert history")
async def clear_alerts(
    only_acknowledged: bool = Query(default=False),
    older_than_hours: int | None = Query(default=None, ge=1, le=24 * 365),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(UsageAlert)
    if only_acknowledged:
        stmt = stmt.where(UsageAlert.acknowledged.is_(True))
    if older_than_hours:
        stmt = stmt.where(UsageAlert.created_at < utcnow() - timedelta(hours=older_than_hours))
    alerts = list((await session.execute(stmt)).scalars().all())
    for alert in alerts:
        await session.delete(alert)
    await session.commit()
    return {"deleted": len(alerts)}

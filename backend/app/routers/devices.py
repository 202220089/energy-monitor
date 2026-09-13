"""Device CRUD (smart plugs / appliances)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Device
from app.schemas import DeviceCreate, DeviceOut, DeviceUpdate

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut], summary="List every smart plug")
async def list_devices(
    active_only: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> list[Device]:
    stmt = select(Device).order_by(Device.name)
    if active_only:
        stmt = stmt.where(Device.active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


@router.post(
    "",
    response_model=DeviceOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new smart plug",
)
async def create_device(
    payload: DeviceCreate, session: AsyncSession = Depends(get_session)
) -> Device:
    device = Device(**payload.model_dump())
    session.add(device)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A device with that name already exists")
    await session.refresh(device)
    return device


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, session: AsyncSession = Depends(get_session)) -> Device:
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int, payload: DeviceUpdate, session: AsyncSession = Depends(get_session)
) -> Device:
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(device, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(status_code=409, detail="A device with that name already exists")
    await session.refresh(device)
    return device


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_device(device_id: int, session: AsyncSession = Depends(get_session)) -> None:
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    await session.delete(device)
    await session.commit()

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.services.students_service import (
    register_student,
    lookup_student,
    lookup_student_by_phone,
    get_student_profile,
    update_student_profile,
    scan_student,
)
from app.core.auth import get_current_user


router = APIRouter(prefix="/students", tags=["Students"])


@router.post("/register")
async def register(payload: dict = Body(...)):
    return await register_student(payload)


@router.post("/lookup")
async def lookup(payload: dict = Body(...)):
    email = (payload or {}).get("email")
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    return await lookup_student(email)


@router.post("/lookup-sms")
async def lookup_sms(payload: dict = Body(...)):
    phone = (payload or {}).get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="phone is required")
    return await lookup_student_by_phone(phone)


@router.get("/me")
async def get_me(token: str = Query(...)):
    return await get_student_profile(token)


@router.put("/me")
async def update_me(payload: dict = Body(...)):
    token = payload.pop("token", None)
    if not token:
        raise HTTPException(status_code=400, detail="token is required")
    return await update_student_profile(token, payload)


@router.post("/scan")
async def scan(payload: dict = Body(...), user=Depends(get_current_user)):
    token = payload.get("token")
    event_id = payload.get("event_id")
    rating = payload.get("rating")
    notes = payload.get("notes")
    if not token or not event_id:
        raise HTTPException(status_code=400, detail="token and event_id are required")
    school_id = user.get("school_id")
    user_id = user.get("id")
    return await scan_student(token, event_id, school_id, user_id, rating, notes)



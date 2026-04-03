from fastapi import APIRouter, Depends, HTTPException, Request, Body, Query
from fastapi.responses import JSONResponse
from app.controllers.auth_controller import (
    login_controller,
    read_current_user_controller,
    reset_password_controller,
    validate_magic_link_controller,
    consume_magic_link_controller,
    set_new_password_controller,
    create_user_controller
)

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login")
async def login(credentials: dict):
    return await login_controller(credentials)

@router.get("/me")
async def read_current_user(request: Request):
    return await read_current_user_controller(request)

@router.post("/reset-password")
async def reset_password(payload: dict = Body(...)):
    return await reset_password_controller(payload)

@router.get("/magic-link/validate")
async def validate_magic_link(token: str = Query(...)):
    """Validate a magic link token"""
    return await validate_magic_link_controller(token)

@router.post("/magic-link/consume")
async def consume_magic_link(
    token: str = Query(...), 
    link_type: str = Query(...)
):
    """Process a magic link after validation"""
    return await consume_magic_link_controller(token, link_type)

@router.post("/set-new-password")
async def set_new_password(payload: dict = Body(...)):
    """Set a new password using a one-time reset token"""
    return await set_new_password_controller(payload)

@router.post("/create-user")
async def create_user(payload: dict = Body(...)):
    """Create a new user account for invite flow"""
    return await create_user_controller(payload) 
from fastapi import APIRouter, Depends, HTTPException, Response
from app.repositories.students_repository import get_student_by_token
from app.core.auth import get_current_user
from app.utils.qr_utils import qr_png_data_uri
import base64
from io import BytesIO
import qrcode

router = APIRouter(prefix="/api/qr", tags=["qr"])

@router.get("/generate/{token}")
async def generate_qr_code(token: str, user=Depends(get_current_user)):
    """Generate QR code image for a student token. Requires authentication."""

    student = get_student_by_token(token)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    
    try:
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2,
        )
        qr.add_data(token)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to bytes
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        
        # Return as image response
        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=86400",  # Cache for 1 day
                "Content-Disposition": f'inline; filename="qr_{token[:8]}.png"'
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to generate QR code")

@router.get("/data/{token}")
async def get_qr_data_uri(token: str, user=Depends(get_current_user)):
    """Get QR code as data URI (for frontend display). Requires authentication."""

    try:
        qr_data_uri = qr_png_data_uri(token)
        return {"token": token, "qrDataUri": qr_data_uri}

    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to generate QR code")
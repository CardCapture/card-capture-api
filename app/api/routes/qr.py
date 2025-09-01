from fastapi import APIRouter, HTTPException, Response
from app.repositories.students_repository import get_student_by_token
from app.utils.qr_utils import qr_png_data_uri
import base64
from io import BytesIO
import qrcode

router = APIRouter(prefix="/api/qr", tags=["qr"])

@router.get("/generate/{token}")
async def generate_qr_code(token: str):
    """Generate QR code image for a student token"""
    
    # Validate token exists (optional - you might want to allow any token)
    student = get_student_by_token(token)
    if not student:
        # Still generate QR even if token doesn't exist yet
        # This allows for pre-generation or testing
        pass
    
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
        raise HTTPException(status_code=500, detail=f"Failed to generate QR code: {str(e)}")

@router.get("/data/{token}")
async def get_qr_data_uri(token: str):
    """Get QR code as data URI (for frontend display)"""
    
    try:
        qr_data_uri = qr_png_data_uri(token)
        return {"token": token, "qrDataUri": qr_data_uri}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate QR code: {str(e)}")
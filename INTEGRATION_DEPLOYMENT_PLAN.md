# Complete PhotoRoom Integration & Deployment Plan

## 🎯 Overview
Full integration of PhotoRoom API with HEIC support into the existing card capture pipeline, maintaining all Supabase storage functionality.

## ✅ Completed Components

### 1. **Core Services**
- `app/services/photoroom_service.py` - Production PhotoRoom API integration
- `app/utils/image_processing_integrated.py` - Enhanced processing with PhotoRoom + fallbacks
- `app/services/uploads_service_v2.py` - Updated uploads with HEIC support

### 2. **Key Features**
- ✅ HEIC/HEIF support for iPhone uploads
- ✅ PhotoRoom background removal with white background output  
- ✅ Automatic fallback to boundary detection if PhotoRoom fails
- ✅ PDF processing for ACU cards
- ✅ Full Supabase storage integration
- ✅ Backwards compatibility

## 🚀 Deployment Steps

### Phase 1: Dependencies & Environment Setup

```bash
# 1. Install new dependencies
pip3 install pillow-heif pdf2image

# 2. Update environment variables in .env
USE_PHOTOROOM=true
PHOTO_ROOM_API_KEY=sk_pr_default_08150f1e94f6f9b9d108a67acd4812ecf3e97bc4

# 3. Update requirements.txt
echo "pillow-heif>=1.1.0" >> requirements.txt
echo "pdf2image>=3.1.0" >> requirements.txt
```

### Phase 2: Code Integration

#### Option A: Drop-in Replacement (Recommended for Production)
```bash
# Replace existing image processing with integrated version
mv app/utils/image_processing.py app/utils/image_processing_backup.py
mv app/utils/image_processing_integrated.py app/utils/image_processing.py

# Replace uploads service
mv app/services/uploads_service.py app/services/uploads_service_backup.py
mv app/services/uploads_service_v2.py app/services/uploads_service.py
```

#### Option B: Gradual Migration (Recommended for Testing)
```python
# In app/utils/image_processing.py, update ensure_trimmed_image:
from app.utils.image_processing_integrated import ensure_trimmed_image as ensure_trimmed_image_v2

def ensure_trimmed_image(original_image_path: str) -> str:
    """Enhanced with PhotoRoom support"""
    return ensure_trimmed_image_v2(original_image_path)
```

### Phase 3: Upload Route Updates

Update `app/api/routes/uploads.py` to support HEIC:

```python
# Add HEIC to allowed content types
ALLOWED_CONTENT_TYPES = [
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif',
    'image/bmp', 'image/tiff', 'image/webp',
    'image/heic', 'image/heif',  # Add HEIC support
    'application/pdf'
]

# Update validation logic
def validate_file_type(file: UploadFile) -> bool:
    # Check both content type and file extension for HEIC
    file_ext = Path(file.filename).suffix.lower()
    
    if file.content_type in ALLOWED_CONTENT_TYPES:
        return True
    
    # Special case for HEIC files (sometimes have generic content type)
    if file_ext in ['.heic', '.heif']:
        return True
    
    return False
```

### Phase 4: Worker Integration

Update `app/worker/worker_v3.py`:

```python
# Replace the image processing line (around line 184)
# OLD:
# trimmed_image_path = ensure_trimmed_image(tmp_file)

# NEW:
from app.utils.image_processing_integrated import ensure_trimmed_image
trimmed_image_path = ensure_trimmed_image(tmp_file)
```

### Phase 5: Testing & Validation

```bash
# Run comprehensive test suite
python3 test_complete_integration.py

# Test specific formats
python3 -c "
from app.utils.image_processing_integrated import ensure_trimmed_image
result = ensure_trimmed_image('test_images/IMG_0554.JPG')
print(f'Processed: {result}')
"

# Test upload service
python3 -c "
import asyncio
from app.services.uploads_service_v2 import upload_file_service
# Run upload test
"
```

## 📋 Configuration Options

### Environment Variables
```bash
# Feature flags
USE_PHOTOROOM=true                    # Enable/disable PhotoRoom
PHOTOROOM_TIMEOUT=30                  # API timeout in seconds
PHOTOROOM_MAX_RETRIES=2              # Max retry attempts

# Quality settings  
PHOTOROOM_OUTPUT_QUALITY=95          # JPEG quality for output
PHOTOROOM_MAX_DIMENSION=2048         # Max image dimension

# Fallback behavior
ENABLE_BOUNDARY_FALLBACK=true        # Use boundary detection if PhotoRoom fails
ENABLE_DOCAI_FALLBACK=true           # Use DocAI if boundary detection fails
```

### Production Recommendations
```python
PRODUCTION_CONFIG = {
    'USE_PHOTOROOM': True,
    'PHOTOROOM_OUTPUT_QUALITY': 90,     # Balance quality/size
    'PHOTOROOM_MAX_DIMENSION': 2048,    # Reasonable for cards
    'ENABLE_FALLBACKS': True,           # Always enable fallbacks
    'LOG_PROCESSING_STATS': True        # Monitor performance
}
```

## 🧪 Testing Strategy

### 1. Unit Tests
```bash
# Test individual components
python3 -m pytest tests/test_photoroom_service.py
python3 -m pytest tests/test_image_processing.py
python3 -m pytest tests/test_heic_conversion.py
```

### 2. Integration Tests  
```bash
# Run full integration suite
python3 test_complete_integration.py

# Test with real uploads
curl -X POST "http://localhost:8000/upload" \
  -F "file=@test_card.heic" \
  -F "school_id=test-school" \
  -F "event_id=test-event"
```

### 3. Load Testing
```bash
# Test PhotoRoom API limits
for i in {1..10}; do
  python3 -c "from app.services.photoroom_service import PhotoRoomService; PhotoRoomService().remove_background('test.jpg')"
done
```

## 📊 Monitoring & Alerts

### Key Metrics to Track
1. **PhotoRoom API Usage**
   - Requests per day/hour
   - Success/failure rates
   - Response times

2. **Processing Performance**
   - Image processing time (PhotoRoom vs fallback)
   - File size reduction ratios
   - HEIC conversion success rates

3. **Error Rates**
   - PhotoRoom API failures
   - Fallback method usage
   - Upload failures by format

### Logging Integration
```python
# Enhanced logging in production
import logging

logger = logging.getLogger('card_processing')

# Log processing method used
logger.info("Image processed", extra={
    'method': 'photoroom',
    'input_format': 'heic',
    'output_size_kb': 234,
    'processing_time_ms': 1500
})
```

## 🚨 Rollback Plan

### If Issues Occur
```bash
# Quick rollback to original processing
mv app/utils/image_processing.py app/utils/image_processing_photoroom.py
mv app/utils/image_processing_backup.py app/utils/image_processing.py

# Disable PhotoRoom via environment
export USE_PHOTOROOM=false

# Restart services
systemctl restart card-capture-api
```

### Gradual Rollback
```python
# Disable PhotoRoom but keep HEIC support
USE_PHOTOROOM=false
ENABLE_BOUNDARY_FALLBACK=true
HEIC_SUPPORT=true
```

## 📈 Performance Expectations

### PhotoRoom Processing
- **Typical response time**: 2-5 seconds per image
- **Success rate**: >95% for standard card images
- **File size reduction**: 20-40% compared to original

### HEIC Conversion
- **Conversion time**: <1 second for typical iPhone photos
- **Quality retention**: 95%+ with JPEG quality=95
- **File size**: 30-50% smaller than original HEIC

### Fallback Methods
- **Boundary detection**: <500ms
- **DocAI processing**: 1-3 seconds
- **Combined pipeline**: 3-8 seconds total

## 🔐 Security Considerations

### API Key Management
```bash
# Production environment
export PHOTO_ROOM_API_KEY="$(cat /secrets/photoroom-api-key)"

# Staging environment  
export PHOTO_ROOM_API_KEY="sk_pr_staging_..."
```

### File Handling
- All temporary files cleaned up automatically
- HEIC files converted and originals deleted
- No sensitive data logged
- Secure Supabase storage integration maintained

## 📞 Support & Troubleshooting

### Common Issues

1. **HEIC files not processing**
   ```bash
   # Check pillow-heif installation
   python3 -c "import pillow_heif; print('HEIC support available')"
   ```

2. **PhotoRoom API failures**
   ```bash
   # Check API key and limits
   curl -H "x-api-key: YOUR_KEY" https://sdk.photoroom.com/v1/segment
   ```

3. **Storage upload failures**
   ```bash
   # Verify Supabase connection
   python3 -c "from app.core.clients import get_supabase_client; print(get_supabase_client())"
   ```

### Debug Mode
```bash
# Enable verbose logging
export LOG_LEVEL=DEBUG
export PHOTOROOM_DEBUG=true

# Run with detailed output
python3 test_complete_integration.py
```

## 🎉 Go-Live Checklist

- [ ] Dependencies installed (`pip3 install pillow-heif pdf2image`)
- [ ] Environment variables set (`USE_PHOTOROOM=true`, API key)
- [ ] Code integrated (image processing + uploads service)
- [ ] Integration tests passing (`python3 test_complete_integration.py`)
- [ ] Upload endpoints support HEIC (`image/heic` in allowed types)
- [ ] Worker updated to use new processing
- [ ] Monitoring/logging configured
- [ ] Rollback plan tested
- [ ] PhotoRoom API limits verified
- [ ] Performance baseline established

## 📄 Additional Resources

- [PhotoRoom API Documentation](https://docs.photoroom.com/)
- [HEIC Format Support](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#heif)
- [Supabase Storage Guide](https://supabase.com/docs/guides/storage)

---

**Estimated Implementation Time**: 2-4 hours
**Risk Level**: Low (comprehensive fallbacks included)
**Impact**: High (better image quality + iPhone support)
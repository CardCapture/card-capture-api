# PhotoRoom Integration Plan for Card Capture API

## Overview
Integration of PhotoRoom API for background removal with HEIC support and production-ready pipeline.

## ✅ Completed Components

### 1. **PhotoRoom Service** (`app/services/photoroom_service.py`)
- ✅ HEIC/HEIF support via `pillow-heif`
- ✅ PDF to image conversion
- ✅ Automatic white background generation (production default)
- ✅ Batch processing capability
- ✅ Error handling and logging

### 2. **Enhanced Image Processing** (`app/utils/image_processing_v2.py`)
- ✅ HEIC conversion pipeline
- ✅ PhotoRoom integration with fallback to boundary detection
- ✅ Image optimization for storage
- ✅ Format validation including HEIC

## 📋 Integration Steps

### Step 1: Update Environment Variables
```bash
# Add to .env file
PHOTO_ROOM_API_KEY=sk_pr_default_08150f1e94f6f9b9d108a67acd4812ecf3e97bc4
```

### Step 2: Install Dependencies
```bash
pip3 install pillow-heif pdf2image
```

### Step 3: Update Upload Controller
Modify `app/controllers/uploads_controller.py` to use the new pipeline:

```python
from app.utils.image_processing_v2 import ensure_trimmed_image_v2

# In upload_file_controller function, replace:
# trimmed_image_path = ensure_trimmed_image(temp_file_path)

# With:
trimmed_image_path = ensure_trimmed_image_v2(
    temp_file_path,
    use_photoroom=True,  # Enable PhotoRoom
    optimize_for_storage=False  # Keep high quality
)
```

### Step 4: Update File Format Validation
In `app/api/routes/uploads.py`, update accepted formats:

```python
ACCEPTED_FORMATS = {
    'image/jpeg', 'image/jpg', 'image/png', 
    'image/heic', 'image/heif',  # Add HEIC support
    'application/pdf'  # PDF support
}
```

### Step 5: Add PhotoRoom Toggle (Optional)
Add a feature flag to enable/disable PhotoRoom:

```python
# In app/config.py
USE_PHOTOROOM = os.getenv('USE_PHOTOROOM', 'true').lower() == 'true'

# In processing pipeline
use_photoroom = config.USE_PHOTOROOM
```

## 🧪 Testing Strategy

### 1. Unit Tests
```python
# Test HEIC conversion
def test_heic_conversion():
    result = convert_heic_to_jpeg("test.heic")
    assert result.endswith(".jpg")

# Test PhotoRoom service
def test_photoroom_service():
    service = PhotoRoomService()
    result = service.remove_background("test.jpg")
    assert result['success'] == True
```

### 2. Integration Tests
```python
# Test complete pipeline
def test_full_pipeline():
    # Test with each format
    for test_file in ["card.jpg", "card.heic", "card.pdf"]:
        result = ensure_trimmed_image_v2(test_file)
        assert os.path.exists(result)
```

### 3. Manual Testing Checklist
- [ ] Upload JPG card → Verify background removed
- [ ] Upload HEIC from iPhone → Verify conversion and processing
- [ ] Upload PDF (ACU format) → Verify conversion and processing
- [ ] Upload PNG with transparency → Verify processing
- [ ] Batch upload multiple formats → Verify all processed

## 🚀 Deployment Steps

### 1. Staging Deployment
```bash
# 1. Update dependencies
pip3 install -r requirements.txt

# 2. Set environment variable
export PHOTO_ROOM_API_KEY=your_api_key

# 3. Test with sample images
python3 test_production_pipeline.py

# 4. Deploy to staging
git push staging mc-wip:main
```

### 2. Production Deployment
```bash
# 1. Verify API limits are sufficient
# 2. Enable monitoring for PhotoRoom API calls
# 3. Deploy with feature flag initially
# 4. Gradual rollout to all users
```

## 📊 API Limits & Monitoring

### PhotoRoom API Limits
- Monitor usage at: https://app.photoroom.com/api-dashboard
- Current plan: Basic (check limits)
- Consider upgrading if needed

### Monitoring Points
1. API response times
2. Failure rates (fallback to boundary detection)
3. HEIC conversion success rate
4. Image quality metrics

## 🔄 Fallback Strategy

If PhotoRoom fails or hits limits:
1. **Primary fallback**: Boundary detection algorithm
2. **Secondary fallback**: DocAI field detection
3. **Final fallback**: Return original image

## 💰 Cost Considerations

- PhotoRoom API: Check pricing tiers
- Storage: White background JPEGs vs transparent PNGs
- Processing: Server CPU for HEIC conversion

## 📝 Configuration Options

```python
# Recommended production settings
PHOTOROOM_CONFIG = {
    'use_photoroom': True,
    'fallback_enabled': True,
    'output_format': 'white_bg_jpg',  # Smaller file size
    'api_timeout': 30,  # seconds
    'max_retries': 2,
    'batch_size': 10  # For batch processing
}
```

## ✅ Benefits

1. **Better quality**: PhotoRoom removes backgrounds more accurately
2. **HEIC support**: iPhone users can upload directly
3. **PDF support**: ACU cards handled automatically
4. **Consistent output**: White background for all cards
5. **Fallback safety**: Multiple fallback methods ensure reliability

## ⚠️ Important Notes

- White background version is default (no color cast issues)
- McMurry cards with full white pages will retain borders (acceptable)
- HEIC files are converted to JPEG before processing
- API key must be kept secure (use environment variables)

## 🎯 Next Steps

1. Review and approve implementation
2. Test with real user uploads
3. Monitor API usage for first week
4. Collect user feedback
5. Optimize based on usage patterns
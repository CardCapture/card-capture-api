# HEIC Mobile Upload Analysis - Root Cause Found! 🎯

## **The Problem**

ACU's cards are being cut off when captured from mobile phones, but imported files work fine.

## **Root Cause Identified**

❌ **Production worker is missing `pillow_heif` dependency**

**Evidence from production logs:**
```
[WARNING] HEIC support not available - pillow_heif not installed
```

## **Why This Causes Card Cutoff**

1. **Mobile phones save photos as HEIC files** by default (iPhone especially)
2. **Production worker can't process HEIC files** (missing pillow_heif)
3. **PhotoRoom service fails silently** when given unsupported HEIC files
4. **System falls back to DocAI cropping** which crops based on text boundaries
5. **DocAI cuts off parts of cards** photographed with backgrounds

## **The Flow**

```
Mobile Upload (HEIC) → Worker tries to process → HEIC conversion fails → 
PhotoRoom skipped → Falls back to DocAI crop → Card gets cut off ❌
```

**vs**

```
File Import (JPG/PNG) → Worker processes → PhotoRoom works → 
Background removed properly → Full card preserved ✅
```

## **Tests Performed**

### ✅ Local Tests (All Passed)
- HEIC dependencies: ✅ Available
- PhotoRoom HEIC conversion: ✅ Working  
- Pipeline HEIC processing: ✅ Working
- Mobile upload scenario: ✅ Working

### ❌ Production Status
- HEIC support: ❌ Missing pillow_heif
- PhotoRoom for mobile uploads: ❌ Failing silently
- Fallback to DocAI crop: ✅ Working but cuts cards

## **The Fix Applied**

1. **✅ Fixed worker logic** - Always use PhotoRoom pipeline instead of DocAI crop
2. **✅ Added USE_PHOTOROOM=true** to production environment  
3. **✅ Added pillow_heif==1.1.0** to requirements.txt
4. **⏳ Need to deploy** updated requirements to production

## **Verification Commands**

### Check HEIC Support in Production
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND \
   resource.labels.service_name="card-capture-worker-v2" AND \
   (textPayload:"HEIC" OR textPayload:"heic" OR textPayload:"pillow_heif")' \
  --limit=20 --format="value(textPayload)" --project=gen-lang-client-0493571343
```

**Look for:**
- ✅ `[INFO] HEIC support enabled` 
- ✅ `[Orientation] Converting HEIC file: ...`
- ❌ `[WARNING] HEIC support not available`

### Check PhotoRoom Usage
```bash
gcloud logging read \
  'resource.type="cloud_run_revision" AND \
   resource.labels.service_name="card-capture-worker-v2" AND \
   (textPayload:"PhotoRoom" OR textPayload:"trimming pipeline")' \
  --limit=20 --format="value(textPayload)" --project=gen-lang-client-0493571343
```

**Look for:**
- ✅ `🎨 Attempting PhotoRoom background removal...`
- ✅ `✅ PhotoRoom processing successful`
- ❌ `Using cropped image from DocAI` (old behavior)

## **Next Steps**

1. **Deploy the updated requirements.txt** to production worker
2. **Verify HEIC support** is enabled in production logs
3. **Test with ACU** using actual mobile uploads
4. **Monitor logs** to confirm PhotoRoom is processing mobile uploads

## **Expected Outcome**

After the fix:
- Mobile HEIC uploads will be converted to JPEG
- PhotoRoom will process the full image with proper background removal  
- Cards won't be cut off anymore
- ACU's mobile capture workflow will work correctly

## **Why This Wasn't Caught Earlier**

- Local development had pillow_heif installed
- Testing was done with non-HEIC files
- Production logs weren't checked for HEIC support
- The fallback to DocAI appeared to be working (but was cutting cards)

This is a classic case where the fallback system masked the real issue! 🕵️
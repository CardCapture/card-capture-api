# Pipeline V3 Deployment Guide

## 🚀 Overview

This guide covers deploying the new **Pipeline V3** architecture alongside the existing **Pipeline V2** with safe feature flag controls.

## ✅ What We Built

### **Pipeline V3 Architecture**
- **3-Stage Processing**: Extraction → Enhancement → Review  
- **5 Modular Enhancers**: Field splitting, requirements, cleaning, address validation, high school matching
- **73% Complexity Reduction**: From 15 steps to 4 steps
- **Comprehensive Testing**: Unit tests + integration tests
- **Feature Flag System**: Safe gradual rollout controls

### **Key Files Created**
```
app/pipeline/
├── models.py                    # FieldData, PipelineContext, ProcessingResult
├── pipeline.py                  # Main CardProcessingPipeline class
├── enhancers/
│   ├── base.py                 # FieldEnhancer base class
│   ├── field_splitter.py       # Splits combined fields
│   ├── address_validator.py    # Google Maps validation
│   ├── high_school_matcher.py  # CEEB code matching
│   ├── data_cleaner.py         # Format phones/dates/emails
│   └── field_requirements.py   # Apply school settings
└── tests/
    ├── test_enhancers.py       # Unit tests
    └── test_pipeline.py        # Integration tests

app/worker/
├── worker_v3.py                # New pipeline worker
└── worker_unified.py           # Routes v2/v3 based on flags

app/config.py                   # Feature flag configuration
```

## 🎛️ Feature Flag Configuration

Control pipeline rollout with these environment variables:

```bash
# Default pipeline version
PIPELINE_VERSION=v2  # or "v3"

# Percentage-based rollout (0-100)
PIPELINE_V3_ROLLOUT_PERCENTAGE=10

# School-specific enablement (comma-separated)
PIPELINE_V3_ENABLED_SCHOOLS=school_abc,school_xyz
```

### **Rollout Priority Order**
1. **School-specific** enablement (highest priority)
2. **Global** PIPELINE_VERSION setting  
3. **Percentage** rollout
4. **Default** to V2 (safest)

## 📋 Deployment Steps

### **Phase 1: Deploy Code (Risk: Low)**

1. **Merge the pipeline-refactor branch**:
   ```bash
   git checkout main
   git merge pipeline-refactor
   ```

2. **Deploy with V3 disabled** (default behavior):
   ```bash
   # Ensure these are set (or unset for defaults)
   PIPELINE_VERSION=v2
   PIPELINE_V3_ROLLOUT_PERCENTAGE=0
   PIPELINE_V3_ENABLED_SCHOOLS=
   ```

3. **Update worker deployment** to use unified worker:
   ```bash
   # In your deployment config, change:
   CMD uvicorn app.worker.worker_unified:app --host 0.0.0.0 --port $PORT
   ```

✅ **Result**: All traffic still goes to V2, but V3 code is deployed and ready

### **Phase 2: Test with Single School (Risk: Low)**

1. **Enable V3 for test school**:
   ```bash
   PIPELINE_V3_ENABLED_SCHOOLS=your_test_school_id
   ```

2. **Process test cards** and verify:
   - Fields are extracted correctly
   - Address validation works
   - High school matching + CEEB codes added
   - Review status accurate

3. **Monitor logs** for any errors or discrepancies

✅ **Result**: Only test school uses V3, all others use V2

### **Phase 3: Gradual Rollout (Risk: Medium)**

1. **Enable 5% rollout**:
   ```bash
   PIPELINE_V3_ROLLOUT_PERCENTAGE=5
   ```

2. **Monitor for 24-48 hours**:
   - Error rates
   - Processing times  
   - Field accuracy
   - Review queue impact

3. **Gradually increase**:
   ```bash
   PIPELINE_V3_ROLLOUT_PERCENTAGE=10  # After monitoring
   PIPELINE_V3_ROLLOUT_PERCENTAGE=25  # After monitoring
   PIPELINE_V3_ROLLOUT_PERCENTAGE=50  # After monitoring
   ```

### **Phase 4: Full Migration (Risk: Low)**

1. **Enable globally**:
   ```bash
   PIPELINE_VERSION=v3
   PIPELINE_V3_ROLLOUT_PERCENTAGE=100
   ```

2. **Monitor for 1 week**

3. **Remove old pipeline** (future cleanup):
   - Archive `worker_v2.py`  
   - Update `worker_unified.py` to only use V3
   - Clean up legacy code

## 🔍 Monitoring & Debugging

### **Check Pipeline Status**
```bash
curl https://your-worker-url/pipeline/config
```

### **Test Routing for Specific School**
```bash
curl -X POST https://your-worker-url/pipeline/test \
  -d '{"school_id": "your_school_id"}'
```

### **Health Checks**
```bash
curl https://your-worker-url/health
curl https://your-worker-url/ready
```

### **Log Monitoring**
Look for these log markers:
- `=== CARD PROCESSING PIPELINE START ===` (V3)
- `=== PROCESSING JOB V2 START ===` (V2)
- `UNIFIED WORKER PROCESSING JOB` (routing decisions)

## ⚡ Adding New Features (Post-Migration)

With V3 architecture, adding features is **dramatically easier**:

### **Example: Add Email Validation**
```python
# 1. Create enhancer
class EmailValidatorEnhancer(FieldEnhancer):
    def enhance(self, fields, context):
        if 'email' in fields:
            fields['email'].value = validate_email(fields['email'].value)
        return fields
    
    def get_description(self):
        return "Validate email addresses"

# 2. Add to pipeline
self.enhancers = [
    FieldSplitterEnhancer(),
    FieldRequirementsEnhancer(), 
    DataCleanerEnhancer(),
    EmailValidatorEnhancer(),  # <- Just add here!
    AddressValidationEnhancer(),
    HighSchoolMatcherEnhancer(),
]
```

**That's it!** No more hunting through 1100-line files.

## 🧪 Testing

### **Run All Tests**
```bash
# Unit tests
python3 test_pipeline_v3_comparison.py

# Feature flags
python3 test_feature_flags.py

# Integration tests (existing)
python3 test_pipeline_integration.py
```

### **Test Real Card Processing**
```python
from app.pipeline.pipeline import CardProcessingPipeline

pipeline = CardProcessingPipeline()
result = pipeline.process(
    image_path="test_card.jpg",
    school_id="your_school",
    user_id="test_user"
)

print(f"Fields: {len(result.fields)}")
print(f"Review Status: {result.metadata['review_status']}")
```

## 🚨 Rollback Plan

If issues arise, **immediate rollback**:

```bash
# Stop all V3 traffic instantly
PIPELINE_VERSION=v2
PIPELINE_V3_ROLLOUT_PERCENTAGE=0
PIPELINE_V3_ENABLED_SCHOOLS=

# Or just for problematic school
PIPELINE_V3_ENABLED_SCHOOLS=good_school_1,good_school_2
# (remove problematic school from list)
```

**Traffic immediately returns to proven V2 pipeline.**

## 📊 Expected Benefits

- **73% fewer processing steps**
- **Easier debugging** with clear stage logging
- **Faster feature development** (new enhancers vs 12-step modifications)
- **Better test coverage** (individual enhancer tests)
- **Improved reliability** (error isolation between enhancers)

## 🔒 Safety Measures

1. **Feature flags** ensure safe rollout
2. **Unified worker** maintains V2 as fallback
3. **Comprehensive tests** validate functionality
4. **Enhanced logging** provides visibility
5. **Graceful error handling** prevents pipeline crashes

---

## 🎉 Ready for Deployment!

The new pipeline architecture is **production-ready** with:
- ✅ Complete feature flag system
- ✅ Comprehensive test coverage  
- ✅ Safe rollout strategy
- ✅ Easy rollback capability
- ✅ Enhanced monitoring

**Adding new features will now be simple and predictable!**
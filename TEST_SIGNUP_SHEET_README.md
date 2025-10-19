# Testing Sign-Up Sheet Major Mapping for Mississippi College

## What We Fixed

✅ Sign-up sheets now extract the `major` field (was previously missing)
✅ Majors are intelligently mapped to school's configured major list
✅ Pipe characters (`|`) in major names are handled correctly (e.g., "Computer Science | BS")
✅ Both `major` (original) and `mapped_major` (matched) fields are created

## How to Test

### Step 1: Save the Sign-Up Sheet Image

Save your Mississippi College sign-up sheet image to:
```
/Users/kregboyd/Applications/card-capture-api/test_images/mc_signup_sheet.jpg
```

### Step 2: Run the Test Script

```bash
cd /Users/kregboyd/Applications/card-capture-api
python3 test_signup_sheet_local.py
```

### Step 3: What the Script Does

The script will:
1. **Upload image** to Supabase storage
2. **Fetch Mississippi College's majors** (60 majors with pipe characters)
3. **Process with Gemini** - Extract all fields including major
4. **Map majors** - Match handwritten majors to MC's major list
5. **Create records** - Save to `reviewed_data` table
6. **Display results** - Show original vs mapped majors

### Step 4: View Results in UI

After successful processing:
- Navigate to: `/events/506fbd1c-56ca-4f24-b514-6a9c2f269927`
- Look for records with `upload_type: "signup_sheet"`
- Check that each record has both:
  - `major` field (original handwritten)
  - `mapped_major` field (matched to MC's list)

## Pre-Configured Test Data

The script uses these Mississippi College IDs:
- **School ID**: `72892a66-df27-4731-9770-d19000244830`
- **Event ID**: `506fbd1c-56ca-4f24-b514-6a9c2f269927`
- **User ID**: `fe3ffca2-5cd1-4817-a560-88401b7990e1`

## Expected Results

From the sign-up sheet you shared, majors like:
- "marketing" → should map to "Marketing | BSBA"
- "psych" → should map to "Psychology | BS"
- "entrepreneur" → should map to "Entrepreneurship | BSBA"
- "Business" → should map to "Business Administration | BSBA"
- "Nursing" → should map to "Pre-Nursing: Traditional | BS"
- "Sports Management" → should map to "Sports Management | BS"

## Troubleshooting

**If the image isn't found:**
```bash
# Check if test_images directory exists
ls -la test_images/

# Create it if missing
mkdir -p test_images/

# List what's in it
ls -la test_images/
```

**If processing fails:**
- Check logs in the script output
- Verify the image is a valid JPG/PNG
- Ensure GEMINI_API_KEY is set in environment

## What to Verify

After running the test, verify in the UI:
1. ✅ All students from the sheet were extracted
2. ✅ Each student has a `major` field (original handwritten text)
3. ✅ Each student has a `mapped_major` field (mapped to MC's list)
4. ✅ Pipe characters in major names are preserved correctly
5. ✅ Unmappable majors default to "Undecided"

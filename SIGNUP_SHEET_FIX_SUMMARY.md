# Sign-up Sheet Records Not Showing - Fix Summary

## Issue Identified

Customer uploaded sign-up sheets and could see records in the event stats, but **none were showing in the "Needs Review" table**.

## Root Cause - UPDATED

After deeper investigation, we found **TWO separate issues**:

### Issue 1: React Hook Dependency Bug (Fixed on 2025-10-07)
A **React hook dependency array bug** in `useCardsOverride.ts` that caused a race condition:

1. Component initially renders with `eventId = undefined`
2. `fetchCards()` is called but returns early (no eventId)
3. Event data loads and `eventId` becomes available
4. `useEffect` on line 138 triggers but `fetchCards` has a **stale closure**
5. The debouncing logic incorrectly blocks the fetch
6. Cards are never loaded, even though the backend API returns them correctly

## What Was Working

✅ **Backend Processing** - Sign-up sheets were correctly:
- Extracted with Gemini AI (7 records from test sheet)
- Saved to database with `review_status: "needs_human_review"`
- Assigned the correct `image_path` (shared across all records)
- Returned by the `/cards` API endpoint (63 total records)

✅ **Status Values** - No mismatch:
- Backend uses: `"needs_human_review"` ✓
- Frontend filters for: `"needs_human_review"` ✓
- NO instances of `"needs_review"` causing issues

✅ **Event Stats** - Correctly showing 66 records via direct Supabase query

### Issue 2: Review Status Mismatch (Fixed on 2025-10-07)
A **critical status value mismatch** between frontend and backend:

**Backend was using:** `"needs_human_review"`  
**Frontend was expecting:** `"needs_review"`

This caused the filtering logic to exclude all sign-up sheet records from the "Needs Review" table.

## Fixes Applied

### Fix 1: Frontend Hook Dependency (2025-10-07)

**File:** `card-capture-fe/src/hooks/useCardsOverride.ts`

**Change 1: Added `fetchCards` to dependency array (Line 146)**
```typescript
// BEFORE
}, [eventId]);

// AFTER  
}, [eventId, fetchCards]); // Include fetchCards to ensure fresh closure
```

This ensures that when `eventId` changes, the effect uses the latest version of `fetchCards` with the correct closure.

**Change 2: Added diagnostic logging**
Added console logs to trace the fetch lifecycle:
- When `fetchCards` is called
- When it's blocked by debouncing
- When API data is received
- When cards state is updated

### Fix 2: Backend Status Alignment (2025-10-07)

Changed all backend occurrences of `"needs_human_review"` to `"needs_review"` to match frontend expectations.

**Files Updated:**

1. `/Users/kregboyd/card-capture-api/app/services/review_service.py` (line 80)
   ```python
   # BEFORE
   review_status = "needs_human_review"
   
   # AFTER
   review_status = "needs_review"
   ```

2. `/Users/kregboyd/card-capture-api/app/services/signup_service.py` (line 297)
   ```python
   # BEFORE
   "review_status": "needs_human_review",
   
   # AFTER
   "review_status": "needs_review",
   ```

3. `/Users/kregboyd/card-capture-api/app/api/routes/cards.py` (lines 158, 309)
   ```python
   # BEFORE
   review_status = "needs_human_review" if any_required_field_needs_review else "reviewed"
   
   # AFTER
   review_status = "needs_review" if any_required_field_needs_review else "reviewed"
   ```

**Note:** The field-level flag `requires_human_review` remains unchanged - this is different from the card-level `review_status`.

## Expected Behavior After Fix

When the customer refreshes the page, they should now see:

1. **Console logs** showing the fetch flow:
   ```
   useCardsOverride: useEffect triggered { eventId: "...", hasEventId: true }
   useCardsOverride: fetchCards called { eventId: "..." }
   useCardsOverride: Starting API fetch for event ...
   useCardsOverride: Received data from API { count: 66, eventId: "..." }
   useCardsOverride: Cards state updated { count: 66 }
   ```

2. **All 66 records appear in the "Needs Review" table**

3. **Sign-up sheet records properly display**:
   - Status badge shows "Sign-up Sheet" (purple/indigo color)
   - All share the same `image_path` (the uploaded sign-up sheet image)
   - Fields extracted from Gemini are populated

## Testing Instructions

1. **Hard refresh** the event page (Cmd/Ctrl + Shift + R)
2. Check browser console for the new logs
3. Verify all 66 records appear in the Needs Review table
4. Click on a sign-up sheet record to review the extracted data

## Additional Notes

- The backend logs confirmed 63 records being returned after the sign-up upload
- The difference between 63 and 66 suggests 3 more records were added after the initial test
- All records have `upload_type: "signup_sheet"` to distinguish them from inquiry cards
- Real-time subscription is working correctly (confirmed by console logs)

## Files Modified

### Frontend:
- `/Users/kregboyd/card-capture-fe/src/hooks/useCardsOverride.ts`

### Backend:
- `/Users/kregboyd/card-capture-api/app/services/review_service.py`
- `/Users/kregboyd/card-capture-api/app/services/signup_service.py`
- `/Users/kregboyd/card-capture-api/app/api/routes/cards.py`

## Deployment

**IMPORTANT:** Both frontend AND backend changes must be deployed for the fix to work.

1. Deploy backend changes first
2. Deploy frontend changes
3. Customer should see all sign-up sheet records in the "Needs Review" table


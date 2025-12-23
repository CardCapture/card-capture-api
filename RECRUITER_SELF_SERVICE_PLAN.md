# Recruiter Self-Service Signup - Implementation Plan

## Executive Summary

Transform CardCapture from subscription-based to per-event payment model, enabling recruiters to self-signup, claim events from a master list, and pay $25 per event. Existing school admins can optionally approve and link recruiter accounts to their main school account.

**Key Changes:**
- Public recruiter signup (no invitation required)
- Master list of 300+ universal Texas college fair events
- $25 per event payment via Stripe
- Optional account linking with admin approval
- Standalone accounts that work independently

---

## Business Model Shift

### Current Model
- School-level Stripe subscriptions
- Admins invite users via magic links
- All users linked to a school account

### New Model
- Per-event $25 payments (individual recruiters)
- Self-service signup
- Standalone accounts that can optionally link to school accounts
- Future: Bulk credit purchases for discounts

---

## User Flow

### Recruiter Signup Flow

```
1. Visit cardcapture.io → Click "Sign Up as Recruiter"
2. Enter email, password, name
3. Select school from dropdown
   - Search/autocomplete through all schools
   - Option: "My school isn't listed"
4. Search for event
   - Search 300+ Texas events by name/date/location
   - Select event from results
5. Stripe Checkout ($25 payment)
6. Payment success → Account created
7. Immediate access to scan cards for that event
8. If school exists → Email sent to school admins
```

### Admin Approval Flow (Optional)

```
1. School admin receives email:
   "Recruiter X created account, claimed Event Y, paid $25"
2. Admin can:
   - Click "Approve & Link" → Recruiter becomes linked user
   - Ignore → Recruiter stays standalone (still works)
   - Reject → Recruiter stays standalone (no refund)
3. If approved:
   - Recruiter's school_id updated to main school
   - Recruiter's event added to school's event list
   - Recruiter gets access to school resources
   - Confirmation email sent
```

### New School Creation Flow

```
1. Recruiter selects "My school isn't listed"
2. Enter new school name
3. Continue with event selection + payment
4. New school created with recruiter as first admin
5. No approval needed (they ARE the admin)
```

---

## Database Schema Changes

### 1. New Table: `universal_events`
Master list of college fair events that recruiters can claim.

```sql
CREATE TABLE universal_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  event_date DATE NOT NULL,
  location TEXT,
  city TEXT,
  state TEXT DEFAULT 'TX',
  venue TEXT,
  description TEXT,
  status TEXT DEFAULT 'active', -- active, past, cancelled
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_universal_events_date ON universal_events(event_date);
CREATE INDEX idx_universal_events_name ON universal_events(name);
CREATE INDEX idx_universal_events_city ON universal_events(city);
```

**Purpose**: Centralized event catalog that all schools/recruiters can reference

### 2. New Table: `event_purchases`
Track $25 payments per recruiter per event.

```sql
CREATE TABLE event_purchases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id),
  universal_event_id UUID NOT NULL REFERENCES universal_events(id),
  amount INTEGER NOT NULL DEFAULT 2500, -- cents
  stripe_payment_intent_id TEXT,
  stripe_checkout_session_id TEXT,
  status TEXT DEFAULT 'pending', -- pending, completed, refunded, failed
  purchased_at TIMESTAMPTZ DEFAULT NOW(),

  UNIQUE(user_id, universal_event_id) -- Prevent duplicate purchases
);

CREATE INDEX idx_event_purchases_user ON event_purchases(user_id);
CREATE INDEX idx_event_purchases_status ON event_purchases(status);
```

**Purpose**: Financial tracking and access control (user can only access events they've paid for)

### 3. New Table: `account_link_requests`
Track pending requests to link standalone recruiters to school accounts.

```sql
CREATE TABLE account_link_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  requester_user_id UUID NOT NULL REFERENCES auth.users(id),
  target_school_id UUID NOT NULL REFERENCES schools(id),
  universal_event_id UUID NOT NULL REFERENCES universal_events(id),
  status TEXT DEFAULT 'pending', -- pending, approved, rejected, expired
  created_at TIMESTAMPTZ DEFAULT NOW(),
  reviewed_at TIMESTAMPTZ,
  reviewed_by UUID REFERENCES auth.users(id),

  UNIQUE(requester_user_id, target_school_id, universal_event_id)
);

CREATE INDEX idx_link_requests_target_school ON account_link_requests(target_school_id);
CREATE INDEX idx_link_requests_status ON account_link_requests(status);
```

**Purpose**: Admin approval workflow for linking standalone accounts

### 4. Update `profiles` Table

```sql
ALTER TABLE profiles
  ADD COLUMN account_status TEXT DEFAULT 'standalone', -- standalone, linked, pending_link
  ADD COLUMN parent_school_id UUID REFERENCES schools(id); -- For tracking link requests
```

**Purpose**: Track account linking state

### 5. Update `schools` Table

```sql
ALTER TABLE schools
  ADD COLUMN is_virtual_school BOOLEAN DEFAULT FALSE,
  ADD COLUMN credits_balance INTEGER DEFAULT 0;
```

**Purpose**:
- `is_virtual_school`: Auto-created schools for standalone recruiters
- `credits_balance`: Future bulk credit purchases

### 6. Link `events` to `universal_events`

```sql
ALTER TABLE events
  ADD COLUMN universal_event_id UUID REFERENCES universal_events(id);
```

**Purpose**: Connect school-specific events to universal events catalog

---

## Backend API Endpoints

### Public Endpoints (No Auth Required)

#### 1. GET `/api/public/schools`
List all schools for recruiter dropdown.

**Response:**
```json
[
  {
    "id": "uuid",
    "name": "McMurry University",
    "city": "Abilene",
    "state": "TX"
  }
]
```

#### 2. GET `/api/public/universal-events/search`
Search universal events.

**Query Params:**
- `query`: Text search (name, location, venue)
- `state`: Filter by state (default: TX)
- `date_from`: ISO date (e.g., 2025-01-01)
- `date_to`: ISO date
- `page`: Page number (default: 1)
- `limit`: Results per page (default: 20)

**Response:**
```json
{
  "events": [
    {
      "id": "uuid",
      "name": "Dallas College Fair",
      "event_date": "2025-10-15",
      "location": "Dallas Convention Center",
      "city": "Dallas",
      "state": "TX",
      "venue": "Main Hall",
      "description": "Annual college fair for DFW area"
    }
  ],
  "total": 150,
  "page": 1,
  "pages": 8
}
```

#### 3. POST `/api/public/recruiter-signup`
Create recruiter account and initiate payment.

**Request:**
```json
{
  "email": "recruiter@example.com",
  "password": "SecurePass123!",
  "first_name": "John",
  "last_name": "Smith",
  "school_selection": {
    "type": "existing" | "new",
    "school_id": "uuid",  // if existing
    "school_name": "New School Name"  // if new
  },
  "universal_event_id": "uuid"
}
```

**Response:**
```json
{
  "user_id": "uuid",
  "checkout_session_id": "stripe_cs_xxx",
  "checkout_url": "https://checkout.stripe.com/..."
}
```

**Logic:**
1. Validate email uniqueness
2. Create Supabase Auth user
3. Create profile with role=['recruiter'], account_status='standalone'
4. If new school → create school with is_virtual_school=true, set user as admin
5. If existing school → set parent_school_id for later linking
6. Create Stripe checkout session ($25)
7. Create event_purchase record (status='pending')
8. Return checkout URL

### Authenticated Endpoints

#### 4. POST `/api/webhooks/stripe`
Handle Stripe payment webhooks.

**Event: `checkout.session.completed`**

**Logic:**
1. Find event_purchase by checkout_session_id
2. Update status to 'completed'
3. Create school-specific event linked to universal_event
4. If parent_school_id exists → create account_link_request
5. Send email to school admins (if applicable)
6. Send welcome email to recruiter

#### 5. GET `/api/account-link-requests`
List pending link requests for admin's school.

**Auth**: Admin only

**Response:**
```json
[
  {
    "id": "uuid",
    "requester": {
      "id": "uuid",
      "email": "recruiter@example.com",
      "first_name": "John",
      "last_name": "Smith"
    },
    "event": {
      "name": "Dallas College Fair",
      "event_date": "2025-10-15"
    },
    "amount_paid": 2500,
    "created_at": "2025-12-15T10:00:00Z",
    "status": "pending"
  }
]
```

#### 6. POST `/api/account-link-requests/{id}/approve`
Approve link request and merge recruiter into school.

**Auth**: Admin only

**Logic:**
1. Verify request belongs to admin's school
2. Update requester's profile:
   - `school_id` = target_school_id
   - `account_status` = 'linked'
   - Remove `parent_school_id`
3. Update request status to 'approved'
4. Update recruiter's event to be under main school
5. Send confirmation email to recruiter

#### 7. POST `/api/account-link-requests/{id}/reject`
Reject link request.

**Auth**: Admin only

**Logic:**
1. Update request status to 'rejected'
2. Send notification to recruiter
3. Recruiter stays standalone (no refund)

#### 8. POST `/api/event-purchases`
Purchase additional event (for existing users).

**Request:**
```json
{
  "universal_event_id": "uuid"
}
```

**Response:**
```json
{
  "checkout_session_id": "stripe_cs_xxx",
  "checkout_url": "https://checkout.stripe.com/..."
}
```

---

## Frontend Pages & Components

### 1. New Page: `/signup/recruiter`
Multi-step signup wizard.

**Steps:**
1. **Account Details**
   - Email input
   - Password input (with strength indicator)
   - First name, last name
   - "Already have an account? Login"

2. **School Selection**
   - Autocomplete dropdown (loads from `/api/public/schools`)
   - Debounced search
   - Shows: School Name, City, State
   - Button at bottom: "My school isn't listed"
   - If clicked → Text input for new school name

3. **Event Selection**
   - Search bar with filters
   - Date range picker
   - Location filter
   - Event cards in grid layout
   - Each card shows: Name, Date, Location, Venue
   - Select button

4. **Payment**
   - Redirect to Stripe Checkout
   - Shows: Event name, $25
   - Success → `/signup/success`
   - Cancel → Back to step 3

**Files:**
- `/src/pages/RecruiterSignupPage.tsx`
- `/src/components/signup/AccountDetailsStep.tsx`
- `/src/components/signup/SchoolSelectionStep.tsx`
- `/src/components/signup/EventSelectionStep.tsx`

### 2. Component: `SchoolSelector.tsx`
Reusable autocomplete dropdown for school selection.

**Features:**
- Search/filter schools by name
- Debounced API calls
- Keyboard navigation
- Shows school location
- "Not listed" option

**Props:**
```typescript
interface SchoolSelectorProps {
  onSelect: (school: School | null) => void;
  onCreateNew: (schoolName: string) => void;
}
```

### 3. Component: `UniversalEventSearch.tsx`
Search and select universal events.

**Features:**
- Text search input
- Date range filter
- Location filter
- Grid layout of event cards
- Pagination
- Loading states

**Props:**
```typescript
interface UniversalEventSearchProps {
  onSelect: (event: UniversalEvent) => void;
}
```

### 4. New Page: `/admin/link-requests`
Admin interface for managing link requests.

**Features:**
- Table of pending requests
- Columns: Recruiter name, email, event, date, amount
- Actions: Approve, Reject, View Details
- Filters: Pending, Approved, Rejected
- Search by recruiter name/email

**Files:**
- `/src/pages/admin/LinkRequestsPage.tsx`
- `/src/components/admin/LinkRequestTable.tsx`

### 5. Page: `/signup/success`
Payment success confirmation.

**Content:**
- Success checkmark animation
- "Welcome to CardCapture!"
- Event confirmed: [Event Name]
- Payment receipt: $25
- Next steps:
  - Download mobile app
  - Start scanning cards
  - View quick start guide
- If linked to school: "We've notified [School] admins"
- CTA: "Go to Dashboard"

### 6. Magic Link Handler: `/accept-link`
One-click approval for admins.

**Flow:**
1. Admin clicks link in email
2. If not logged in → Login first
3. Show confirmation page:
   - Recruiter details
   - Event details
   - "Approve" and "Reject" buttons
4. On approve → Success message
5. Redirect to admin dashboard

---

## Email Templates

### 1. New Recruiter Signup Notification (to School Admins)

**Subject:** New recruiter signed up for [Event Name]

**Recipients:** All users with 'admin' role for target school

**Content:**
```
Hi [Admin Name],

A new recruiter has signed up for CardCapture and selected your school:

Recruiter: John Smith (recruiter@example.com)
Event: Dallas College Fair - Oct 15, 2025
Amount Paid: $25

They can start scanning cards immediately. If you'd like to link their
account to your main school account, click below:

[Approve & Link Account Button]

If you don't recognize this person, no action is needed. They can continue
using CardCapture independently, and you can still access their scanned
cards from this event if needed.

Questions? Reply to this email or contact support@cardcapture.io
```

### 2. Welcome Email (to New Recruiter)

**Subject:** Welcome to CardCapture!

**Content:**
```
Hi John,

Welcome to CardCapture! Your account is ready.

Event Confirmed: Dallas College Fair
Date: October 15, 2025
Payment: $25 (Receipt attached)

Next Steps:
1. Download the mobile app [Link]
2. Start scanning inquiry cards at the event
3. View your dashboard [Link]

We've notified McMurry University admins about your signup. They may
link your account to their main school account, giving you access to
additional resources.

Quick Start Guide: [Link]
Need help? support@cardcapture.io

Happy scanning!
The CardCapture Team
```

### 3. Link Approval Confirmation (to Recruiter)

**Subject:** Your account has been linked to [School Name]

**Content:**
```
Hi John,

Great news! McMurry University has approved your account link request.

Your account is now connected to McMurry University's main CardCapture
account. This means:

✓ Your event is now visible in the school's dashboard
✓ Your scanned cards can be processed by the school's team
✓ You have access to school resources and settings

Questions? Contact your school admin or reply to this email.

Thanks,
The CardCapture Team
```

### 4. Link Rejection Notification (to Recruiter)

**Subject:** Account link update for [School Name]

**Content:**
```
Hi John,

McMurry University has reviewed your account link request and chosen
not to link your account at this time.

What this means:
- No refund for your $25 payment (per our policy)
- You can continue using CardCapture independently
- Your scanned cards are still accessible in your dashboard
- The school may still choose to process your cards separately

Questions? Contact support@cardcapture.io

Thanks,
The CardCapture Team
```

---

## Step-by-Step Implementation Plan

### Phase 1: Database Foundation (Week 1)

**Goal:** Set up database schema without breaking existing functionality

**Tasks:**
1. Create migration for `universal_events` table
2. Create migration for `event_purchases` table
3. Create migration for `account_link_requests` table
4. Update `profiles` table (add columns)
5. Update `schools` table (add columns)
6. Update `events` table (add universal_event_id)
7. Write RLS policies for new tables

**Testing:**
- Run migrations on local database
- Verify existing functionality still works
- Check RLS policies with test queries

**Rollback Plan:**
- Keep rollback migrations ready
- Test on staging first

### Phase 2: Universal Events Management (Week 1-2)

**Goal:** Import event data and create admin UI

**Tasks:**
1. Create CSV template for event import
2. Write import script (`scripts/import_universal_events.py`)
3. Import 300+ Texas events
4. Create backend endpoint: GET `/api/public/universal-events/search`
5. Test search functionality (pagination, filters)

**Testing:**
- Verify all events imported correctly
- Test search with various filters
- Check pagination
- Performance test with 300+ records

### Phase 3: Public Signup API (Week 2)

**Goal:** Backend support for recruiter signup

**Tasks:**
1. Create endpoint: GET `/api/public/schools`
2. Create endpoint: POST `/api/public/recruiter-signup`
3. Implement Supabase Auth user creation
4. Implement profile creation with role='recruiter'
5. Handle new school creation (is_virtual_school=true)
6. Create Stripe checkout session ($25)
7. Create event_purchase record

**Testing:**
- Unit tests for each function
- Integration test: full signup flow
- Test with existing school
- Test with new school creation
- Test duplicate email handling
- Test Stripe session creation

### Phase 4: Payment Processing (Week 2-3)

**Goal:** Handle Stripe webhooks and complete purchases

**Tasks:**
1. Update POST `/api/webhooks/stripe`
2. Handle `checkout.session.completed` event
3. Update event_purchase status
4. Create school-specific event
5. Create account_link_request (if applicable)
6. Test webhook locally with Stripe CLI

**Testing:**
- Test successful payment flow
- Test payment failure handling
- Test duplicate webhook delivery
- Verify event creation
- Verify link request creation

### Phase 5: Account Linking Backend (Week 3)

**Goal:** Admin approval workflow

**Tasks:**
1. Create endpoint: GET `/api/account-link-requests`
2. Create endpoint: POST `/api/account-link-requests/:id/approve`
3. Create endpoint: POST `/api/account-link-requests/:id/reject`
4. Implement account merging logic
5. Add authorization checks (admin only)

**Testing:**
- Test approve flow
- Test reject flow
- Test permissions (non-admin can't approve)
- Verify school_id updates
- Test event ownership transfer

### Phase 6: Frontend Signup Flow (Week 3-4)

**Goal:** User-facing signup interface

**Tasks:**
1. Create `/signup/recruiter` page (multi-step wizard)
2. Build `AccountDetailsStep` component
3. Build `SchoolSelector` component
4. Build `UniversalEventSearch` component
5. Implement step navigation
6. Add form validation
7. Integrate with backend APIs
8. Handle Stripe redirect

**Testing:**
- Test full signup flow
- Test form validation
- Test error handling
- Test step navigation (back/forward)
- Cross-browser testing
- Mobile responsiveness

### Phase 7: Admin Link Management UI (Week 4)

**Goal:** Admin interface for approving links

**Tasks:**
1. Create `/admin/link-requests` page
2. Build `LinkRequestTable` component
3. Implement approve/reject actions
4. Add filters and search
5. Add loading states and error handling

**Testing:**
- Test approve action
- Test reject action
- Test filters
- Test empty state
- Test permissions

### Phase 8: Email Notifications (Week 4-5)

**Goal:** Automated email communication

**Tasks:**
1. Create email templates in Resend
2. Implement admin notification email
3. Implement welcome email
4. Implement approval confirmation email
5. Implement rejection notification email
6. Create magic link for one-click approval

**Testing:**
- Send test emails
- Verify templates render correctly
- Test magic links
- Check email deliverability
- Test spam score

### Phase 9: Integration Testing (Week 5)

**Goal:** End-to-end testing of complete flow

**Test Scenarios:**
1. New recruiter, existing school, admin approves
2. New recruiter, existing school, admin rejects
3. New recruiter, existing school, admin ignores
4. New recruiter, new school (becomes admin)
5. Existing user purchases additional event
6. Payment failure handling
7. Duplicate purchase prevention
8. Cross-tenant data isolation

### Phase 10: Beta Testing (Week 5-6)

**Goal:** Real-world validation with limited users

**Tasks:**
1. Select 5-10 beta recruiters
2. Provide signup instructions
3. Monitor signup flow
4. Collect feedback
5. Fix bugs
6. Iterate on UX

### Phase 11: Migration of Existing Customers (Week 6)

**Goal:** Transition current subscription customers

**Tasks:**
1. Add credits_balance = 999999 to existing schools
2. Update UI to show "Legacy Unlimited Plan"
3. Communicate changes to existing customers
4. Provide migration FAQ

### Phase 12: Public Launch (Week 7)

**Goal:** Full release to production

**Tasks:**
1. Update landing page with "Sign Up as Recruiter" CTA
2. Enable feature in production
3. Monitor error logs
4. Monitor Stripe webhooks
5. Set up customer support
6. Prepare launch announcement

---

## Testing Strategy

### Unit Tests

**Backend:**
- `test_recruiter_signup_endpoint.py`
- `test_event_search_endpoint.py`
- `test_account_linking.py`
- `test_payment_processing.py`
- `test_email_sending.py`

**Frontend:**
- `SchoolSelector.test.tsx`
- `UniversalEventSearch.test.tsx`
- `RecruiterSignupPage.test.tsx`
- `LinkRequestsPage.test.tsx`

### Integration Tests

**Full Signup Flow:**
```python
def test_recruiter_signup_flow():
    # 1. Call signup endpoint
    # 2. Verify user created in Supabase Auth
    # 3. Verify profile created with correct role
    # 4. Verify Stripe session created
    # 5. Simulate webhook
    # 6. Verify event_purchase completed
    # 7. Verify email sent
```

### E2E Tests (Playwright)

```typescript
test('recruiter signup with existing school', async ({ page }) => {
  // Navigate to signup page
  // Fill in account details
  // Select existing school
  // Search and select event
  // Complete Stripe checkout (test mode)
  // Verify success page
  // Verify email sent to admin
});
```

### Manual QA Checklist

- [ ] New recruiter can sign up
- [ ] School autocomplete works
- [ ] Event search returns results
- [ ] Payment processing completes
- [ ] Admin receives notification email
- [ ] Admin can approve link request
- [ ] Recruiter receives confirmation
- [ ] Admin can reject link request
- [ ] Recruiter receives rejection notice
- [ ] Standalone recruiter can scan cards
- [ ] Linked recruiter can access school events
- [ ] New school creation works
- [ ] Duplicate purchase is prevented
- [ ] RLS prevents cross-tenant access
- [ ] Mobile app works with new accounts

---

## Security Considerations

### 1. Rate Limiting
- Limit signup attempts per IP: 5/hour
- Limit event search: 100 requests/minute
- Prevent brute force on email enumeration

### 2. Email Verification
- Require email verification before first scan (optional)
- Use Supabase email confirmation

### 3. Payment Security
- Use Stripe Checkout (PCI compliant)
- Verify webhook signatures
- Log all payment events

### 4. RLS Policies
- Ensure standalone users only see their data
- Verify linked users see correct combined data
- Test cross-tenant isolation

### 5. Input Validation
- Sanitize all user inputs
- Validate email format
- Password strength requirements
- Prevent SQL injection

### 6. Magic Link Security
- Time-limited (24 hours)
- One-time use only
- Verify sender before executing action

---

## Monitoring & Analytics

### Key Metrics

**Signup Funnel:**
- Visits to /signup/recruiter
- Step 1 completion rate
- Step 2 completion rate
- Step 3 completion rate
- Payment completion rate
- Overall conversion rate

**Account Linking:**
- Link requests created
- Approval rate
- Time to approval (median, p95)
- Rejection rate
- Ignored rate (>30 days)

**Financial:**
- Revenue per event
- Revenue per day
- Average events per recruiter
- Failed payment rate

**Engagement:**
- Time to first scan
- Cards scanned per recruiter
- Standalone vs linked usage

### Error Monitoring

**Critical Errors to Alert:**
- Stripe webhook failures
- Payment processing errors
- Email send failures
- RLS policy violations

**Logging:**
- All signup attempts
- All payment events
- All link approvals/rejections
- All email sends

---

## Rollback Plan

### If Critical Bug Found Post-Launch

1. **Disable Public Signup**
   - Add feature flag: `RECRUITER_SIGNUP_ENABLED=false`
   - Show maintenance message on signup page

2. **Revert Database Migrations**
   - Have rollback SQL scripts ready
   - Test rollback on staging first

3. **Communication**
   - Email in-progress signups
   - Update status page
   - Provide timeline for fix

4. **Manual Processing**
   - Handle stuck signups manually
   - Refund failed payments
   - Create accounts via SuperAdmin

---

## Future Enhancements

### Bulk Credit Purchases (Q2 2026)

**Pricing Tiers:**
- 5 events: $110 ($22/event)
- 10 events: $200 ($20/event)
- 25 events: $450 ($18/event)

**Implementation:**
- Add `/api/schools/{id}/purchase-credits` endpoint
- Update `schools.credits_balance`
- Deduct credits on event purchase
- Show credit balance in UI

### Mobile App Support

- Add recruiter signup in iOS/Android app
- QR code event check-in
- Push notifications for link approvals

### Team Invitations

- Allow recruiters to invite colleagues
- Shared event purchases
- Team-level billing

### Analytics Dashboard

- Events attended over time
- Cards scanned per event
- ROI metrics
- Recruiter leaderboard

---

## FAQ

### What happens if a recruiter pays for an event but the school admin never approves?

The recruiter can still use CardCapture independently. They'll have access to scan cards for that event and view/export their scanned data. The school can still access the recruiter's cards if needed, they just won't be formally linked in the system.

### Can a recruiter purchase multiple events?

Yes! After their initial signup, they can purchase additional events from their dashboard. Each event costs $25.

### What if a school wants all their recruiters linked automatically?

We can add a school-level setting: `auto_approve_links=true`. When enabled, link requests are auto-approved without admin intervention.

### Can a standalone recruiter later link to a school?

Yes! They can submit a link request from their account settings. The school admin would need to approve.

### What happens to existing subscription customers?

They keep their existing subscriptions with unlimited events. We'll mark them as "Legacy Unlimited Plan" and give them `credits_balance=999999`.

### How do we handle refunds?

Per our policy, event purchases are non-refundable. However, we can manually refund in customer service scenarios (payment errors, duplicate charges, etc.).

### Can a recruiter work for multiple schools?

Currently no - one account = one school. If needed in the future, we can implement a "switch school" feature or allow multiple profiles.

---

## Success Criteria

### Launch Success (Week 7)
- [ ] 10+ recruiter signups in first week
- [ ] >80% payment completion rate
- [ ] <5 critical bugs reported
- [ ] Zero security incidents
- [ ] >90% email deliverability

### 30-Day Success (Week 11)
- [ ] 100+ recruiter signups
- [ ] >70% signup conversion rate
- [ ] >50% admin approval rate
- [ ] $2,500+ in revenue
- [ ] <10% support ticket rate

### 90-Day Success (Week 19)
- [ ] 500+ recruiter signups
- [ ] $12,500+ in revenue
- [ ] Positive customer feedback (NPS >30)
- [ ] Feature requests prioritized
- [ ] Proven product-market fit

---

## Resources & Documentation

### Reference Documentation
- [Supabase Auth Docs](https://supabase.com/docs/guides/auth)
- [Stripe Checkout Docs](https://stripe.com/docs/payments/checkout)
- [Stripe Webhooks](https://stripe.com/docs/webhooks)
- [Resend Email API](https://resend.com/docs)

### Internal Docs
- `/STUDENT_REGISTRATION_GUIDE.md` - Similar flow for reference
- `/IMAGE_PIPELINE_ANALYSIS.md` - Current pipeline docs
- `supabase/migrations/` - Database schema

### Tools
- Stripe CLI for webhook testing
- Supabase CLI for migrations
- Playwright for E2E tests
- Postman collection for API testing

---

## Contact & Support

**Implementation Lead:** TBD
**Backend Developer:** TBD
**Frontend Developer:** TBD
**QA Lead:** TBD
**Product Owner:** TBD

---

**Last Updated:** 2025-12-15
**Version:** 1.0
**Status:** Planning Phase

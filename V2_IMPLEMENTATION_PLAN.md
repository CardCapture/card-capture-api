# CardCapture V2 Implementation Plan
## Universal Cards + Online Registration System

**Branch:** `feature/v2-universal-cards`
**Goal:** Build new system supporting universal physical cards with serial numbers and online student registrations, while keeping existing custom card workflow operational for current customers.

---

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Database Changes](#database-changes)
4. [Backend Implementation](#backend-implementation)
5. [Frontend Implementation](#frontend-implementation)
6. [Testing Plan](#testing-plan)
7. [Migration Strategy](#migration-strategy)
8. [Timeline](#timeline)

---

## Overview

### Current State (V1)
- **3 paying customers** using custom card scanning
- Custom cards → OCR → `reviewed_data` table
- `upload_type = 'inquiry_card'`
- Complex review workflow with field-level flags
- **Must remain operational - do not break!**

### New State (V2)
- **Universal cards** with serial numbers (reusable across schools)
- **Online registration** with QR codes
- New `student_school_interactions` table (versions table)
- Simplified workflow:
  - QR codes → auto-approved (student entered data)
  - Handwritten cards → review workflow (OCR verification)

### Key Principles
1. **No risk to V1** - Build V2 alongside, don't touch `reviewed_data` for legacy customers
2. **Shared student data** - Serial numbers prevent duplicate OCR costs
3. **School-specific versions** - Each school can edit their copy independently
4. **Trust student input** - QR codes skip review, handwritten cards get reviewed

---

## Architecture

### Data Flow Comparison

#### V1 (Legacy - Keep Running)
```
Custom Card → Upload → OCR → reviewed_data → School Reviews → Export
```

#### V2 (New System)

**Path A: Online Registration → QR Code**
```
Student registers at cardcapture.io/register
    ↓
Creates student record (serial_number = NULL)
    ↓
Creates token in student_identifiers
    ↓
Emails/texts QR code
    ↓
School scans QR code at event
    ↓
Creates student_school_interactions row
    ↓
review_status = 'reviewed' (auto-approved)
    ↓
Ready to Export
```

**Path B: Universal Card (Handwritten)**
```
Student fills out universal card #12345
    ↓
School scans card (serial + photo)
    ↓
Check: Does serial #12345 exist in students table?
    ↓
IF YES:
    - Skip OCR (save $$$)
    - Copy student data
    - Apply school-specific settings
    - Check review flags based on requirements
    ↓
IF NO:
    - Run OCR pipeline
    - Create student record with serial #12345
    - Apply school-specific settings
    - Determine review status
    ↓
Create student_school_interactions row
    ↓
review_status = 'needs_review' or 'reviewed'
    ↓
Needs Review tab OR Ready to Export
```

### Database Schema

#### Core Tables

**1. students (existing, add serial_number)**
```sql
- id (PK)
- serial_number (UNIQUE) ← NEW!
- email
- first_name, last_name, preferred_first_name
- cell, address, address_2, city, state, zip_code
- date_of_birth, high_school, grade_level, grad_year
- gpa, gpa_scale, sat_score, act_score
- student_type, entry_term, entry_year
- major, academic_interests, intended_majors
- source_method ('card_scan', 'online_registration', etc.)
- verified (boolean)
- extras (JSONB)
- created_at, updated_at
```

**2. student_school_interactions (NEW - The "versions" table)**
```sql
- id (PK)
- student_id (FK → students.id)
- school_id (FK → schools.id)
- event_id (FK → events.id)
- user_id (FK → profiles.id)
- fields (JSONB) ← School's editable copy!
- review_status ('reviewed', 'needs_review', 'exported', 'archived')
- rating (1-5, optional)
- notes (TEXT, optional)
- source_method ('qr_code', 'universal_card')
- reviewed_at, exported_at
- created_at, updated_at
- UNIQUE(student_id, school_id, event_id)
```

**3. student_identifiers (existing - keep for QR tokens)**
```sql
- id (PK)
- token (TEXT, unique)
- student_id (FK → students.id)
- active (BOOLEAN)
```

**4. reviewed_data (existing - DO NOT TOUCH for V1)**
```sql
- Keep for legacy customers
- upload_type = 'inquiry_card'
- All existing functionality preserved
```

### Field Structure in JSONB

Each field in `student_school_interactions.fields`:

```json
{
  "field_name": {
    "value": "actual value",
    "confidence": 0.95,
    "source": "ocr" | "student_self" | "rep",
    "enabled": true,
    "required": true,
    "requires_review": false,
    "original_value": "original OCR value"
  }
}
```

**Review Logic:**
- **QR Code scans:** All fields have `requires_review = false`, `confidence = 1.0`
- **Handwritten cards:**
  - Empty required field → `requires_review = true`
  - Low confidence (<0.7) → `requires_review = true`
  - Otherwise → `requires_review = false`

---

## Database Changes

### Migration File: `20251002000000_v2_universal_cards.sql`

```sql
-- 1. Add serial_number to students table
ALTER TABLE students
ADD COLUMN IF NOT EXISTS serial_number TEXT UNIQUE;

CREATE INDEX IF NOT EXISTS idx_students_serial
ON students(serial_number)
WHERE serial_number IS NOT NULL;

-- 2. Create student_school_interactions table
CREATE TABLE IF NOT EXISTS student_school_interactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Links
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    school_id UUID NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    event_id UUID REFERENCES events(id) ON DELETE SET NULL,
    user_id UUID REFERENCES profiles(id) ON DELETE SET NULL,

    -- School's editable version of student data
    fields JSONB NOT NULL DEFAULT '{}',

    -- Review workflow
    review_status TEXT DEFAULT 'reviewed' CHECK (
        review_status IN ('reviewed', 'needs_review', 'exported', 'archived')
    ),

    -- Optional rating/notes from recruiter
    rating INTEGER CHECK (rating >= 1 AND rating <= 5),
    notes TEXT,

    -- Source tracking
    source_method TEXT CHECK (source_method IN ('qr_code', 'universal_card')),

    -- Workflow timestamps
    reviewed_at TIMESTAMPTZ,
    exported_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- One school can only have one version per student per event
    UNIQUE(student_id, school_id, event_id)
);

-- 3. Indexes for performance
CREATE INDEX idx_interactions_student ON student_school_interactions(student_id);
CREATE INDEX idx_interactions_school ON student_school_interactions(school_id);
CREATE INDEX idx_interactions_event ON student_school_interactions(event_id);
CREATE INDEX idx_interactions_review_status ON student_school_interactions(review_status);
CREATE INDEX idx_interactions_school_event ON student_school_interactions(school_id, event_id);

-- 4. RLS Policies (tenant isolation)
ALTER TABLE student_school_interactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "school_select" ON student_school_interactions
FOR SELECT
USING (school_id IN (SELECT school_id FROM profiles WHERE id = auth.uid()));

CREATE POLICY "school_insert" ON student_school_interactions
FOR INSERT
WITH CHECK (school_id IN (SELECT school_id FROM profiles WHERE id = auth.uid()));

CREATE POLICY "school_update" ON student_school_interactions
FOR UPDATE
USING (school_id IN (SELECT school_id FROM profiles WHERE id = auth.uid()));

CREATE POLICY "school_delete" ON student_school_interactions
FOR DELETE
USING (school_id IN (SELECT school_id FROM profiles WHERE id = auth.uid()));

CREATE POLICY "admin_all" ON student_school_interactions
FOR ALL
USING (
    EXISTS (
        SELECT 1 FROM profiles
        WHERE id = auth.uid()
        AND 'admin' = ANY(role)
    )
);

-- 5. Trigger for updated_at
CREATE TRIGGER update_interactions_updated_at
BEFORE UPDATE ON student_school_interactions
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- 6. Documentation
COMMENT ON TABLE student_school_interactions IS
'V2: Each school''s editable version of a student for an event. Replaces reviewed_data for universal cards and QR codes.';
```

---

## Backend Implementation

### File Structure

```
app/
├── api/
│   └── routes/
│       └── v2/
│           ├── __init__.py
│           └── students.py          # New V2 endpoints
├── services/
│   └── v2/
│       ├── __init__.py
│       ├── students_service.py      # V2 business logic
│       └── interactions_service.py  # Interaction management
├── repositories/
│   └── v2/
│       ├── __init__.py
│       └── interactions_repository.py
└── utils/
    └── v2/
        ├── __init__.py
        └── field_utils.py           # Field preparation logic
```

### API Endpoints

#### **POST /api/v2/students/scan-card**
Scan universal card with serial number

**Request:**
```json
{
  "serial_number": "12345",
  "image": "base64_encoded_image",  // Optional if card exists
  "event_id": "uuid",
  "rating": 4,  // Optional
  "notes": "Very interested in engineering"  // Optional
}
```

**Response:**
```json
{
  "success": true,
  "ocr_skipped": true,  // or false if OCR was run
  "student_id": "uuid",
  "interaction_id": "uuid",
  "review_status": "reviewed",
  "fields_needing_review": []  // Array of field keys if needs_review
}
```

**Logic:**
1. Check if student exists by serial_number
2. If exists: Copy data, skip OCR
3. If new: Run OCR, create student
4. Get school's field settings
5. Apply review logic (handwritten card rules)
6. Create student_school_interactions row
7. Return status

#### **POST /api/v2/students/scan-qr**
Scan student's QR code

**Request:**
```json
{
  "token": "student_qr_token",
  "event_id": "uuid",
  "rating": 5,  // Optional
  "notes": "Great fit for our program"  // Optional
}
```

**Response:**
```json
{
  "success": true,
  "student_id": "uuid",
  "interaction_id": "uuid",
  "review_status": "reviewed"  // Always reviewed for QR
}
```

**Logic:**
1. Lookup student by token
2. Get school's field settings
3. Prepare fields with trust_data=True (skip review)
4. Create student_school_interactions row with review_status='reviewed'
5. Return success

#### **GET /api/v2/events/:event_id/interactions**
Get all student interactions for an event

**Query Params:**
- `review_status` (optional): 'needs_review', 'reviewed', 'exported', 'archived'
- `source_method` (optional): 'qr_code', 'universal_card'

**Response:**
```json
{
  "interactions": [
    {
      "id": "uuid",
      "student_id": "uuid",
      "fields": { /* JSONB fields */ },
      "review_status": "reviewed",
      "source_method": "qr_code",
      "rating": 4,
      "notes": "...",
      "created_at": "2025-10-02T...",
      "reviewed_at": "2025-10-02T..."
    }
  ]
}
```

#### **PUT /api/v2/interactions/:id**
Update interaction (edit fields, change status)

**Request:**
```json
{
  "fields": { /* Updated fields JSONB */ },
  "review_status": "reviewed",  // Optional
  "rating": 5,  // Optional
  "notes": "Updated notes"  // Optional
}
```

**Response:**
```json
{
  "success": true,
  "interaction": { /* Updated interaction */ }
}
```

#### **POST /api/v2/interactions/:id/export**
Mark interaction as exported

**Response:**
```json
{
  "success": true,
  "exported_at": "2025-10-02T..."
}
```

### Core Service Functions

#### **scan_universal_card_v2()**
```python
async def scan_universal_card_v2(
    serial_number: str,
    image_base64: Optional[str],
    event_id: str,
    school_id: str,
    user_id: str,
    rating: Optional[int] = None,
    notes: Optional[str] = None
) -> dict:
    """
    Scan universal card with serial number
    - Check if student exists by serial
    - Skip OCR if exists, run OCR if new
    - Apply school-specific review logic
    - Create student_school_interactions row
    """

    sb = get_supabase_client()

    # 1. Check if student exists
    student = get_student_by_serial(serial_number)

    # 2. Check for duplicate scan
    if student:
        existing = check_existing_interaction(
            student['id'], school_id, event_id
        )
        if existing:
            return {
                "success": False,
                "error": "already_scanned",
                "message": "Already scanned this student"
            }

    # 3a. FAST PATH: Reuse existing student data
    if student:
        fields = student_to_fields(student, trust_data=False)
        ocr_skipped = True

    # 3b. SLOW PATH: Run OCR on new card
    else:
        if not image_base64:
            raise HTTPException(400, "Image required for new card")

        ocr_result = await run_ocr_pipeline(image_base64, school_id, event_id, user_id)
        student = create_student_from_ocr(serial_number, ocr_result)
        fields = ocr_result.fields
        ocr_skipped = False

    # 4. Apply school-specific settings and review logic
    school_settings = get_school_field_settings(school_id)
    fields = apply_school_settings_and_review(
        fields,
        school_settings,
        source_method='universal_card'
    )

    # 5. Determine overall review status
    needs_review = any(f.get('requires_review') for f in fields.values())
    review_status = 'needs_review' if needs_review else 'reviewed'

    # 6. Create interaction
    interaction = create_interaction({
        "student_id": student['id'],
        "school_id": school_id,
        "event_id": event_id,
        "user_id": user_id,
        "fields": fields,
        "source_method": "universal_card",
        "review_status": review_status,
        "rating": rating,
        "notes": notes,
        "reviewed_at": None if needs_review else now()
    })

    return {
        "success": True,
        "ocr_skipped": ocr_skipped,
        "student_id": student['id'],
        "interaction_id": interaction['id'],
        "review_status": review_status,
        "fields_needing_review": [
            k for k, v in fields.items() if v.get('requires_review')
        ] if needs_review else []
    }
```

#### **scan_qr_code_v2()**
```python
async def scan_qr_code_v2(
    token: str,
    event_id: str,
    school_id: str,
    user_id: str,
    rating: Optional[int] = None,
    notes: Optional[str] = None
) -> dict:
    """
    Scan student's QR code
    - Student entered data directly = trusted
    - Always auto-approve (review_status = 'reviewed')
    """

    # 1. Lookup student
    student = get_student_by_token(token)
    if not student:
        raise HTTPException(400, "Invalid token")

    # 2. Check for duplicate
    existing = check_existing_interaction(
        student['id'], school_id, event_id
    )
    if existing:
        return {
            "success": False,
            "error": "already_scanned"
        }

    # 3. Get school settings
    school_settings = get_school_field_settings(school_id)

    # 4. Prepare fields - trust student data!
    fields = student_to_fields(student, trust_data=True)
    fields = apply_school_settings(fields, school_settings)
    # All fields have requires_review = False

    # 5. Create interaction (auto-approved)
    interaction = create_interaction({
        "student_id": student['id'],
        "school_id": school_id,
        "event_id": event_id,
        "user_id": user_id,
        "fields": fields,
        "source_method": "qr_code",
        "review_status": "reviewed",  # Always reviewed!
        "rating": rating,
        "notes": notes,
        "reviewed_at": now()
    })

    return {
        "success": True,
        "student_id": student['id'],
        "interaction_id": interaction['id'],
        "review_status": "reviewed"
    }
```

#### **apply_school_settings_and_review()**
```python
def apply_school_settings_and_review(
    fields: dict,
    school_settings: dict,
    source_method: str
) -> dict:
    """
    Apply school-specific settings and review logic
    - Sets enabled/required based on school config
    - Sets requires_review flags for handwritten cards only
    """

    for field_key in fields:
        field = fields[field_key]

        # Apply school settings
        field['enabled'] = field_key in school_settings.get('enabled_fields', [])
        field['required'] = field_key in school_settings.get('required_fields', [])

        # Review logic ONLY for handwritten cards
        if source_method == 'universal_card' and field['enabled']:
            value = field.get('value', '')
            confidence = field.get('confidence', 1.0)

            # Mark for review if:
            # 1. Required but empty
            if field['required'] and not value:
                field['requires_review'] = True

            # 2. Has value but low confidence
            elif value and confidence < 0.7:
                field['requires_review'] = True

            else:
                field['requires_review'] = False
        else:
            # QR code or disabled field - no review
            field['requires_review'] = False

    return fields
```

#### **student_to_fields()**
```python
def student_to_fields(student: dict, trust_data: bool = False) -> dict:
    """
    Convert student record to field structure

    Args:
        student: Student from database
        trust_data: If True, set confidence=1.0 and source='student_self'
    """

    fields = {}

    field_list = [
        'first_name', 'last_name', 'preferred_first_name',
        'email', 'cell', 'permission_to_text',
        'address', 'address_2', 'city', 'state', 'zip_code',
        'date_of_birth', 'high_school', 'grade_level', 'grad_year',
        'gpa', 'gpa_scale', 'sat_score', 'act_score',
        'student_type', 'entry_term', 'entry_year',
        'major', 'academic_interests', 'intended_majors'
    ]

    for field_key in field_list:
        value = student.get(field_key, '')

        if trust_data:
            # Student entered this directly
            confidence = 1.0
            source = 'student_self'
        else:
            # May have come from OCR
            confidence = student.get(f'{field_key}_confidence', 0.85)
            source = student.get('source_method', 'ocr')

        fields[field_key] = {
            'value': value,
            'confidence': confidence,
            'source': source,
            'enabled': True,  # Will be set by school settings
            'required': False,  # Will be set by school settings
            'requires_review': False,  # Will be set by review logic
            'original_value': value
        }

    return fields
```

---

## Frontend Implementation

### File Structure

```
src/
├── pages/
│   └── v2/
│       ├── EventDashboard.tsx       # Main event view
│       ├── StudentScanner.tsx       # Card/QR scanner
│       ├── InteractionsList.tsx     # List of students
│       ├── InteractionEditor.tsx    # Edit student fields
│       └── BulkExport.tsx          # Export multiple students
├── components/
│   └── v2/
│       ├── SerialNumberInput.tsx    # Serial # input field
│       ├── StudentCard.tsx          # Display student info
│       ├── ReviewStatusBadge.tsx    # Status indicator
│       └── FieldEditor.tsx          # Individual field editor
└── hooks/
    └── v2/
        ├── useInteractions.ts       # Fetch interactions
        ├── useUpdateInteraction.ts  # Update interaction
        └── useExportInteractions.ts # Export logic
```

### Key Components

#### **StudentScanner.tsx**
```tsx
function StudentScanner({ eventId }: { eventId: string }) {
  const [scanMode, setScanMode] = useState<'qr' | 'card'>('qr');
  const [serialNumber, setSerialNumber] = useState('');
  const [image, setImage] = useState<string | null>(null);

  const scanCard = useMutation({
    mutationFn: (data: ScanCardRequest) =>
      api.post('/api/v2/students/scan-card', data),
    onSuccess: (result) => {
      if (result.review_status === 'needs_review') {
        toast.warning(`Card scanned - ${result.fields_needing_review.length} fields need review`);
      } else {
        toast.success('Card scanned - ready to export!');
      }
    }
  });

  const scanQR = useMutation({
    mutationFn: (data: ScanQRRequest) =>
      api.post('/api/v2/students/scan-qr', data),
    onSuccess: () => {
      toast.success('QR code scanned - ready to export!');
    }
  });

  const handleScan = () => {
    if (scanMode === 'qr') {
      // Decode QR code to get token
      const token = decodeQR(image);
      scanQR.mutate({ token, event_id: eventId });
    } else {
      // Universal card scan
      scanCard.mutate({
        serial_number: serialNumber,
        image: image,
        event_id: eventId
      });
    }
  };

  return (
    <div>
      <Tabs value={scanMode} onChange={setScanMode}>
        <Tab value="qr">QR Code</Tab>
        <Tab value="card">Universal Card</Tab>
      </Tabs>

      {scanMode === 'card' && (
        <SerialNumberInput
          value={serialNumber}
          onChange={setSerialNumber}
        />
      )}

      <CameraCapture onCapture={setImage} />

      <Button onClick={handleScan} disabled={!image}>
        Scan {scanMode === 'qr' ? 'QR Code' : 'Card'}
      </Button>
    </div>
  );
}
```

#### **InteractionsList.tsx**
```tsx
function InteractionsList({ eventId }: { eventId: string }) {
  const [filter, setFilter] = useState<'all' | 'needs_review' | 'reviewed'>('all');

  const { data: interactions } = useQuery({
    queryKey: ['interactions', eventId, filter],
    queryFn: () => fetchInteractions(eventId, {
      review_status: filter === 'all' ? undefined : filter
    })
  });

  return (
    <>
      <Tabs value={filter} onChange={setFilter}>
        <Tab value="all">All Students</Tab>
        <Tab value="needs_review">
          Needs Review ({interactions?.filter(i => i.review_status === 'needs_review').length})
        </Tab>
        <Tab value="reviewed">
          Ready to Export ({interactions?.filter(i => i.review_status === 'reviewed').length})
        </Tab>
      </Tabs>

      <Table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Email</th>
            <th>Source</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {interactions?.map(interaction => (
            <tr key={interaction.id}>
              <td>
                {interaction.fields.first_name?.value} {interaction.fields.last_name?.value}
              </td>
              <td>{interaction.fields.email?.value}</td>
              <td>
                {interaction.source_method === 'qr_code' ? (
                  <Badge variant="success">QR Code</Badge>
                ) : (
                  <Badge variant="info">Card Scan</Badge>
                )}
              </td>
              <td>
                {interaction.review_status === 'needs_review' ? (
                  <Badge variant="warning">
                    Review ({countFieldsNeedingReview(interaction.fields)})
                  </Badge>
                ) : (
                  <Badge variant="success">✓ Reviewed</Badge>
                )}
              </td>
              <td>
                <Button
                  size="sm"
                  onClick={() => openEditor(interaction)}
                >
                  {interaction.review_status === 'needs_review' ? 'Review' : 'Edit'}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </Table>
    </>
  );
}

function countFieldsNeedingReview(fields: Record<string, Field>) {
  return Object.values(fields).filter(f => f.requires_review).length;
}
```

#### **InteractionEditor.tsx**
```tsx
function InteractionEditor({ interaction }: { interaction: Interaction }) {
  const [fields, setFields] = useState(interaction.fields);

  const updateMutation = useMutation({
    mutationFn: (data: UpdateInteractionRequest) =>
      api.put(`/api/v2/interactions/${interaction.id}`, data),
    onSuccess: () => {
      toast.success('Changes saved');
    }
  });

  const markReviewed = () => {
    updateMutation.mutate({
      fields,
      review_status: 'reviewed',
      reviewed_at: new Date().toISOString()
    });
  };

  const updateField = (key: string, value: string) => {
    setFields({
      ...fields,
      [key]: {
        ...fields[key],
        value,
        // Clear review flag when edited
        requires_review: false
      }
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h2>Edit Student Information</h2>
        {interaction.source_method === 'qr_code' && (
          <Badge variant="success">Student Self-Registered</Badge>
        )}
      </div>

      <Form>
        {Object.entries(fields).map(([key, field]) => {
          if (!field.enabled) return null;

          return (
            <FormField key={key}>
              <Label>
                {formatFieldName(key)}
                {field.required && <span className="text-red-500">*</span>}
                {field.requires_review && (
                  <Badge variant="warning" className="ml-2">
                    Needs Review
                    {field.confidence < 0.7 && (
                      <span className="ml-1">
                        ({Math.round(field.confidence * 100)}% confident)
                      </span>
                    )}
                  </Badge>
                )}
              </Label>

              <Input
                value={field.value}
                onChange={(e) => updateField(key, e.target.value)}
                className={field.requires_review ? 'border-yellow-500' : ''}
              />

              {field.original_value && field.original_value !== field.value && (
                <p className="text-sm text-gray-500">
                  OCR originally read: "{field.original_value}"
                </p>
              )}
            </FormField>
          );
        })}
      </Form>

      <div className="flex gap-2">
        <Button onClick={() => updateMutation.mutate({ fields })}>
          Save Changes
        </Button>

        {interaction.review_status === 'needs_review' && (
          <Button variant="primary" onClick={markReviewed}>
            Mark as Reviewed
          </Button>
        )}
      </div>
    </div>
  );
}
```

#### **BulkExport.tsx**
```tsx
function BulkExport({ eventId }: { eventId: string }) {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const { data: interactions } = useQuery({
    queryKey: ['interactions', eventId, 'reviewed'],
    queryFn: () => fetchInteractions(eventId, { review_status: 'reviewed' })
  });

  const exportMutation = useMutation({
    mutationFn: async () => {
      // Mark as exported
      await Promise.all(
        selectedIds.map(id =>
          api.post(`/api/v2/interactions/${id}/export`)
        )
      );

      // Generate CSV/export file
      const csv = generateCSV(
        interactions?.filter(i => selectedIds.includes(i.id))
      );
      downloadCSV(csv, `export-${eventId}.csv`);
    },
    onSuccess: () => {
      toast.success(`Exported ${selectedIds.length} students`);
      setSelectedIds([]);
    }
  });

  return (
    <div>
      <div className="mb-4">
        <Checkbox
          checked={selectedIds.length === interactions?.length}
          onChange={() => {
            if (selectedIds.length === interactions?.length) {
              setSelectedIds([]);
            } else {
              setSelectedIds(interactions?.map(i => i.id) || []);
            }
          }}
        >
          Select All ({interactions?.length || 0})
        </Checkbox>
      </div>

      <Table>
        {interactions?.map(interaction => (
          <tr key={interaction.id}>
            <td>
              <Checkbox
                checked={selectedIds.includes(interaction.id)}
                onChange={() => {
                  if (selectedIds.includes(interaction.id)) {
                    setSelectedIds(selectedIds.filter(id => id !== interaction.id));
                  } else {
                    setSelectedIds([...selectedIds, interaction.id]);
                  }
                }}
              />
            </td>
            <td>{interaction.fields.first_name?.value}</td>
            <td>{interaction.fields.last_name?.value}</td>
            <td>{interaction.fields.email?.value}</td>
          </tr>
        ))}
      </Table>

      <Button
        onClick={() => exportMutation.mutate()}
        disabled={selectedIds.length === 0}
      >
        Export Selected ({selectedIds.length})
      </Button>
    </div>
  );
}
```

---

## Testing Plan

### Unit Tests

**Backend:**
- [ ] Test `scan_universal_card_v2()` with existing student (skip OCR)
- [ ] Test `scan_universal_card_v2()` with new student (run OCR)
- [ ] Test `scan_qr_code_v2()` auto-approves (review_status='reviewed')
- [ ] Test review logic: empty required field → requires_review=true
- [ ] Test review logic: low confidence → requires_review=true
- [ ] Test review logic: good data → requires_review=false
- [ ] Test duplicate scan detection (same student, school, event)
- [ ] Test school settings application (enabled/required fields)

**Frontend:**
- [ ] Test SerialNumberInput validation
- [ ] Test camera capture for both QR and card modes
- [ ] Test interaction list filtering (all/needs_review/reviewed)
- [ ] Test field editor saves changes correctly
- [ ] Test review flag indicators appear correctly
- [ ] Test bulk export selection and CSV generation

### Integration Tests

- [ ] End-to-end: Register online → Receive QR → Scan at event → Verify in export list
- [ ] End-to-end: Fill card → Scan card (new) → Review fields → Mark reviewed → Export
- [ ] End-to-end: Same card scanned by 2 schools → Both get separate versions
- [ ] End-to-end: Card #12345 scanned twice by same school → Second scan rejected
- [ ] Verify RLS: School A cannot see School B's interactions
- [ ] Verify OCR reuse: Second school scanning card skips OCR

### Demo Scenarios

**Scenario 1: Online Registration + QR Code**
1. Student goes to cardcapture.io/register
2. Fills out profile form
3. Receives QR code via email/SMS
4. Goes to college fair
5. Shows QR code to Texas A&M recruiter
6. Recruiter scans → Immediately appears in "Ready to Export"
7. No review needed (student entered data)

**Scenario 2: Universal Card - First Scan**
1. Student picks up blank universal card #12345
2. Fills it out by hand
3. Shows to Baylor recruiter
4. Recruiter scans card + takes photo
5. OCR runs, extracts data
6. Some fields flagged for review (low confidence)
7. Appears in "Needs Review" tab
8. Recruiter reviews, fixes errors, marks reviewed
9. Moves to "Ready to Export"

**Scenario 3: Universal Card - Second Scan (Reuse)**
1. Same student with card #12345
2. Shows to SMU recruiter
3. Recruiter scans card
4. System finds existing student by serial
5. OCR skipped! Data reused
6. SMU's settings applied (different required fields than Baylor)
7. Review status determined by SMU's requirements
8. SMU can edit their version independently

---

## Migration Strategy

### Phase 1: Build V2 (Weeks 1-3)
- Create feature branch
- Run database migration
- Build backend endpoints
- Build frontend components
- Test with demo data

### Phase 2: Demo & Feedback (Week 4)
- Set up demo event
- Print universal cards with serial numbers
- Run through all scenarios
- Gather feedback
- Polish UI/UX

### Phase 3: Customer Migration (Weeks 5-6)

**For each of 3 existing customers:**

1. **Data Export (Backup)**
   ```sql
   -- Export customer's data for backup
   SELECT * FROM reviewed_data
   WHERE school_id = 'customer-school-id'
   AND upload_type = 'inquiry_card';
   ```

2. **Migration Script**
   ```sql
   -- Migrate customer's reviewed_data to V2 structure
   INSERT INTO student_school_interactions (
       student_id, school_id, event_id, user_id,
       fields, review_status, source_method,
       reviewed_at, exported_at, created_at
   )
   SELECT
       -- Find or create student
       COALESCE(
           (SELECT id FROM students WHERE email = rd.fields->>'email' LIMIT 1),
           (INSERT INTO students (email, first_name, last_name, source_method)
            VALUES (
                rd.fields->>'email',
                rd.fields->'first_name'->>'value',
                rd.fields->'last_name'->>'value',
                'inquiry_card'
            )
            RETURNING id)
       ),
       rd.school_id,
       rd.event_id,
       rd.user_id,
       rd.fields,
       rd.review_status,
       'universal_card',
       rd.reviewed_at,
       rd.exported_at,
       rd.created_at
   FROM reviewed_data rd
   WHERE rd.school_id = 'customer-school-id'
   AND rd.upload_type = 'inquiry_card'
   ON CONFLICT (student_id, school_id, event_id) DO NOTHING;
   ```

3. **Feature Flag Toggle**
   ```sql
   -- Enable V2 for customer
   UPDATE schools
   SET extras = jsonb_set(
       COALESCE(extras, '{}'),
       '{use_v2}',
       'true'
   )
   WHERE id = 'customer-school-id';
   ```

4. **Training & Transition**
   - Walk through new interface
   - Explain QR codes vs universal cards
   - Show simplified review process
   - Provide support for 2 weeks

5. **Fallback Period (30 days)**
   - Keep V1 available via toggle
   - Monitor for issues
   - Be ready to rollback if needed

6. **V1 Deprecation**
   - After 30 days of stability
   - Archive old `reviewed_data` entries
   - Remove V1 code

### Rollback Plan

If V2 has issues:
```sql
-- Disable V2 for customer
UPDATE schools
SET extras = jsonb_set(
    COALESCE(extras, '{}'),
    '{use_v2}',
    'false'
)
WHERE id = 'customer-school-id';
```

Customer immediately sees V1 interface again with all their original data intact.

---

## Timeline

### Week 1: Database & Core Backend
- **Day 1:** Create branch, run migration
- **Day 2:** Build `scan_universal_card_v2()` service
- **Day 3:** Build `scan_qr_code_v2()` service
- **Day 4:** Build interaction CRUD endpoints
- **Day 5:** Unit tests for backend

### Week 2: Frontend Components
- **Day 1:** Build StudentScanner component
- **Day 2:** Build InteractionsList component
- **Day 3:** Build InteractionEditor component
- **Day 4:** Build BulkExport component
- **Day 5:** Integration testing

### Week 3: Polish & Demo Prep
- **Day 1:** UI/UX improvements
- **Day 2:** Print universal cards with serial numbers
- **Day 3:** Set up demo event in database
- **Day 4:** End-to-end testing all scenarios
- **Day 5:** Demo dry run

### Week 4: Demo & Feedback
- **Day 1:** Run demo with stakeholders
- **Day 2-3:** Address feedback
- **Day 4-5:** Final polish

### Week 5-6: Customer Migration
- **Week 5:** Migrate customer 1 & 2
- **Week 6:** Migrate customer 3, monitoring

---

## Success Criteria

### Demo Success
- [ ] Student registers online → receives QR code
- [ ] QR code scanned → appears in "Ready to Export" immediately
- [ ] Universal card scanned → OCR runs, fields extracted
- [ ] Same card scanned by 2nd school → OCR skipped, data reused
- [ ] Review workflow: flag fields → recruiter fixes → mark reviewed
- [ ] Export: select students → download CSV

### Production Success
- [ ] All 3 customers migrated successfully
- [ ] No data loss during migration
- [ ] V2 performance equals or exceeds V1
- [ ] OCR reuse working (50%+ scans skip OCR)
- [ ] Zero downtime during rollout
- [ ] Customer satisfaction maintained or improved

---

## Notes & Considerations

### Cost Savings
- **OCR reuse:** If card scanned by 3 schools, save 2/3 OCR costs
- **Student registration:** Pre-filled data = fewer OCR errors
- **Bulk events:** 200-student event, 50% reuse = significant savings

### Data Privacy
- Students "own" their data via online registration
- Schools get their own editable copies
- RLS ensures schools can't see other schools' data
- Student can update their profile → next scan uses new data

### Future Enhancements (Post-V2)
- Student portal to manage their data
- Multi-event QR code (one QR for all events)
- Analytics dashboard (which schools scanned which students)
- Integration with CRMs (auto-sync to Slate, Salesforce, etc.)
- Mobile app for students to carry digital card

---

## Getting Started Tomorrow

1. **Create branch:**
   ```bash
   git checkout main
   git pull
   git checkout -b feature/v2-universal-cards
   git add V2_IMPLEMENTATION_PLAN.md
   git commit -m "docs: Add V2 implementation plan"
   git push -u origin feature/v2-universal-cards
   ```

2. **Run migration:**
   ```bash
   cd card-capture-api
   # Add migration file to supabase/migrations/
   npx supabase db push
   ```

3. **Start with backend:**
   - Create `app/api/routes/v2/students.py`
   - Create `app/services/v2/students_service.py`
   - Implement `scan_universal_card_v2()`

4. **Test as you go:**
   - Use Postman/curl to test endpoints
   - Verify database inserts
   - Check RLS policies working

Let's build this! 🚀

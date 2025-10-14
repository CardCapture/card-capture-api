# Transcript Parser Productization Plan

## Overview

Transform the transcript parser from a single-customer tool into a multi-tenant product where each customer (school/organization) can configure their own GPA calculation rules and consistently apply them to all transcripts they process.

## Core Principles

1. **Customer = School/Organization**: Each customer has ONE set of GPA rules applied to ALL transcripts
2. **LLM for Extraction Only**: Gemini extracts raw course data; backend performs all calculations
3. **Customer Control**: Schools configure their GPA methodology once, with ability to review/edit results
4. **Ignore School GPA**: We are the source of truth; school-reported GPAs are for reference only
5. **Auditability**: Every calculation is transparent and traceable

---

## Architecture Components

### 1. GPA Calculation Profile (Per Customer)

Each customer configures a profile containing their GPA calculation methodology:

#### A. Scale Configuration
```json
{
  "scale_type": "weighted_4.0",  // Options: "weighted_4.0", "unweighted_4.0", "100_point", "5.0_scale"
  "grade_point_mappings": {
    "A": { "min": 90, "max": 100, "points": 4.0 },
    "B": { "min": 80, "max": 89, "points": 3.0 },
    "C": { "min": 70, "max": 79, "points": 2.0 },
    "D": { "min": 60, "max": 69, "points": 1.0 },
    "F": { "min": 0, "max": 59, "points": 0.0 }
  }
}
```

#### B. Weight Bonus Configuration
```json
{
  "weight_bonuses": {
    "AP": 1.0,
    "IB": 1.0,
    "Dual_Credit": 1.0,
    "Honors": 1.0,
    "Pre_AP": 1.0,
    "Pre_IB": 1.0
  },
  "minimum_grade_for_weight": 60,  // D or better
  "weight_description": "All advanced courses receive +1.0 bonus if grade is D or better"
}
```

#### C. Course Inclusion Rules
```json
{
  "include_pe_athletics": true,
  "include_fine_arts": true,
  "include_electives": true,
  "include_j_courses": true,          // Courses taken before 9th grade
  "include_pass_fail": false,          // P/CR courses with no numeric grade
  "include_zero_credit": true,         // Courses with grade but 0 credits earned
  "include_local_credit_only": true,
  "grade_levels": ["9", "10", "11", "12", "J"]
}
```

#### D. Advanced Course Detection
```json
{
  "advanced_course_flags": ["H", "Q", "D", "P", "I", "K"],
  "advanced_course_keywords": [
    "Honors", "AP", "IB", "Dual Credit", "Pre-AP", "Pre-IB",
    "Advanced Placement", "International Baccalaureate"
  ],
  "custom_markers": []  // Customer-specific markers
}
```

---

## Data Flow

### Phase 1: Profile Configuration (One-time per customer)

```
Customer → GPA Profile Setup UI → Save Profile to DB
```

**UI allows customer to:**
- Select scale type (4.0 weighted, 4.0 unweighted, etc.)
- Configure grade point values
- Set weight bonuses for each advanced course type
- Choose which courses to include/exclude
- Define advanced course markers

**Output:** `gpa_calculation_profile` stored in database, linked to customer

---

### Phase 2: Transcript Upload & Processing

```
1. Upload Transcript PDF
   ↓
2. Load Customer's GPA Profile
   ↓
3. Generate Dynamic Gemini Prompt (based on profile rules)
   ↓
4. Gemini Extracts Raw Course Data ONLY
   {
     "student": {...},
     "courses": [
       {
         "course_name": "AP English",
         "course_code": "ENG301",
         "final_grade_numeric": 85,
         "credits_attempted": 1.0,
         "credits_earned": 1.0,
         "semester_grades": {"s1": 87, "s2": 89},
         "flags": ":P",
         "raw_text": "22/23 ENG 3  85  87  86  1.00  P"
       },
       ...
     ]
   }
   ↓
5. Backend Applies Customer's Rules
   - Detect advanced courses (using customer's markers)
   - Apply inclusion/exclusion rules
   - Calculate base points
   - Apply weight bonuses
   - Sum quality points and credits
   - Calculate GPA = total_quality_points / total_credits
   ↓
6. Return Results to Customer
   - Calculated GPA
   - Course-by-course breakdown
   - Included/excluded courses with reasons
   - Quality points per course
```

---

## Dynamic Gemini Prompt Generation

The system generates a custom prompt for each customer based on their profile:

### Prompt Template
```
You are an expert transcript parser for US high school academic records.

TASK: Extract all student and course information from this transcript.
DO NOT calculate GPA - only extract raw data.

ADVANCED COURSE MARKERS TO DETECT:
{customer.advanced_course_flags}  // e.g., "H, Q, D, P, I, K"
{customer.advanced_course_keywords}  // e.g., "Honors, AP, IB, Dual Credit"

If courses are split by semester, COMBINE them into single entries.

EXTRACT INTO THIS JSON SCHEMA:
{
  "student": {
    "name": "Last, First Middle",
    "date_of_birth": "YYYY-MM-DD",
    "student_id": "ID",
    "school": "School Name",
    "district": "District Name",
    "reported_gpa": 3.45  // For reference only
  },
  "courses": [
    {
      "course_name": "English 3",
      "course_code": "ENG301",
      "credits_attempted": 1.0,
      "credits_earned": 1.0,
      "final_grade_numeric": 86,
      "final_grade_letter": "B",
      "semester_grades": {"s1": 85, "s2": 87},
      "flags": ":H",  // Course flags from transcript
      "raw_text": "22/23 ENG 3  85  87  86  1.00  H",
      "school_year": "2022-23",
      "grade_level": "11"
    }
  ]
}

Return ONLY the JSON. Do NOT calculate GPA.
```

---

## Backend GPA Calculation Engine

```python
class GPACalculator:
    def __init__(self, profile: GPACalculationProfile):
        self.profile = profile

    def calculate(self, courses: List[Course]) -> GPAResult:
        included_courses = []

        for course in courses:
            # 1. Apply inclusion rules
            if not self._should_include(course):
                course.excluded = True
                course.exclusion_reason = self._get_exclusion_reason(course)
                continue

            # 2. Detect if advanced course
            course.is_advanced = self._detect_advanced(course)

            # 3. Calculate base points
            course.base_points = self._get_base_points(course.final_grade_numeric)

            # 4. Apply weight bonus
            course.weight_bonus = self._get_weight_bonus(course)

            # 5. Calculate quality points
            course.quality_points = (course.base_points + course.weight_bonus) * course.credits_attempted

            included_courses.append(course)

        # 6. Calculate final GPA
        total_qp = sum(c.quality_points for c in included_courses)
        total_credits = sum(c.credits_attempted for c in included_courses)
        gpa = total_qp / total_credits if total_credits > 0 else 0.0

        return GPAResult(
            gpa=round(gpa, 3),
            total_quality_points=total_qp,
            total_credits=total_credits,
            courses_included=len(included_courses),
            weighted_courses=len([c for c in included_courses if c.weight_bonus > 0]),
            course_details=included_courses
        )

    def _should_include(self, course: Course) -> bool:
        # Check against customer's inclusion rules
        if not self.profile.include_pe_athletics and self._is_pe(course):
            return False
        if not self.profile.include_j_courses and course.grade_level == "J":
            return False
        if not self.profile.include_pass_fail and course.final_grade_letter in ["P", "CR"]:
            return False
        # ... etc
        return True

    def _detect_advanced(self, course: Course) -> bool:
        # Check course flags and keywords against customer's markers
        raw_text = (course.raw_text or "").upper()
        flags = (course.flags or "").upper()
        name = (course.course_name or "").upper()

        # Check flags
        for flag in self.profile.advanced_course_flags:
            if f":{flag}" in flags or f":{flag}" in raw_text:
                return True

        # Check keywords
        for keyword in self.profile.advanced_course_keywords:
            if keyword.upper() in name or keyword.upper() in raw_text:
                return True

        return False

    def _get_weight_bonus(self, course: Course) -> float:
        if not course.is_advanced:
            return 0.0

        # Check minimum grade requirement
        if course.final_grade_numeric and course.final_grade_numeric < self.profile.minimum_grade_for_weight:
            return 0.0

        # Determine course type and return appropriate bonus
        # (simplified - would need more sophisticated detection)
        if "AP" in course.course_name.upper():
            return self.profile.weight_bonuses.get("AP", 0.0)
        if "HONORS" in course.course_name.upper():
            return self.profile.weight_bonuses.get("Honors", 0.0)
        # ... etc

        # Default to smallest non-zero weight if advanced but type unclear
        return min([v for v in self.profile.weight_bonuses.values() if v > 0], default=0.0)
```

---

## Review & Edit Interface

After calculation, customer sees:

### Summary View
```
Student: Aguilar, Alyssa Nicole
Calculated GPA: 4.018
Total Credits: 27.5
Courses Included: 29
Weighted Courses: 4
```

### Course-by-Course Breakdown (Table)
| Course | Grade | Credits | Base | Weight | QP | Include | Actions |
|--------|-------|---------|------|--------|----|---------|----|
| ENG 1 | 88 | 1.0 | 3.0 | 0.0 | 3.0 | ✅ | [Edit] [Exclude] |
| ENG 3:D | B | 1.0 | 3.0 | 1.0 | 4.0 | ✅ | [Edit] [Exclude] |
| PEITS | 99 | 1.0 | 4.0 | 0.0 | 4.0 | ✅ | [Edit] [Exclude] |
| ... | ... | ... | ... | ... | ... | ... | ... |

**Customer can:**
1. **Edit a course**: Change grade, credits, or weight
2. **Exclude a course**: Remove from GPA calculation
3. **Include an excluded course**: Add back to calculation
4. **Flag for review**: Mark course for manual verification
5. **Save changes**: Recalculate GPA with edits

### Edit Modal
```
Course: AP English 3
Grade: [85] ← editable
Credits: [1.0] ← editable
Is Advanced: [✓] ← checkbox
Weight Bonus: [1.0] ← dropdown (0, 0.5, 1.0)
Include in GPA: [✓] ← checkbox

[Cancel] [Save & Recalculate]
```

**When saved:**
- Store edit as `course_override` record
- Recalculate GPA with override applied
- Show "edited" indicator on course row
- Log who made the change and when

---

## Database Schema

### `gpa_calculation_profiles`
```sql
CREATE TABLE gpa_calculation_profiles (
  id UUID PRIMARY KEY,
  customer_id UUID NOT NULL,
  name VARCHAR(255),  -- "Default Profile"
  scale_type VARCHAR(50),  -- "weighted_4.0"
  grade_point_mappings JSONB,
  weight_bonuses JSONB,
  minimum_grade_for_weight INTEGER,
  course_inclusion_rules JSONB,
  advanced_course_markers JSONB,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  UNIQUE(customer_id)  -- One profile per customer
);
```

### `transcript_extractions`
```sql
CREATE TABLE transcript_extractions (
  id UUID PRIMARY KEY,
  customer_id UUID NOT NULL,
  profile_id UUID REFERENCES gpa_calculation_profiles(id),
  file_path TEXT,
  student_data JSONB,  -- Name, DOB, school, etc.
  raw_courses JSONB,  -- Courses extracted by Gemini
  calculated_gpa DECIMAL(5,3),
  total_quality_points DECIMAL(10,2),
  total_credits DECIMAL(10,2),
  courses_included INTEGER,
  weighted_courses INTEGER,
  created_at TIMESTAMP,
  created_by UUID
);
```

### `course_extractions`
```sql
CREATE TABLE course_extractions (
  id UUID PRIMARY KEY,
  transcript_id UUID REFERENCES transcript_extractions(id),
  course_name VARCHAR(255),
  course_code VARCHAR(50),
  final_grade_numeric DECIMAL(5,2),
  final_grade_letter VARCHAR(10),
  credits_attempted DECIMAL(5,2),
  credits_earned DECIMAL(5,2),
  semester_grades JSONB,
  flags VARCHAR(50),
  raw_text TEXT,
  school_year VARCHAR(20),
  grade_level VARCHAR(10),

  -- Calculated fields
  is_advanced BOOLEAN,
  base_points DECIMAL(5,2),
  weight_bonus DECIMAL(5,2),
  quality_points DECIMAL(10,2),
  include_in_gpa BOOLEAN,
  exclusion_reason TEXT,

  created_at TIMESTAMP
);
```

### `course_overrides`
```sql
CREATE TABLE course_overrides (
  id UUID PRIMARY KEY,
  course_extraction_id UUID REFERENCES course_extractions(id),
  transcript_id UUID REFERENCES transcript_extractions(id),

  -- Override fields (null = no override)
  override_grade DECIMAL(5,2),
  override_credits DECIMAL(5,2),
  override_is_advanced BOOLEAN,
  override_weight_bonus DECIMAL(5,2),
  override_include_in_gpa BOOLEAN,

  override_reason TEXT,
  created_at TIMESTAMP,
  created_by UUID
);
```

---

## API Endpoints

### Profile Management
```
POST   /api/profiles                    # Create GPA profile
GET    /api/profiles/:customerId        # Get customer's profile
PUT    /api/profiles/:profileId         # Update profile
```

### Transcript Processing
```
POST   /api/transcripts/upload          # Upload & parse transcript
GET    /api/transcripts/:id             # Get transcript results
GET    /api/transcripts/:id/courses     # Get course breakdown
```

### Course Review & Edit
```
PUT    /api/courses/:courseId/override  # Save course override
POST   /api/transcripts/:id/recalculate # Recalculate after edits
DELETE /api/courses/:courseId/override  # Remove override
```

---

## Implementation Phases

### Phase 1: Configuration System
- [ ] Build GPA profile data model
- [ ] Create profile configuration API
- [ ] Build simple admin UI for profile setup
- [ ] Test with current customer's rules

### Phase 2: Calculation Engine Refactor
- [ ] Extract current hardcoded logic into `GPACalculator` class
- [ ] Implement profile-driven calculation
- [ ] Add dynamic prompt generation
- [ ] Update Gemini integration to return raw data only
- [ ] Build validation to ensure no LLM math

### Phase 3: Course Extraction & Storage
- [ ] Design database schema
- [ ] Build course extraction storage
- [ ] Create API for transcript results
- [ ] Add course-level detail endpoints

### Phase 4: Review & Edit Interface
- [ ] Build course breakdown UI
- [ ] Implement override functionality
- [ ] Add recalculation after edits
- [ ] Store audit trail of changes

### Phase 5: Testing & Validation
- [ ] Test with multiple customer profiles
- [ ] Validate calculations against known results
- [ ] Performance testing with large transcripts
- [ ] Edge case handling

### Phase 6: Production Launch
- [ ] Migration plan for existing customer
- [ ] Documentation for profile setup
- [ ] Customer onboarding process
- [ ] Monitoring and alerting

---

## Key Benefits

1. **Customer Control**: Each school defines their own GPA methodology
2. **Consistency**: Same rules applied to all transcripts for a customer
3. **Reliability**: Backend calculations, not LLM math
4. **Transparency**: Full audit trail of how GPA was calculated
5. **Flexibility**: Easy to add new customers with different rules
6. **Correctability**: Customers can review and fix extraction errors
7. **Scalability**: Multi-tenant architecture ready for many customers

---

## Open Questions / Future Enhancements

1. **Multiple profiles per customer**: Do some schools need different rules for different scenarios?
2. **Profile templates**: Pre-built profiles for common GPA methodologies (Texas AAR, College Board, etc.)?
3. **Bulk processing**: Upload and process multiple transcripts at once?
4. **Reporting**: Generate summary reports across multiple transcripts?
5. **Version history**: Track changes to profiles over time?
6. **ML improvement**: Learn from corrections to improve extraction accuracy?
7. **Format detection**: Auto-detect transcript format and adjust parsing strategy?

---

## Success Metrics

- **Accuracy**: < 0.1 GPA point error rate after customer review
- **Extraction Success**: > 95% of transcripts parse successfully
- **Edit Rate**: < 10% of courses require manual correction
- **Time to Process**: < 30 seconds per transcript
- **Customer Satisfaction**: Customers trust the calculated GPA

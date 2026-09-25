# Card Fields

A school's `schools.card_fields` array is the only source of field keys. Extraction
is told to fill exactly these keys, and the pipeline drops anything else before
saving (`drop_unconfigured_fields` in `app/pipeline/enhancers/field_requirements.py`).
The review form and exports are built from the same list.

## Field entry

```json
{
  "key": "intended_sport",
  "label": "Intended Sport",
  "card_label": "What sport do you play?",
  "field_type": "text",
  "enabled": true,
  "required": false
}
```

- `key`: snake_case, unique per school. Use an existing canonical key when one fits
  (`cell`, `high_school`, `entry_term`, `student_type`...).
- `label`: what reviewers and export headers show.
- `card_label` (optional): the exact text printed on the card. Passed to Gemini so it
  can find the line when the label differs from the key.
- `field_type`: `text`, `select`, `checkbox`, `email`, `phone`, or `date`.
- `options`: required for `select`; rendered as a dropdown in review.
- `extract: false` (optional): review-only field that isn't on the card. It is left
  out of the extraction prompt and shows up blank for the reviewer to fill in.

## Adding a field for a school

```sql
update schools
set card_fields = card_fields || '[{"key":"intended_sport","label":"Intended Sport","card_label":"What sport do you play?","field_type":"text","enabled":true,"required":false}]'::jsonb
where id = '<school_id>';
```

Review-only dropdown (e.g. Student Type when the card has no checkbox):

```sql
update schools
set card_fields = card_fields || '[{"key":"student_type","label":"Student Type","field_type":"select","options":["Freshman","Transfer"],"extract":false,"enabled":true,"required":false}]'::jsonb
where id = '<school_id>';
```

After adding a field, upload one real card for that school and confirm the value
lands in the new field.

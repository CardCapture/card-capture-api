-- Discovered-field suggestions for the vision-only extraction path.
-- When the vision path reads a clearly-labeled field on a card that is not in
-- the school's configured card_fields, it is captured here so an admin can
-- accept it into card_fields later (Option C, discovery-as-suggestions).
-- See docai_removal_plan.md.

ALTER TABLE schools
ADD COLUMN IF NOT EXISTS suggested_card_fields jsonb NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN schools.suggested_card_fields IS
  'Fields discovered by the vision-only extraction path that are not yet in card_fields. Each entry: {key, label, field_type, sample_value}. Admin can promote these into card_fields.';

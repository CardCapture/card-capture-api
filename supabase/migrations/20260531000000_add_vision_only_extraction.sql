-- Vision-only extraction feature flag (DocAI removal). See docai_removal_plan.md.
-- When true, the extraction pipeline skips DocAI and uses Gemini vision with the
-- streamlined prompt. Defaults false so existing schools are unaffected.

ALTER TABLE schools
ADD COLUMN IF NOT EXISTS use_vision_only_extraction boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN schools.use_vision_only_extraction IS
  'When true, extraction pipeline skips DocAI and uses Gemini vision with the streamlined prompt. See docai_removal_plan.md.';

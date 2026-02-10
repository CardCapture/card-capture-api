-- Add explicit MFA exemption flag for shared accounts
ALTER TABLE user_mfa_settings
ADD COLUMN IF NOT EXISTS mfa_exempt BOOLEAN DEFAULT FALSE;

-- Add comment explaining the field
COMMENT ON COLUMN user_mfa_settings.mfa_exempt IS
'Set to TRUE to completely exempt user from MFA requirements. Used for shared accounts like admissions@mc.edu';

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_user_mfa_settings_mfa_exempt
ON user_mfa_settings(mfa_exempt)
WHERE mfa_exempt = TRUE;

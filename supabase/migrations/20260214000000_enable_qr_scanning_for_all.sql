-- Enable QR scanning for all existing schools
UPDATE public.schools SET enable_qr_scanning = true WHERE enable_qr_scanning = false;

-- Change default so new schools get QR scanning enabled automatically
ALTER TABLE public.schools ALTER COLUMN enable_qr_scanning SET DEFAULT true;

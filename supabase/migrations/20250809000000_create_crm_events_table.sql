-- Create crm_events table for storing CRM event templates
CREATE TABLE IF NOT EXISTS public.crm_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  school_id UUID NOT NULL,
  crm_event_id VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  event_date DATE NOT NULL,
  source VARCHAR(50) DEFAULT 'csv' CHECK (source IN ('csv', 'manual', 'api')),
  metadata JSONB DEFAULT '{}',
  last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Ensure CRM event IDs are unique per school
  CONSTRAINT unique_crm_event_per_school UNIQUE (school_id, crm_event_id)
);

-- Add indexes for performance
CREATE INDEX idx_crm_events_school_id ON public.crm_events(school_id);
CREATE INDEX idx_crm_events_crm_event_id ON public.crm_events(crm_event_id);
CREATE INDEX idx_crm_events_name ON public.crm_events(name);
CREATE INDEX idx_crm_events_event_date ON public.crm_events(event_date);

-- Add RLS policies (will be activated once profiles table exists)
ALTER TABLE public.crm_events ENABLE ROW LEVEL SECURITY;

-- Note: RLS policies will need to be added after profiles table is created
-- For now, we'll add a simple policy for testing
CREATE POLICY "Temporary allow all for testing" ON public.crm_events
  FOR ALL
  USING (true)
  WITH CHECK (true);

-- Create function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger to auto-update updated_at
CREATE TRIGGER update_crm_events_updated_at
  BEFORE UPDATE ON public.crm_events
  FOR EACH ROW
  EXECUTE FUNCTION update_updated_at_column();

-- Add comments for documentation
COMMENT ON TABLE public.crm_events IS 'Stores CRM event templates for mapping to CardCapture events';
COMMENT ON COLUMN public.crm_events.crm_event_id IS 'Unique identifier from the external CRM system';
COMMENT ON COLUMN public.crm_events.source IS 'How the event was created: csv, manual, or api';
COMMENT ON COLUMN public.crm_events.metadata IS 'Additional flexible data storage for future extensions';
COMMENT ON COLUMN public.crm_events.last_synced_at IS 'Last time this record was synchronized with external system';
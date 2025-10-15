# Card Capture Database Setup Guide

## Overview

You now have a simple, Docker-free setup to work with your Supabase databases directly. This guide covers connecting to staging/production databases for local development.

---

## Prerequisites

### Install PostgreSQL Client (psql)

The scripts use `psql` to connect to your databases. Install it with Homebrew:

```bash
brew install postgresql@16
# Add to PATH
echo 'export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Verify installation:
```bash
psql --version
```

---

## Quick Start

### 1. Connect to Database (Interactive)

The easiest way to connect:

```bash
cd /Users/kregboyd/Applications/card-capture-api
./db-connect.sh
```

This gives you an interactive menu to choose staging or production, then opens a PostgreSQL shell where you can run queries:

```sql
-- Example queries
\dt                           -- List all tables
\d cards                      -- Describe cards table
SELECT COUNT(*) FROM profiles; -- Count profiles
SELECT * FROM cards LIMIT 5;  -- Show recent cards
```

Exit the shell with `\q` or `Ctrl+D`.

---

### 2. Use Helper Functions

Load helper functions for quick operations:

```bash
cd /Users/kregboyd/Applications/card-capture-api
source db-helpers.sh
```

Now you can run commands like:

```bash
# List all tables
list-tables staging
list-tables prod

# Check migration status
migration-status staging

# Describe a table
describe-table cards staging

# Count rows
count-rows profiles staging

# Run a quick query
query-staging 'SELECT COUNT(*) FROM cards;'
```

---

### 3. Manage Migrations

Use the migration helper:

```bash
./db-migrate.sh
```

This provides an interactive menu for:
1. Creating new migrations
2. Listing pending migrations
3. Applying migrations to staging
4. Applying migrations to production (with safety checks)
5. Checking migration status

**Recommended workflow:**
1. Create migration: `./db-migrate.sh` → option 1
2. Edit the generated SQL file in `supabase/migrations/`
3. Test on staging: `./db-migrate.sh` → option 3
4. Verify it worked: `./db-migrate.sh` → option 5
5. Apply to production: `./db-migrate.sh` → option 4

---

## Direct Connection Strings

If you prefer to use your own tools (TablePlus, Postico, DBeaver, etc.):

### Staging
```
Host: db.ftlweumoajawitlszpqx.supabase.co
Port: 5432
Database: postgres
User: postgres
Password: 7b4Mk4tm43J.DKM
```

Full URL:
```
postgresql://postgres:7b4Mk4tm43J.DKM@db.ftlweumoajawitlszpqx.supabase.co:5432/postgres
```

### Production
```
Host: db.pkpcqmlswrwsefxqhfuf.supabase.co
Port: 5432
Database: postgres
User: postgres
Password: 7b4Mk4tm43J.DKM
```

Full URL:
```
postgresql://postgres:7b4Mk4tm43J.DKM@db.pkpcqmlswrwsefxqhfuf.supabase.co:5432/postgres
```

---

## Using Supabase CLI

You can also use the Supabase CLI to interact with remote databases:

### Link to Staging Project

```bash
cd /Users/kregboyd/Applications/card-capture-api
supabase link --project-ref ftlweumoajawitlszpqx --password 7b4Mk4tm43J.DKM
```

### Link to Production Project

```bash
supabase link --project-ref pkpcqmlswrwsefxqhfuf --password 7b4Mk4tm43J.DKM
```

### Useful Commands After Linking

```bash
# Pull remote schema to local
supabase db pull

# View differences between local and remote
supabase db diff

# Push migrations to remote
supabase db push

# Reset remote database (CAREFUL!)
supabase db reset --linked

# Open Supabase Studio for your project
supabase projects open
```

---

## Common Tasks

### Check Database Schema

```bash
source db-helpers.sh
list-tables staging
```

Or in psql:
```sql
\dt          -- List tables
\dv          -- List views
\df          -- List functions
\du          -- List users/roles
```

### Run a SQL File

```bash
psql "postgresql://postgres:7b4Mk4tm43J.DKM@db.ftlweumoajawitlszpqx.supabase.co:5432/postgres" -f myfile.sql
```

### Export Schema/Data

```bash
# Export schema only
pg_dump "postgresql://postgres:7b4Mk4tm43J.DKM@db.ftlweumoajawitlszpqx.supabase.co:5432/postgres" --schema-only > schema.sql

# Export specific table
pg_dump "postgresql://postgres:7b4Mk4tm43J.DKM@db.ftlweumoajawitlszpqx.supabase.co:5432/postgres" --table=cards > cards.sql

# Export data from a table
pg_dump "postgresql://postgres:7b4Mk4tm43J.DKM@db.ftlweumoajawitlszpqx.supabase.co:5432/postgres" --data-only --table=profiles > profiles_data.sql
```

### Investigate Issues

```bash
# Check recent errors in a table
query-staging "SELECT * FROM audit_log WHERE level = 'error' ORDER BY created_at DESC LIMIT 10;"

# Check user profiles
query-staging "SELECT id, email, role, school_id FROM profiles WHERE email LIKE '%@example.com%';"

# Check processing jobs
query-staging "SELECT id, status, created_at FROM bulk_uploads WHERE status = 'failed' ORDER BY created_at DESC LIMIT 5;"
```

---

## Python Scripts with Direct DB Access

Your existing Python scripts can use the connection strings directly:

```python
import psycopg2

# Staging connection
conn = psycopg2.connect(
    "postgresql://postgres:7b4Mk4tm43J.DKM@db.ftlweumoajawitlszpqx.supabase.co:5432/postgres"
)
cursor = conn.cursor()
cursor.execute("SELECT * FROM profiles LIMIT 5")
print(cursor.fetchall())
```

Or use the environment variables already in your `.env`:

```python
import os
import psycopg2

conn = psycopg2.connect(os.getenv("DATABASE_URL_STAGING"))
```

---

## Safety Tips

1. **Always test on staging first** - Never run untested queries on production
2. **Use transactions** - Wrap risky operations in `BEGIN; ... ROLLBACK;` to test first
3. **Backup before migrations** - Use `supabase db dump` before major changes
4. **Use WHERE clauses** - Never run `DELETE` or `UPDATE` without a WHERE clause
5. **Check row counts** - Before deleting, run a SELECT COUNT(*) with the same WHERE clause

### Safe Query Pattern

```sql
-- 1. Check what you're about to modify
BEGIN;
SELECT * FROM cards WHERE status = 'draft' LIMIT 10;

-- 2. See how many rows will be affected
SELECT COUNT(*) FROM cards WHERE status = 'draft';

-- 3. Make the change
UPDATE cards SET status = 'pending' WHERE status = 'draft';

-- 4. Verify the change
SELECT * FROM cards WHERE status = 'pending' LIMIT 10;

-- 5. Commit if it looks good, or rollback if not
COMMIT;  -- or ROLLBACK;
```

---

## Troubleshooting

### "Connection refused"
- Check your internet connection
- Verify the database URL is correct
- Check Supabase dashboard to ensure database is running

### "psql: command not found"
- Install PostgreSQL client: `brew install postgresql@16`
- Add to PATH: `export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"`

### "Permission denied"
- Ensure you're using the correct password
- Check that your IP is allowed in Supabase dashboard (usually all IPs are allowed by default)

### "Migrations not applying"
- Check SQL syntax in your migration file
- Ensure migrations are in `supabase/migrations/` directory
- Check migration status: `./db-migrate.sh` → option 5

---

## Switching to Local Development (Optional)

If you later want to use local Supabase with Docker:

1. Install Docker Desktop: https://www.docker.com/products/docker-desktop
2. Start Docker
3. Run: `cd card-capture-api && supabase start`
4. Connect to local DB: `postgresql://postgres:postgres@localhost:54322/postgres`
5. Access Supabase Studio: http://localhost:54323

Local development is great for:
- Offline work
- Testing destructive operations
- Rapid iteration without network latency

---

## Summary of Files Created

```
card-capture-api/
├── db-connect.sh       # Interactive database connection tool
├── db-helpers.sh       # Helper functions for quick queries
├── db-migrate.sh       # Migration management tool
└── DB_SETUP_README.md  # This file
```

Make them executable if needed:
```bash
chmod +x db-connect.sh db-helpers.sh db-migrate.sh
```

---

## Quick Reference Commands

```bash
# Connect to database
./db-connect.sh

# Load helper functions
source db-helpers.sh

# Manage migrations
./db-migrate.sh

# Quick query
query-staging 'SELECT COUNT(*) FROM cards;'

# List tables
list-tables staging

# Check migrations
migration-status staging
```

---

**You're all set!** You now have a simple, Docker-free workflow for working with your Supabase databases. Start with staging, test thoroughly, then carefully apply changes to production.

Need help? Check the troubleshooting section above or refer to the Supabase docs: https://supabase.com/docs

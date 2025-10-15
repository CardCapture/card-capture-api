#!/bin/bash
# Migration helper script for Card Capture

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Database connection strings (using Session Pooler - IPv4 compatible)
STAGING_DB="postgresql://postgres.ftlweumoajawitlszpqx:7b4Mk4tm43J.DKM@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
PROD_DB="postgresql://postgres.pkpcqmlswrwsefxqhfuf:7b4Mk4tm43J.DKM@aws-0-us-east-2.pooler.supabase.com:5432/postgres"

echo -e "${YELLOW}Card Capture Migration Tool${NC}"
echo "============================"
echo ""
echo "What would you like to do?"
echo "1) Create new migration"
echo "2) List pending migrations"
echo "3) Run migrations on STAGING"
echo "4) Run migrations on PRODUCTION ${RED}[CAREFUL!]${NC}"
echo "5) Check migration status"
echo "6) Rollback last migration (manual SQL)"
echo ""
read -p "Enter choice [1-6]: " choice

case $choice in
    1)
        read -p "Migration name (e.g., add_user_column): " name
        timestamp=$(date +%Y%m%d%H%M%S)
        filename="supabase/migrations/${timestamp}_${name}.sql"
        touch "$filename"
        echo -e "${GREEN}Created: $filename${NC}"
        echo "-- Migration: $name" > "$filename"
        echo "-- Created: $(date)" >> "$filename"
        echo "" >> "$filename"
        echo "-- Add your SQL here" >> "$filename"
        echo ""
        echo "Edit this file and add your SQL, then run option 3 to apply to staging"
        ;;

    2)
        echo -e "${YELLOW}Recent migration files:${NC}"
        ls -lt supabase/migrations/ | head -10
        ;;

    3)
        echo -e "${GREEN}Running migrations on STAGING...${NC}"
        cd supabase && supabase db push --db-url "$STAGING_DB" || {
            echo -e "${RED}Migration failed. Check the SQL syntax.${NC}"
            exit 1
        }
        echo -e "${GREEN}✓ Migrations applied to STAGING${NC}"
        ;;

    4)
        echo -e "${RED}⚠️  WARNING: PRODUCTION DATABASE ⚠️${NC}"
        echo "This will run migrations on PRODUCTION!"
        read -p "Type 'APPLY TO PRODUCTION' to confirm: " confirm
        if [ "$confirm" = "APPLY TO PRODUCTION" ]; then
            echo -e "${YELLOW}Running migrations on PRODUCTION...${NC}"
            cd supabase && supabase db push --db-url "$PROD_DB" || {
                echo -e "${RED}Migration failed. Check the SQL syntax.${NC}"
                exit 1
            }
            echo -e "${GREEN}✓ Migrations applied to PRODUCTION${NC}"
        else
            echo "Cancelled."
        fi
        ;;

    5)
        echo "Select environment:"
        echo "1) Staging"
        echo "2) Production"
        read -p "Choice: " env_choice

        DB=$STAGING_DB
        ENV_NAME="STAGING"
        if [ "$env_choice" = "2" ]; then
            DB=$PROD_DB
            ENV_NAME="PRODUCTION"
        fi

        echo -e "${YELLOW}Migration status on $ENV_NAME:${NC}"
        psql "$DB" -c "SELECT version, name FROM supabase_migrations.schema_migrations ORDER BY version DESC LIMIT 20;" 2>/dev/null || {
            echo "Checking migrations table..."
            psql "$DB" -c "SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 20;" 2>/dev/null || {
                echo "Could not find migrations table. Migrations may not be initialized."
            }
        }
        ;;

    6)
        echo -e "${YELLOW}Rollback requires manual SQL.${NC}"
        echo "To rollback a migration:"
        echo "1. Connect to the database: ./db-connect.sh"
        echo "2. Write inverse SQL (e.g., DROP TABLE if you created one)"
        echo "3. Run: DELETE FROM supabase_migrations.schema_migrations WHERE version = 'YYYYMMDDHHMMSS';"
        ;;

    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

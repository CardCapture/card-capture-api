#!/bin/bash
# Database helper commands for quick operations

# Load environment variables
source .env

# Database connection strings (using Session Pooler - IPv4 compatible)
STAGING_DB="postgresql://postgres.ftlweumoajawitlszpqx:7b4Mk4tm43J.DKM@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
PROD_DB="postgresql://postgres.pkpcqmlswrwsefxqhfuf:7b4Mk4tm43J.DKM@aws-0-us-east-2.pooler.supabase.com:5432/postgres"

# Default to staging
DB_URL="${DATABASE_URL_STAGING}"

# Function to run a query on staging
query-staging() {
    echo "Running on STAGING..."
    psql "$STAGING_DB" -c "$1"
}

# Function to run a query on production (requires confirmation)
query-prod() {
    echo "⚠️  PRODUCTION DATABASE"
    read -p "Confirm running on PROD (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        psql "$PROD_DB" -c "$1"
    fi
}

# Function to list all tables
list-tables() {
    ENV=${1:-staging}
    DB=$STAGING_DB
    if [ "$ENV" = "prod" ]; then
        DB=$PROD_DB
    fi
    echo "Tables in $ENV:"
    psql "$DB" -c "\dt"
}

# Function to check migration status
migration-status() {
    ENV=${1:-staging}
    DB=$STAGING_DB
    if [ "$ENV" = "prod" ]; then
        DB=$PROD_DB
    fi
    echo "Migration status in $ENV:"
    psql "$DB" -c "SELECT * FROM supabase_migrations.schema_migrations ORDER BY version DESC LIMIT 10;"
}

# Function to describe a table
describe-table() {
    TABLE=$1
    ENV=${2:-staging}
    DB=$STAGING_DB
    if [ "$ENV" = "prod" ]; then
        DB=$PROD_DB
    fi
    echo "Structure of $TABLE in $ENV:"
    psql "$DB" -c "\d $TABLE"
}

# Function to count rows in a table
count-rows() {
    TABLE=$1
    ENV=${2:-staging}
    DB=$STAGING_DB
    if [ "$ENV" = "prod" ]; then
        DB=$PROD_DB
    fi
    psql "$DB" -c "SELECT COUNT(*) FROM $TABLE;"
}

# Show available commands
show-help() {
    echo "Available commands:"
    echo "  source db-helpers.sh          # Load these functions"
    echo "  query-staging 'SQL'           # Run query on staging"
    echo "  query-prod 'SQL'              # Run query on production (with confirmation)"
    echo "  list-tables [staging|prod]    # List all tables"
    echo "  migration-status [staging|prod] # Check migration status"
    echo "  describe-table TABLE [staging|prod] # Show table structure"
    echo "  count-rows TABLE [staging|prod]     # Count rows in table"
    echo ""
    echo "Examples:"
    echo "  query-staging 'SELECT * FROM profiles LIMIT 5;'"
    echo "  list-tables staging"
    echo "  describe-table cards"
    echo "  count-rows users staging"
}

# If script is run directly (not sourced), show help
if [ "${BASH_SOURCE[0]}" -ef "$0" ]; then
    show-help
fi

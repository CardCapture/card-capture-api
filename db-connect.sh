#!/bin/bash
# Quick database connection script for Card Capture

# Colors for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Card Capture Database Connection${NC}"
echo "=================================="
echo ""
echo "Select environment:"
echo "1) Staging (ftlweumoajawitlszpqx)"
echo "2) Production (pkpcqmlswrwsefxqhfuf) ${RED}[CAREFUL!]${NC}"
echo ""
read -p "Enter choice [1-2]: " choice

case $choice in
    1)
        echo -e "${GREEN}Connecting to STAGING (via Session Pooler)...${NC}"
        export PGPASSWORD="7b4Mk4tm43J.DKM"
        psql "postgresql://postgres.ftlweumoajawitlszpqx:7b4Mk4tm43J.DKM@aws-0-us-east-1.pooler.supabase.com:5432/postgres"
        ;;
    2)
        echo -e "${RED}⚠️  WARNING: PRODUCTION DATABASE ⚠️${NC}"
        read -p "Are you sure? (yes/no): " confirm
        if [ "$confirm" = "yes" ]; then
            export PGPASSWORD="7b4Mk4tm43J.DKM"
            psql "postgresql://postgres.pkpcqmlswrwsefxqhfuf:7b4Mk4tm43J.DKM@aws-0-us-east-2.pooler.supabase.com:5432/postgres"
        else
            echo "Cancelled."
        fi
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

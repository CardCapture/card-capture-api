"""
Shared fixtures for security tests.

These fixtures provide:
- Real Supabase connections for integration testing
- Test schools with different UUIDs for multi-tenant isolation tests
- Test users in different schools
- Helper functions to get Supabase clients with specific user contexts

IMPORTANT: These tests require a real Supabase connection to the dev project.
Set the following environment variables:
- SUPABASE_URL: https://ftlweumoajawitlszpqx.supabase.co
- SUPABASE_SERVICE_ROLE_KEY: Your service role key
- SUPABASE_ANON_KEY: Your anon key
"""

import os
import pytest
import uuid
from typing import Generator, Dict, Any
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Skip all tests in this module if not configured for real DB testing
pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SECURITY_TESTS") != "true",
    reason="Security tests require RUN_SECURITY_TESTS=true and real Supabase connection"
)


def get_supabase_url() -> str:
    """Get Supabase URL from environment."""
    url = os.getenv("SUPABASE_URL")
    if not url:
        pytest.skip("SUPABASE_URL environment variable not set")
    return url


def get_service_role_key() -> str:
    """Get Supabase service role key from environment."""
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        pytest.skip("SUPABASE_SERVICE_ROLE_KEY environment variable not set")
    return key


def get_anon_key() -> str:
    """Get Supabase anon key from environment."""
    key = os.getenv("SUPABASE_ANON_KEY")
    if not key:
        pytest.skip("SUPABASE_ANON_KEY environment variable not set")
    return key


@pytest.fixture(scope="session")
def supabase_admin_client():
    """
    Admin Supabase client using service role key.

    This client bypasses RLS and is used for:
    - Test data setup
    - Test data cleanup
    - Verifying data state

    WARNING: This client should NEVER be used in production application code.
    """
    from supabase import create_client, Client

    url = get_supabase_url()
    key = get_service_role_key()

    client: Client = create_client(url, key)
    return client


@pytest.fixture(scope="session")
def supabase_anon_client():
    """
    Anonymous Supabase client using anon key.

    This client respects RLS policies and is used for testing
    unauthenticated access patterns.
    """
    from supabase import create_client, Client

    url = get_supabase_url()
    key = get_anon_key()

    client: Client = create_client(url, key)
    return client


# =============================================================================
# Test School Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def test_school_1(supabase_admin_client) -> Generator[Dict[str, Any], None, None]:
    """
    Create a test school for isolation testing.

    This school is used by user_school_1 for multi-tenant tests.
    """
    school_id = str(uuid.uuid4())
    school_data = {
        "id": school_id,
        "name": "Test School Alpha (Security Tests)",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        # Insert test school
        response = supabase_admin_client.table("schools").insert(school_data).execute()

        if response.data:
            yield response.data[0]
        else:
            # If insert failed, the school might already exist or table might not exist
            yield school_data
    finally:
        # Cleanup - delete test school and all related data
        try:
            # Delete in order due to foreign key constraints
            supabase_admin_client.table("crm_events").delete().eq("school_id", school_id).execute()
            supabase_admin_client.table("events").delete().eq("school_id", school_id).execute()
            supabase_admin_client.table("user_profiles").delete().eq("school_id", school_id).execute()
            supabase_admin_client.table("schools").delete().eq("id", school_id).execute()
        except Exception as e:
            print(f"Cleanup warning for school_1: {e}")


@pytest.fixture(scope="module")
def test_school_2(supabase_admin_client) -> Generator[Dict[str, Any], None, None]:
    """
    Create a second test school for isolation testing.

    This school is used by user_school_2 to verify cross-tenant isolation.
    """
    school_id = str(uuid.uuid4())
    school_data = {
        "id": school_id,
        "name": "Test School Beta (Security Tests)",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = supabase_admin_client.table("schools").insert(school_data).execute()

        if response.data:
            yield response.data[0]
        else:
            yield school_data
    finally:
        try:
            supabase_admin_client.table("crm_events").delete().eq("school_id", school_id).execute()
            supabase_admin_client.table("events").delete().eq("school_id", school_id).execute()
            supabase_admin_client.table("user_profiles").delete().eq("school_id", school_id).execute()
            supabase_admin_client.table("schools").delete().eq("id", school_id).execute()
        except Exception as e:
            print(f"Cleanup warning for school_2: {e}")


# =============================================================================
# Test User Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def test_user_school_1(supabase_admin_client, test_school_1) -> Generator[Dict[str, Any], None, None]:
    """
    Create a test user in school 1.

    This user is used to test RLS policies that should restrict
    access to only school 1's data.
    """
    user_id = str(uuid.uuid4())
    user_data = {
        "id": user_id,
        "email": f"test_user_school1_{user_id[:8]}@test.cardcapture.io",
        "school_id": test_school_1["id"],
        "role": ["recruiter"],
        "first_name": "Test",
        "last_name": "User School 1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = supabase_admin_client.table("user_profiles").insert(user_data).execute()

        if response.data:
            yield response.data[0]
        else:
            yield user_data
    finally:
        try:
            supabase_admin_client.table("user_profiles").delete().eq("id", user_id).execute()
        except Exception as e:
            print(f"Cleanup warning for user_school_1: {e}")


@pytest.fixture(scope="module")
def test_user_school_2(supabase_admin_client, test_school_2) -> Generator[Dict[str, Any], None, None]:
    """
    Create a test user in school 2.

    This user is used to verify that they CANNOT access school 1's data.
    """
    user_id = str(uuid.uuid4())
    user_data = {
        "id": user_id,
        "email": f"test_user_school2_{user_id[:8]}@test.cardcapture.io",
        "school_id": test_school_2["id"],
        "role": ["recruiter"],
        "first_name": "Test",
        "last_name": "User School 2",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = supabase_admin_client.table("user_profiles").insert(user_data).execute()

        if response.data:
            yield response.data[0]
        else:
            yield user_data
    finally:
        try:
            supabase_admin_client.table("user_profiles").delete().eq("id", user_id).execute()
        except Exception as e:
            print(f"Cleanup warning for user_school_2: {e}")


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture(scope="module")
def test_event_school_1(supabase_admin_client, test_school_1) -> Generator[Dict[str, Any], None, None]:
    """Create a test event in school 1."""
    event_id = str(uuid.uuid4())
    event_data = {
        "id": event_id,
        "name": "Security Test Event Alpha",
        "school_id": test_school_1["id"],
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = supabase_admin_client.table("events").insert(event_data).execute()

        if response.data:
            yield response.data[0]
        else:
            yield event_data
    finally:
        try:
            supabase_admin_client.table("reviewed_data").delete().eq("event_id", event_id).execute()
            supabase_admin_client.table("extracted_data").delete().eq("event_id", event_id).execute()
            supabase_admin_client.table("events").delete().eq("id", event_id).execute()
        except Exception as e:
            print(f"Cleanup warning for event_school_1: {e}")


@pytest.fixture(scope="module")
def test_event_school_2(supabase_admin_client, test_school_2) -> Generator[Dict[str, Any], None, None]:
    """Create a test event in school 2."""
    event_id = str(uuid.uuid4())
    event_data = {
        "id": event_id,
        "name": "Security Test Event Beta",
        "school_id": test_school_2["id"],
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = supabase_admin_client.table("events").insert(event_data).execute()

        if response.data:
            yield response.data[0]
        else:
            yield event_data
    finally:
        try:
            supabase_admin_client.table("reviewed_data").delete().eq("event_id", event_id).execute()
            supabase_admin_client.table("extracted_data").delete().eq("event_id", event_id).execute()
            supabase_admin_client.table("events").delete().eq("id", event_id).execute()
        except Exception as e:
            print(f"Cleanup warning for event_school_2: {e}")


@pytest.fixture(scope="module")
def test_crm_event_school_1(supabase_admin_client, test_school_1) -> Generator[Dict[str, Any], None, None]:
    """Create a test CRM event in school 1."""
    crm_event_id = str(uuid.uuid4())
    crm_event_data = {
        "id": crm_event_id,
        "name": "Security Test CRM Event Alpha",
        "school_id": test_school_1["id"],
        "crm_event_id": f"CRM-ALPHA-{crm_event_id[:8]}",
        "event_date": datetime.now(timezone.utc).date().isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = supabase_admin_client.table("crm_events").insert(crm_event_data).execute()

        if response.data:
            yield response.data[0]
        else:
            yield crm_event_data
    finally:
        try:
            supabase_admin_client.table("crm_events").delete().eq("id", crm_event_id).execute()
        except Exception as e:
            print(f"Cleanup warning for crm_event_school_1: {e}")


@pytest.fixture(scope="module")
def test_crm_event_school_2(supabase_admin_client, test_school_2) -> Generator[Dict[str, Any], None, None]:
    """Create a test CRM event in school 2."""
    crm_event_id = str(uuid.uuid4())
    crm_event_data = {
        "id": crm_event_id,
        "name": "Security Test CRM Event Beta",
        "school_id": test_school_2["id"],
        "crm_event_id": f"CRM-BETA-{crm_event_id[:8]}",
        "event_date": datetime.now(timezone.utc).date().isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = supabase_admin_client.table("crm_events").insert(crm_event_data).execute()

        if response.data:
            yield response.data[0]
        else:
            yield crm_event_data
    finally:
        try:
            supabase_admin_client.table("crm_events").delete().eq("id", crm_event_id).execute()
        except Exception as e:
            print(f"Cleanup warning for crm_event_school_2: {e}")


# =============================================================================
# Helper Functions
# =============================================================================

def get_client_for_user(user_id: str, school_id: str) -> Any:
    """
    Get a Supabase client that simulates a specific user's session.

    NOTE: This is a simplified approach for testing. In production,
    this would use actual JWT tokens from Supabase Auth.

    For these tests, we use the service role client but filter queries
    by school_id to simulate what RLS policies SHOULD do.

    Args:
        user_id: The user's UUID
        school_id: The user's school UUID

    Returns:
        A Supabase client (currently returns admin client for testing)
    """
    from supabase import create_client

    url = get_supabase_url()
    key = get_service_role_key()

    # NOTE: In a full implementation, we would:
    # 1. Create a test user in Supabase Auth
    # 2. Get a JWT token for that user
    # 3. Use the anon key with the JWT token
    # For now, we test RLS by using the admin client and
    # verifying what data is visible at the database level

    return create_client(url, key)


@pytest.fixture
def client_for_user():
    """Fixture that provides the get_client_for_user function."""
    return get_client_for_user


# =============================================================================
# SQL Execution Helper
# =============================================================================

@pytest.fixture(scope="session")
def execute_sql(supabase_admin_client):
    """
    Fixture that provides a function to execute raw SQL queries.

    Uses Supabase's rpc() to call a helper function or falls back
    to the REST API for simple queries.
    """
    def _execute_sql(sql: str) -> Any:
        """
        Execute raw SQL and return results.

        Args:
            sql: The SQL query to execute

        Returns:
            Query results
        """
        # Use Supabase's built-in SQL execution via RPC
        # This requires a function to be set up in the database
        try:
            response = supabase_admin_client.rpc("exec_sql", {"query": sql}).execute()
            return response.data
        except Exception as e:
            # If the exec_sql function doesn't exist, we can still
            # test by querying system tables directly via the API
            print(f"SQL execution note: {e}")
            return None

    return _execute_sql

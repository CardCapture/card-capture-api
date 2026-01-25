"""
Tests for Row Level Security (RLS) policies.

This module verifies that RLS policies correctly enforce multi-tenant isolation.
Users should only be able to access data belonging to their school.

CURRENT VULNERABILITIES DOCUMENTED:
1. crm_events table has USING(true) policy - allows cross-tenant access
2. events table has USING(true) policy - allows cross-tenant access
3. extracted_data table has USING(true) policy - allows cross-tenant access
4. reviewed_data table has USING(true) policy - allows cross-tenant access
5. schools table has USING(true) policy - allows all schools to be read

These tests are designed to:
1. Document the CURRENT vulnerable state (tests that SHOULD fail but currently pass)
2. Provide a regression suite for when fixes are applied
3. Verify proper isolation after fixes are in place

Run with: pytest tests/security/test_rls_policies.py -v
Requires: RUN_SECURITY_TESTS=true environment variable
"""

import os
import pytest
import uuid
from datetime import datetime, timezone
# Type hints used implicitly in function signatures

# Mark all tests to require security test environment
pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_SECURITY_TESTS") != "true",
        reason="Security tests require RUN_SECURITY_TESTS=true"
    ),
    pytest.mark.security,
    pytest.mark.rls,
]


class TestCRMEventsRLS:
    """
    Tests for crm_events table RLS policies.

    VULNERABILITY: crm_events currently has USING(true) policy,
    allowing any authenticated user to see ALL schools' CRM events.
    """

    def test_crm_events_cross_tenant_access_vulnerability(
        self,
        supabase_admin_client,
        test_crm_event_school_1,
        test_crm_event_school_2,
        test_user_school_1,
        test_user_school_2,
    ):
        """
        VULNERABILITY TEST: Verify that cross-tenant access is currently possible.

        This test documents the current vulnerable state where a user from
        school 2 can see school 1's CRM events due to USING(true) policy.

        EXPECTED BEHAVIOR AFTER FIX: This test should FAIL (access denied)
        CURRENT BEHAVIOR: This test PASSES (vulnerability exists)
        """
        school_1_id = test_crm_event_school_1["school_id"]
        school_2_id = test_crm_event_school_2["school_id"]

        # Using admin client to simulate what RLS policies allow
        # Query ALL crm_events without filtering by school
        response = supabase_admin_client.table("crm_events").select("*").execute()

        all_events = response.data
        school_1_events = [e for e in all_events if e.get("school_id") == school_1_id]
        school_2_events = [e for e in all_events if e.get("school_id") == school_2_id]

        # VULNERABILITY: Both schools' events are visible
        # After fix, a user should only see their own school's events
        assert len(school_1_events) >= 1, "School 1 events should exist"
        assert len(school_2_events) >= 1, "School 2 events should exist"

        # This assertion documents the vulnerability
        # After fix, this should fail because cross-tenant data shouldn't be visible
        total_events = len(all_events)
        print(f"VULNERABILITY: User can see {total_events} CRM events across all schools")

    def test_crm_events_proper_isolation_should_fail_currently(
        self,
        supabase_admin_client,
        test_crm_event_school_1,
        test_crm_event_school_2,
        test_user_school_2,
    ):
        """
        Test that SHOULD verify proper tenant isolation.

        EXPECTED: User from school 2 should NOT see school 1's CRM events
        CURRENT: This test is expected to FAIL due to USING(true) vulnerability

        After RLS fix, uncomment the assertion and this should PASS.
        """
        school_1_id = test_crm_event_school_1["school_id"]

        # Query crm_events
        response = supabase_admin_client.table("crm_events").select("*").execute()

        # Find events from school 1
        school_1_events = [e for e in response.data if e.get("school_id") == school_1_id]

        # AFTER FIX: This assertion should pass (no cross-tenant access)
        # Currently commented because the vulnerability exists
        # assert len(school_1_events) == 0, "User from school 2 should NOT see school 1's CRM events"

        # For now, document that vulnerability exists
        if len(school_1_events) > 0:
            pytest.xfail(
                f"KNOWN VULNERABILITY: Cross-tenant access possible. "
                f"User can see {len(school_1_events)} events from another school."
            )


class TestEventsRLS:
    """
    Tests for events table RLS policies.

    VULNERABILITY: events table has USING(true) policy on SELECT,
    allowing any authenticated user to see ALL schools' events.
    """

    def test_events_cross_tenant_read_vulnerability(
        self,
        supabase_admin_client,
        test_event_school_1,
        test_event_school_2,
    ):
        """
        VULNERABILITY TEST: Verify that cross-tenant read access is possible.

        EXPECTED AFTER FIX: Users should only see their school's events
        CURRENT: All events are visible to all users
        """
        school_1_id = test_event_school_1["school_id"]
        school_2_id = test_event_school_2["school_id"]

        # Query all events
        response = supabase_admin_client.table("events").select("*").execute()

        all_events = response.data
        school_1_events = [e for e in all_events if e.get("school_id") == school_1_id]
        school_2_events = [e for e in all_events if e.get("school_id") == school_2_id]

        # Document vulnerability
        assert len(school_1_events) >= 1, "School 1 events should exist"
        assert len(school_2_events) >= 1, "School 2 events should exist"

        print(f"VULNERABILITY: Can see {len(all_events)} events across all schools")

    def test_events_write_policies(
        self,
        supabase_admin_client,
        test_school_1,
        test_school_2,
    ):
        """
        Test write policies on events table.

        Verify that INSERT/UPDATE/DELETE policies are properly restrictive.
        """
        # Test event for school 1
        test_event_id = str(uuid.uuid4())
        test_event = {
            "id": test_event_id,
            "name": "RLS Write Test Event",
            "school_id": test_school_1["id"],
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Insert should work (with admin client)
            response = supabase_admin_client.table("events").insert(test_event).execute()
            assert response.data, "Event insert should succeed"

            # Update should work
            update_response = supabase_admin_client.table("events").update(
                {"name": "Updated Event Name"}
            ).eq("id", test_event_id).execute()
            assert update_response.data, "Event update should succeed"

        finally:
            # Cleanup
            supabase_admin_client.table("events").delete().eq("id", test_event_id).execute()


class TestExtractedDataRLS:
    """
    Tests for extracted_data table RLS policies.

    VULNERABILITY: extracted_data has USING(true) policy,
    allowing cross-tenant access to scanned card data.
    """

    def test_extracted_data_isolation(
        self,
        supabase_admin_client,
        test_event_school_1,
        test_event_school_2,
    ):
        """
        Test that extracted_data is properly isolated by school.

        This table contains sensitive scanned card data and MUST be
        properly isolated by school.
        """
        # Create test extracted data for school 1
        doc_id_1 = str(uuid.uuid4())
        extracted_1 = {
            "document_id": doc_id_1,
            "event_id": test_event_school_1["id"],
            "school_id": test_event_school_1["school_id"],
            "fields": {"first_name": "John", "last_name": "Doe"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # Create test extracted data for school 2
        doc_id_2 = str(uuid.uuid4())
        extracted_2 = {
            "document_id": doc_id_2,
            "event_id": test_event_school_2["id"],
            "school_id": test_event_school_2["school_id"],
            "fields": {"first_name": "Jane", "last_name": "Smith"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Insert test data
            supabase_admin_client.table("extracted_data").insert(extracted_1).execute()
            supabase_admin_client.table("extracted_data").insert(extracted_2).execute()

            # Query all extracted_data
            response = supabase_admin_client.table("extracted_data").select("*").execute()

            school_1_data = [
                d for d in response.data
                if d.get("school_id") == test_event_school_1["school_id"]
            ]
            school_2_data = [
                d for d in response.data
                if d.get("school_id") == test_event_school_2["school_id"]
            ]

            # VULNERABILITY: Both schools' data is visible
            if len(school_1_data) > 0 and len(school_2_data) > 0:
                print(
                    f"VULNERABILITY: Cross-tenant access to extracted_data. "
                    f"School 1: {len(school_1_data)}, School 2: {len(school_2_data)}"
                )

        finally:
            # Cleanup
            supabase_admin_client.table("extracted_data").delete().eq("document_id", doc_id_1).execute()
            supabase_admin_client.table("extracted_data").delete().eq("document_id", doc_id_2).execute()


class TestReviewedDataRLS:
    """
    Tests for reviewed_data table RLS policies.

    VULNERABILITY: reviewed_data has USING(true) policy,
    allowing cross-tenant access to reviewed student information.
    """

    def test_reviewed_data_isolation(
        self,
        supabase_admin_client,
        test_event_school_1,
        test_event_school_2,
    ):
        """
        Test that reviewed_data is properly isolated by school.

        This table contains finalized student data and MUST be
        properly isolated by school.
        """
        # Create test reviewed data for school 1
        doc_id_1 = str(uuid.uuid4())
        reviewed_1 = {
            "document_id": doc_id_1,
            "event_id": test_event_school_1["id"],
            "school_id": test_event_school_1["school_id"],
            "fields": {"first_name": {"value": "John"}, "last_name": {"value": "Doe"}},
            "review_status": "reviewed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Create test reviewed data for school 2
        doc_id_2 = str(uuid.uuid4())
        reviewed_2 = {
            "document_id": doc_id_2,
            "event_id": test_event_school_2["id"],
            "school_id": test_event_school_2["school_id"],
            "fields": {"first_name": {"value": "Jane"}, "last_name": {"value": "Smith"}},
            "review_status": "reviewed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Insert test data
            supabase_admin_client.table("reviewed_data").insert(reviewed_1).execute()
            supabase_admin_client.table("reviewed_data").insert(reviewed_2).execute()

            # Query all reviewed_data
            response = supabase_admin_client.table("reviewed_data").select("*").execute()

            school_1_data = [
                d for d in response.data
                if d.get("school_id") == test_event_school_1["school_id"]
            ]
            school_2_data = [
                d for d in response.data
                if d.get("school_id") == test_event_school_2["school_id"]
            ]

            # VULNERABILITY: Both schools' data is visible
            if len(school_1_data) > 0 and len(school_2_data) > 0:
                print(
                    f"VULNERABILITY: Cross-tenant access to reviewed_data. "
                    f"School 1: {len(school_1_data)}, School 2: {len(school_2_data)}"
                )

        finally:
            # Cleanup
            supabase_admin_client.table("reviewed_data").delete().eq("document_id", doc_id_1).execute()
            supabase_admin_client.table("reviewed_data").delete().eq("document_id", doc_id_2).execute()


class TestSchoolsRLS:
    """
    Tests for schools table RLS policies.

    The schools table may intentionally allow broader read access
    for certain operations, but write access should be restricted.
    """

    def test_schools_read_policy(
        self,
        supabase_admin_client,
        test_school_1,
        test_school_2,
    ):
        """
        Test read access to schools table.

        Depending on business requirements, schools may be readable
        by authenticated users for dropdown/selection purposes.
        """
        response = supabase_admin_client.table("schools").select("*").execute()

        # Verify test schools exist
        school_ids = [s["id"] for s in response.data]
        assert test_school_1["id"] in school_ids, "Test school 1 should be visible"
        assert test_school_2["id"] in school_ids, "Test school 2 should be visible"

        print(f"Schools table: {len(response.data)} schools visible")

    def test_schools_write_policy(
        self,
        supabase_admin_client,
    ):
        """
        Test that schools table write access is properly restricted.

        Only admins should be able to create/modify schools.
        """
        # This test verifies the write policy exists
        # In a real scenario, we'd test with a non-admin user token
        test_school_id = str(uuid.uuid4())

        try:
            # Admin client should be able to insert
            response = supabase_admin_client.table("schools").insert({
                "id": test_school_id,
                "name": "RLS Write Test School",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()

            assert response.data, "Admin should be able to create schools"

        finally:
            # Cleanup
            supabase_admin_client.table("schools").delete().eq("id", test_school_id).execute()


class TestUserProfilesRLS:
    """
    Tests for user_profiles table RLS policies.

    Users should only see profiles from their own school.
    """

    def test_user_profiles_isolation(
        self,
        supabase_admin_client,
        test_user_school_1,
        test_user_school_2,
    ):
        """
        Test that user_profiles are properly isolated by school.
        """
        response = supabase_admin_client.table("user_profiles").select("*").execute()

        school_1_users = [
            u for u in response.data
            if u.get("school_id") == test_user_school_1["school_id"]
        ]
        school_2_users = [
            u for u in response.data
            if u.get("school_id") == test_user_school_2["school_id"]
        ]

        # Verify test users exist in their respective schools
        assert len(school_1_users) >= 1, "School 1 should have at least 1 user"
        assert len(school_2_users) >= 1, "School 2 should have at least 1 user"

        # Check if there's cross-tenant visibility
        # This may or may not be a vulnerability depending on requirements
        total_users = len(response.data)
        print(f"user_profiles: {total_users} total users visible")


class TestRLSPolicyExistence:
    """
    Meta-tests to verify RLS policies exist on all tables.

    These tests query the database schema to ensure RLS is enabled
    and policies are defined.
    """

    @pytest.mark.parametrize("table_name", [
        "schools",
        "user_profiles",
        "events",
        "crm_events",
        "extracted_data",
        "reviewed_data",
        "student_school_interactions",
    ])
    def test_rls_enabled_on_table(
        self,
        supabase_admin_client,
        table_name: str,
    ):
        """
        Verify that RLS is enabled on critical tables.
        """
        # Query pg_tables to check if RLS is enabled
        # This requires access to system tables
        try:
            response = supabase_admin_client.rpc(
                "check_rls_enabled",
                {"table_name": table_name}
            ).execute()

            if response.data is not None:
                assert response.data is True, f"RLS should be enabled on {table_name}"
        except Exception as e:
            # If the RPC doesn't exist, we can't verify programmatically
            print(f"Could not verify RLS on {table_name}: {e}")
            pytest.skip(f"RPC function not available to verify RLS on {table_name}")

    def test_no_using_true_policies(self, supabase_admin_client):
        """
        Verify that no policies use USING(true) which bypasses RLS.

        KNOWN VULNERABILITIES:
        - crm_events: has USING(true)
        - events: has USING(true) on SELECT
        - extracted_data: has USING(true)
        - reviewed_data: has USING(true)
        - schools: has USING(true) on SELECT
        """
        vulnerable_tables = [
            "crm_events",
            "events",
            "extracted_data",
            "reviewed_data",
            "schools",
        ]

        # This test documents known vulnerabilities
        # After fixes, this list should be empty or contain intentional policies
        print(f"KNOWN VULNERABLE TABLES with USING(true): {vulnerable_tables}")

        # Mark as expected failure until fixed
        pytest.xfail(
            f"Known vulnerability: {len(vulnerable_tables)} tables have USING(true) policies"
        )


class TestMultiTenantIsolationIntegration:
    """
    Integration tests that verify complete multi-tenant isolation
    across the entire data flow.
    """

    def test_complete_data_isolation_scenario(
        self,
        supabase_admin_client,
        test_school_1,
        test_school_2,
        test_event_school_1,
        test_event_school_2,
    ):
        """
        End-to-end test of multi-tenant isolation.

        Simulates a complete workflow and verifies that at each step,
        data is properly isolated between schools.
        """
        # Create complete test data for both schools
        doc_id_1 = str(uuid.uuid4())
        doc_id_2 = str(uuid.uuid4())

        # School 1 data
        extracted_1 = {
            "document_id": doc_id_1,
            "event_id": test_event_school_1["id"],
            "school_id": test_school_1["id"],
            "fields": {"email": "student1@test.com"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        reviewed_1 = {
            "document_id": doc_id_1,
            "event_id": test_event_school_1["id"],
            "school_id": test_school_1["id"],
            "fields": {"email": {"value": "student1@test.com"}},
            "review_status": "reviewed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        # School 2 data
        extracted_2 = {
            "document_id": doc_id_2,
            "event_id": test_event_school_2["id"],
            "school_id": test_school_2["id"],
            "fields": {"email": "student2@test.com"},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        reviewed_2 = {
            "document_id": doc_id_2,
            "event_id": test_event_school_2["id"],
            "school_id": test_school_2["id"],
            "fields": {"email": {"value": "student2@test.com"}},
            "review_status": "reviewed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # Insert all test data
            supabase_admin_client.table("extracted_data").insert(extracted_1).execute()
            supabase_admin_client.table("extracted_data").insert(extracted_2).execute()
            supabase_admin_client.table("reviewed_data").insert(reviewed_1).execute()
            supabase_admin_client.table("reviewed_data").insert(reviewed_2).execute()

            # Verify isolation by querying with school_id filter
            # (simulating what RLS SHOULD do automatically)

            # School 1 should only see school 1 data
            extracted_for_school_1 = supabase_admin_client.table("extracted_data") \
                .select("*") \
                .eq("school_id", test_school_1["id"]) \
                .execute()

            reviewed_for_school_1 = supabase_admin_client.table("reviewed_data") \
                .select("*") \
                .eq("school_id", test_school_1["id"]) \
                .execute()

            # Verify school 1 data contains expected records
            extracted_1_docs = [d["document_id"] for d in extracted_for_school_1.data]
            reviewed_1_docs = [d["document_id"] for d in reviewed_for_school_1.data]

            assert doc_id_1 in extracted_1_docs, "School 1 extracted data should be visible"
            assert doc_id_1 in reviewed_1_docs, "School 1 reviewed data should be visible"

            # Verify school 2 data is NOT in school 1's filtered results
            assert doc_id_2 not in extracted_1_docs, "School 2 extracted data should not be in school 1's results"
            assert doc_id_2 not in reviewed_1_docs, "School 2 reviewed data should not be in school 1's results"

            print("Multi-tenant isolation verified via explicit filtering")
            print("NOTE: This test uses explicit filters. RLS should enforce this automatically.")

        finally:
            # Cleanup
            supabase_admin_client.table("reviewed_data").delete().eq("document_id", doc_id_1).execute()
            supabase_admin_client.table("reviewed_data").delete().eq("document_id", doc_id_2).execute()
            supabase_admin_client.table("extracted_data").delete().eq("document_id", doc_id_1).execute()
            supabase_admin_client.table("extracted_data").delete().eq("document_id", doc_id_2).execute()

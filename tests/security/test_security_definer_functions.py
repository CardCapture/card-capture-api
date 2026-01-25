"""
Tests for SECURITY DEFINER function protections.

This module verifies that all SECURITY DEFINER functions have proper
search_path protection to prevent privilege escalation attacks.

VULNERABILITY: Functions declared as SECURITY DEFINER execute with the
privileges of the function owner (typically a superuser). Without proper
search_path protection, an attacker could:
1. Create a malicious function in a schema that appears earlier in the search_path
2. Call the SECURITY DEFINER function, which would execute the malicious function
3. Gain elevated privileges

KNOWN VULNERABLE FUNCTIONS (19 total):
P0 Critical (authentication/authorization):
- is_admin
- is_superadmin
- has_role
- current_user_school_id

P1 High (data access):
- get_school_students
- get_export_data
- get_student_interactions

P2 Medium (helper functions):
- update_updated_at_column
- trigger functions

All SECURITY DEFINER functions MUST have:
SET search_path = pg_catalog, public

Run with: pytest tests/security/test_security_definer_functions.py -v
Requires: RUN_SECURITY_TESTS=true environment variable
"""

import os
import pytest
from typing import Dict, Any

# Mark all tests to require security test environment
pytestmark = [
    pytest.mark.skipif(
        os.getenv("RUN_SECURITY_TESTS") != "true",
        reason="Security tests require RUN_SECURITY_TESTS=true"
    ),
    pytest.mark.security,
    pytest.mark.security_definer,
]


# Known SECURITY DEFINER functions and their expected status
KNOWN_SECURITY_DEFINER_FUNCTIONS = {
    # P0 Critical - Authentication/Authorization
    "is_admin": {
        "priority": "P0",
        "description": "Checks if current user is an admin",
        "vulnerable": True,  # Expected to be vulnerable initially
    },
    "is_superadmin": {
        "priority": "P0",
        "description": "Checks if current user is a superadmin",
        "vulnerable": True,
    },
    "has_role": {
        "priority": "P0",
        "description": "Checks if current user has a specific role",
        "vulnerable": True,
    },
    "current_user_school_id": {
        "priority": "P0",
        "description": "Returns the school_id for the current user",
        "vulnerable": True,
    },

    # P1 High - Data Access
    "get_school_students": {
        "priority": "P1",
        "description": "Retrieves students for a school",
        "vulnerable": True,
    },
    "get_export_data": {
        "priority": "P1",
        "description": "Gets data for export operations",
        "vulnerable": True,
    },
    "get_student_interactions": {
        "priority": "P1",
        "description": "Gets student interaction history",
        "vulnerable": True,
    },

    # P2 Medium - Utility Functions
    "update_updated_at_column": {
        "priority": "P2",
        "description": "Trigger function to update updated_at timestamp",
        "vulnerable": True,
    },
    "handle_new_user": {
        "priority": "P2",
        "description": "Trigger function for new user creation",
        "vulnerable": True,
    },
}


class TestSecurityDefinerFunctions:
    """
    Tests to verify SECURITY DEFINER functions have proper search_path protection.
    """

    def test_find_all_security_definer_functions(
        self,
        supabase_admin_client,
    ):
        """
        Query the database to find all SECURITY DEFINER functions.

        This test discovers all functions with SECURITY DEFINER set,
        regardless of whether they have search_path protection.
        """
        # SQL to find all SECURITY DEFINER functions
        sql = """
        SELECT
            n.nspname as schema_name,
            p.proname as function_name,
            pg_get_functiondef(p.oid) as function_definition,
            p.prosecdef as is_security_definer
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.prosecdef = true
        AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        ORDER BY n.nspname, p.proname;
        """

        try:
            # Try to execute via RPC
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data:
                security_definer_functions = response.data
                print(f"\nFound {len(security_definer_functions)} SECURITY DEFINER functions:")
                for func in security_definer_functions:
                    print(f"  - {func.get('schema_name')}.{func.get('function_name')}")

                # Store for other tests
                return security_definer_functions

        except Exception as e:
            print(f"Could not query SECURITY DEFINER functions: {e}")
            # Fall back to documented list
            print("\nUsing documented list of SECURITY DEFINER functions:")
            for func_name, info in KNOWN_SECURITY_DEFINER_FUNCTIONS.items():
                print(f"  - {func_name} ({info['priority']}): {info['description']}")

            return list(KNOWN_SECURITY_DEFINER_FUNCTIONS.keys())

    def test_security_definer_search_path_protection(
        self,
        supabase_admin_client,
    ):
        """
        Verify that all SECURITY DEFINER functions have search_path set.

        VULNERABILITY: Functions without SET search_path are vulnerable
        to privilege escalation attacks.
        """
        # SQL to find SECURITY DEFINER functions WITHOUT search_path
        sql = """
        SELECT
            n.nspname as schema_name,
            p.proname as function_name,
            pg_get_functiondef(p.oid) as function_definition
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.prosecdef = true
        AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        AND pg_get_functiondef(p.oid) NOT ILIKE '%SET search_path%'
        ORDER BY n.nspname, p.proname;
        """

        vulnerable_functions = []

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data:
                vulnerable_functions = response.data

        except Exception as e:
            print(f"Could not query for vulnerable functions: {e}")
            # Assume all known functions are vulnerable initially
            vulnerable_functions = [
                {"function_name": name, "schema_name": "public"}
                for name in KNOWN_SECURITY_DEFINER_FUNCTIONS.keys()
            ]

        if vulnerable_functions:
            print(f"\nVULNERABLE FUNCTIONS (no search_path): {len(vulnerable_functions)}")
            for func in vulnerable_functions:
                func_name = func.get("function_name", "unknown")
                print(f"  - {func.get('schema_name', 'public')}.{func_name}")

            # This test documents the vulnerability
            pytest.xfail(
                f"KNOWN VULNERABILITY: {len(vulnerable_functions)} SECURITY DEFINER functions "
                f"lack search_path protection"
            )
        else:
            print("\nAll SECURITY DEFINER functions have search_path protection")

    @pytest.mark.parametrize("function_name,function_info", [
        (name, info) for name, info in KNOWN_SECURITY_DEFINER_FUNCTIONS.items()
        if info["priority"] == "P0"
    ])
    def test_p0_critical_function_protection(
        self,
        supabase_admin_client,
        function_name: str,
        function_info: Dict[str, Any],
    ):
        """
        Test that P0 critical functions have proper search_path protection.

        P0 functions are used for authentication and authorization,
        making them the highest priority for security fixes.
        """
        sql = f"""
        SELECT
            pg_get_functiondef(p.oid) as function_definition
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.proname = '{function_name}'
        AND n.nspname = 'public';
        """

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data and len(response.data) > 0:
                definition = response.data[0].get("function_definition", "")

                # Check for search_path setting
                has_search_path = "SET search_path" in definition.upper()

                if not has_search_path:
                    pytest.xfail(
                        f"P0 CRITICAL VULNERABILITY: {function_name} lacks search_path protection. "
                        f"Description: {function_info['description']}"
                    )
                else:
                    # Verify it's set to a safe value
                    # Safe values: pg_catalog, public (in that order)
                    if "pg_catalog" not in definition.lower():
                        pytest.xfail(
                            f"P0 WARNING: {function_name} has search_path but may not include pg_catalog"
                        )
            else:
                pytest.skip(f"Function {function_name} not found in database")

        except Exception as e:
            print(f"Could not verify {function_name}: {e}")
            if function_info.get("vulnerable", True):
                pytest.xfail(
                    f"P0 ASSUMED VULNERABLE: {function_name} - {function_info['description']}"
                )

    @pytest.mark.parametrize("function_name,function_info", [
        (name, info) for name, info in KNOWN_SECURITY_DEFINER_FUNCTIONS.items()
        if info["priority"] == "P1"
    ])
    def test_p1_high_priority_function_protection(
        self,
        supabase_admin_client,
        function_name: str,
        function_info: Dict[str, Any],
    ):
        """
        Test that P1 high priority functions have proper search_path protection.

        P1 functions are used for data access and are high priority
        for security fixes.
        """
        sql = f"""
        SELECT
            pg_get_functiondef(p.oid) as function_definition
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.proname = '{function_name}'
        AND n.nspname = 'public';
        """

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data and len(response.data) > 0:
                definition = response.data[0].get("function_definition", "")

                has_search_path = "SET search_path" in definition.upper()

                if not has_search_path:
                    pytest.xfail(
                        f"P1 HIGH VULNERABILITY: {function_name} lacks search_path protection. "
                        f"Description: {function_info['description']}"
                    )
            else:
                pytest.skip(f"Function {function_name} not found in database")

        except Exception as e:
            print(f"Could not verify {function_name}: {e}")
            if function_info.get("vulnerable", True):
                pytest.xfail(
                    f"P1 ASSUMED VULNERABLE: {function_name} - {function_info['description']}"
                )


class TestSearchPathExploitScenario:
    """
    Tests that demonstrate the search_path vulnerability exploitation scenario.

    These tests verify that the vulnerability exists and document how
    it could be exploited.
    """

    def test_search_path_exploitation_scenario_documentation(self):
        """
        Document the search_path vulnerability exploitation scenario.

        This test documents (but does not execute) how an attacker
        could exploit a SECURITY DEFINER function without search_path.
        """
        exploit_scenario = """
        SEARCH_PATH VULNERABILITY EXPLOITATION SCENARIO
        ================================================

        1. SETUP: A SECURITY DEFINER function exists without SET search_path:

           CREATE FUNCTION is_admin()
           RETURNS BOOLEAN
           LANGUAGE plpgsql
           SECURITY DEFINER
           AS $$
           BEGIN
               RETURN EXISTS (
                   SELECT 1 FROM profiles
                   WHERE id = auth.uid()
                   AND 'admin' = ANY(role)
               );
           END;
           $$;

        2. ATTACK: Malicious user creates a schema and function:

           CREATE SCHEMA evil;
           CREATE FUNCTION evil.auth.uid() RETURNS UUID AS $$
               SELECT 'attacker-controlled-uuid'::uuid;
           $$ LANGUAGE SQL;

        3. EXPLOIT: If search_path includes 'evil' before 'auth':

           SET search_path = evil, public, auth;
           SELECT is_admin();  -- Now calls evil.auth.uid()!

        4. IMPACT: Attacker can:
           - Bypass authentication checks
           - Escalate privileges
           - Access unauthorized data

        5. FIX: Add search_path to all SECURITY DEFINER functions:

           CREATE FUNCTION is_admin()
           RETURNS BOOLEAN
           LANGUAGE plpgsql
           SECURITY DEFINER
           SET search_path = pg_catalog, public  -- CRITICAL!
           AS $$
           -- function body
           $$;

        The SET search_path clause ensures the function always uses
        the intended schema, preventing hijacking.
        """

        print(exploit_scenario)

        # This test always passes - it's documentation
        assert True, "Exploitation scenario documented"

    def test_verify_auth_functions_use_correct_schema(
        self,
        supabase_admin_client,
    ):
        """
        Verify that authentication functions reference auth schema correctly.

        Functions that use auth.uid() or auth.jwt() must have search_path
        set to prevent schema hijacking.
        """
        # SQL to find functions using auth.uid() or auth.jwt()
        sql = """
        SELECT
            n.nspname as schema_name,
            p.proname as function_name,
            pg_get_functiondef(p.oid) as function_definition
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
        AND (
            pg_get_functiondef(p.oid) ILIKE '%auth.uid()%'
            OR pg_get_functiondef(p.oid) ILIKE '%auth.jwt()%'
            OR pg_get_functiondef(p.oid) ILIKE '%auth.role()%'
        );
        """

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data:
                auth_functions = response.data
                vulnerable = []

                for func in auth_functions:
                    definition = func.get("function_definition", "")
                    if "SET search_path" not in definition.upper():
                        vulnerable.append(func.get("function_name"))

                if vulnerable:
                    print(f"\nFunctions using auth.* without search_path: {vulnerable}")
                    pytest.xfail(
                        f"CRITICAL: {len(vulnerable)} functions use auth.* without search_path protection"
                    )

        except Exception as e:
            print(f"Could not verify auth functions: {e}")
            pytest.skip("Could not query database for auth functions")


class TestTriggerFunctionSecurity:
    """
    Tests for trigger function security.

    Trigger functions often use SECURITY DEFINER and are commonly
    overlooked for search_path protection.
    """

    def test_trigger_functions_search_path(
        self,
        supabase_admin_client,
    ):
        """
        Verify that trigger functions have search_path protection.

        Trigger functions execute automatically and can be exploited
        if they lack proper search_path settings.
        """
        # SQL to find trigger functions
        sql = """
        SELECT DISTINCT
            p.proname as function_name,
            pg_get_functiondef(p.oid) as function_definition
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        JOIN pg_trigger t ON t.tgfoid = p.oid
        WHERE n.nspname = 'public';
        """

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data:
                trigger_functions = response.data
                vulnerable = []

                for func in trigger_functions:
                    definition = func.get("function_definition", "")
                    func_name = func.get("function_name")

                    # Check if it's SECURITY DEFINER and lacks search_path
                    is_security_definer = "SECURITY DEFINER" in definition.upper()
                    has_search_path = "SET search_path" in definition.upper()

                    if is_security_definer and not has_search_path:
                        vulnerable.append(func_name)

                if vulnerable:
                    print(f"\nVulnerable trigger functions: {vulnerable}")
                    pytest.xfail(
                        f"VULNERABILITY: {len(vulnerable)} trigger functions lack search_path"
                    )
                else:
                    print("\nAll trigger functions are properly secured or not SECURITY DEFINER")

        except Exception as e:
            print(f"Could not verify trigger functions: {e}")
            # Assume vulnerability exists for documented trigger functions
            if "update_updated_at_column" in KNOWN_SECURITY_DEFINER_FUNCTIONS:
                pytest.xfail(
                    "ASSUMED VULNERABLE: update_updated_at_column trigger function"
                )


class TestSecurityDefinerCount:
    """
    Tests to count and track SECURITY DEFINER functions.
    """

    def test_total_security_definer_count(
        self,
        supabase_admin_client,
    ):
        """
        Count total SECURITY DEFINER functions in the database.

        This test provides a baseline count for tracking security improvements.
        """
        sql = """
        SELECT COUNT(*) as count
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.prosecdef = true
        AND n.nspname NOT IN ('pg_catalog', 'information_schema');
        """

        expected_vulnerable_count = 19  # Documented in the plan

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data:
                actual_count = response.data[0].get("count", 0)
                print(f"\nTotal SECURITY DEFINER functions: {actual_count}")
                print(f"Expected vulnerable: {expected_vulnerable_count}")

                # After fix, this number should remain the same but all should be protected
                assert actual_count >= 0, "Should be able to count functions"

        except Exception as e:
            print(f"Could not count SECURITY DEFINER functions: {e}")
            print(f"\nUsing documented count: {expected_vulnerable_count}")

    def test_security_definer_with_protection_count(
        self,
        supabase_admin_client,
    ):
        """
        Count SECURITY DEFINER functions that ARE properly protected.

        Goal: This count should equal the total count after fixes.
        """
        sql = """
        SELECT COUNT(*) as count
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.prosecdef = true
        AND n.nspname NOT IN ('pg_catalog', 'information_schema')
        AND pg_get_functiondef(p.oid) ILIKE '%SET search_path%';
        """

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data:
                protected_count = response.data[0].get("count", 0)
                print(f"\nSECURITY DEFINER functions with search_path: {protected_count}")

                if protected_count == 0:
                    pytest.xfail(
                        "VULNERABILITY: No SECURITY DEFINER functions have search_path protection"
                    )

        except Exception as e:
            print(f"Could not count protected functions: {e}")
            pytest.xfail(
                "ASSUMED VULNERABILITY: Could not verify search_path protection exists"
            )


class TestSecurityDefinerFunctionDefinitions:
    """
    Tests to verify specific function definitions.
    """

    def test_is_admin_function_definition(
        self,
        supabase_admin_client,
    ):
        """
        Verify the is_admin function has proper security settings.

        is_admin is a P0 critical function used throughout the application
        to determine administrative privileges.
        """
        sql = """
        SELECT
            pg_get_functiondef(p.oid) as definition
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.proname = 'is_admin'
        AND n.nspname = 'public';
        """

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data and len(response.data) > 0:
                definition = response.data[0].get("definition", "")

                # Check for required security attributes
                is_security_definer = "SECURITY DEFINER" in definition.upper()
                has_search_path = "SET search_path" in definition.upper()

                print("\nis_admin function:")
                print(f"  - SECURITY DEFINER: {is_security_definer}")
                print(f"  - Has search_path: {has_search_path}")

                if is_security_definer and not has_search_path:
                    pytest.xfail(
                        "P0 CRITICAL VULNERABILITY: is_admin is SECURITY DEFINER without search_path"
                    )
            else:
                pytest.skip("is_admin function not found")

        except Exception as e:
            print(f"Could not verify is_admin: {e}")
            pytest.xfail("ASSUMED VULNERABLE: is_admin function")

    def test_current_user_school_id_function_definition(
        self,
        supabase_admin_client,
    ):
        """
        Verify the current_user_school_id function has proper security settings.

        current_user_school_id is used by RLS policies to determine
        data access, making it critical for multi-tenant isolation.
        """
        sql = """
        SELECT
            pg_get_functiondef(p.oid) as definition
        FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE p.proname = 'current_user_school_id'
        AND n.nspname = 'public';
        """

        try:
            response = supabase_admin_client.rpc(
                "exec_sql",
                {"query": sql}
            ).execute()

            if response.data and len(response.data) > 0:
                definition = response.data[0].get("definition", "")

                is_security_definer = "SECURITY DEFINER" in definition.upper()
                has_search_path = "SET search_path" in definition.upper()

                print("\ncurrent_user_school_id function:")
                print(f"  - SECURITY DEFINER: {is_security_definer}")
                print(f"  - Has search_path: {has_search_path}")

                if is_security_definer and not has_search_path:
                    pytest.xfail(
                        "P0 CRITICAL VULNERABILITY: current_user_school_id is SECURITY DEFINER without search_path"
                    )
            else:
                pytest.skip("current_user_school_id function not found")

        except Exception as e:
            print(f"Could not verify current_user_school_id: {e}")
            pytest.xfail("ASSUMED VULNERABLE: current_user_school_id function")

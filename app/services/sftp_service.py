from fastapi.responses import JSONResponse
from app.core.clients import get_supabase_client
from app.utils.retry_utils import log_debug
from typing import Dict, Any, Optional
import traceback

# Try to import SFTP utils for testing connections
try:
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from sftp_utils import SFTPConfig
    import paramiko
    SFTP_AVAILABLE = True
    log_debug("SFTP functionality loaded successfully", service="sftp")
except ImportError as e:
    log_debug(f"SFTP functionality not available: {str(e)}", service="sftp")
    SFTP_AVAILABLE = False
    SFTPConfig = None
    paramiko = None


async def create_or_update_sftp_config_service(payload: Dict[str, Any], user: Dict[str, Any]):
    """
    Create or update SFTP configuration for a school
    """
    try:
        school_id = payload.get("school_id")
        host = payload.get("host")
        port = payload.get("port", 22)
        username = payload.get("username")
        password = payload.get("password")
        remote_path = payload.get("remote_path")
        enabled = payload.get("enabled", True)

        # Validate required fields
        if not all([school_id, host, username, password, remote_path]):
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required fields: school_id, host, username, password, remote_path"}
            )

        # Validate user has access to this school
        user_school_id = user.get("school_id")
        if user_school_id != school_id:
            # Check if user is admin
            user_roles = user.get("role", [])
            if not ("admin" in user_roles if isinstance(user_roles, list) else user_roles == "admin"):
                return JSONResponse(
                    status_code=403,
                    content={"error": "You don't have permission to configure SFTP for this school"}
                )

        log_debug(f"SFTP CONFIG: Creating/updating SFTP config for school_id: {school_id}", service="sftp")

        # Prepare SFTP config data
        sftp_data = {
            "school_id": school_id,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "remote_path": remote_path,
            "enabled": enabled
        }

        # Check if config already exists
        supabase_client = get_supabase_client()
        existing_result = supabase_client.table("sftp_configs").select("id").eq("school_id", school_id).execute()

        if existing_result.data:
            # Update existing config
            config_id = existing_result.data[0]["id"]
            result = supabase_client.table("sftp_configs").update(sftp_data).eq("id", config_id).execute()
            log_debug(f"SFTP CONFIG: Updated existing config for school_id: {school_id}", service="sftp")
        else:
            # Create new config
            result = supabase_client.table("sftp_configs").insert(sftp_data).execute()
            log_debug(f"SFTP CONFIG: Created new config for school_id: {school_id}", service="sftp")

        if hasattr(result, 'error') and result.error:
            raise Exception(f"Database error: {result.error}")

        return JSONResponse(
            status_code=200,
            content={
                "message": "SFTP configuration saved successfully",
                "config_id": result.data[0]["id"] if result.data else None
            }
        )

    except Exception as e:
        log_debug(f"SFTP CONFIG: Error saving config: {str(e)}", service="sftp")
        log_debug("Full traceback:", traceback.format_exc(), service="sftp")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to save SFTP configuration: {str(e)}"}
        )


async def test_sftp_connection_service(payload: Dict[str, Any], user: Dict[str, Any]):
    """
    Test SFTP connection with provided credentials
    """
    try:
        if not SFTP_AVAILABLE:
            return JSONResponse(
                status_code=503,
                content={"error": "SFTP functionality is not available. Please ensure required dependencies are installed."}
            )

        school_id = payload.get("school_id")
        host = payload.get("host")
        port = payload.get("port", 22)
        username = payload.get("username")
        password = payload.get("password")
        remote_path = payload.get("remote_path", "/")

        # Validate required fields
        if not all([host, username, password]):
            return JSONResponse(
                status_code=400,
                content={"error": "Missing required fields for testing: host, username, password"}
            )

        # Validate user has access to this school
        if school_id:
            user_school_id = user.get("school_id")
            if user_school_id != school_id:
                # Check if user is admin
                user_roles = user.get("role", [])
                if not ("admin" in user_roles if isinstance(user_roles, list) else user_roles == "admin"):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "You don't have permission to test SFTP for this school"}
                    )

        log_debug(f"SFTP TEST: Testing connection to {host}:{port} with username {username}", service="sftp")

        # Test SFTP connection
        ssh = None
        sftp = None
        try:
            # Initialize SSH client
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Connect to SFTP server
            ssh.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=10  # 10 second timeout
            )

            # Open SFTP session
            sftp = ssh.open_sftp()

            # Test if remote path exists or can be created
            path_accessible = True
            path_message = f"Remote path '{remote_path}' is accessible"
            
            try:
                sftp.stat(remote_path)
            except FileNotFoundError:
                try:
                    # Try to create the directory
                    sftp.mkdir(remote_path)
                    path_message = f"Remote path '{remote_path}' was created successfully"
                    log_debug(f"SFTP TEST: Created remote directory: {remote_path}", service="sftp")
                except Exception as mkdir_error:
                    path_accessible = False
                    path_message = f"Remote path '{remote_path}' does not exist and cannot be created: {str(mkdir_error)}"
            except Exception as stat_error:
                path_accessible = False
                path_message = f"Cannot access remote path '{remote_path}': {str(stat_error)}"

            # Close connections
            sftp.close()
            ssh.close()

            log_debug(f"SFTP TEST: Connection successful to {host}:{port}", service="sftp")

            return JSONResponse(
                status_code=200,
                content={
                    "message": "SFTP connection test successful",
                    "connection_status": "success",
                    "host": host,
                    "port": port,
                    "username": username,
                    "path_accessible": path_accessible,
                    "path_message": path_message
                }
            )

        except paramiko.AuthenticationException:
            error_msg = "Authentication failed - invalid username or password"
            log_debug(f"SFTP TEST: {error_msg}", service="sftp")
            return JSONResponse(
                status_code=401,
                content={
                    "message": "SFTP connection test failed",
                    "connection_status": "failed",
                    "error": error_msg
                }
            )
        except paramiko.SSHException as ssh_error:
            error_msg = f"SSH connection error: {str(ssh_error)}"
            log_debug(f"SFTP TEST: {error_msg}", service="sftp")
            return JSONResponse(
                status_code=400,
                content={
                    "message": "SFTP connection test failed",
                    "connection_status": "failed",
                    "error": error_msg
                }
            )
        except Exception as conn_error:
            error_msg = f"Connection failed: {str(conn_error)}"
            log_debug(f"SFTP TEST: {error_msg}", service="sftp")
            return JSONResponse(
                status_code=400,
                content={
                    "message": "SFTP connection test failed",
                    "connection_status": "failed",
                    "error": error_msg
                }
            )
        finally:
            # Ensure connections are closed
            try:
                if sftp:
                    sftp.close()
                if ssh:
                    ssh.close()
            except:
                pass

    except Exception as e:
        log_debug(f"SFTP TEST: Unexpected error: {str(e)}", service="sftp")
        log_debug("Full traceback:", traceback.format_exc(), service="sftp")
        return JSONResponse(
            status_code=500,
            content={"error": f"SFTP test failed: {str(e)}"}
        )


async def get_sftp_config_service(school_id: str, user: Dict[str, Any]):
    """
    Get SFTP configuration for a school
    """
    try:
        # Validate user has access to this school
        user_school_id = user.get("school_id")
        if user_school_id != school_id:
            # Check if user is admin
            user_roles = user.get("role", [])
            if not ("admin" in user_roles if isinstance(user_roles, list) else user_roles == "admin"):
                return JSONResponse(
                    status_code=403,
                    content={"error": "You don't have permission to view SFTP config for this school"}
                )

        log_debug(f"SFTP CONFIG: Fetching config for school_id: {school_id}", service="sftp")

        # Fetch SFTP config
        supabase_client = get_supabase_client()
        result = supabase_client.table("sftp_configs").select("*").eq("school_id", school_id).execute()

        if not result.data:
            return JSONResponse(
                status_code=404,
                content={"error": "No SFTP configuration found for this school"}
            )

        config = result.data[0]
        
        # Remove sensitive password from response
        config_response = {
            "id": config["id"],
            "school_id": config["school_id"],
            "host": config["host"],
            "port": config["port"],
            "username": config["username"],
            "remote_path": config["remote_path"],
            "enabled": config["enabled"],
            "created_at": config.get("created_at"),
            "updated_at": config.get("updated_at"),
            "password_configured": bool(config.get("password"))
        }

        return JSONResponse(
            status_code=200,
            content={"config": config_response}
        )

    except Exception as e:
        log_debug(f"SFTP CONFIG: Error fetching config: {str(e)}", service="sftp")
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to fetch SFTP configuration: {str(e)}"}
        ) 
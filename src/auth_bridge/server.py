#!/usr/bin/env python3
"""
Authentication Bridge Server
Handles SV2 authentication by intercepting and processing login requests
"""

import asyncio
import logging
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Optional, Any
from aiohttp import web
import aiohttp_cors
import webbrowser
import tempfile


class AuthBridgeServer:
    """Authentication bridge server for SV2"""

    def __init__(self, port: int = 8888):
        self.port = port
        self.logger = logging.getLogger(__name__)
        self.app = web.Application()
        self.session_store: Dict[str, Dict[str, Any]] = {}
        self.auth_token: Optional[str] = None
        self.user_info: Optional[Dict[str, Any]] = None
        self.last_auth_params: Optional[Dict[str, str]] = None
        self.redirect_uri_used: Optional[str] = (
            None  # Track which redirect_uri was used
        )

        self._setup_routes()
        self._setup_cors()

    @staticmethod
    def get_wine_prefix() -> Path:
        """Get the correct Wine prefix, handling Bottles if configured"""
        bottle_name = os.environ.get("SV2_BOTTLE_NAME")
        if bottle_name:
            # Check for Bottles flatpak prefix
            bottles_prefix = (
                Path.home()
                / ".var/app/com.usebottles.bottles/data/bottles/bottles"
                / bottle_name
            )
            if bottles_prefix.exists():
                return bottles_prefix
        # Fall back to WINEPREFIX or default
        return Path(os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine-sv2")))

    def _setup_routes(self):
        """Setup HTTP routes"""
        self.app.router.add_get("/", self.index_handler)
        self.app.router.add_get("/auth/start", self.auth_start_handler)
        self.app.router.add_get("/auth/callback", self.auth_callback_handler)
        self.app.router.add_get("/auth/status", self.auth_status_handler)
        self.app.router.add_post("/auth/inject", self.auth_inject_handler)
        self.app.router.add_get("/static/{filename}", self.static_handler)

    def _setup_cors(self):
        """Setup CORS for cross-origin requests"""
        cors = aiohttp_cors.setup(
            self.app,
            defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                    allow_methods="*",
                )
            },
        )

        # Add CORS to all routes
        for route in list(self.app.router.routes()):
            cors.add(route)

    async def index_handler(self, request: web.Request) -> web.Response:
        """Main index page"""
        html = """
<!DOCTYPE html>
<html>
<head>
    <title>SV2 Authentication Bridge</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        .container { max-width: 600px; margin: 0 auto; }
        .status { padding: 20px; border-radius: 5px; margin: 20px 0; }
        .success { background-color: #d4edda; border: 1px solid #c3e6cb; color: #155724; }
        .warning { background-color: #fff3cd; border: 1px solid #ffeaa7; color: #856404; }
        .error { background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24; }
        button { background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .log { background: #f8f9fa; padding: 15px; border-radius: 5px; font-family: monospace; white-space: pre-wrap; max-height: 200px; overflow-y: auto; }
    </style>
</head>
<body>
    <div class="container">
        <h1>SV2 Authentication Bridge</h1>
        <p>This service helps bypass Qt WebView authentication issues in Synthesizer V Studio 2 Pro.</p>
        
        <div id="status" class="status warning">
            Status: Waiting for authentication request...
        </div>
        
        <button onclick="startAuth()">Start Authentication</button>
        <button onclick="checkStatus()">Check Status</button>
        
        <h3>Log</h3>
        <div id="log" class="log"></div>
    </div>

    <script>
        let logContent = '';
        
        function log(message) {
            logContent += new Date().toISOString() + ' - ' + message + '\\n';
            document.getElementById('log').textContent = logContent;
        }
        
        async function startAuth() {
            try {
                const response = await fetch('/auth/start');
                const data = await response.json();
                log('Authentication started: ' + data.message);
                updateStatus('Authentication in progress...', 'warning');
            } catch (error) {
                log('Error starting authentication: ' + error);
                updateStatus('Error starting authentication', 'error');
            }
        }
        
        async function checkStatus() {
            try {
                const response = await fetch('/auth/status');
                const data = await response.json();
                log('Status: ' + JSON.stringify(data));
                
                if (data.authenticated) {
                    updateStatus('Authentication successful!', 'success');
                } else {
                    updateStatus('Not authenticated', 'warning');
                }
            } catch (error) {
                log('Error checking status: ' + error);
                updateStatus('Error checking status', 'error');
            }
        }
        
        function updateStatus(message, type) {
            const statusEl = document.getElementById('status');
            statusEl.textContent = 'Status: ' + message;
            statusEl.className = 'status ' + type;
        }
        
        // Auto-refresh status every 5 seconds
        setInterval(checkStatus, 5000);
        
        log('Authentication bridge ready');
    </script>
</body>
</html>
        """
        return web.Response(text=html, content_type="text/html")

    async def auth_start_handler(self, request: web.Request) -> web.Response:
        """Start authentication process"""
        self.logger.info("Starting authentication process")

        # Build Keycloak authorization URL with correct parameters
        import uuid
        import urllib.parse

        state = str(uuid.uuid4())

        # For SV2 app authentication, use the custom URI scheme
        # SV2 uses a different client_id than the web login (authr3-frontend)
        client_id = "svstudio2"  # Guess based on redirect_uri pattern
        redirect_uri = "dreamtonics-svstudio2://auth/callback"

        response_type = os.environ.get("SV2_OAUTH_RESPONSE_TYPE", "code").strip()
        if not response_type:
            response_type = "code"

        auth_params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": response_type,
            "state": state,
            "scope": "openid profile email",
        }

        auth_url = (
            "https://account.dreamtonics.com/realms/Dreamtonics/protocol/openid-connect/auth?"
            + urllib.parse.urlencode(auth_params)
        )

        # Store the redirect_uri for later use in token exchange
        self.redirect_uri_used = redirect_uri

        try:
            self.logger.info(f"Opening auth URL: {auth_url}")
            self.logger.info(f"Using redirect_uri: {redirect_uri}")
            webbrowser.open(auth_url)
            return web.json_response(
                {
                    "status": "success",
                    "message": "Authentication started in system browser",
                    "auth_url": auth_url,
                    "state": state,
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to open browser: {e}")
            return web.json_response(
                {"status": "error", "message": f"Failed to open browser: {e}"},
                status=500,
            )

    async def auth_callback_handler(self, request: web.Request) -> web.Response:
        """Handle authentication callback"""
        params = dict(request.query)
        self.logger.info(f"Received auth callback with code: {params.get('code', 'N/A')[:20]}...")
        self.last_auth_params = {k: str(v) for k, v in params.items()}

        if "code" in params:
            # Store auth params and write auth code to cb file
            # SV2 will handle token exchange internally using cv + cb files
            success = await self._store_auth_payload(params)

            if success:
                self.logger.info("Auth code written to SV2 license directory")
                return web.Response(
                    text="""
<!DOCTYPE html>
<html>
<head><title>Authentication Successful</title></head>
<body>
    <h1>Authentication Successful!</h1>
    <p>The login has been forwarded to Synthesizer V Studio 2.</p>
    <p>You can now close this window and return to SV2.</p>
    <script>setTimeout(function() { window.close(); }, 2000);</script>
</body>
</html>
                    """,
                    content_type="text/html",
                )

            self.logger.error("Failed to write auth code to SV2")
            return web.Response(
                text="""
<!DOCTYPE html>
<html>
<head><title>Authentication Failed</title></head>
<body>
    <h1>Failed to Forward to SV2</h1>
    <p>Could not write authentication data.</p>
    <p>Make sure SV2 is running and try again.</p>
</body>
</html>
                """,
                content_type="text/html",
                status=500,
            )

        # Handle direct access token (if provided)
        access_token = params.get("access_token") or params.get("token")
        if access_token:
            self.auth_token = access_token
            self.user_info = {
                "user_id": params.get("user_id") or params.get("uid") or "",
                "username": params.get("username") or params.get("user") or "",
                "email": params.get("email") or "",
            }
            self.logger.info("Direct access token received")
            await self._inject_auth_token()
            return web.Response(
                text="""
<!DOCTYPE html>
<html>
<head><title>Authentication Successful</title></head>
<body>
    <h1>Authentication Successful!</h1>
    <p>You can now close this window and return to Synthesizer V Studio 2.</p>
    <script>window.close();</script>
</body>
</html>
                """,
                content_type="text/html",
            )

        return web.json_response(
            {
                "status": "error",
                "message": "Invalid authentication callback - no code or token",
            },
            status=400,
        )

    async def auth_status_handler(self, request: web.Request) -> web.Response:
        """Get current authentication status"""
        return web.json_response(
            {
                "authenticated": self.auth_token is not None,
                "has_auth_code": bool(
                    self.last_auth_params and "code" in self.last_auth_params
                ),
                "user_info": self.user_info if self.user_info else None,
            }
        )

    async def auth_inject_handler(self, request: web.Request) -> web.Response:
        """Inject authentication token into SV2"""
        if not self.auth_token:
            return web.json_response(
                {"status": "error", "message": "No authentication token available"},
                status=400,
            )

        success = await self._inject_auth_token()
        return web.json_response(
            {
                "status": "success" if success else "error",
                "message": "Token injection " + ("successful" if success else "failed"),
            }
        )

    async def static_handler(self, request: web.Request) -> web.Response:
        """Serve static files"""
        filename = request.match_info["filename"]
        # For security, only serve specific files
        if filename not in ["style.css", "script.js"]:
            raise web.HTTPNotFound()

        static_dir = Path(__file__).parent / "static"
        file_path = static_dir / filename

        if not file_path.exists():
            raise web.HTTPNotFound()

        return web.FileResponse(file_path)

    async def _store_auth_payload(self, params: Dict[str, Any]) -> bool:
        """Store authentication payload for later use"""
        try:
            wine_prefix = self.get_wine_prefix()
            token_file = (
                wine_prefix / "drive_c" / "users" / "Public" / "sv2_auth_token.json"
            )

            payload = {
                "access_token": self.auth_token,
                "auth_params": {k: str(v) for k, v in params.items()},
                "timestamp": asyncio.get_event_loop().time(),
            }

            token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(token_file, "w") as f:
                json.dump(payload, f, indent=2)

            await self._inject_registry_payload(payload["auth_params"])
            self.logger.info(f"Auth payload written to {token_file}")

            # Write auth code directly to SV2's license/cb file
            # SV2 will use this with the code_verifier (cv file) to complete token exchange
            auth_code = params.get("code")
            if auth_code:
                await self._write_auth_code_to_cb_file(auth_code)

            return True
        except Exception as e:
            self.logger.error(f"Failed to store auth payload: {e}")
            return False

    async def _write_auth_code_to_cb_file(self, auth_code: str) -> bool:
        """Write auth code directly to SV2's license/cb file"""
        try:
            wine_prefix = self.get_wine_prefix()

            # SV2 stores license files in AppData/Roaming/Dreamtonics/Synthesizer V Studio 2/license/
            # Try multiple possible user directories
            possible_users = ["steamuser", "Public", os.environ.get("USER", "user")]

            for user in possible_users:
                license_dir = (
                    wine_prefix / "drive_c" / "users" / user / "AppData" / "Roaming"
                    / "Dreamtonics" / "Synthesizer V Studio 2" / "license"
                )
                cv_file = license_dir / "cv"

                if cv_file.exists():
                    cb_file = license_dir / "cb"
                    cb_file.write_text(auth_code)
                    self.logger.info(f"Auth code written to {cb_file}")
                    return True

            # If no cv file found, try to create cb in the most common location
            license_dir = (
                wine_prefix / "drive_c" / "users" / "steamuser" / "AppData" / "Roaming"
                / "Dreamtonics" / "Synthesizer V Studio 2" / "license"
            )
            if license_dir.exists():
                cb_file = license_dir / "cb"
                cb_file.write_text(auth_code)
                self.logger.info(f"Auth code written to {cb_file} (cv file not found)")
                return True

            self.logger.warning(f"Could not find SV2 license directory to write cb file")
            return False

        except Exception as e:
            self.logger.error(f"Failed to write auth code to cb file: {e}")
            return False

    async def _inject_registry_payload(self, params: Dict[str, str]) -> bool:
        """Inject auth code payload into Wine registry"""
        try:
            auth_code = params.get("code", "")
            state = params.get("state", "")
            session_state = params.get("session_state", "")
            issuer = params.get("iss", "")
            timestamp = str(int(asyncio.get_event_loop().time()))

            reg_key = (
                r"HKEY_CURRENT_USER\Software\Dreamtonics\Synthesizer V Studio 2\Auth"
            )
            reg_values = [
                ("AuthCode", auth_code),
                ("State", state),
                ("SessionState", session_state),
                ("Issuer", issuer),
                ("AuthTimestamp", timestamp),
            ]

            bottle_name = os.environ.get("SV2_BOTTLE_NAME")
            if bottle_name and shutil.which("flatpak"):
                # Use bottles-cli reg command for each value
                all_success = True
                for value_name, value_data in reg_values:
                    result = subprocess.run(
                        [
                            "flatpak",
                            "run",
                            "--command=bottles-cli",
                            "com.usebottles.bottles",
                            "reg",
                            "add",
                            "-b",
                            bottle_name,
                            "-k",
                            reg_key,
                            "-v",
                            value_name,
                            "-d",
                            value_data,
                        ],
                        capture_output=True,
                        text=True,
                    )
                    if result.returncode != 0:
                        self.logger.warning(
                            f"Registry value {value_name} failed: {result.stderr}"
                        )
                        all_success = False

                if all_success:
                    self.logger.info("Registry payload injection successful")
                    return True
                self.logger.warning("Some registry values may have failed")
                return True  # Continue anyway as file-based fallback exists
            else:
                # Use wine regedit with .reg file
                reg_content = f'''REGEDIT4

[HKEY_CURRENT_USER\\Software\\Dreamtonics\\Synthesizer V Studio 2\\Auth]
"AuthCode"="{auth_code}"
"State"="{state}"
"SessionState"="{session_state}"
"Issuer"="{issuer}"
"AuthTimestamp"="{timestamp}"
'''
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".reg", delete=False
                ) as f:
                    f.write(reg_content)
                    reg_file = f.name

                wine_prefix = str(self.get_wine_prefix())
                env = os.environ.copy()
                env["WINEPREFIX"] = wine_prefix

                wine_exe = "wine-staging" if shutil.which("wine-staging") else "wine"
                result = subprocess.run(
                    [wine_exe, "regedit", reg_file],
                    env=env,
                    capture_output=True,
                    text=True,
                )

                os.unlink(reg_file)

                if result.returncode == 0:
                    self.logger.info("Registry payload injection successful")
                    return True
                self.logger.error(f"Registry payload injection failed: {result.stderr}")
                return False
        except Exception as e:
            self.logger.error(f"Registry payload injection error: {e}")
            return False

    def setup_uri_handler(self) -> bool:
        """Setup dreamtonics-svstudio2:// URI handler"""
        try:
            bottle_name = os.environ.get("SV2_BOTTLE_NAME")
            bottle_arg = ""
            if bottle_name:
                if " " in bottle_name or '"' in bottle_name:
                    safe_name = bottle_name.replace('"', '\\"')
                    bottle_arg = f' --bottle "{safe_name}"'
                else:
                    bottle_arg = f" --bottle {bottle_name}"

            desktop_entry = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=SV2 Auth Bridge Handler
Exec=sv2-auth-bridge --handle-uri %u --port {self.port}{bottle_arg}
NoDisplay=true
StartupNotify=true
MimeType=x-scheme-handler/dreamtonics-svstudio2;
"""

            # Write desktop entry
            desktop_dir = Path.home() / ".local" / "share" / "applications"
            desktop_dir.mkdir(parents=True, exist_ok=True)

            desktop_file = desktop_dir / "sv2-auth-bridge.desktop"
            with open(desktop_file, "w") as f:
                f.write(desktop_entry)

            # Update MIME database
            subprocess.run(
                ["update-desktop-database", str(desktop_dir)], capture_output=True
            )

            self.logger.info("URI handler registered successfully")
            return True

        except Exception as e:
            self.logger.error(f"Failed to setup URI handler: {e}")
            return False

    @staticmethod
    def _extract_uri_params(uri: str) -> Dict[str, str]:
        parsed = urllib.parse.urlparse(uri)
        params: Dict[str, list[str]] = {}

        for source in [parsed.query, parsed.fragment]:
            if source:
                params.update(urllib.parse.parse_qs(source, keep_blank_values=True))

        # Flatten params (take first value)
        flat_params = {k: v[0] if isinstance(v, list) else v for k, v in params.items()}
        return flat_params

    @staticmethod
    def forward_uri_to_callback(uri: str, port: int = 8888) -> bool:
        params = AuthBridgeServer._extract_uri_params(uri)
        query = urllib.parse.urlencode(params)
        callback_url = f"http://localhost:{port}/auth/callback"
        if query:
            callback_url = f"{callback_url}?{query}"

        try:
            with urllib.request.urlopen(callback_url, timeout=5) as response:
                return response.status == 200
        except Exception:
            return False

    @staticmethod
    def _find_sv2_executable(wine_prefix: str) -> Optional[Path]:
        prefix_path = Path(wine_prefix)
        drive_c = prefix_path / "drive_c"
        candidates = [
            drive_c / "svstudio2_app" / "synthv-studio.exe",
            drive_c
            / "Program Files"
            / "Dreamtonics"
            / "Synthesizer V Studio 2"
            / "synthv-studio.exe",
            drive_c
            / "Program Files (x86)"
            / "Dreamtonics"
            / "Synthesizer V Studio 2"
            / "synthv-studio.exe",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        try:
            for found in drive_c.rglob("synthv-studio.exe"):
                return found
        except Exception:
            return None

        return None

    @staticmethod
    def _to_windows_path(unix_path: Path, wine_prefix: str) -> str:
        prefix = Path(wine_prefix).resolve()
        path = unix_path.resolve()
        try:
            rel = path.relative_to(prefix / "drive_c")
            return "C:\\" + "\\".join(rel.parts)
        except Exception:
            return str(unix_path)

    @staticmethod
    def setup_wine_protocol_handler(bottle_name: Optional[str] = None) -> bool:
        bottle = bottle_name or os.environ.get("SV2_BOTTLE_NAME")
        wine_prefix = (
            AuthBridgeServer.get_wine_prefix()
            if bottle
            else os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine-sv2"))
        )
        exe_path = AuthBridgeServer._find_sv2_executable(str(wine_prefix))
        if not exe_path:
            return False

        exe_win_path = AuthBridgeServer._to_windows_path(exe_path, str(wine_prefix))

        reg_content = f"""REGEDIT4

[HKEY_CURRENT_USER\\Software\\Classes\\dreamtonics-svstudio2]
@=\"URL:Dreamtonics SVStudio2 Protocol\"
\"URL Protocol\"=\"\"

[HKEY_CURRENT_USER\\Software\\Classes\\dreamtonics-svstudio2\\shell\\open\\command]
@=\"\\\"{exe_win_path}\\\" \\\"%1\\\"\"
"""

        try:
            if bottle and shutil.which("flatpak"):
                reg_file = Path(wine_prefix) / "drive_c" / "sv2_protocol.reg"
                reg_file.write_text(reg_content)
                result = subprocess.run(
                    [
                        "flatpak",
                        "run",
                        "--command=bottles-cli",
                        "com.usebottles.bottles",
                        "run",
                        "-b",
                        bottle,
                        "-e",
                        "regedit",
                        "C:\\sv2_protocol.reg",
                    ],
                    capture_output=True,
                    text=True,
                )
                return result.returncode == 0

            reg_dir = Path.home() / ".sv2-bridge"
            reg_dir.mkdir(parents=True, exist_ok=True)
            reg_file = reg_dir / "sv2_protocol.reg"
            reg_file.write_text(reg_content)

            env = os.environ.copy()
            env["WINEPREFIX"] = str(wine_prefix)

            wine_exe = "wine-staging" if shutil.which("wine-staging") else "wine"
            result = subprocess.run(
                [wine_exe, "regedit", str(reg_file)],
                env=env,
                capture_output=True,
                text=True,
            )

            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def forward_uri_to_wine(uri: str, bottle_name: Optional[str] = None) -> bool:
        bottle = bottle_name or os.environ.get("SV2_BOTTLE_NAME")
        if bottle and shutil.which("flatpak"):
            import logging

            logger = logging.getLogger(__name__)

            # Method 0: Use bottles-cli shell -i with start command (most reliable)
            logger.info(f"Attempting to forward URI via bottles-cli shell: {uri}")
            try:
                # Use start command through shell interface to avoid argument parsing issues
                shell_cmd = f'start "" "{uri}"'
                result = subprocess.run(
                    [
                        "flatpak",
                        "run",
                        "--command=bottles-cli",
                        "com.usebottles.bottles",
                        "shell",
                        "-b",
                        bottle,
                        "-i",
                        shell_cmd,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                logger.info(
                    f"bottles-cli shell result: returncode={result.returncode}, stderr={result.stderr[:200] if result.stderr else ''}"
                )
                stderr_text = result.stderr or ""
                shell_error = (
                    "/bin/sh" in stderr_text
                    or "unexpected" in stderr_text.lower()
                    or "ShellExecuteEx failed" in stderr_text
                )
                if result.returncode == 0 and not shell_error:
                    return True
            except subprocess.TimeoutExpired:
                logger.warning("bottles-cli shell timed out")
            except Exception as e:
                logger.warning(f"bottles-cli shell failed: {e}")

            # Method 1: Use a batch file and URI file in the bottle to avoid shell parsing issues
            logger.info(f"Attempting to forward URI via bottles-cli cmd batch: {uri}")
            wine_prefix = AuthBridgeServer.get_wine_prefix()
            uri_path = Path(wine_prefix) / "drive_c" / "sv2_uri.txt"
            bat_path = Path(wine_prefix) / "drive_c" / "sv2_open_uri.bat"
            uri_path.write_text(uri)
            bat_content = """@echo off
setlocal
set /p SV2_URI=<C:\\sv2_uri.txt
start "" "%SV2_URI%"
"""
            bat_path.write_text(bat_content)

            try:
                result = subprocess.run(
                    [
                        "flatpak",
                        "run",
                        "--command=bottles-cli",
                        "com.usebottles.bottles",
                        "run",
                        "-b",
                        bottle,
                        "-e",
                        "C:\\windows\\system32\\cmd.exe",
                        "/c",
                        "C:\\sv2_open_uri.bat",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                logger.info(
                    f"bottles-cli cmd result: returncode={result.returncode}, stderr={result.stderr[:200] if result.stderr else ''}"
                )
                stderr_text = result.stderr or ""
                cmd_error = (
                    "Executable file path does not exist" in stderr_text
                    or "ShellExecuteEx" in stderr_text
                    or "/bin/sh" in stderr_text
                    or "unexpected" in stderr_text.lower()
                )
                if result.returncode == 0 and not cmd_error:
                    return True
            except subprocess.TimeoutExpired:
                logger.warning("bottles-cli cmd timed out")
            except Exception as e:
                logger.warning(f"bottles-cli cmd failed: {e}")

            # Method 2: Use rundll32 url.dll,FileProtocolHandler
            logger.info(f"Attempting to forward URI via bottles-cli rundll32: {uri}")
            try:
                result = subprocess.run(
                    [
                        "flatpak",
                        "run",
                        "--command=bottles-cli",
                        "com.usebottles.bottles",
                        "run",
                        "-b",
                        bottle,
                        "-e",
                        "C:\\windows\\system32\\rundll32.exe",
                        "url.dll,FileProtocolHandler",
                        uri,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                logger.info(
                    f"bottles-cli rundll32 result: returncode={result.returncode}, stdout={result.stdout[:200] if result.stdout else ''}, stderr={result.stderr[:200] if result.stderr else ''}"
                )
                stderr_text = result.stderr or ""
                shell_error = (
                    "/bin/sh" in stderr_text or "unexpected" in stderr_text.lower()
                )
                if result.returncode == 0 and not shell_error:
                    return True
            except subprocess.TimeoutExpired:
                logger.warning("bottles-cli rundll32 timed out")
            except Exception as e:
                logger.warning(f"bottles-cli rundll32 failed: {e}")

            # Method 3: Try launching SV2 directly with URI argument
            logger.info("Trying direct SV2 launch method...")
            exe_win_path = "C:\\svstudio2_app\\synthv-studio.exe"
            exe_path = AuthBridgeServer._find_sv2_executable(str(wine_prefix))
            if exe_path:
                exe_win_path = AuthBridgeServer._to_windows_path(
                    exe_path, str(wine_prefix)
                )
            try:
                result = subprocess.run(
                    [
                        "flatpak",
                        "run",
                        "--command=bottles-cli",
                        "com.usebottles.bottles",
                        "run",
                        "-b",
                        bottle,
                        "-e",
                        exe_win_path,
                        uri,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                logger.info(
                    f"bottles-cli direct launch result: returncode={result.returncode}, stderr={result.stderr[:200] if result.stderr else ''}"
                )
                return result.returncode == 0
            except subprocess.TimeoutExpired:
                logger.warning("bottles-cli direct launch timed out")
                return False
            except Exception as e:
                logger.warning(f"bottles-cli direct launch failed: {e}")
                return False

        wine_prefix = os.environ.get("WINEPREFIX", os.path.expanduser("~/.wine-sv2"))
        env = os.environ.copy()
        env["WINEPREFIX"] = wine_prefix

        wine_exe = "wine-staging" if shutil.which("wine-staging") else "wine"
        try:
            result = subprocess.run(
                [wine_exe, "start", uri], env=env, capture_output=True, text=True
            )
            if result.returncode == 0:
                return True

            result = subprocess.run(
                [wine_exe, "rundll32", "url.dll,FileProtocolHandler", uri],
                env=env,
                capture_output=True,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    async def start_server(self):
        """Start the authentication bridge server"""
        self.logger.info(f"Starting auth bridge server on port {self.port}")

        # Setup URI handler for Linux desktop
        self.setup_uri_handler()

        runner = web.AppRunner(self.app)
        await runner.setup()

        site = web.TCPSite(runner, "localhost", self.port)
        await site.start()

        self.logger.info(f"Auth bridge server running at http://localhost:{self.port}")
        print(f"Auth bridge server running at http://localhost:{self.port}")

    async def stop_server(self):
        """Stop the authentication bridge server"""
        self.logger.info("Stopping auth bridge server")


async def main():
    """Main entry point for auth bridge server"""
    import argparse

    parser = argparse.ArgumentParser(description="SV2 Authentication Bridge Server")
    parser.add_argument("--port", type=int, default=8888, help="Server port")
    parser.add_argument("--handle-uri", help="Handle dreamtonics-svstudio2:// URI")
    parser.add_argument(
        "--bottle",
        help="Bottles bottle name to forward URIs into",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    # Also accept URI as positional argument (for Firefox which passes URI directly)
    parser.add_argument(
        "uri", nargs="?", help="URI to handle (alternative to --handle-uri)"
    )

    args = parser.parse_args()

    if args.bottle:
        os.environ["SV2_BOTTLE_NAME"] = args.bottle

    # If URI passed as positional argument, treat it as --handle-uri
    if args.uri and args.uri.startswith("dreamtonics-svstudio2://"):
        args.handle_uri = args.uri

    # Setup logging to file and console
    log_file = "/tmp/auth_bridge.log"
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file),
        ],
    )

    if args.handle_uri:
        # Handle URI scheme - forward to running auth bridge server
        # The server will write auth code to SV2's cb file
        handled = AuthBridgeServer.forward_uri_to_callback(
            args.handle_uri, port=args.port
        )
        if handled:
            print("Authentication forwarded to SV2 successfully")
        else:
            print("Failed to forward callback (is auth bridge server running?)")
        return

    # Start server
    server = AuthBridgeServer(port=args.port)

    try:
        await server.start_server()

        # Keep server running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        await server.stop_server()


def main_sync():
    """Synchronous entry point for console_scripts"""
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()

#!/usr/bin/env python3
"""
model-gateway.py — Model Gateway CLI

Manage tenants, providers, and models on a running Model Gateway instance.

Usage:
    python scripts/model-gateway.py [OPTIONS] COMMAND [ARGS]...

Commands:
    config   [key] [value]     View or set persistent configuration
    login    -u <user>         Authenticate and store credentials
    logout                     Remove stored credentials

    tenant   create <name>
    tenant   list
    tenant   get    <uuid>
    tenant   delete <uuid>

    provider create <type> <name>
    provider list
    provider get    <uuid>
    provider validate <type>
    provider delete <uuid>

    model    add       <provider_uuid> <model_id>
    model    list      <provider_uuid>
    model    available <provider_uuid>
    model    list-all
    model    delete    <provider_uuid> <model_uuid>

    provision          Interactive end-to-end setup

Environment variables:
    MGW_BASE_URL       Gateway base URL  (overrides stored config)

Configuration is stored in ~/.mgw/config.json.
Credentials are stored in ~/.mgw/credentials.
State (tenant/provider UUIDs) is stored in ~/.mgw/state.json.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import subprocess
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterator, Optional

import typer
from typing_extensions import Annotated

# ---------------------------------------------------------------------------
# Optional dependency: requests.  Give a clean error if missing.
# ---------------------------------------------------------------------------
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:  # pragma: no cover
    sys.exit(
        "ERROR: 'requests' is required.  Install it with:\n"
        "  pip install requests\n"
    )

# ---------------------------------------------------------------------------
# Rich
# ---------------------------------------------------------------------------
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
    from rich.status import Status
    from rich import box
except ImportError:  # pragma: no cover
    sys.exit(
        "ERROR: 'rich' is required.  Install it with:\n"
        "  pip install rich\n"
    )

# ---------------------------------------------------------------------------
# Questionary
# ---------------------------------------------------------------------------
try:
    import questionary
    from questionary import Style as QStyle
except ImportError:  # pragma: no cover
    sys.exit(
        "ERROR: 'questionary' is required.  Install it with:\n"
        "  pip install questionary\n"
    )

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

__version__ = "1.1.0"

# ---------------------------------------------------------------------------
# Paths  (~/.mgw/)
# ---------------------------------------------------------------------------
MGW_DIR = Path(__file__).parent / ".mgw"
CONFIG_FILE = MGW_DIR / "config.json"
CREDENTIALS_FILE = MGW_DIR / "credentials"
STATE_FILE = MGW_DIR / "state.json"

# ---------------------------------------------------------------------------
# Logging  (~/.mgw/mgw.log)
# ---------------------------------------------------------------------------


LOG_FILE = MGW_DIR / "mgw.log"


def _setup_logger() -> logging.Logger:
    log = logging.getLogger("model-gateway")
    log.propagate = False  # don't let records bubble up to the root logger
    MGW_DIR.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=(1024 * 1024),
        backupCount=5,
    )
    fh.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)-7s] [%(module)s::%(funcName)s:%(lineno)d]\t%(message)s"
        )
    )
    log.addHandler(fh)
    log.setLevel(logging.INFO)
    return log


logger = _setup_logger()

# Keys recognised by the config command
_CONFIG_KEYS = ("url", "insecure", "namespace")

# ---------------------------------------------------------------------------
# Provider type registry
# Maps CLI type name → API path slug
# ---------------------------------------------------------------------------
PROVIDER_TYPES: dict[str, str] = {
    "openai": "openai",
    "azure-openai": "azure-openai",
    "watsonxai": "watsonxai",
    "ollama": "ollama",
    "anthropic": "anthropic",
    "bedrock": "bedrock",
    "gemini": "gemini",
    "mistral": "mistral",
    "groq": "groq",
    "cerebras": "cerebras",
    "xai": "xai",
    "nim": "nim",
    "cohere": "cohere",
    "wxai-router": "wxai-router",
    "adobe-firefly": "adobe-firefly",
}

# ---------------------------------------------------------------------------
# Rich console + theme
# ---------------------------------------------------------------------------

_THEME = Theme(
    {
        "ok": "bold green",
        "warn": "bold yellow",
        "err": "bold red",
        "info": "dim cyan",
        "muted": "dim white",
        "accent": "bold cyan",
        "uuid": "dim magenta",
        "header": "bold white",
        "skip": "yellow",
    }
)

console = Console(theme=_THEME, highlight=False)

# Questionary style — matches the rich theme palette
_Q_STYLE = QStyle(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green bold"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("separator", "fg:cyan"),
        ("instruction", "fg:white dim"),
    ]
)

# ---------------------------------------------------------------------------
# Error display helpers  (mirrors ibmca errors.py show_error_panel)
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dataclass
from rich.console import Group as _Group
from requests import Response as _Response


@_dataclass
class _EI:
    """Lightweight error info (title + body text)."""
    title: str
    content: str


def show_error_panel(
    info: "_EI",
    exception: "Exception | None" = None,
    response: "_Response | None" = None,
) -> None:
    """Render a rich error Panel (red border, width 100) — matches ibmca UX."""
    response_text = ""
    request_id = ""
    if response is not None:
        content_type = response.headers.get("Content-Type", "").lower()
        if "application/json" in content_type:
            data_dict = response.json()
            response_text = data_dict.get("error", {}).get("message", response.text)
        else:
            response_text = response.text
        request_id = response.headers.get("x-ibm-mgw-requestid", "")
        if request_id:
            request_id = f"\n\n[yellow]Please reference request ID {request_id} when contacting support[/]"

    exception_text = ""
    if exception:
        logger.exception(str(exception))
        exception_text = f"\n\n[red]Details:[/] {exception}"

    grouped = _Group(info.content, response_text, exception_text, request_id)
    console.print(
        Panel(
            grouped,
            expand=True,
            border_style="bold red",
            title=info.title,
            width=100,
        )
    )


# Pre-defined error info constants (mirrors ibmca errors.py)
_ERR_AUTH = _EI(
    title="Authentication Failure",
    content="\nPlease use '[italic]model-gateway.py login -u <user>[/italic]' to authenticate.\n",
)
_ERR_MISSING_URL = _EI(
    title="Missing Service URL",
    content="\nPlease use '[italic]model-gateway.py config url https://<gateway url>[/italic]' to set the URL.\n",
)
_ERR_CERT = _EI(
    title="Certificate Validation",
    content="\nThe service's SSL certificate failed validation. Check that the certificate has not expired or has a hostname mismatch.\n",
)
_ERR_SERVICE = _EI(
    title="Service Error",
    content="\nThe service responded with an error. Please check the service's logs for more information.\n",
)
_ERR_JSON = _EI(
    title="Invalid JSON",
    content="\nAn error occurred parsing JSON.\n",
)
_ERR_CONFIG = _EI(
    title="Config",
    content="\nAn error occurred while storing or retrieving config.\n",
)


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def _ok(msg: str) -> None:
    """Print a success line."""
    console.print(f"[ok]✔[/ok]  {msg}")


def _warn(msg: str) -> None:
    """Print a warning line."""
    console.print(f"[warn]⚠[/warn]  {msg}")


def _err(msg: str) -> None:
    """Print an error panel and exit 1."""
    show_error_panel(_EI("Error", msg))
    raise typer.Exit(1)


def _info(msg: str) -> None:
    """Print a muted info line."""
    console.print(f"[info]ℹ[/info]  [muted]{msg}[/muted]")


def _spinner(label: str) -> Status:
    """Return a rich Status spinner context manager."""
    return console.status(f"[accent]{label}[/accent]", spinner="dots")


def _print_output(data: Any, output_fmt: str) -> None:
    """Render data as a rich table or pretty JSON depending on --output."""
    if output_fmt == "json" or not isinstance(data, (dict, list)):
        console.print_json(json.dumps(data, indent=2))
        return

    rows = data if isinstance(data, list) else [data]
    if not rows:
        _info("No results.")
        return

    if not isinstance(rows[0], dict):
        for item in rows:
            console.print(str(item))
        return

    keys = list(rows[0].keys())
    tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="header", show_edge=False)
    for k in keys:
        tbl.add_column(k.upper(), overflow="fold")
    for row in rows:
        tbl.add_row(*[str(row.get(k, "")) for k in keys])
    console.print(tbl)


def _kv_panel(data: dict[str, Any], title: str = "") -> None:
    """Render a key-value dict as a neat panel."""
    lines = "\n".join(
        f"[muted]{k}[/muted]  [accent]{v}[/accent]" for k, v in data.items()
    )
    console.print(Panel(lines, title=f"[header]{title}[/header]" if title else "", border_style="cyan", padding=(0, 1)))


# ---------------------------------------------------------------------------
# Dev mode — automatic kubectl port-forward
# ---------------------------------------------------------------------------

_DEV_LOCAL_PORT = 18080  # avoids collisions with common 8080 usage


def _free_port(preferred: int) -> int:
    """Return preferred port if free, otherwise find a random free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if s.connect_ex(("localhost", preferred)) != 0:
            return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _port_forward_context(namespace: str, local_port: int) -> Iterator[str]:
    """Spawn kubectl port-forward to the MG pod and yield the local base URL.

    Starts ``kubectl port-forward deployment/model-gateway -n <namespace>
    <local_port>:8080`` as a background process, waits up to 10 s for the
    port to become reachable, then yields ``https://localhost:<local_port>``.
    Tears the process down on exit regardless of how the context exits.

    Args:
        namespace: Kubernetes namespace containing the model-gateway deployment.
        local_port: Local TCP port to forward to.

    Yields:
        Base URL string for the forwarded gateway.

    Raises:
        typer.Exit: If kubectl is not found or the port never becomes reachable.
    """
    cmd = [
        "kubectl", "port-forward",
        "deployment/model-gateway",
        "-n", namespace,
        f"{local_port}:8080",
    ]
    logger.debug("dev mode: starting port-forward: %s", " ".join(cmd))
    console.print(
        f"[info]ℹ[/info]  [muted]Dev mode — starting port-forward:"
        f" deployment/model-gateway → localhost:{local_port}[/muted]"
    )
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        _err("kubectl not found in PATH — cannot start port-forward.")

    try:
        # Wait until the local port accepts connections (up to 10 s).
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex(("localhost", local_port)) == 0:
                    break
            if proc.poll() is not None:
                stderr_out = (proc.stderr.read() or b"").decode().strip()
                _err(
                    f"kubectl port-forward exited early.\n{stderr_out}"
                )
            time.sleep(0.3)
        else:
            proc.terminate()
            _err(
                f"Timed out waiting for port-forward on localhost:{local_port}.\n"
                "Check that the model-gateway deployment is Running and kubectl context is correct."
            )

        console.print(
            f"[ok]✔[/ok]  [muted]Port-forward ready — "
            f"localhost:{local_port} → model-gateway-service:8080[/muted]"
        )
        yield f"https://localhost:{local_port}"

    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        logger.debug("dev mode: port-forward stopped")


# ---------------------------------------------------------------------------
# Typer app + shared state
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="model-gateway",
    help="Model Gateway CLI — manage tenants, providers, and models.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Nested app groups
tenant_app = typer.Typer(help="Tenant management (admin).", no_args_is_help=True, rich_markup_mode="rich")
provider_app = typer.Typer(help="Provider management.", no_args_is_help=True, rich_markup_mode="rich")
model_app = typer.Typer(help="Model management.", no_args_is_help=True, rich_markup_mode="rich")
user_app = typer.Typer(help="User management.", no_args_is_help=True, rich_markup_mode="rich")
policy_app = typer.Typer(help="Policy management.", no_args_is_help=True, rich_markup_mode="rich")
ratelimit_app = typer.Typer(help="Rate-limit management.", no_args_is_help=True, rich_markup_mode="rich")
lb_app = typer.Typer(help="Load-balancer management.", no_args_is_help=True, rich_markup_mode="rich")

app.add_typer(tenant_app, name="tenant")
app.add_typer(provider_app, name="provider")
app.add_typer(model_app, name="model")
app.add_typer(user_app, name="user")
app.add_typer(policy_app, name="policy")
app.add_typer(ratelimit_app, name="rate-limit")
app.add_typer(lb_app, name="load-balancer")

# Mutable state shared across callback → subcommands
state: dict[str, Any] = {
    "base_url": "",
    "output": "table",
}


# ---------------------------------------------------------------------------
# Version callback
# ---------------------------------------------------------------------------


def version_callback(value: bool) -> None:
    if value:
        console.print(
            Panel(
                f"[header]Model Gateway CLI[/header]  [accent]v{__version__}[/accent]",
                border_style="cyan",
                padding=(0, 2),
            )
        )
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Provider credential helpers
# ---------------------------------------------------------------------------


def _prompt_or_env(var: str, prompt: str, *, secret: bool = True, default: str = "") -> str:
    """Return env var value, or interactively prompt if unset.

    Args:
        var: Environment variable name to check first.
        prompt: Human-readable label shown at the interactive prompt.
        secret: If True, use a password prompt (input hidden).
        default: Default value pre-filled in the prompt (non-secret only).
    """
    val = os.environ.get(var, "")
    if val:
        return val
    if secret:
        answer = questionary.password(f"{prompt}:", style=_Q_STYLE).ask()
    else:
        answer = questionary.text(f"{prompt}:", default=default, style=_Q_STYLE).ask()
    if not answer:
        _err(
            f"[accent]{var}[/accent] is required for this provider type.\n"
            f"Export it or enter it when prompted."
        )
    return answer


def _resolve_provider_data(provider_type: str) -> dict[str, Any]:
    """Build the provider 'data' payload — reads env vars, prompts interactively if unset."""
    t = provider_type.lower()

    if t == "openai":
        data: dict[str, Any] = {
            "apikey": _prompt_or_env("OPENAI_API_KEY", "OpenAI API key"),
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        }
        if os.environ.get("OPENAI_SKIP_VALIDATION", "").lower() in ("1", "true", "yes"):
            data["skip_validation"] = True
        return data
    if t == "azure-openai":
        data = {
            "apikey": _prompt_or_env("AZURE_OPENAI_API_KEY", "Azure OpenAI API key"),
            "resource_name": _prompt_or_env("AZURE_OPENAI_RESOURCE_NAME", "Azure resource name", secret=False),
        }
        data["api_version"] = _prompt_or_env(
            "AZURE_OPENAI_API_VERSION", "Azure OpenAI API version", secret=False
        )
        for env, key in [
            ("AZURE_OPENAI_SUBSCRIPTION_ID", "subscription_id"),
            ("AZURE_OPENAI_RESOURCE_GROUP", "resource_group_name"),
            ("AZURE_OPENAI_ACCOUNT_NAME", "account_name"),
        ]:
            val = os.environ.get(env, "")
            if val:
                data[key] = val
        return data
    if t == "watsonxai":
        data = {
            "apikey": _prompt_or_env("WATSONXAI_API_KEY", "watsonx.ai API key"),
            "base_url": _prompt_or_env(
                "WATSONXAI_BASE_URL",
                "watsonx.ai base URL",
                secret=False,
                default="https://us-south.ml.cloud.ibm.com",
            ),
        }
        # space_id and project_id: prompt interactively if not set via env var.
        # At least one is typically required for SaaS deployments.
        for env, key, label in [
            ("WATSONXAI_SPACE_ID", "space_id", "Space ID (leave blank to skip)"),
            ("WATSONXAI_PROJECT_ID", "project_id", "Project ID (leave blank to skip)"),
        ]:
            val = os.environ.get(env, "")
            if not val:
                val = questionary.text(f"watsonx.ai {label}:", style=_Q_STYLE).ask() or ""
            if val:
                data[key] = val
        # auth_url and other optional fields remain env-var-only (rarely needed).
        auth_url = os.environ.get("WATSONXAI_AUTH_URL", "")
        if auth_url:
            data["auth_url"] = auth_url
        return data
    if t == "ollama":
        data = {"host": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")}
        keep_alive = os.environ.get("OLLAMA_KEEP_ALIVE", "")
        if keep_alive:
            try:
                data["keep_alive"] = int(keep_alive)
            except ValueError:
                pass
        return data
    if t == "anthropic":
        return {"apikey": _prompt_or_env("ANTHROPIC_API_KEY", "Anthropic API key")}
    if t == "bedrock":
        data = {
            "access_key_id": _prompt_or_env("AWS_ACCESS_KEY_ID", "AWS access key ID"),
            "secret_access_key": _prompt_or_env("AWS_SECRET_ACCESS_KEY", "AWS secret access key"),
            "region": os.environ.get("AWS_REGION", "us-east-1"),
        }
        for env, key in [
            ("AWS_SESSION_TOKEN", "session_token"),
            ("AWS_BEDROCK_BASE_URL", "base_url"),
        ]:
            val = os.environ.get(env, "")
            if val:
                data[key] = val
        return data
    if t == "gemini":
        return {"apikey": _prompt_or_env("GEMINI_API_KEY", "Gemini API key")}
    if t == "mistral":
        return {"apikey": _prompt_or_env("MISTRAL_API_KEY", "Mistral API key")}
    if t == "groq":
        return {"apikey": _prompt_or_env("GROQ_API_KEY", "Groq API key")}
    if t == "cerebras":
        return {"apikey": _prompt_or_env("CEREBRAS_API_KEY", "Cerebras API key")}
    if t == "xai":
        return {"apikey": _prompt_or_env("XAI_API_KEY", "xAI API key")}
    if t == "nim":
        return {"apikey": _prompt_or_env("NIM_API_KEY", "NIM API key")}
    if t == "cohere":
        return {"apikey": _prompt_or_env("COHERE_API_KEY", "Cohere API key")}
    if t == "adobe-firefly":
        return {
            "client_id": _prompt_or_env("ADOBE_FIREFLY_CLIENT_ID", "Adobe Firefly client ID"),
            "client_secret": _prompt_or_env("ADOBE_FIREFLY_CLIENT_SECRET", "Adobe Firefly client secret"),
        }
    if t == "wxai-router":
        return {}

    _err(
        f"Unknown provider type [accent]{provider_type}[/accent].\n"
        f"Supported types: {', '.join(sorted(PROVIDER_TYPES))}"
    )
    return {}  # unreachable — _err raises


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GatewayError(Exception):
    """Raised when the gateway returns a non-2xx response."""

    def __init__(self, status_code: int, body: Any, url: str = "") -> None:
        self.status_code = status_code
        self.body = body
        self.url = url
        if isinstance(body, dict) and "error" in body:
            msg = body["error"].get("message", json.dumps(body))
        else:
            msg = json.dumps(body) if isinstance(body, dict) else str(body)
        super().__init__(f"HTTP {status_code}: {msg}  [{url}]")


# ---------------------------------------------------------------------------
# GatewayClient
# ---------------------------------------------------------------------------


class GatewayClient:
    """Thin HTTP client for the Model Gateway REST API."""

    _RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
    _MAX_RETRIES = 3
    _BACKOFF_FACTOR = 0.5

    def __init__(
        self,
        base_url: str,
        token: str,
        requests_verify: "bool | str" = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")

        # requests_verify mirrors ibmca's ctx.obj['requests_verify']:
        #   True  → verify against system CAs
        #   False → skip (self-signed cert)
        #   str   → path to a PEM bundle
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )
        self._session.verify = requests_verify

        retry = Retry(
            total=self._MAX_RETRIES,
            backoff_factor=self._BACKOFF_FACTOR,
            status_forcelist=self._RETRY_STATUSES,
            allowed_methods={"GET", "DELETE"},
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _raise_for_status(self, resp: requests.Response) -> None:
        if not resp.ok:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            err = GatewayError(resp.status_code, body, resp.url)
            logger.error("HTTP %s %s — %s", resp.status_code, resp.url, err)
            raise err

    def get(self, path: str, **kwargs: Any) -> Any:
        resp = self._session.get(self._url(path), **kwargs)
        self._raise_for_status(resp)
        return resp.json() if resp.content else None

    def post(self, path: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        resp = self._session.post(self._url(path), json=payload, **kwargs)
        self._raise_for_status(resp)
        return resp.json() if resp.content else None

    def patch(self, path: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        resp = self._session.patch(self._url(path), json=payload, **kwargs)
        self._raise_for_status(resp)
        return resp.json() if resp.content else None

    def put(self, path: str, payload: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        resp = self._session.put(self._url(path), json=payload, **kwargs)
        self._raise_for_status(resp)
        return resp.json() if resp.content else None

    def delete(self, path: str, **kwargs: Any) -> Any:
        resp = self._session.delete(self._url(path), **kwargs)
        self._raise_for_status(resp)
        return resp.json() if resp.content else None


# ---------------------------------------------------------------------------
# Persistent config helpers  (~/.mgw/config.json)
# ---------------------------------------------------------------------------


def read_config() -> dict[str, Any]:
    """Read the persistent CLI config file; return empty dict if missing."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to read config file: %s", CONFIG_FILE)
            return {}
    return {}


def write_config(cfg: dict[str, Any]) -> None:
    """Write the persistent CLI config file, creating the directory if needed."""
    try:
        MGW_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except OSError:
        logger.exception("Failed to write config file: %s", CONFIG_FILE)
        raise


def get_config_value(key: str) -> str:
    """Return a single config value, or empty string if unset."""
    return read_config().get(key, "")


def set_config_value(key: str, value: "str | bool") -> None:
    """Set a single config value and persist it."""
    cfg = read_config()
    cfg[key] = value
    write_config(cfg)


# ---------------------------------------------------------------------------
# Credentials helpers  (~/.mgw/credentials)
# ---------------------------------------------------------------------------


def read_credentials() -> dict[str, Any]:
    """Read the stored credentials; return empty dict if missing."""
    if CREDENTIALS_FILE.exists():
        try:
            return json.loads(CREDENTIALS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to read credentials file: %s", CREDENTIALS_FILE)
            return {}
    return {}


def write_credentials(creds: dict[str, Any]) -> None:
    """Persist credentials, creating the directory if needed."""
    try:
        MGW_DIR.mkdir(parents=True, exist_ok=True)
        CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2))
        CREDENTIALS_FILE.chmod(0o600)
    except OSError:
        logger.exception("Failed to write credentials file: %s", CREDENTIALS_FILE)
        raise


def clear_credentials() -> None:
    """Remove stored credentials (logout)."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()


def get_stored_token() -> str:
    """Return the stored JWT access token, or empty string if absent/expired."""
    creds = read_credentials()
    token = creds.get("token", "")
    expires_at = creds.get("expires_at", 0)
    if token and (expires_at == 0 or time.time() < expires_at):
        return token
    return ""


def _token_status() -> str:
    """Return 'ok', 'expired', or 'missing' for the stored token."""
    creds = read_credentials()
    token = creds.get("token", "")
    if not token:
        return "missing"
    expires_at = creds.get("expires_at", 0)
    if expires_at != 0 and time.time() >= expires_at:
        return "expired"
    return "ok"


# ---------------------------------------------------------------------------
# requests_verify helper — resolves the right verify= value for requests
# ---------------------------------------------------------------------------


def _get_requests_verify() -> "bool | str":
    """Return the requests verify argument from stored config.

    Mirrors ibmca's requests_verify config key:
      True  → verify against system CAs
      False → skip verification (self-signed cert accepted)
      str   → path to a PEM bundle of trusted CAs

    Also honours the ``insecure`` config key set by ``config insecure true``:
    if insecure is truthy, returns False (skip verification).
    """
    cfg = read_config()

    # ``config insecure true`` takes precedence — maps to verify=False.
    insecure_val = cfg.get("insecure", False)
    if isinstance(insecure_val, str):
        insecure_val = insecure_val.lower() in ("true", "1", "yes")
    if insecure_val:
        return False

    val = cfg.get("requests_verify", True)
    if val is True or val is False:
        return val
    if isinstance(val, str):
        if val.lower() in ("false", "0", "no"):
            return False
        if val.lower() in ("true", "1", "yes"):
            return True
        return val  # treat as PEM path
    return True


# ---------------------------------------------------------------------------
# State file helpers  (~/.mgw/state.json)
# ---------------------------------------------------------------------------

_STATE_SECRET_NAME = "model-gateway-cli-state"


def _get_state_namespace() -> str:
    """Return the configured namespace for cluster state sync, or empty string."""
    return get_config_value("namespace")


def _sync_state_to_cluster(s: dict[str, Any]) -> None:
    """Best-effort: write state.json into a Kubernetes Secret in the configured namespace.

    Uses kubectl apply with a Secret manifest so the operation is idempotent.
    Failures are logged as warnings only — local state is always the primary store.
    """
    import base64
    import subprocess

    namespace = _get_state_namespace()
    if not namespace:
        return

    # Strip notes array — it's large and not needed for cluster state recovery.
    state_for_cluster = {k: v for k, v in s.items() if k != "notes"}
    encoded = base64.b64encode(json.dumps(state_for_cluster, indent=2).encode()).decode()

    manifest = json.dumps({
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": _STATE_SECRET_NAME,
            "namespace": namespace,
            "labels": {"app.kubernetes.io/managed-by": "model-gateway-cli"},
        },
        "type": "Opaque",
        "data": {"state.json": encoded},
    })

    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        logger.info("State synced to cluster secret %s/%s", namespace, _STATE_SECRET_NAME)
    else:
        logger.warning(
            "Could not sync state to cluster (non-fatal): %s", result.stderr.strip()
        )


def _restore_state_from_cluster() -> dict[str, Any]:
    """Try to fetch state.json from the cluster Secret; return empty dict on any failure."""
    import base64
    import subprocess

    namespace = _get_state_namespace()
    if not namespace:
        return {}

    result = subprocess.run(
        [
            "kubectl", "get", "secret", _STATE_SECRET_NAME,
            "-n", namespace,
            "-o", "jsonpath={.data.state\\.json}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return {}

    try:
        restored = json.loads(base64.b64decode(result.stdout.strip()).decode())
        logger.info("Restored state from cluster secret %s/%s", namespace, _STATE_SECRET_NAME)
        return restored
    except Exception as exc:
        logger.warning("Failed to parse cluster state secret: %s", exc)
        return {}


def read_state() -> dict[str, Any]:
    """Read the local state file; fall back to cluster Secret if local file is missing."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            logger.exception("Failed to read state file: %s", STATE_FILE)
            return {}

    # Local file missing — try to restore from cluster.
    restored = _restore_state_from_cluster()
    if restored:
        # Persist locally so subsequent reads are fast.
        try:
            MGW_DIR.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(restored, indent=2))
            logger.info("Restored state written to %s", STATE_FILE)
        except OSError:
            pass  # Non-fatal — in-memory restored state is still returned.
    return restored


def write_state(s: dict[str, Any]) -> None:
    """Overwrite the local state file and sync to the cluster Secret."""
    try:
        MGW_DIR.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(s, indent=2))
    except OSError:
        logger.exception("Failed to write state file: %s", STATE_FILE)
        raise
    # Best-effort cluster sync — never blocks or fails the caller.
    _sync_state_to_cluster(s)


def update_tenant_state(tenant_data: dict[str, Any]) -> None:
    """Merge tenant data into the state file."""
    s = read_state()
    s["tenant"] = {
        "uuid": tenant_data.get("id") or tenant_data.get("uuid", ""),
        "name": tenant_data.get("name", ""),
        "apikey": tenant_data.get("apikey", ""),
    }
    write_state(s)


def update_provider_state(name: str, provider_data: dict[str, Any]) -> None:
    """Merge a provider entry into the state file."""
    s = read_state()
    providers = s.setdefault("providers", {})
    providers[name] = {
        "uuid": provider_data.get("uuid", ""),
        "type": provider_data.get("type", ""),
    }
    write_state(s)


def remove_provider_state(uuid: str) -> None:
    """Remove a provider from the state file by UUID."""
    s = read_state()
    providers = s.get("providers", {})
    to_remove = [k for k, v in providers.items() if v.get("uuid") == uuid]
    for k in to_remove:
        del providers[k]
    s["providers"] = providers
    write_state(s)


def get_provider_uuid_from_state(name: str) -> Optional[str]:
    """Look up a provider UUID by name from the state file."""
    return read_state().get("providers", {}).get(name, {}).get("uuid")


# ---------------------------------------------------------------------------
# Client factories (read from shared state dict)
# ---------------------------------------------------------------------------


def _admin_client() -> GatewayClient:
    """Return an authenticated admin GatewayClient, or exit with an auth error."""
    status = _token_status()
    if status == "expired":
        logger.warning("Admin client: stored token has expired")
        show_error_panel(
            _EI(
                "Authentication Failure",
                "\nYour session has expired.\n"
                "Please use '[italic]model-gateway.py login[/italic]' to authenticate again.\n",
            )
        )
        raise typer.Exit(1)
    if status == "missing":
        logger.warning("Admin client: no stored token found")
        show_error_panel(_ERR_AUTH)
        raise typer.Exit(1)
    return GatewayClient(
        state["base_url"], get_stored_token(),
        requests_verify=state.get("requests_verify", True),
    )


def _tenant_client() -> GatewayClient:
    """Return an authenticated tenant GatewayClient, or exit with an auth error.

    Token priority:
      1. Tenant API key stored in ~/.mgw/state.json  (written by ``provision`` /
         ``tenant apikey-create`` flows).
      2. Admin JWT stored in ~/.mgw/credentials  (written by ``login``).

    Provider and model endpoints require a tenant-scoped API key; they reject the
    admin JWT with HTTP 401.  Using the state-file API key here means commands like
    ``provider list`` work out of the box once a tenant has been provisioned.
    """
    # Prefer the tenant-scoped API key when available.
    tenant_apikey: str = read_state().get("tenant", {}).get("apikey", "")
    if tenant_apikey:
        logger.debug("Tenant client: using tenant API key from state file")
        return GatewayClient(
            state["base_url"], tenant_apikey,
            requests_verify=state.get("requests_verify", True),
        )

    # Fall back to the admin JWT stored by ``login``.
    status = _token_status()
    if status == "expired":
        logger.warning("Tenant client: stored token has expired")
        show_error_panel(
            _EI(
                "Authentication Failure",
                "\nYour session has expired.\n"
                "Please use '[italic]model-gateway.py login[/italic]' to authenticate again.\n",
            )
        )
        raise typer.Exit(1)
    if status == "missing":
        logger.warning("Tenant client: no stored token found — no tenant API key in state either")
        show_error_panel(
            _EI(
                "Authentication Failure",
                "\nNo tenant API key found and no active session.\n"
                "Run '[italic]model-gateway.py provision[/italic]' to set up a tenant,\n"
                "or '[italic]model-gateway.py login -u <user>[/italic]' to authenticate.\n",
            )
        )
        raise typer.Exit(1)
    return GatewayClient(
        state["base_url"], get_stored_token(),
        requests_verify=state.get("requests_verify", True),
    )


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------


def _find_existing_provider(
    client: GatewayClient, name: str, provider_type: str
) -> Optional[str]:
    """Return the UUID of an existing provider matching name+type, or None."""
    try:
        result = client.get("/v1/providers")
    except GatewayError as exc:
        logger.warning("Could not list providers while checking for '%s': %s", name, exc)
        return None
    items = result.get("data", []) if isinstance(result, dict) else (result or [])
    for p in items:
        if p.get("name") == name and p.get("type") == provider_type:
            return p.get("uuid", "")
    return None


def _find_existing_tenant(client: GatewayClient, name: str) -> Optional[dict[str, Any]]:
    """Return the first tenant dict matching name, or None."""
    try:
        result = client.get("/v1/admin/tenants")
    except GatewayError as exc:
        logger.warning("Could not list tenants while checking for '%s': %s", name, exc)
        return None
    items = result.get("data", []) if isinstance(result, dict) else (result or [])
    for t in items:
        if t.get("name") == name:
            return t
    return None


# ---------------------------------------------------------------------------
# Model helpers
# ---------------------------------------------------------------------------


def _find_existing_model(client: GatewayClient, provider_uuid: str, model_id: str) -> Optional[str]:
    """Return the UUID of a registered model matching model_id, or None."""
    try:
        result = client.get(f"/v1/providers/{provider_uuid}/models")
    except GatewayError as exc:
        logger.warning("Could not list models for provider '%s' while checking for '%s': %s", provider_uuid, model_id, exc)
        return None
    items = result.get("data", []) if isinstance(result, dict) else (result or [])
    for m in items:
        if m.get("id") == model_id:
            return m.get("uuid", "")
    return None


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def _mask(s: str, visible: int = 8) -> str:
    """Return a masked credential string for safe display."""
    if not s:
        return "(none)"
    return s[:visible] + "..." if len(s) > visible else s


def _handle_request_errors(exc: Exception, base_url: str) -> None:
    """Translate common request errors into styled messages and exit."""
    if isinstance(exc, GatewayError):
        logger.error("Gateway error (%s) from %s: %s", exc.status_code, base_url, exc)
        show_error_panel(_ERR_SERVICE, exception=exc)
    elif isinstance(exc, requests.exceptions.SSLError):
        logger.error("TLS error connecting to %s: %s", base_url, exc)
        show_error_panel(
            _EI(
                "TLS Error",
                f"Certificate verification failed for [accent]{base_url}[/accent].\n"
                "Use '[italic]model-gateway.py config url <url>[/italic]' to configure certificate trust, "
                "or pass [accent]--insecure / -k[/accent] to skip verification.",
            ),
            exception=exc,
        )
    elif isinstance(exc, requests.exceptions.ConnectionError):
        logger.error("Connection error to %s: %s", base_url, exc)
        show_error_panel(
            _EI(
                "Connection Error",
                f"Could not connect to [accent]{base_url}[/accent].\n"
                "Check that the gateway is running and the URL is correct.",
            ),
            exception=exc,
        )
    else:
        logger.error("Unexpected error from %s: %s", base_url, exc, exc_info=True)
        show_error_panel(_ERR_SERVICE, exception=exc)
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Root callback — global options
# ---------------------------------------------------------------------------


@app.callback()
def main(
    ctx: typer.Context,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose logging"),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show version and exit.",
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
    base_url: Annotated[
        Optional[str],
        typer.Option(
            "--base-url",
            metavar="URL",
            help="Gateway base URL (overrides config / MGW_BASE_URL)",
            rich_help_panel="Connection",
        ),
    ] = None,
    output: Annotated[
        str,
        typer.Option(
            "--output",
            help="Output format: [accent]json[/accent] or [accent]table[/accent]",
            rich_help_panel="Customization",
        ),
    ] = "table",
    dev: Annotated[
        bool,
        typer.Option(
            "--dev",
            help=(
                "Dev mode: automatically port-forward the model-gateway deployment "
                "so the script can reach it without a pre-existing port-forward. "
                "Requires --namespace and kubectl in PATH."
            ),
            rich_help_panel="Connection",
        ),
    ] = False,
    namespace: Annotated[
        Optional[str],
        typer.Option(
            "--namespace", "-n",
            metavar="NS",
            help="Kubernetes namespace (required with --dev).",
            rich_help_panel="Connection",
        ),
    ] = None,
) -> None:
    """[bold cyan]Model Gateway CLI[/bold cyan] — manage tenants, providers, and models."""
    logger.info(f"executing command '{ctx.invoked_subcommand}'")

    if verbose:
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        logger.addHandler(ch)
        typer.echo(f"Logging to: {LOG_FILE}")

    # --dev: spin up a kubectl port-forward and override the base URL for the
    # duration of this invocation.  The port-forward is torn down on exit via
    # ctx.call_on_close so it cleans up even if the subcommand raises.
    if dev:
        if not namespace:
            # Fall back to the namespace saved via `config namespace <ns>`
            namespace = get_config_value("namespace") or None
        if not namespace:
            _err("--namespace is required when using --dev (or run: config namespace <namespace>).")
        # Persist the namespace so state sync helpers can find the cluster Secret
        # without needing --namespace on every subsequent command.
        if namespace != get_config_value("namespace"):
            set_config_value("namespace", namespace)
            logger.info("Namespace '%s' saved to config.", namespace)
        local_port = _free_port(_DEV_LOCAL_PORT)
        _pf_ctx = _port_forward_context(namespace, local_port)
        dev_url = _pf_ctx.__enter__()
        ctx.call_on_close(lambda: _pf_ctx.__exit__(None, None, None))
        # Override URL + disable TLS verification for the local tunnel.
        base_url = dev_url
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        state["requests_verify"] = False

    resolved_url = (
        base_url
        or os.environ.get("MGW_BASE_URL", "")
        or get_config_value("url")
        or ""
    )

    if output not in ("json", "table"):
        _err("--output must be [accent]json[/accent] or [accent]table[/accent].")

    requests_verify = state.get("requests_verify") if dev else _get_requests_verify()

    # Disable urllib3 insecure-request warnings when verification is off.
    if requests_verify is False:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    state["base_url"] = resolved_url
    state["requests_verify"] = requests_verify
    state["output"] = output

    # Commands that don't interact with the gateway don't need a URL or token.
    # patch-secret validates the URL itself after reading state.
    if ctx.invoked_subcommand in ("config", "logout", "patch-secret"):
        return

    # During shell tab-completion, Typer sets resilient_parsing=True.
    # Skip all live guards so completion works without needing credentials.
    if ctx.resilient_parsing:
        return

    # Sub-app groups (tenant/provider/model) show their own help page when
    # invoked with --help; auth is validated inside each individual command via
    # _admin_client() / _tenant_client(), not at the group dispatch level.
    if ctx.invoked_subcommand in ("tenant", "provider", "model"):
        if resolved_url:
            state["base_url"] = resolved_url
        return

    # For all concrete commands (login, provision, …), require a URL.
    if not resolved_url:
        show_error_panel(_ERR_MISSING_URL)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Certificate chain helpers (mirrors ibmca certs.py — inline, no extra dep)
# ---------------------------------------------------------------------------


def _get_certificate_chain(url: str, timeout: int = 10):
    """Retrieve the SSL certificate chain from url.  Returns list or None."""
    import ssl
    import socket
    from urllib.parse import urlparse

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or 443

    try:
        from cryptography import x509 as _x509
        from cryptography.hazmat.backends import default_backend as _default_backend
    except ImportError:
        return None  # cryptography not installed — skip chain display

    certs_list = []
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                path = parsed.path or "/"
                ssock.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode())
                ssock.recv(4096)
                if hasattr(ssock, "get_peer_cert_chain"):
                    for der in (ssock.get_peer_cert_chain() or []):  # type: ignore[attr-defined]
                        certs_list.append(_x509.load_der_x509_certificate(der, _default_backend()))
                else:
                    der = ssock.getpeercert(binary_form=True)
                    if der:
                        certs_list.append(_x509.load_der_x509_certificate(der, _default_backend()))
    except Exception:
        logger.exception("Failed to retrieve certificate chain")
        return None
    return certs_list or None


def _print_cert_chain(certs_list: list) -> None:
    """Render certificate chain details as rich tables (mirrors ibmca certs.print_certs)."""
    from rich.markup import escape as _escape
    try:
        from cryptography import x509 as _x509
    except ImportError:
        return

    console.rule("[bold yellow]Certificate Chain Details")
    for i, cert in enumerate(certs_list):
        tbl = Table(title=f"[yellow]Certificate {i}", title_justify="left", show_header=False, show_lines=True)
        tbl.add_row("Subject", _escape(str(cert.subject)))
        tbl.add_row("Issuer", _escape(str(cert.issuer)))
        tbl.add_row("Serial Number", _escape(str(cert.serial_number)))
        tbl.add_row("Valid From", _escape(str(cert.not_valid_before_utc)))
        tbl.add_row("Expires", _escape(str(cert.not_valid_after_utc)))
        try:
            san = cert.extensions.get_extension_for_class(_x509.SubjectAlternativeName)
            tbl.add_row("Subject Alternative Names", _escape(str(san.value.get_values_for_type(_x509.DNSName))))
        except _x509.ExtensionNotFound:
            tbl.add_row("Subject Alternative Names", "None")
        console.print(tbl)


def _store_cert_chain(certs_list: list, pem_path: Path) -> bool:
    """Write PEM-encoded certificate chain to disk.  Returns True on success."""
    try:
        from cryptography.hazmat.primitives import serialization as _serial
        pem_path.parent.mkdir(parents=True, exist_ok=True)
        with pem_path.open("wb") as f:
            for i, cert in enumerate(certs_list):
                f.write(cert.public_bytes(_serial.Encoding.PEM))
                if i < len(certs_list) - 1:
                    f.write(b"\n")
        return True
    except Exception:
        logger.exception("Failed to store certificate chain")
        return False


def _verify_url(url: str) -> None:
    """Probe url, handle SSL errors exactly as ibmca setup.py verify_url does.

    On success stores requests_verify in config.
    On SSL failure:
      - shows cert chain
      - self-signed (len==1): prompts to trust → stores requests_verify=False
      - CA-signed but unknown (len>1): stores chain as PEM, prompts to trust →
        stores requests_verify=<pem_path>
    Raises typer.Exit on any unresolvable error.
    """
    try:
        response = requests.get(url)
        response.raise_for_status()
        set_config_value("requests_verify", True)
    except requests.exceptions.SSLError as e:
        if "CERTIFICATE_VERIFY_FAILED" in str(e) or "certificate verify failed" in str(e).lower():
            typer.echo(typer.style("The service's SSL certificate failed validation", fg=typer.colors.YELLOW))
            certs_chain = _get_certificate_chain(url)
            if certs_chain is None:
                typer.echo(typer.style("Could not get the service's SSL certificate chain", fg=typer.colors.RED))
                raise typer.Exit(1)

            _print_cert_chain(certs_chain)

            from rich.prompt import Confirm
            if len(certs_chain) == 1:
                typer.echo(typer.style(
                    "The service is using the above SSL certificate not signed by a known Certificate Authority",
                    fg=typer.colors.YELLOW,
                ))
                if Confirm.ask("[yellow]Do you want to trust it?"):
                    set_config_value("requests_verify", False)
                else:
                    raise typer.Exit(1)
            else:
                pem_path = MGW_DIR / "certs.pem"
                if not _store_cert_chain(certs_chain, pem_path):
                    show_error_panel(_ERR_CERT)
                    raise typer.Exit(1)

                resp2 = requests.get(url, verify=str(pem_path.resolve()))
                if resp2.status_code == 200:
                    typer.echo(typer.style(
                        "The service's above SSL certificate chain is from an unknown Certificate Authority",
                        fg=typer.colors.YELLOW,
                    ))
                    if Confirm.ask("[yellow]Do you want to trust it?"):
                        set_config_value("requests_verify", str(pem_path.resolve()))
                    else:
                        raise typer.Exit(1)
                else:
                    show_error_panel(_ERR_CERT)
                    raise typer.Exit(1)
        else:
            show_error_panel(
                _EI("SSL Error", f"An SSL error occurred connecting to {url}"),
                exception=e,
            )
            raise typer.Exit(1)
    except requests.exceptions.RequestException as e:
        show_error_panel(_ERR_SERVICE, exception=e)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# config command
# ---------------------------------------------------------------------------


@app.command("config")
def cmd_config(
    key: Annotated[
        Optional[str],
        typer.Argument(
            help=f"Configuration key to view or set. Supported: {', '.join(_CONFIG_KEYS)}",
            metavar="KEY",
        ),
    ] = None,
    key_value: Annotated[
        Optional[str],
        typer.Argument(
            help="Value to assign to KEY. Omit to display the current value.",
            metavar="VALUE",
        ),
    ] = None,
) -> None:
    """Sets or gets local configuration values.

    If no arguments are specified, the values for all configuration keys are displayed.
    If a key name is provided its value will be displayed.
    If a key name and a value is provided, the key will be updated with the value.

    [green]Example:[/] Set the gateway URL:

    [code]model-gateway.py config url https://gateway-host:8080[/]

    [green]Example:[/] View the configured URL:

    [code]model-gateway.py config url[/]
    """
    try:
        if key is None:
            cfg = read_config()
            if not cfg:
                typer.echo("No configuration values exist")
            else:
                for k, v in cfg.items():
                    typer.echo(
                        f"{typer.style(k, fg=typer.colors.BLUE, bold=True)}: "
                        f"{typer.style(str(v), italic=True)}"
                    )
            return

        if key_value is None:
            cfg = read_config()
            if key in cfg:
                typer.echo(
                    f"{typer.style(key, fg=typer.colors.BLUE, bold=True)}: "
                    f"{typer.style(str(cfg[key]), italic=True)}"
                )
            else:
                typer.echo(f"No configuration key named {key} exists")
            return

        # Setting a value — just persist it, no network probe.
        # Connectivity is validated at login time, not here.
        set_config_value(key, key_value)

    except typer.Exit:
        logger.info(f"Exiting without saving config: [{key} : {key_value}]")
        raise
    except Exception as e:
        show_error_panel(_ERR_CONFIG, exception=e)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# login command
# ---------------------------------------------------------------------------


@app.command("login")
def cmd_login(
    token: Annotated[
        str,
        typer.Option(
            "-t", "--token",
            help="API token",
            prompt=True,
            hide_input=True,
            show_default=False,
        ),
    ],
) -> None:
    """Authenticate with the Model Gateway and store credentials locally.

    The token is verified by calling GET /v1/admin/tenants — a 200 response confirms it is valid.

    Use [code]model-gateway.py config url https://gateway-url[/] to set the gateway URL.

    \b
    Examples:
      model-gateway.py login
      model-gateway.py login -t <token>
    """
    base_url = state["base_url"]
    requests_verify = state.get("requests_verify", True)

    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/v1/admin/tenants",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=15,
            verify=requests_verify,
        )

        if resp.status_code == 200:
            write_credentials({"token": token, "expires_at": 0})
            logger.info("Login successful")
            typer.echo(typer.style("Login successful", fg=typer.colors.GREEN))

        elif resp.status_code == 401:
            logger.warning("Login failed: 401 Unauthorized")
            show_error_panel(
                _EI("Login Failure", "Please check the provided token.")
            )
            raise typer.Exit(1)
        else:
            logger.error("Login failed: HTTP %s", resp.status_code)
            resp.raise_for_status()

    except requests.exceptions.SSLError as e:
        show_error_panel(
            _EI(
                "Login Failure",
                "The service's SSL certificate failed validation.\n"
                "Use '[italic]model-gateway.py config url <url>[/italic]' to configure certificate trust.",
            ),
            exception=e,
        )
        raise typer.Exit(1)
    except requests.exceptions.RequestException as e:
        show_error_panel(
            _EI("Login Failure", "The service sent an error response."),
            exception=e,
        )
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# logout command
# ---------------------------------------------------------------------------


@app.command("logout")
def cmd_logout() -> None:
    """Remove stored credentials (log out of the Model Gateway).

    \b
    Example:
      model-gateway.py logout
    """
    try:
        clear_credentials()
    except Exception:
        logger.exception("Error logging out")
        typer.echo(typer.style("Failed to delete access token", fg=typer.colors.RED))


# ---------------------------------------------------------------------------
# tenant commands
# ---------------------------------------------------------------------------


@tenant_app.command("create")
def tenant_create(
    name: Annotated[str, typer.Argument(help="Tenant name")],
) -> None:
    """Create a new tenant."""
    try:
        client = _admin_client()
        with _spinner(f"Creating tenant '{name}'..."):
            result = client.post("/v1/admin/tenants", {"name": name})
        update_tenant_state(result)
        _ok(f"Tenant [accent]{name}[/accent] created  [muted](state → {STATE_FILE})[/muted]")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@tenant_app.command("list")
def tenant_list() -> None:
    """List all tenants."""
    try:
        client = _admin_client()
        with _spinner("Fetching tenants..."):
            result = client.get("/v1/admin/tenants")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@tenant_app.command("get")
def tenant_get(
    uuid: Annotated[str, typer.Argument(help="Tenant UUID")],
) -> None:
    """Get a tenant by UUID."""
    try:
        client = _admin_client()
        with _spinner(f"Fetching tenant {uuid}..."):
            result = client.get(f"/v1/admin/tenants/{uuid}")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@tenant_app.command("delete")
def tenant_delete(
    uuid: Annotated[str, typer.Argument(help="Tenant UUID")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a tenant by UUID."""
    if not yes:
        # Fetch the tenant name so the confirmation is human-readable.
        try:
            client = _admin_client()
            with _spinner(f"Fetching tenant {uuid}..."):
                tenant_info = client.get(f"/v1/admin/tenants/{uuid}")
            display = tenant_info.get("name", uuid) if isinstance(tenant_info, dict) else uuid
        except Exception:
            display = uuid

        confirmed = questionary.confirm(
            f"Delete tenant '{display}' ({uuid})? This cannot be undone.",
            default=False,
            style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)

    try:
        client = _admin_client()
        with _spinner(f"Deleting tenant {uuid}..."):
            client.delete(f"/v1/admin/tenants/{uuid}")
        _ok(f"Tenant [uuid]{uuid}[/uuid] deleted")
        s = read_state()
        if s.get("tenant", {}).get("uuid") == uuid:
            s.pop("tenant", None)
            write_state(s)
            _info(f"State file updated: {STATE_FILE}")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# provider commands
# ---------------------------------------------------------------------------


@provider_app.command("create")
def provider_create(
    provider_type: Annotated[
        str,
        typer.Argument(
            metavar="TYPE",
            help=f"Provider type. Supported: {', '.join(sorted(PROVIDER_TYPES))}",
        ),
    ],
    name: Annotated[str, typer.Argument(help="Provider display name")],
    description: Annotated[
        str,
        typer.Option("--description", metavar="TEXT", help="Optional description"),
    ] = "",
) -> None:
    """Create a provider (credentials read from env vars or prompted interactively).

    If an environment variable listed below is set it is used silently.
    If it is not set, the script prompts you to enter the value interactively.

    \b
    azure-openai
      AZURE_OPENAI_API_KEY          API key (required)
      AZURE_OPENAI_RESOURCE_NAME    Azure resource name (required)
      AZURE_OPENAI_API_VERSION      API version (required, prompted if not set)

    \b
    watsonxai
      WATSONXAI_API_KEY             API key (required)
      WATSONXAI_BASE_URL            Base URL (default: https://us-south.ml.cloud.ibm.com)
      WATSONXAI_SPACE_ID            Deployment space ID (optional, prompted if blank)
      WATSONXAI_PROJECT_ID          Project ID (optional, prompted if blank)
      WATSONXAI_AUTH_URL            Custom auth URL (optional, env-var only)

    \b
    openai
      OPENAI_API_KEY                API key (required)
      OPENAI_BASE_URL               Base URL (default: https://api.openai.com/v1)

    \b
    anthropic
      ANTHROPIC_API_KEY             API key (required)

    \b
    bedrock
      AWS_ACCESS_KEY_ID             Access key ID (required)
      AWS_SECRET_ACCESS_KEY         Secret access key (required)
      AWS_REGION                    Region (default: us-east-1)
      AWS_SESSION_TOKEN             Session token (optional)

    \b
    gemini
      GEMINI_API_KEY                API key (required)

    \b
    mistral
      MISTRAL_API_KEY               API key (required)

    \b
    groq
      GROQ_API_KEY                  API key (required)

    \b
    ollama
      OLLAMA_HOST                   Host URL (default: http://127.0.0.1:11434)

    \b
    cohere
      COHERE_API_KEY                API key (required)

    \b
    adobe-firefly
      ADOBE_FIREFLY_CLIENT_ID       Client ID (required)
      ADOBE_FIREFLY_CLIENT_SECRET   Client secret (required)
    """
    provider_type = provider_type.lower()
    if provider_type not in PROVIDER_TYPES:
        _err(
            f"Unknown provider type [accent]{provider_type}[/accent].\n"
            f"Supported: {', '.join(sorted(PROVIDER_TYPES))}"
        )

    try:
        client = _tenant_client()
        with _spinner(f"Checking for existing provider '{name}'..."):
            existing_uuid = _find_existing_provider(client, name, provider_type)
        if existing_uuid:
            _warn(
                f"Provider [accent]{name}[/accent] ([muted]{provider_type}[/muted]) already exists"
                f" — UUID: [uuid]{existing_uuid}[/uuid]  [muted](skipped)[/muted]"
            )
            update_provider_state(name, {"uuid": existing_uuid, "type": provider_type})
            return

        data = _resolve_provider_data(provider_type)
        payload: dict[str, Any] = {"name": name, "data": data}
        if description:
            payload["description"] = description

        with _spinner(f"Creating provider '{name}'..."):
            result = client.post(f"/v1/providers/{PROVIDER_TYPES[provider_type]}", payload)
        update_provider_state(name, result)
        _ok(f"Provider [accent]{name}[/accent] created  [muted](state → {STATE_FILE})[/muted]")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


def _print_providers(data: "list[dict] | dict", output_fmt: str) -> None:
    """Render providers as a clean table (model IDs as a list, data column omitted).

    Falls back to raw JSON when --output json is requested.
    """
    if output_fmt == "json":
        _print_output(data, output_fmt)
        return

    rows = data if isinstance(data, list) else [data]
    if not rows:
        _info("No providers found.")
        return

    tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="header", show_edge=False)
    tbl.add_column("UUID", overflow="fold", style="uuid")
    tbl.add_column("NAME", overflow="fold", style="accent")
    tbl.add_column("TYPE", overflow="fold")
    tbl.add_column("MODELS", overflow="fold")
    tbl.add_column("DESCRIPTION", overflow="fold", style="muted")

    for row in rows:
        models = row.get("models") or []
        model_ids = ", ".join(m.get("id", "") or m.get("alias", "") for m in models) or "[dim]—[/dim]"
        tbl.add_row(
            row.get("uuid", ""),
            row.get("name", ""),
            row.get("type_display_name", "") or row.get("type", ""),
            model_ids,
            row.get("description", ""),
        )

    console.print(tbl)


@provider_app.command("list")
def provider_list() -> None:
    """List all providers for the current tenant."""
    try:
        client = _tenant_client()
        with _spinner("Fetching providers..."):
            result = client.get("/v1/providers")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_providers(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@provider_app.command("get")
def provider_get(
    uuid: Annotated[str, typer.Argument(help="Provider UUID")],
) -> None:
    """Get a provider by UUID."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching provider {uuid}..."):
            result = client.get(f"/v1/providers/{uuid}")
        _print_providers(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@provider_app.command("validate")
def provider_validate(
    provider_type: Annotated[
        str,
        typer.Argument(
            metavar="TYPE",
            help=f"Provider type to validate. Supported: {', '.join(sorted(PROVIDER_TYPES))}",
        ),
    ],
) -> None:
    """Validate provider credentials without creating a provider."""
    provider_type = provider_type.lower()
    if provider_type not in PROVIDER_TYPES:
        _err(
            f"Unknown provider type [accent]{provider_type}[/accent].\n"
            f"Supported: {', '.join(sorted(PROVIDER_TYPES))}"
        )

    try:
        client = _tenant_client()
        data = _resolve_provider_data(provider_type)
        with _spinner(f"Validating {provider_type} credentials..."):
            result = client.post("/v1/providers/validate", {"type": provider_type, "data": data})
        _ok(f"Credentials for [accent]{provider_type}[/accent] are valid")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@provider_app.command("delete")
def provider_delete(
    uuid: Annotated[str, typer.Argument(help="Provider UUID")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a provider by UUID."""
    if not yes:
        # Fetch the provider name so the confirmation is human-readable.
        try:
            client = _tenant_client()
            with _spinner(f"Fetching provider {uuid}..."):
                provider_info = client.get(f"/v1/providers/{uuid}")
            display = provider_info.get("name", uuid) if isinstance(provider_info, dict) else uuid
        except Exception:
            display = uuid

        confirmed = questionary.confirm(
            f"Delete provider '{display}' ({uuid})? This cannot be undone.",
            default=False,
            style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)

    try:
        client = _tenant_client()
        with _spinner(f"Deleting provider {uuid}..."):
            client.delete(f"/v1/providers/{uuid}")
        _ok(f"Provider [uuid]{uuid}[/uuid] deleted")
        remove_provider_state(uuid)
        _info(f"State file updated: {STATE_FILE}")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# model commands
# ---------------------------------------------------------------------------


@model_app.command("add")
def model_add(
    provider_uuid: Annotated[str, typer.Argument(help="Provider UUID")],
    model_id: Annotated[str, typer.Argument(help="Upstream model ID (e.g. gpt-4.1-2025-04-14)")],
    alias: Annotated[
        str,
        typer.Option("--alias", metavar="ALIAS", help=(
            "Optional alias for the model. When set, the Model Gateway inference API "
            "routes on the alias — patch-secret will write the alias (not the model id) "
            "into ibm-providers-config-secret."
        )),
    ] = "",
    description: Annotated[
        str,
        typer.Option("--description", metavar="TEXT", help="Optional description"),
    ] = "",
    metadata: Annotated[
        str,
        typer.Option("--metadata", metavar="JSON", help="Optional metadata as JSON string"),
    ] = "",
) -> None:
    """Register a model under a provider."""
    try:
        client = _tenant_client()
        with _spinner(f"Checking for existing model '{model_id}'..."):
            existing_uuid = _find_existing_model(client, provider_uuid, model_id)
        if existing_uuid:
            _warn(
                f"Model [accent]{model_id}[/accent] already registered"
                f" — UUID: [uuid]{existing_uuid}[/uuid]  [muted](skipped)[/muted]"
            )
            return

        payload: dict[str, Any] = {"id": model_id}
        if alias:
            payload["alias"] = alias
        if description:
            payload["description"] = description
        if metadata:
            try:
                payload["metadata"] = json.loads(metadata)
            except json.JSONDecodeError as exc:
                _err(f"--metadata is not valid JSON: {exc}")

        with _spinner(f"Registering model '{model_id}'..."):
            result = client.post(f"/v1/providers/{provider_uuid}/models", payload)
        _ok(f"Model [accent]{model_id}[/accent] added")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@model_app.command("list")
def model_list(
    provider_uuid: Annotated[str, typer.Argument(help="Provider UUID")],
) -> None:
    """List registered models for a provider."""
    try:
        client = _tenant_client()
        with _spinner("Fetching models..."):
            result = client.get(f"/v1/providers/{provider_uuid}/models")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@model_app.command("available")
def model_available(
    provider_uuid: Annotated[str, typer.Argument(help="Provider UUID")],
) -> None:
    """List available upstream models for a provider."""
    try:
        client = _tenant_client()
        with _spinner("Fetching available models..."):
            result = client.get(f"/v1/providers/{provider_uuid}/models/available")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@model_app.command("list-all")
def model_list_all() -> None:
    """List all models across all providers."""
    try:
        client = _tenant_client()
        with _spinner("Fetching all models..."):
            result = client.get("/v1/models")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@model_app.command("delete")
def model_delete(
    provider_uuid: Annotated[str, typer.Argument(help="Provider UUID")],
    model_uuid: Annotated[str, typer.Argument(help="Model UUID")],
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
) -> None:
    """Delete a model from a provider."""
    if not yes:
        # Fetch the model id/alias so the confirmation is human-readable.
        try:
            client = _tenant_client()
            with _spinner(f"Fetching model {model_uuid}..."):
                model_info = client.get(f"/v1/providers/{provider_uuid}/models/{model_uuid}")
            display = model_info.get("alias") or model_info.get("id", model_uuid) if isinstance(model_info, dict) else model_uuid
        except Exception:
            display = model_uuid

        confirmed = questionary.confirm(
            f"Delete model '{display}' ({model_uuid}) from provider {provider_uuid}? This cannot be undone.",
            default=False,
            style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)

    try:
        client = _tenant_client()
        with _spinner(f"Deleting model {model_uuid}..."):
            client.delete(f"/v1/providers/{provider_uuid}/models/{model_uuid}")
        _ok(f"Model [uuid]{model_uuid}[/uuid] deleted from provider [uuid]{provider_uuid}[/uuid]")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# tenant update command
# ---------------------------------------------------------------------------


@tenant_app.command("update")
def tenant_update(
    uuid: Annotated[str, typer.Argument(help="Tenant UUID")],
    name: Annotated[str, typer.Option("--name", "-n", help="New tenant name", show_default=False)],
) -> None:
    """Update a tenant's name."""
    try:
        client = _admin_client()
        with _spinner(f"Updating tenant {uuid}..."):
            result = client.patch(f"/v1/admin/tenants/{uuid}", {"name": name})
        _ok(f"Tenant [uuid]{uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# tenant apikey commands (admin)
# ---------------------------------------------------------------------------


@tenant_app.command("apikey-list")
def tenant_apikey_list(
    uuid: Annotated[str, typer.Argument(help="Tenant UUID")],
) -> None:
    """List all API keys for a tenant."""
    try:
        client = _admin_client()
        with _spinner(f"Fetching API keys for tenant {uuid}..."):
            result = client.get(f"/v1/admin/tenants/{uuid}/apikey")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@tenant_app.command("apikey-create")
def tenant_apikey_create(
    uuid: Annotated[str, typer.Argument(help="Tenant UUID")],
    description: Annotated[str, typer.Option("--description", "-d", help="Key description", show_default=False)] = "",
) -> None:
    """Create a new API key for a tenant."""
    payload: dict[str, Any] = {}
    if description:
        payload["description"] = description
    try:
        client = _admin_client()
        with _spinner(f"Creating API key for tenant {uuid}..."):
            result = client.post(f"/v1/admin/tenants/{uuid}/apikey", payload)
        _ok(f"API key created for tenant [uuid]{uuid}[/uuid]")
        _print_output(result, state["output"])

        # Persist the new API key into state so _tenant_client() can use it
        # immediately for provider / model / user commands.
        apikey_value: str = ""
        if isinstance(result, dict):
            apikey_value = result.get("apikey", "") or result.get("key", "")
        if apikey_value:
            s = read_state()
            tenant_entry = s.setdefault("tenant", {})
            tenant_entry["uuid"] = tenant_entry.get("uuid") or uuid
            tenant_entry["apikey"] = apikey_value
            write_state(s)
            _info(f"Tenant API key saved to {STATE_FILE} — provider/model commands are now ready.")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@tenant_app.command("apikey-delete")
def tenant_apikey_delete(
    uuid: Annotated[str, typer.Argument(help="Tenant UUID")],
    key_uuid: Annotated[str, typer.Argument(help="API key UUID")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete an API key from a tenant."""
    if not yes:
        confirmed = questionary.confirm(
            f"Delete API key '{key_uuid}' from tenant '{uuid}'? This cannot be undone.",
            default=False, style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    try:
        client = _admin_client()
        with _spinner(f"Deleting API key {key_uuid}..."):
            client.delete(f"/v1/admin/tenants/{uuid}/apikey/{key_uuid}")
        _ok(f"API key [uuid]{key_uuid}[/uuid] deleted")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@tenant_app.command("apikey-update")
def tenant_apikey_update(
    uuid: Annotated[str, typer.Argument(help="Tenant UUID")],
    key_uuid: Annotated[str, typer.Argument(help="API key UUID")],
    description: Annotated[str, typer.Option("--description", "-d", help="New description", show_default=False)] = "",
) -> None:
    """Update the description of a tenant API key."""
    try:
        client = _admin_client()
        with _spinner(f"Updating API key {key_uuid}..."):
            result = client.patch(f"/v1/admin/tenants/{uuid}/apikey/{key_uuid}", {"description": description})
        _ok(f"API key [uuid]{key_uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# model get / update commands
# ---------------------------------------------------------------------------


@model_app.command("get")
def model_get(
    provider_uuid: Annotated[str, typer.Argument(help="Provider UUID")],
    model_uuid: Annotated[str, typer.Argument(help="Model UUID")],
) -> None:
    """Get a model by UUID."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching model {model_uuid}..."):
            result = client.get(f"/v1/providers/{provider_uuid}/models/{model_uuid}")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@model_app.command("update")
def model_update(
    provider_uuid: Annotated[str, typer.Argument(help="Provider UUID")],
    model_uuid: Annotated[str, typer.Argument(help="Model UUID")],
    alias: Annotated[str, typer.Option("--alias", help="New alias", show_default=False)] = "",
    description: Annotated[str, typer.Option("--description", help="New description", show_default=False)] = "",
) -> None:
    """Update a model's alias or description."""
    payload: dict[str, Any] = {}
    if alias:
        payload["alias"] = alias
    if description:
        payload["description"] = description
    if not payload:
        _err("Provide at least --alias or --description.")
    try:
        client = _tenant_client()
        with _spinner(f"Updating model {model_uuid}..."):
            result = client.patch(f"/v1/providers/{provider_uuid}/models/{model_uuid}", payload)
        _ok(f"Model [uuid]{model_uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# user commands
# ---------------------------------------------------------------------------


@user_app.command("create")
def user_create(
    name: Annotated[str, typer.Argument(help="User name")],
) -> None:
    """Create a new user."""
    try:
        client = _tenant_client()
        with _spinner(f"Creating user '{name}'..."):
            result = client.post("/v1/users", {"name": name})
        _ok(f"User [accent]{name}[/accent] created")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("list")
def user_list() -> None:
    """List all users."""
    try:
        client = _tenant_client()
        with _spinner("Fetching users..."):
            result = client.get("/v1/users")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("get")
def user_get(
    uuid: Annotated[str, typer.Argument(help="User UUID")],
) -> None:
    """Get a user by UUID."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching user {uuid}..."):
            result = client.get(f"/v1/users/{uuid}")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("update")
def user_update(
    uuid: Annotated[str, typer.Argument(help="User UUID")],
    name: Annotated[str, typer.Option("--name", "-n", help="New user name", show_default=False)],
) -> None:
    """Update a user's name."""
    try:
        client = _tenant_client()
        with _spinner(f"Updating user {uuid}..."):
            result = client.patch(f"/v1/users/{uuid}", {"name": name})
        _ok(f"User [uuid]{uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("delete")
def user_delete(
    uuid: Annotated[str, typer.Argument(help="User UUID")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete a user by UUID."""
    if not yes:
        try:
            client = _tenant_client()
            info = client.get(f"/v1/users/{uuid}")
            display = info.get("name", uuid) if isinstance(info, dict) else uuid
        except Exception:
            display = uuid
        confirmed = questionary.confirm(
            f"Delete user '{display}' ({uuid})? This cannot be undone.",
            default=False, style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    try:
        client = _tenant_client()
        with _spinner(f"Deleting user {uuid}..."):
            client.delete(f"/v1/users/{uuid}")
        _ok(f"User [uuid]{uuid}[/uuid] deleted")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("apikey-list")
def user_apikey_list(
    uuid: Annotated[str, typer.Argument(help="User UUID")],
) -> None:
    """List API keys for a user."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching API keys for user {uuid}..."):
            result = client.get(f"/v1/users/{uuid}/apikeys")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("apikey-create")
def user_apikey_create(
    uuid: Annotated[str, typer.Argument(help="User UUID")],
    description: Annotated[str, typer.Option("--description", "-d", help="Key description", show_default=False)] = "",
) -> None:
    """Create an API key for a user."""
    payload: dict[str, Any] = {}
    if description:
        payload["description"] = description
    try:
        client = _tenant_client()
        with _spinner(f"Creating API key for user {uuid}..."):
            result = client.post(f"/v1/users/{uuid}/apikeys", payload or None)
        _ok(f"API key created for user [uuid]{uuid}[/uuid]")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("apikey-delete")
def user_apikey_delete(
    uuid: Annotated[str, typer.Argument(help="User UUID")],
    key_uuid: Annotated[str, typer.Argument(help="API key UUID")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete a user API key."""
    if not yes:
        confirmed = questionary.confirm(
            f"Delete API key '{key_uuid}' from user '{uuid}'? This cannot be undone.",
            default=False, style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    try:
        client = _tenant_client()
        with _spinner(f"Deleting API key {key_uuid}..."):
            client.delete(f"/v1/users/{uuid}/apikeys/{key_uuid}")
        _ok(f"API key [uuid]{key_uuid}[/uuid] deleted")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@user_app.command("apikey-update")
def user_apikey_update(
    uuid: Annotated[str, typer.Argument(help="User UUID")],
    key_uuid: Annotated[str, typer.Argument(help="API key UUID")],
    description: Annotated[str, typer.Option("--description", "-d", help="New description", show_default=False)] = "",
) -> None:
    """Update a user API key's description."""
    try:
        client = _tenant_client()
        with _spinner(f"Updating API key {key_uuid}..."):
            result = client.patch(f"/v1/users/{uuid}/apikeys/{key_uuid}", {"description": description})
        _ok(f"API key [uuid]{key_uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# policy commands
# ---------------------------------------------------------------------------


@policy_app.command("create")
def policy_create(
    subject: Annotated[str, typer.Argument(help="Policy subject")],
    action: Annotated[str, typer.Argument(help="Policy action")],
    resource: Annotated[str, typer.Argument(help="Policy resource")],
    effect: Annotated[str, typer.Option("--effect", help="allow or deny")] = "allow",
) -> None:
    """Create a new policy."""
    try:
        client = _tenant_client()
        with _spinner("Creating policy..."):
            result = client.post("/v1/policies", {"subject": subject, "action": action, "resource": resource, "effect": effect})
        _ok("Policy created")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@policy_app.command("list")
def policy_list() -> None:
    """List all policies."""
    try:
        client = _tenant_client()
        with _spinner("Fetching policies..."):
            result = client.get("/v1/policies")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@policy_app.command("get")
def policy_get(
    uuid: Annotated[str, typer.Argument(help="Policy UUID")],
) -> None:
    """Get a policy by UUID."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching policy {uuid}..."):
            result = client.get(f"/v1/policies/{uuid}")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@policy_app.command("update")
def policy_update(
    uuid: Annotated[str, typer.Argument(help="Policy UUID")],
    subject: Annotated[str, typer.Option("--subject", help="New subject", show_default=False)] = "",
    action: Annotated[str, typer.Option("--action", help="New action", show_default=False)] = "",
    resource: Annotated[str, typer.Option("--resource", help="New resource", show_default=False)] = "",
    effect: Annotated[str, typer.Option("--effect", help="New effect", show_default=False)] = "",
) -> None:
    """Update a policy."""
    payload: dict[str, Any] = {}
    if subject:
        payload["subject"] = subject
    if action:
        payload["action"] = action
    if resource:
        payload["resource"] = resource
    if effect:
        payload["effect"] = effect
    if not payload:
        _err("Provide at least one of --subject, --action, --resource, --effect.")
    try:
        client = _tenant_client()
        with _spinner(f"Updating policy {uuid}..."):
            result = client.put(f"/v1/policies/{uuid}", payload)
        _ok(f"Policy [uuid]{uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@policy_app.command("delete")
def policy_delete(
    uuid: Annotated[str, typer.Argument(help="Policy UUID")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete a policy by UUID."""
    if not yes:
        confirmed = questionary.confirm(
            f"Delete policy '{uuid}'? This cannot be undone.",
            default=False, style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    try:
        client = _tenant_client()
        with _spinner(f"Deleting policy {uuid}..."):
            client.delete(f"/v1/policies/{uuid}")
        _ok(f"Policy [uuid]{uuid}[/uuid] deleted")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# rate-limit commands
# ---------------------------------------------------------------------------


@ratelimit_app.command("create")
def ratelimit_create(
    config: Annotated[str, typer.Argument(help="Rate-limit config as a JSON string")],
) -> None:
    """Create a rate-limit configuration (pass full JSON payload as argument)."""
    try:
        payload = json.loads(config)
    except json.JSONDecodeError as exc:
        _err(f"Invalid JSON: {exc}")
        return
    try:
        client = _tenant_client()
        with _spinner("Creating rate-limit..."):
            result = client.post("/v1/rate-limits", payload)
        _ok("Rate-limit created")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@ratelimit_app.command("list")
def ratelimit_list() -> None:
    """List all rate-limit configurations."""
    try:
        client = _tenant_client()
        with _spinner("Fetching rate-limits..."):
            result = client.get("/v1/rate-limits")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@ratelimit_app.command("get")
def ratelimit_get(
    uuid: Annotated[str, typer.Argument(help="Rate-limit UUID")],
) -> None:
    """Get a rate-limit configuration by UUID."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching rate-limit {uuid}..."):
            result = client.get(f"/v1/rate-limits/{uuid}")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@ratelimit_app.command("update")
def ratelimit_update(
    uuid: Annotated[str, typer.Argument(help="Rate-limit UUID")],
    config: Annotated[str, typer.Argument(help="Updated config as a JSON string")],
) -> None:
    """Update a rate-limit configuration (pass full JSON payload as argument)."""
    try:
        payload = json.loads(config)
    except json.JSONDecodeError as exc:
        _err(f"Invalid JSON: {exc}")
        return
    try:
        client = _tenant_client()
        with _spinner(f"Updating rate-limit {uuid}..."):
            result = client.put(f"/v1/rate-limits/{uuid}", payload)
        _ok(f"Rate-limit [uuid]{uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@ratelimit_app.command("delete")
def ratelimit_delete(
    uuid: Annotated[str, typer.Argument(help="Rate-limit UUID")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete a rate-limit configuration."""
    if not yes:
        confirmed = questionary.confirm(
            f"Delete rate-limit '{uuid}'? This cannot be undone.",
            default=False, style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    try:
        client = _tenant_client()
        with _spinner(f"Deleting rate-limit {uuid}..."):
            client.delete(f"/v1/rate-limits/{uuid}")
        _ok(f"Rate-limit [uuid]{uuid}[/uuid] deleted")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# load-balancer commands
# ---------------------------------------------------------------------------


@lb_app.command("create")
def lb_create(
    name: Annotated[str, typer.Argument(help="Load-balancer name")],
    alias: Annotated[str, typer.Argument(help="Load-balancer alias")],
    algorithm: Annotated[str, typer.Option("--algorithm", "-a", help="Balancing algorithm (e.g. round-robin)")] = "round-robin",
) -> None:
    """Create a new load balancer."""
    try:
        client = _tenant_client()
        with _spinner(f"Creating load-balancer '{name}'..."):
            result = client.post("/v1/load-balancers", {"name": name, "alias": alias, "algorithm": algorithm})
        _ok(f"Load-balancer [accent]{name}[/accent] created")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("list")
def lb_list() -> None:
    """List all load balancers."""
    try:
        client = _tenant_client()
        with _spinner("Fetching load-balancers..."):
            result = client.get("/v1/load-balancers")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("get")
def lb_get(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
) -> None:
    """Get a load balancer by UUID."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching load-balancer {uuid}..."):
            result = client.get(f"/v1/load-balancers/{uuid}")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("update")
def lb_update(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
    name: Annotated[str, typer.Option("--name", "-n", help="New name", show_default=False)] = "",
    algorithm: Annotated[str, typer.Option("--algorithm", "-a", help="New algorithm", show_default=False)] = "",
) -> None:
    """Update a load balancer."""
    payload: dict[str, Any] = {}
    if name:
        payload["name"] = name
    if algorithm:
        payload["algorithm"] = algorithm
    if not payload:
        _err("Provide at least --name or --algorithm.")
    try:
        client = _tenant_client()
        with _spinner(f"Updating load-balancer {uuid}..."):
            result = client.put(f"/v1/load-balancers/{uuid}", payload)
        _ok(f"Load-balancer [uuid]{uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("delete")
def lb_delete(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete a load balancer."""
    if not yes:
        confirmed = questionary.confirm(
            f"Delete load-balancer '{uuid}'? This cannot be undone.",
            default=False, style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    try:
        client = _tenant_client()
        with _spinner(f"Deleting load-balancer {uuid}..."):
            client.delete(f"/v1/load-balancers/{uuid}")
        _ok(f"Load-balancer [uuid]{uuid}[/uuid] deleted")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("backend-list")
def lb_backend_list(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
) -> None:
    """List backends for a load balancer."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching backends for load-balancer {uuid}..."):
            result = client.get(f"/v1/load-balancers/{uuid}/backends")
        rows = result.get("data", result) if isinstance(result, dict) else result
        _print_output(rows, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("backend-create")
def lb_backend_create(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
    model_uuid: Annotated[str, typer.Argument(help="Model UUID to add as backend")],
    weight: Annotated[int, typer.Option("--weight", "-w", help="Backend weight")] = 1,
    priority: Annotated[int, typer.Option("--priority", "-p", help="Backend priority")] = 0,
) -> None:
    """Add a model as a backend to a load balancer."""
    try:
        client = _tenant_client()
        with _spinner(f"Adding backend {model_uuid} to load-balancer {uuid}..."):
            result = client.post(
                f"/v1/load-balancers/{uuid}/backends",
                {"model_uuid": model_uuid, "weight": weight, "priority": priority},
            )
        _ok(f"Backend [uuid]{model_uuid}[/uuid] added to load-balancer [uuid]{uuid}[/uuid]")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("backend-get")
def lb_backend_get(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
    backend_uuid: Annotated[str, typer.Argument(help="Backend UUID")],
) -> None:
    """Get a specific backend of a load balancer."""
    try:
        client = _tenant_client()
        with _spinner(f"Fetching backend {backend_uuid}..."):
            result = client.get(f"/v1/load-balancers/{uuid}/backends/{backend_uuid}")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("backend-update")
def lb_backend_update(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
    backend_uuid: Annotated[str, typer.Argument(help="Backend UUID")],
    weight: Annotated[int, typer.Option("--weight", "-w", help="New weight", show_default=False)] = 0,
    priority: Annotated[int, typer.Option("--priority", "-p", help="New priority", show_default=False)] = -1,
) -> None:
    """Update a load-balancer backend."""
    payload: dict[str, Any] = {}
    if weight:
        payload["weight"] = weight
    if priority >= 0:
        payload["priority"] = priority
    if not payload:
        _err("Provide at least --weight or --priority.")
    try:
        client = _tenant_client()
        with _spinner(f"Updating backend {backend_uuid}..."):
            result = client.put(f"/v1/load-balancers/{uuid}/backends/{backend_uuid}", payload)
        _ok(f"Backend [uuid]{backend_uuid}[/uuid] updated")
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


@lb_app.command("backend-delete")
def lb_backend_delete(
    uuid: Annotated[str, typer.Argument(help="Load-balancer UUID")],
    backend_uuid: Annotated[str, typer.Argument(help="Backend UUID")],
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """Delete a backend from a load balancer."""
    if not yes:
        confirmed = questionary.confirm(
            f"Delete backend '{backend_uuid}' from load-balancer '{uuid}'? This cannot be undone.",
            default=False, style=_Q_STYLE,
        ).ask()
        if not confirmed:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    try:
        client = _tenant_client()
        with _spinner(f"Deleting backend {backend_uuid}..."):
            client.delete(f"/v1/load-balancers/{uuid}/backends/{backend_uuid}")
        _ok(f"Backend [uuid]{backend_uuid}[/uuid] deleted")
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# usage commands
# ---------------------------------------------------------------------------


@app.command("usage")
def cmd_usage(
    user: Annotated[bool, typer.Option("--user", "-u", help="Show usage for the current user only.")] = False,
) -> None:
    """Get tenant usage statistics (--user for per-user breakdown)."""
    path = "/v1/usage/user" if user else "/v1/usage"
    try:
        client = _tenant_client()
        with _spinner("Fetching usage..."):
            result = client.get(path)
        _print_output(result, state["output"])
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# restore-state command — rebuild state.json from the live gateway
# ---------------------------------------------------------------------------


@app.command("restore-state")
def cmd_restore_state() -> None:
    """Rebuild .mgw/state.json from the live gateway after it has been wiped.

    Fetches tenants and providers from the gateway, prompts you to select the
    active tenant and paste its API key (the gateway never re-exposes keys after
    creation — retrieve it from [italic]ibm-providers-config-secret[/italic] in
    Kubernetes).

    \b
    Example:
      model-gateway.py restore-state
    """
    base_url = state["base_url"]
    requests_verify = state.get("requests_verify", True)

    console.print(
        Panel(
            "[header]Restore State[/header]\n"
            "[muted]Rebuilds[/muted] [accent].mgw/state.json[/accent] "
            "[muted]from the live gateway.[/muted]\n"
            "[muted]You will need the tenant API key from[/muted] "
            "[accent]ibm-providers-config-secret[/accent][muted].[/muted]",
            border_style="cyan",
            padding=(0, 2),
        )
    )
    console.print()

    try:
        admin_client = _admin_client()

        # ── Step 1: pick a tenant ─────────────────────────────────────────────
        with _spinner("Fetching tenants..."):
            result = admin_client.get("/v1/admin/tenants")
        tenants = result.get("data", result) if isinstance(result, dict) else (result or [])

        if not tenants:
            _err("No tenants found on this gateway.")

        if len(tenants) == 1:
            chosen_tenant = tenants[0]
            _info(
                f"One tenant found: [accent]{chosen_tenant.get('name')}[/accent]"
                f"  [uuid]{chosen_tenant.get('id') or chosen_tenant.get('uuid', '')}[/uuid]"
            )
        else:
            choices = [
                f"{t.get('name', '?')}  ({t.get('id') or t.get('uuid', '')})"
                for t in tenants
            ]
            answer = questionary.select(
                "Select the tenant to restore:",
                choices=choices,
                style=_Q_STYLE,
            ).ask()
            if not answer:
                console.print("[warn]Aborted.[/warn]")
                raise typer.Exit(0)
            idx = choices.index(answer)
            chosen_tenant = tenants[idx]

        tenant_uuid: str = chosen_tenant.get("id") or chosen_tenant.get("uuid", "")
        tenant_name: str = chosen_tenant.get("name", "")

        # ── Step 2: get the tenant API key ────────────────────────────────────
        console.print()
        console.print(
            Panel(
                f"[muted]The gateway never re-exposes API keys after creation.\n"
                f"Retrieve the key from your Kubernetes secret:[/muted]\n\n"
                f"  [accent]kubectl get secret ibm-providers-config-secret -n <namespace>[/accent]\n"
                f"  [accent]  -o jsonpath='{{.data.providers_config\\.json}}' | base64 --decode[/accent]\n\n"
                f"[muted]Copy the[/muted] [accent]api_key[/accent] [muted]value from the JSON.[/muted]",
                border_style="yellow",
                title="[warn]API Key Required[/warn]",
                padding=(0, 2),
            )
        )
        console.print()

        tenant_apikey = questionary.password(
            "Paste the tenant API key:",
            style=_Q_STYLE,
        ).ask()
        if not tenant_apikey:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)

        # Validate the key against the providers endpoint before saving.
        with _spinner("Validating API key..."):
            test_client = GatewayClient(base_url, tenant_apikey, requests_verify=requests_verify)
            try:
                test_client.get("/v1/providers")
            except GatewayError as exc:
                if exc.status_code == 401:
                    _err(
                        "API key validation failed (HTTP 401).\n"
                        "Double-check the key value and try again."
                    )
                raise

        _ok("API key validated")

        # ── Step 3: fetch providers ───────────────────────────────────────────
        with _spinner("Fetching providers..."):
            prov_result = test_client.get("/v1/providers")
        providers_list = (
            prov_result.get("data", prov_result)
            if isinstance(prov_result, dict)
            else (prov_result or [])
        )

        providers_state: dict[str, Any] = {}
        for p in providers_list:
            pname = p.get("name", "")
            puuid = p.get("uuid", "")
            ptype = p.get("type", "")
            if pname and puuid:
                providers_state[pname] = {"uuid": puuid, "type": ptype}

        # ── Step 4: write state.json ──────────────────────────────────────────
        new_state: dict[str, Any] = {
            "tenant": {
                "uuid": tenant_uuid,
                "name": tenant_name,
                "apikey": tenant_apikey,
            },
            "providers": providers_state,
        }
        write_state(new_state)

        # ── Summary ───────────────────────────────────────────────────────────
        console.print()
        _ok(f"Tenant   [accent]{tenant_name}[/accent]  [uuid]{tenant_uuid}[/uuid]")
        if providers_state:
            for pname, pdata in providers_state.items():
                _ok(f"Provider [accent]{pname}[/accent]  [uuid]{pdata['uuid']}[/uuid]  [muted]({pdata['type']})[/muted]")
        else:
            _warn("No providers found — state saved with tenant only.")
        _info(f"State written to {STATE_FILE}")

    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# provision command — interactive end-to-end setup (no TOML required)
# ---------------------------------------------------------------------------


@app.command("provision")
def provision() -> None:
    """Interactive end-to-end setup — create a tenant, providers, and models.

    Walks through each step with prompts. All provider credentials are read
    from environment variables or prompted interactively; no config file needed.

    The resulting tenant UUID and API key are saved to ~/.mgw/state.json for
    use by subsequent commands.
    """
    base_url = state["base_url"]
    requests_verify = state.get("requests_verify", True)

    # ── Header ───────────────────────────────────────────────────────────────
    console.print(
        Panel(
            f"[header]Model Gateway — Interactive Provision[/header]\n"
            f"[muted]Base URL :[/muted] [accent]{base_url}[/accent]",
            border_style="cyan",
            padding=(0, 2),
        )
    )
    console.print()

    try:
        admin_client = _admin_client()

        # ── Step 1: Tenant ────────────────────────────────────────────────────
        console.rule("[muted]Step 1 — Tenant[/muted]", style="dim cyan")

        # Fetch existing tenants so the user can see what's already there.
        with _spinner("Fetching existing tenants..."):
            try:
                tenants_result = admin_client.get("/v1/admin/tenants")
                existing_tenants: list[dict] = (
                    tenants_result.get("data", tenants_result)
                    if isinstance(tenants_result, dict)
                    else (tenants_result or [])
                )
            except GatewayError:
                existing_tenants = []

        if existing_tenants:
            tenant_names = [t.get("name", t.get("id", "")) for t in existing_tenants]
            tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="header", show_edge=False)
            tbl.add_column("NAME", style="accent")
            tbl.add_column("UUID", style="uuid")
            for t in existing_tenants:
                tbl.add_row(t.get("name", ""), t.get("id") or t.get("uuid", ""))
            console.print(Panel(tbl, title="[muted]Existing tenants[/muted]", border_style="dim cyan", padding=(0, 1)))
            console.print()
        else:
            tenant_names = []
            _info("No tenants found — a new one will be created.")
            console.print()

        tenant_name = questionary.text(
            "Tenant name:",
            default=tenant_names[0] if len(tenant_names) == 1 else "",
            style=_Q_STYLE,
        ).ask()
        if not tenant_name:
            console.print("[warn]Provision cancelled.[/warn]")
            raise typer.Exit(0)

        # Idempotent: reuse if tenant already exists.
        with _spinner(f"Checking for existing tenant '{tenant_name}'..."):
            existing_tenant = _find_existing_tenant(admin_client, tenant_name)

        if existing_tenant:
            tenant_uuid = existing_tenant.get("id") or existing_tenant.get("uuid", "")
            # Gateway never re-exposes the apikey after creation — read from local state
            # BEFORE update_tenant_state() overwrites it with the gateway response.
            saved_apikey = read_state().get("tenant", {}).get("apikey", "")
            tenant_apikey = existing_tenant.get("apikey", "") or saved_apikey
            # Preserve the apikey in the state update — inject it back so it isn't lost.
            if not existing_tenant.get("apikey") and tenant_apikey:
                existing_tenant["apikey"] = tenant_apikey
            update_tenant_state(existing_tenant)
            _warn(
                f"Tenant [accent]{tenant_name}[/accent] already exists"
                f" — [uuid]{tenant_uuid}[/uuid]  [muted](reusing)[/muted]"
            )
        else:
            with _spinner(f"Creating tenant '{tenant_name}'..."):
                tenant_result = admin_client.post("/v1/admin/tenants", {"name": tenant_name})
            update_tenant_state(tenant_result)
            tenant_uuid = tenant_result.get("id") or tenant_result.get("uuid", "")
            tenant_apikey = tenant_result.get("apikey", "")
            _ok(
                f"Tenant [accent]{tenant_name}[/accent]  [uuid]{tenant_uuid}[/uuid]"
                f"  apikey=[muted]{_mask(tenant_apikey)}[/muted]"
            )

        _info(f"Saved to {STATE_FILE}")
        console.print()

        if not tenant_apikey:
            _err("No API key available for this tenant — cannot provision providers.")

        tenant_client = GatewayClient(base_url, tenant_apikey, requests_verify=requests_verify)

        # ── Step 2: Providers + models (loop) ─────────────────────────────────
        console.rule("[muted]Step 2 — Providers & Models[/muted]", style="dim cyan")
        console.print()

        summary: list[dict[str, Any]] = []
        provider_type_choices = sorted(PROVIDER_TYPES.keys())

        while True:
            add_provider = questionary.confirm(
                "Add a provider?",
                default=True,
                style=_Q_STYLE,
            ).ask()
            if not add_provider:
                break

            p_type = questionary.select(
                "Provider type:",
                choices=provider_type_choices,
                style=_Q_STYLE,
            ).ask()
            if not p_type:
                break

            p_name = questionary.text(
                "Provider name:",
                style=_Q_STYLE,
            ).ask()
            if not p_name:
                _warn("No name entered — skipping provider.")
                continue

            p_desc = questionary.text(
                "Description (optional):",
                default="",
                style=_Q_STYLE,
            ).ask() or ""

            # Idempotent: reuse existing provider.
            with _spinner(f"Checking for existing provider '{p_name}'..."):
                existing_uuid = _find_existing_provider(tenant_client, p_name, p_type)

            if existing_uuid:
                provider_uuid = existing_uuid
                p_status = "skipped"
                _warn(
                    f"Provider [accent]{p_name}[/accent] already exists"
                    f" — [uuid]{provider_uuid}[/uuid]  [muted](reusing)[/muted]"
                )
                update_provider_state(p_name, {"uuid": provider_uuid, "type": p_type})
            else:
                data = _resolve_provider_data(p_type)
                payload: dict[str, Any] = {"name": p_name, "data": data}
                if p_desc:
                    payload["description"] = p_desc
                with _spinner(f"Creating provider '{p_name}'..."):
                    p_result = tenant_client.post(f"/v1/providers/{PROVIDER_TYPES[p_type]}", payload)
                provider_uuid = p_result.get("uuid", "")
                update_provider_state(p_name, p_result)
                p_status = "created"
                _ok(f"Provider [accent]{p_name}[/accent] ([muted]{p_type}[/muted])  [uuid]{provider_uuid}[/uuid]")

            # ── Models for this provider ──────────────────────────────────────
            model_rows: list[dict[str, str]] = []
            while True:
                add_model = questionary.confirm(
                    f"  Add a model to '{p_name}'?",
                    default=True,
                    style=_Q_STYLE,
                ).ask()
                if not add_model:
                    break

                m_id = questionary.text("  Model ID (e.g. gpt-4o):", style=_Q_STYLE).ask()
                if not m_id:
                    _warn("  No model ID entered — skipping.")
                    continue

                m_alias = questionary.text(
                    "  Alias (optional — leave blank to use model ID):",
                    default="",
                    style=_Q_STYLE,
                ).ask() or ""

                m_desc = questionary.text(
                    "  Description (optional):",
                    default="",
                    style=_Q_STYLE,
                ).ask() or ""

                with _spinner(f"  Checking for existing model '{m_id}'..."):
                    existing_m_uuid = _find_existing_model(tenant_client, provider_uuid, m_id)

                if existing_m_uuid:
                    m_status = "skipped"
                    m_uuid = existing_m_uuid
                    console.print(f"  [skip]·[/skip] [muted]{m_id}[/muted]  [muted](skipped)[/muted]")
                else:
                    m_payload: dict[str, Any] = {"id": m_id}
                    if m_alias:
                        m_payload["alias"] = m_alias
                    if m_desc:
                        m_payload["description"] = m_desc
                    with _spinner(f"  Registering model '{m_id}'..."):
                        m_result = tenant_client.post(
                            f"/v1/providers/{provider_uuid}/models", m_payload
                        )
                    m_uuid = m_result.get("uuid", "")
                    m_status = "created"
                    console.print(f"  [ok]✔[/ok] [accent]{m_id}[/accent]  [uuid]{m_uuid}[/uuid]")

                model_rows.append({"id": m_id, "uuid": m_uuid, "status": m_status})

            summary.append({
                "provider": p_name,
                "type": p_type,
                "uuid": provider_uuid,
                "status": p_status,
                "models": model_rows,
            })
            console.print()

        # ── Summary ───────────────────────────────────────────────────────────
        console.rule("[muted]Summary[/muted]", style="dim cyan")
        console.print()

        if summary:
            tbl = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="header", show_edge=False)
            tbl.add_column("PROVIDER", style="accent")
            tbl.add_column("TYPE", style="muted")
            tbl.add_column("UUID", style="uuid")
            tbl.add_column("STATUS")
            tbl.add_column("MODELS")

            for p in summary:
                total = len(p["models"])
                new_c = sum(1 for m in p["models"] if m["status"] == "created")
                skip_c = total - new_c
                note = f"{new_c} created, {skip_c} skipped" if total else "none"
                status_style = "ok" if p["status"] == "created" else "skip"
                tbl.add_row(p["provider"], p["type"], p["uuid"], f"[{status_style}]{p['status']}[/{status_style}]", note)

            console.print(tbl)
            console.print()

        console.print(
            Panel(
                f"[muted]Tenant :[/muted]  [accent]{tenant_name}[/accent]  [uuid]{tenant_uuid}[/uuid]\n"
                f"[muted]API key:[/muted]  [accent]{_mask(tenant_apikey)}[/accent]\n"
                f"[muted]State  :[/muted]  {STATE_FILE}",
                title="[header]Provision complete[/header]",
                border_style="green",
                padding=(0, 2),
            )
        )

    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, state["base_url"])


# ---------------------------------------------------------------------------
# patch-secret command — write ibm-providers-config-secret into Kubernetes
# ---------------------------------------------------------------------------


def _patch_providers_config_secret(
    namespace: str,
    tenant_apikey: str,
    provider_name: str,
    base_url: str,
    requests_verify: "bool | str",
) -> None:
    """Build providers_config.json from the live Model Gateway and patch the secret.

    Queries /v1/models (tenant-scoped) to discover the real model id registered
    in the gateway — the id is what the Reasoning Service must send as the
    ``model`` field, NOT the provider name.

    Args:
        namespace: Kubernetes namespace containing ibm-providers-config-secret.
        tenant_apikey: Tenant-scoped API key for the Model Gateway.
        provider_name: Provider name (used as the llm key prefix).
        base_url: Model Gateway base URL.
        requests_verify: requests SSL verify setting.

    Raises:
        typer.Exit: On any unrecoverable error.
    """
    logger.info(
        "Building providers_config.json for provider '%s' in namespace '%s'",
        provider_name, namespace,
    )

    # ── 1. Fetch the real model id from /v1/providers/{uuid}/models ──────────
    # We must use the provider-scoped endpoint, NOT /v1/models.
    # /v1/models is the OpenAI-compatible list and replaces "id" with the alias
    # when one is set, hiding the real upstream deployment name.
    # /v1/providers/{uuid}/models always returns the original model id in "id"
    # and the alias separately in "alias".
    tenant_client = GatewayClient(base_url, tenant_apikey, requests_verify=requests_verify)

    # Resolve the provider UUID from state.
    saved_providers = read_state().get("providers", {})
    provider_uuid: str = saved_providers.get(provider_name, {}).get("uuid", "")
    if not provider_uuid:
        _err(
            f"No UUID found for provider [accent]{provider_name}[/accent] in state.\n"
            "Run [italic]model-gateway.py provision[/italic] first."
        )

    with _spinner("Fetching registered models from Model Gateway..."):
        try:
            models_result = tenant_client.get(f"/v1/providers/{provider_uuid}/models")
        except GatewayError as exc:
            _handle_request_errors(exc, base_url)

    models = models_result.get("data", []) if isinstance(models_result, dict) else (models_result or [])
    if not models:
        _err(
            "No models are registered in the Model Gateway.\n"
            "Run [italic]model model add[/italic] to register a model first."
        )

    # If there's more than one model, let the user pick which to set as active.
    if len(models) == 1:
        chosen = models[0]
    else:
        choices = [m["id"] for m in models if m.get("id")]
        chosen_id = questionary.select(
            "Multiple models found — select the active model:",
            choices=choices,
            style=_Q_STYLE,
        ).ask()
        if not chosen_id:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
        chosen = next(m for m in models if m["id"] == chosen_id)

    # Prefer alias over canonical id: when an alias is set the Model Gateway
    # inference API routes on the alias and rejects the canonical id.
    # See .mgw/state.json note: model-alias-inference-mismatch
    model_id: str = chosen.get("alias") or chosen.get("id", "")
    llm_key = f"ai-gateway-{provider_name}"

    logger.info("Using model id '%s' → llm_key '%s'", model_id, llm_key)

    # ── 2. Build new provider entry ──────────────────────────────────────────
    # When --dev is active, base_url is the local port-forward address
    # (https://localhost:18080).  The Reasoning Service pod runs inside the
    # cluster and cannot reach localhost on the host machine, so we always
    # use the stable ClusterIP service URL for the secret — regardless of
    # how this script connected to the gateway.
    svc_base_url = f"https://model-gateway-service.{namespace}.svc.cluster.local:8080"
    new_entry: dict[str, Any] = {
        "provider": "ai_gateway",
        "base_url": f"{svc_base_url}/v1",
        "api_key": tenant_apikey,
        "model": model_id,
        "verify_ssl": False,
        "max_completion_tokens": 2048,
        "temperature": 0.7,
        "timeout": 120,
        "context_window_token_limit": 272000,
    }

    # ── 3. Read existing secret and merge ────────────────────────────────────
    import base64
    import subprocess

    secret_name = "ibm-providers-config-secret"

    existing_llms: dict[str, Any] = {}
    existing_config: dict[str, Any] = {}
    with _spinner(f"Reading existing {secret_name} from namespace {namespace}..."):
        get_result = subprocess.run(
            [
                "kubectl", "get", "secret", secret_name,
                "-n", namespace,
                "-o", "jsonpath={.data.providers_config\\.json}",
            ],
            capture_output=True,
            text=True,
        )

    if get_result.returncode == 0 and get_result.stdout.strip():
        try:
            existing_json = base64.b64decode(get_result.stdout.strip()).decode()
            existing_config = json.loads(existing_json)
            existing_llms = existing_config.get("llms", {})
            logger.info(
                "Found existing secret with %d llm(s): %s",
                len(existing_llms), list(existing_llms.keys()),
            )
        except Exception as exc:
            logger.warning("Could not parse existing secret — starting fresh: %s", exc)
    else:
        logger.info("No existing secret found — creating new one.")

    # Merge: add/overwrite only this provider's entry; preserve all others.
    merged_llms = {**existing_llms, llm_key: new_entry}

    # ── 4. Choose active_llm ─────────────────────────────────────────────────
    if len(merged_llms) == 1:
        active_llm = llm_key
    else:
        # Show current active_llm as default if known, else default to new entry.
        existing_active = existing_config.get("active_llm", llm_key) if existing_llms else llm_key
        active_llm = questionary.select(
            "Multiple providers in secret — select the active LLM:",
            choices=list(merged_llms.keys()),
            default=existing_active if existing_active in merged_llms else llm_key,
            style=_Q_STYLE,
        ).ask()
        if not active_llm:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)

    providers_config = {"active_llm": active_llm, "llms": merged_llms}
    providers_json = json.dumps(providers_config, indent=2)

    # ── 5. Write back ────────────────────────────────────────────────────────
    encoded = base64.b64encode(providers_json.encode()).decode()
    patch_payload = json.dumps({
        "data": {"providers_config.json": encoded}
    })

    with _spinner(f"Patching {secret_name} in namespace {namespace}..."):
        result = subprocess.run(
            [
                "kubectl", "patch", "secret", secret_name,
                "-n", namespace,
                "--type=merge",
                "-p", patch_payload,
            ],
            capture_output=True,
            text=True,
        )

    if result.returncode != 0:
        _err(
            f"kubectl patch failed:\n{result.stderr.strip()}\n\n"
            "Ensure kubectl is configured and you have write access to the namespace."
        )

    logger.info(
        "Patched %s in namespace %s with %d llm(s), active_llm=%s",
        secret_name, namespace, len(merged_llms), active_llm,
    )
    _ok(
        f"[accent]{secret_name}[/accent] patched in [accent]{namespace}[/accent]\n"
        f"  active_llm : [bold]{active_llm}[/bold]\n"
        f"  llms       : {', '.join(merged_llms.keys())}"
    )
    _info(f"Model id written: [bold]{model_id}[/bold]  (from GET /v1/providers/{{uuid}}/models)")
    _warn(
        "Restart the Reasoning Service pod to pick up the new secret:\n"
        f"  kubectl rollout restart deployment/ibm-reasoning-service-deploy -n {namespace}"
    )


@app.command("patch-secret")
def cmd_patch_secret(
    namespace: Annotated[
        Optional[str],
        typer.Option(
            "--namespace", "-n",
            metavar="NAMESPACE",
            help="Kubernetes namespace containing ibm-providers-config-secret.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Patch ibm-providers-config-secret with the correct Model Gateway model id.

    Reads the tenant API key and provider name from [italic]~/.mgw/state.json[/italic],
    queries [italic]GET /v1/models[/italic] from the live Model Gateway to resolve
    the real model id, then writes a valid [italic]providers_config.json[/italic]
    directly into the Kubernetes secret.

    This fixes the [bold red]'model <name> not found'[/bold red] error that occurs
    when the secret contains the provider name instead of the gateway model id.

    \b
    Example:
      model-gateway.py patch-secret --namespace ccx-prod
    """
    base_url = state["base_url"]
    if not base_url:
        show_error_panel(_ERR_MISSING_URL)
        raise typer.Exit(1)

    requests_verify = state.get("requests_verify", True)

    # ── Read tenant API key + provider name from state ───────────────────────
    saved = read_state()
    tenant_apikey: str = saved.get("tenant", {}).get("apikey", "")
    providers_state: dict = saved.get("providers", {})

    if not tenant_apikey:
        _err(
            "No tenant API key found in state.\n"
            "Run [italic]model-gateway.py provision[/italic] first to create a tenant."
        )

    # Determine the provider name to use as the llm key prefix.
    if len(providers_state) == 1:
        provider_name = next(iter(providers_state))
    elif len(providers_state) > 1:
        provider_name = questionary.select(
            "Multiple providers in state — select the active provider:",
            choices=list(providers_state.keys()),
            style=_Q_STYLE,
        ).ask()
        if not provider_name:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)
    else:
        _err(
            "No providers found in state.\n"
            "Run [italic]model-gateway.py provision[/italic] to set up a provider."
        )

    # ── Resolve namespace ─────────────────────────────────────────────────────
    if not namespace:
        namespace = questionary.text(
            "Kubernetes namespace for ibm-providers-config-secret:",
            style=_Q_STYLE,
        ).ask()
        if not namespace:
            console.print("[warn]Aborted.[/warn]")
            raise typer.Exit(0)

    # ── Preview panel ─────────────────────────────────────────────────────────
    console.print(
        Panel(
            f"[muted]Tenant API key:[/muted]  [accent]{_mask(tenant_apikey)}[/accent]\n"
            f"[muted]Provider      :[/muted]  [accent]{provider_name}[/accent]\n"
            f"[muted]Namespace     :[/muted]  [accent]{namespace}[/accent]\n"
            f"[muted]Secret        :[/muted]  [accent]ibm-providers-config-secret[/accent]",
            title="[header]Patch Secret[/header]",
            border_style="cyan",
            padding=(0, 2),
        )
    )

    try:
        _patch_providers_config_secret(
            namespace=namespace,
            tenant_apikey=tenant_apikey,
            provider_name=provider_name,
            base_url=base_url,
            requests_verify=requests_verify,
        )
    except (GatewayError, requests.exceptions.SSLError, requests.exceptions.ConnectionError) as exc:
        _handle_request_errors(exc, base_url)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()

###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2024. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################
"""
ILMT REST API client for the validate command.

Queries the IBM License Metric Tool v2 REST API for contractual license metric
utilization (content_operation_count) for a given server and month.

content_operation_count was previously an adoption metric reported via
.ums.data.json files. It is now a contractual metric exposed directly through
the standard ILMT license_usage REST API under the same metric name.

Authentication:
  The ILMT token is a static string obtained from the ILMT UI:
    User icon → Profile → Show token
  Or retrieved once via POST /api/get_token (username/password) if SSO is not
  enabled. The token is stored in servers.toml as API_TOKEN and passed in the
  request header as:  Token: <value>

Endpoint used:
  GET /api/sam/v2/license_usage
  Query params: startdate=YYYY-MM-DD  enddate=YYYY-MM-DD

Reference:
  https://www.ibm.com/docs/en/license-metric-tool/9.2.0?topic=v2-retrieval-license-metric-utilization
  https://www.ibm.com/docs/en/license-metric-tool/9.2.0?topic=api-authenticating-rest-requests
"""

import calendar
import json
import ssl
from datetime import date
from pathlib import Path

import requests
import urllib3

from helper_scripts.license.validate.config_loader import ServerConfig

# Suppress InsecureRequestWarning when TLS_VERIFY=false
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_CERT_EXTENSIONS = (".crt", ".pem", ".cer")

# The contractual metric code name ILMT exposes via the license_usage API.
# Previously an adoption metric; now a first-class contractual metric under
# the same name. Matched against the metric_code_name field (not metric_name,
# which is a human-readable label that may vary).
_METRIC_CODE_NAME = "content_operation_count"

# Product name prefix to scope the metric to CCx products only, avoiding
# accidental matches from unrelated products that may use the same metric code.
_PRODUCT_PREFIX = "ibm content cortex"


# ── SSL context ───────────────────────────────────────────────────────────────

def _build_ssl_context(certs_dir: Path) -> ssl.SSLContext | None:
    """
    Walk certs_dir and load all certificate files into an SSLContext.
    Returns None if the directory doesn't exist or contains no certs.

    Uses a context that trusts *only* the provided certificates so that
    self-signed / private CA chains (e.g. OpenShift service-serving certs)
    are accepted without being rejected because they are absent from the
    system CA store.
    """
    if not certs_dir.exists():
        return None
    cert_files = [
        f for f in certs_dir.rglob("*")
        if f.is_file() and f.suffix.lower() in _CERT_EXTENSIONS and f.stat().st_size > 0
    ]
    if not cert_files:
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    loaded = 0
    for cert in cert_files:
        try:
            ctx.load_verify_locations(cafile=str(cert))
            loaded += 1
        except ssl.SSLError:
            pass
    if loaded == 0:
        return None
    return ctx


# ── Response parsing ──────────────────────────────────────────────────────────

def _sum_from_payload(payload: dict | list) -> int:
    """
    Sum content_operation_count values from an ILMT /api/sam/v2/license_usage
    response payload.

    The response is a JSON object with a 'rows' array of contractual license
    usage records. Each record has a 'metric_code_name' and a 'hwm_quantity'
    (high-water-mark for the period). We iterate all rows and sum hwm_quantity
    for any row whose metric_code_name matches content_operation_count.

    Expected response shape:
      {
        "total": N,
        "rows": [
          {
            "product_name": "...",
            "metric_code_name": "content_operation_count",
            "hwm_quantity": 14132
          },
          ...
        ]
      }

    hwm_quantity of -1 means unlimited/not applicable — treated as 0.
    """
    rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    total = 0
    for record in rows:
        if not isinstance(record, dict):
            continue
        # Match metric_code_name and scope to CCx products only
        metric_match   = record.get("metric_code_name", "").lower() == _METRIC_CODE_NAME
        product_name   = record.get("product_name", "").lower()
        product_match  = product_name.startswith(_PRODUCT_PREFIX)
        if metric_match and product_match:
            try:
                qty = int(record.get("hwm_quantity", 0))
                if qty > 0:   # -1 = unlimited, skip
                    total += qty
            except (TypeError, ValueError):
                pass
    return total


# ── Per-month query ───────────────────────────────────────────────────────────

def query_month(
    server: ServerConfig,
    year: int,
    month: int,
    insecure: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
) -> int:
    """
    Query an ILMT server for a month and return the total content_operation_count.

    start_date / end_date pin the query boundaries for the first/last month.
    If not provided, defaults to the 1st → last day of the month.
    insecure=True disables TLS verification regardless of server.tls_verify.

    Auth: the API_TOKEN from ServerConfig is passed as the 'Token' header, which
    is the recommended approach per ILMT docs (avoids token in URL).
    """
    _, days_in_month = calendar.monthrange(year, month)
    tls_verify = False if insecure else server.tls_verify

    s = start_date if start_date else date(year, month, 1)
    e = end_date   if end_date   else date(year, month, days_in_month)

    session = requests.Session()
    if tls_verify:
        ctx = _build_ssl_context(server.ssl_certs_dir)
        if ctx is not None:
            from requests.adapters import HTTPAdapter

            class _SSLAdapter(HTTPAdapter):
                def __init__(self, ssl_context: ssl.SSLContext, **kwargs):
                    self._ssl_ctx = ssl_context
                    super().__init__(**kwargs)

                def init_poolmanager(self, *args, **kwargs):
                    kwargs["ssl_context"] = self._ssl_ctx
                    super().init_poolmanager(*args, **kwargs)

            session.mount("https://", _SSLAdapter(ctx))

    resp = session.get(
        f"{server.url}/api/sam/v2/license_usage",
        headers={
            "Token":           server.api_key,   # api_key holds API_TOKEN for ILMT
            "Accept":          "application/json",
            "Accept-Language": "en-US",
        },
        params={
            "startdate": s.strftime("%Y-%m-%d"),
            "enddate":   e.strftime("%Y-%m-%d"),
        },
        verify=tls_verify,
        timeout=60,
    )
    resp.raise_for_status()

    payload = resp.json()
    if not payload:
        return 0

    return _sum_from_payload(payload)

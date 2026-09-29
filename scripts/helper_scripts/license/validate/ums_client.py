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
UMS audit snapshot client for the validate command.

Queries the IBM Usage Metering Service audit snapshot API for a given server
and month, summing content_operation_count across all CCx mappingIds.
"""

import calendar
import io
import json
import ssl
import zipfile
from datetime import date
from pathlib import Path

import requests
import urllib3

from helper_scripts.license.validate.config_loader import ServerConfig

# Suppress InsecureRequestWarning when TLS_VERIFY=false
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── SSL context ───────────────────────────────────────────────────────────────

_CERT_EXTENSIONS = (".crt", ".pem", ".cer")


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


# ── Record parsing ────────────────────────────────────────────────────────────

def _sum_from_payload(payload: list, start: date, end: date) -> int:
    """
    Sum content_operation_count from a UMS snapshot payload, filtering to days
    within [start, end].

    NOTE: UMS ignores startTime/endTime params and returns its own rolling
    window — we must filter dailyAggregates by date client-side.

    The metric lives at:
      payload[].metrics[].dailyAggregates.<YYYY-MM-DD>
        .breakdowns[].metricBreakdown[].group.content_operation_count
    """
    total = 0
    for product in payload:
        for metric in product.get("metrics", []):
            daily = metric.get("dailyAggregates", {})
            for day_str, day_data in daily.items():
                try:
                    day = date.fromisoformat(day_str)
                except ValueError:
                    continue
                if not (start <= day <= end):
                    continue
                for breakdown in day_data.get("breakdowns", []):
                    for item in breakdown.get("metricBreakdown", []):
                        group = item.get("group", {})
                        if "content_operation_count" in group:
                            total += int(group["content_operation_count"])
    return total


# ── Zip extraction ────────────────────────────────────────────────────────────

def _extract_from_zip(content: bytes) -> list:
    """
    Unzip the UMS snapshot in memory and return the records from
    usage_metrics.json as a list.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        names = zf.namelist()
        metrics_file = next((n for n in names if n == "usage_metrics.json"), None)
        if metrics_file:
            raw = zf.read(metrics_file)
            if raw.strip():
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return parsed
    return []


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
    Query a UMS server for a month and return the total summed metric.

    start_date / end_date pin the query boundaries for the first/last month.
    If not provided, defaults to the 1st → last day of the month.
    insecure=True disables TLS verification regardless of server.tls_verify.
    """
    _, days_in_month = calendar.monthrange(year, month)
    tls_verify = False if insecure else server.tls_verify

    s = start_date if start_date else date(year, month, 1)
    e = end_date   if end_date   else date(year, month, days_in_month)

    start = f"{s.year:04d}-{s.month:02d}-{s.day:02d}T00:00:00Z"
    end   = f"{e.year:04d}-{e.month:02d}-{e.day:02d}T23:59:59Z"

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
        f"{server.url}/api/v1/snapshot",
        headers={"Authorization": f"Bearer {server.api_key}"},
        params={"startTime": start, "endTime": end},
        verify=tls_verify,
        timeout=60,
        stream=True,
    )
    resp.raise_for_status()

    content = resp.content
    if not content or not content.startswith(b"PK"):
        return 0

    records = _extract_from_zip(content)
    return _sum_from_payload(records, start=s, end=e)

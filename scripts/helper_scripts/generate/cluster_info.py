###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2026. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################

"""
Live cluster resource queries for generate mode.

These helpers are called by prerequisites.py generate mode when IBM-managed
CNPG or Redis is selected.  They use the Kubernetes Python client to read the
secrets created by the IBM operators after those operators reach Ready status.

If the expected secrets are not found (e.g. the customer has not yet deployed
the infrastructure CRs), ClusterResourceNotFoundError is raised and generate
mode should surface a clear error panel + exit(1).

CR discovery
------------
Rather than hardcoding the CNPG Cluster or Redis CR name, the helpers below
list deployed CRs in the namespace and filter by a name hint (substring match
against "wdu" or "mg").  When exactly one candidate is found it is used
automatically.  When more than one matches the caller receives the list and
should ask the customer to confirm before proceeding.

Secret naming convention
------------------------
IBM CNPG operator creates two secrets per Cluster CR named <cluster-name>:
  <cluster-name>-ca   → data['ca.crt']   (CA certificate, base64)
  <cluster-name>-app  → data['password'] (app user password, base64)

IBM Redis operator creates one secret named from the CR's
spec.connectionSecret.secretName (if set) or defaults to
<cr-name>-<release>-secret.  We fall back to listing secrets by label
  app.kubernetes.io/instance=<cr-name> type=Opaque  → pick the one
  whose name contains "secret" and has key "password".

CNPG service naming convention
-------------------------------
CNPG exposes a read-write service at <cluster-name>-rw in the same namespace.
We first try to read it from status.writeService; if absent we synthesize:
  <cluster-name>-rw.<namespace>.svc.cluster.local

Redis master service naming convention
---------------------------------------
IBM Redis operator creates a service named <cr-name>-master-svc.
"""

import base64
import re
from logging import Logger
from typing import List, Optional, Tuple

from kubernetes.client import ApiException

from helper_scripts.utilities.kubernetes_utilites import KubernetesUtilities


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class ClusterResourceNotFoundError(Exception):
    """Raised when a required cluster secret or resource is not found.

    Args:
        resource_kind: Kind of resource not found (e.g. "Secret").
        resource_name: Name of the resource (e.g. "ibm-pg-cluster-mg-ca").
        namespace: Kubernetes namespace searched.
        hint: Optional human-readable guidance for the customer.
    """

    def __init__(
        self,
        resource_kind: str,
        resource_name: str,
        namespace: str,
        hint: str = "",
    ) -> None:
        self.resource_kind = resource_kind
        self.resource_name = resource_name
        self.namespace = namespace
        self.hint = hint
        super().__init__(
            f"{resource_kind} '{resource_name}' not found in namespace '{namespace}'. "
            + (hint if hint else "Deploy the infrastructure CRs and wait for readiness.")
        )


class MultipleResourcesFoundError(Exception):
    """Raised when more than one candidate CR matches the name hint.

    The caller should present ``candidates`` to the user and ask them to
    confirm which one to use.
    """

    def __init__(self, resource_kind: str, namespace: str, candidates: List[str]) -> None:
        self.resource_kind = resource_kind
        self.namespace = namespace
        self.candidates = candidates
        super().__init__(
            f"Multiple {resource_kind} CRs found in namespace '{namespace}': "
            + ", ".join(candidates)
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_secret_field(
    k8s: KubernetesUtilities,
    secret_name: str,
    field_key: str,
    namespace: str,
    logger: Optional[Logger],
) -> str:
    """Read a single base64-encoded field from a Kubernetes secret.

    The Kubernetes Python client returns secret data values as already-decoded
    bytes (the server sends base64; the client library decodes them).  This
    function re-encodes the value to base64 so the return contract matches
    what callers expect (a base64 string, consistent with the previous
    kubectl-based implementation).

    Args:
        k8s:         Initialised KubernetesUtilities instance.
        secret_name: Name of the Kubernetes secret.
        field_key:   Key inside ``secret.data``, e.g. ``"password"`` or ``"ca.crt"``.
        namespace:   Kubernetes namespace.
        logger:      Logger for debug output.

    Returns:
        The base64-encoded string value of the secret data field.

    Raises:
        ClusterResourceNotFoundError: Secret does not exist (ApiException 404)
            or the requested key is absent / empty in the secret data.
        RuntimeError: Kubernetes API call failed for any other reason.
    """
    if logger:
        logger.debug(
            f"Reading secret '{secret_name}' key '{field_key}' in namespace '{namespace}'"
        )

    try:
        secret = k8s.core_v1.read_namespaced_secret(
            name=secret_name,
            namespace=namespace,
        )
    except ApiException as exc:
        if exc.status == 404:
            raise ClusterResourceNotFoundError(
                resource_kind="Secret",
                resource_name=secret_name,
                namespace=namespace,
            ) from exc
        raise RuntimeError(
            f"Kubernetes API error reading secret '{secret_name}' "
            f"(status={exc.status}): {exc.reason}"
        ) from exc

    data = secret.data or {}
    raw = data.get(field_key)

    if not raw:
        raise ClusterResourceNotFoundError(
            resource_kind="Secret",
            resource_name=secret_name,
            namespace=namespace,
            hint=(
                f"Secret exists but key '{field_key}' is empty. "
                "The IBM operator may not have finished populating it yet — "
                "wait for the cluster to reach Ready status."
            ),
        )

    # The Python k8s client returns secret.data values as base64-encoded strings.
    # Return as-is if already a str; re-encode only if bytes were returned.
    if isinstance(raw, bytes):
        return base64.b64encode(raw).decode("utf-8")
    return raw


def _name_matches_hint(name: str, hint: str) -> bool:
    """Return True if *name* contains *hint* (case-insensitive)."""
    return hint.lower() in name.lower()


# ---------------------------------------------------------------------------
# CR discovery
# ---------------------------------------------------------------------------

def discover_cnpg_clusters(
    namespace: str,
    name_hint: str,
    logger: Optional[Logger] = None,
) -> List[str]:
    """List CNPG Cluster CR names in *namespace* whose name contains *name_hint*.

    Queries the ``clusters.pg.ibm.com`` CRD (IBM CNPG operator).  Falls back to
    ``clusters.postgresql.cnpg.io`` (upstream CNPG) if the IBM CRD is absent.

    Args:
        namespace:  Kubernetes namespace to search.
        name_hint:  Substring to match against CR names (e.g. ``"wdu"`` or ``"mg"``).
        logger:     Optional logger for debug output.

    Returns:
        List of matching CR names (may be empty).

    Raises:
        RuntimeError: Kubernetes API call failed.
    """
    k8s = KubernetesUtilities(logger=logger, require_connection=True)
    candidates: List[str] = []

    # Try both IBM and upstream CNPG API groups
    for group, version in [("pg.ibm.com", "v1"), ("postgresql.cnpg.io", "v1")]:
        try:
            result = k8s.custom_api.list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural="clusters",
            )
            for item in result.get("items", []):
                cr_name = item.get("metadata", {}).get("name", "")
                if cr_name and _name_matches_hint(cr_name, name_hint):
                    candidates.append(cr_name)
                    if logger:
                        logger.debug(
                            f"Discovered CNPG cluster '{cr_name}' "
                            f"(group={group}) matching hint '{name_hint}'"
                        )
            if candidates:
                break  # Stop on first group that returned results
        except ApiException as exc:
            if exc.status in (404, 405):
                # CRD not registered under this group — try the next
                if logger:
                    logger.debug(f"CNPG CRD not found under group={group}: {exc.status}")
                continue
            raise RuntimeError(
                f"Kubernetes API error listing CNPG clusters "
                f"(group={group}, status={exc.status}): {exc.reason}"
            ) from exc

    return candidates


def discover_cnpg_poolers(
    namespace: str,
    cluster_name: str,
    logger: Optional[Logger] = None,
) -> List[str]:
    """List CNPG Pooler CR names in *namespace* whose ``spec.cluster.name`` matches
    *cluster_name*.

    Queries the ``poolers.pg.ibm.com`` CRD (IBM CNPG operator).  Falls back to
    ``poolers.postgresql.cnpg.io`` (upstream CNPG) if the IBM CRD is absent.

    Args:
        namespace:     Kubernetes namespace to search.
        cluster_name:  CNPG Cluster CR name the pooler must reference.
        logger:        Optional logger for debug output.

    Returns:
        List of matching Pooler CR names (may be empty).

    Raises:
        RuntimeError: Kubernetes API call failed.
    """
    k8s = KubernetesUtilities(logger=logger, require_connection=True)
    candidates: List[str] = []

    for group, version in [("pg.ibm.com", "v1"), ("postgresql.cnpg.io", "v1")]:
        try:
            result = k8s.custom_api.list_namespaced_custom_object(
                group=group,
                version=version,
                namespace=namespace,
                plural="poolers",
            )
            for item in result.get("items", []):
                pooler_name = item.get("metadata", {}).get("name", "")
                linked_cluster = (
                    item.get("spec", {}).get("cluster", {}).get("name", "")
                )
                if pooler_name and linked_cluster == cluster_name:
                    candidates.append(pooler_name)
                    if logger:
                        logger.debug(
                            f"Discovered Pooler '{pooler_name}' "
                            f"(group={group}) linked to cluster '{cluster_name}'"
                        )
            if candidates:
                break  # Stop on first group that returned results
        except ApiException as exc:
            if exc.status in (404, 405):
                if logger:
                    logger.debug(f"Pooler CRD not found under group={group}: {exc.status}")
                continue
            raise RuntimeError(
                f"Kubernetes API error listing CNPG poolers "
                f"(group={group}, status={exc.status}): {exc.reason}"
            ) from exc

    return candidates


def discover_redis_crs(
    namespace: str,
    name_hint: str,
    logger: Optional[Logger] = None,
) -> List[str]:
    """List IBM Redis CR names in *namespace* whose name contains *name_hint*.

    Queries the ``rediscps.redis.ibm.com`` CRD (IBM Redis operator).

    Args:
        namespace:  Kubernetes namespace to search.
        name_hint:  Substring to match against CR names (e.g. ``"mg"``).
        logger:     Optional logger for debug output.

    Returns:
        List of matching CR names (may be empty).

    Raises:
        RuntimeError: Kubernetes API call failed.
    """
    k8s = KubernetesUtilities(logger=logger, require_connection=True)
    candidates: List[str] = []

    try:
        result = k8s.custom_api.list_namespaced_custom_object(
            group="redis.ibm.com",
            version="v1",
            namespace=namespace,
            plural="rediscps",
        )
        for item in result.get("items", []):
            cr_name = item.get("metadata", {}).get("name", "")
            if cr_name and _name_matches_hint(cr_name, name_hint):
                candidates.append(cr_name)
                if logger:
                    logger.debug(
                        f"Discovered Redis CR '{cr_name}' matching hint '{name_hint}'"
                    )
    except ApiException as exc:
        if exc.status in (404, 405):
            if logger:
                logger.debug(f"Redis CRD not found: {exc.status}")
        else:
            raise RuntimeError(
                f"Kubernetes API error listing Redis CRs "
                f"(status={exc.status}): {exc.reason}"
            ) from exc

    return candidates


def get_cnpg_cluster_details(
    k8s: KubernetesUtilities,
    cluster_name: str,
    namespace: str,
    logger: Optional[Logger] = None,
) -> dict:
    """Read a live CNPG Cluster CR and extract relevant details.

    Returns a dict with keys:
      - ``ca_secret``          – name of the CA secret (``<cluster>-ca`` by default,
                                 confirmed from status.certificates.serverCASecret)
      - ``app_secret``         – name of the app-user secret (``<cluster>-app``)
      - ``server_tls_secret``  – name of the server TLS secret that holds ``tls.crt``
                                 and ``tls.key`` for mTLS (from
                                 status.certificates.serverTLSSecret); empty string
                                 when the cluster did not set mTLS.
      - ``rw_service``         – read-write service FQDN (from status.writeService
                                 or derived as ``<cluster>-rw.<namespace>.svc.cluster.local``)
      - ``pooler_service``     – empty string (filled in by callers if needed)
      - ``database``           – database name from spec.bootstrap.initdb.database
                                 (or ``""`` if absent)
    """
    details = {
        "ca_secret": f"{cluster_name}-ca",
        "app_secret": f"{cluster_name}-app",
        "server_tls_secret": "",   # populated from status.certificates.serverTLSSecret
        "rw_service": f"{cluster_name}-rw.{namespace}.svc.cluster.local",
        "pooler_service": "",
        "database": "",
    }

    for group in ("pg.ibm.com", "postgresql.cnpg.io"):
        try:
            cr = k8s.custom_api.get_namespaced_custom_object(
                group=group,
                version="v1",
                namespace=namespace,
                plural="clusters",
                name=cluster_name,
            )

            # Override RW service from status if the operator has set it
            status = cr.get("status", {})
            write_service = status.get("writeService", "")
            if write_service:
                # writeService may already be an FQDN or just a service name
                if "." not in write_service:
                    write_service = f"{write_service}.{namespace}.svc.cluster.local"
                details["rw_service"] = write_service
                if logger:
                    logger.debug(
                        f"CNPG '{cluster_name}' writeService from status: {write_service}"
                    )

            # Extract secret names from status.certificates
            # CNPG operator sets:
            #   status.certificates.serverCASecret    – CA secret name (confirms <cluster>-ca)
            #   status.certificates.serverTLSSecret   – server TLS cert+key secret
            #                                           (keys: tls.crt / tls.key)
            #   status.certificates.clientCASecret    – client CA (for client cert auth)
            certs_status = status.get("certificates", {})

            server_ca_secret = certs_status.get("serverCASecret", "")
            if server_ca_secret:
                details["ca_secret"] = server_ca_secret
                if logger:
                    logger.debug(
                        f"CNPG '{cluster_name}' serverCASecret from status: {server_ca_secret}"
                    )

            server_tls_secret = certs_status.get("serverTLSSecret", "")
            if server_tls_secret:
                details["server_tls_secret"] = server_tls_secret
                if logger:
                    logger.debug(
                        f"CNPG '{cluster_name}' serverTLSSecret from status: {server_tls_secret}"
                    )

            # Extract database name from bootstrap spec
            spec = cr.get("spec", {})
            db_name = (
                spec.get("bootstrap", {})
                    .get("initdb", {})
                    .get("database", "")
            )
            if db_name:
                details["database"] = db_name
                if logger:
                    logger.debug(
                        f"CNPG '{cluster_name}' bootstrap database: {db_name}"
                    )

            break  # Found CR — stop trying groups
        except ApiException as exc:
            if exc.status == 404:
                continue
            raise RuntimeError(
                f"Kubernetes API error reading CNPG cluster '{cluster_name}' "
                f"(status={exc.status}): {exc.reason}"
            ) from exc

    return details


def get_redis_cr_details(
    k8s: KubernetesUtilities,
    cr_name: str,
    namespace: str,
    logger: Optional[Logger] = None,
) -> dict:
    """Read a live IBM Redis CR and extract connection details.

    Returns a dict with keys:
      - ``password_secret`` – name of the secret holding the Redis password
      - ``master_svc``      – short hostname of the master service
      - ``use_tls``         – bool, True when TLS is enabled in the CR spec
    """
    details = {
        "password_secret": f"{cr_name}-secret",   # conservative fallback
        "master_svc": f"{cr_name}-master-svc",
        "use_tls": True,
    }

    try:
        cr = k8s.custom_api.get_namespaced_custom_object(
            group="redis.ibm.com",
            version="v1",
            namespace=namespace,
            plural="rediscps",
            name=cr_name,
        )

        spec = cr.get("spec", {})

        # spec.credentialSecret — plain string used by redis.ibm.com/v1 operator
        cred_secret = spec.get("credentialSecret", "")
        if cred_secret:
            details["password_secret"] = cred_secret
            if logger:
                logger.debug(
                    f"Redis '{cr_name}' credentialSecret: {cred_secret}"
                )

        # spec.connectionSecret.secretName — older IBM Redis operator field
        conn_secret = spec.get("connectionSecret", {}).get("secretName", "")
        if conn_secret:
            details["password_secret"] = conn_secret
            if logger:
                logger.debug(
                    f"Redis '{cr_name}' connectionSecret.secretName: {conn_secret}"
                )

        # spec.redisPassword.secretName — another older variant
        pw_secret = spec.get("redisPassword", {}).get("secretName", "")
        if pw_secret:
            details["password_secret"] = pw_secret

        # TLS: IBM Redis uses spec.tls.enabled (bool) or spec.enableTLS
        tls_spec = spec.get("tls", {})
        if isinstance(tls_spec, dict):
            details["use_tls"] = bool(tls_spec.get("enabled", True))
        elif "enableTLS" in spec:
            details["use_tls"] = bool(spec["enableTLS"])

        # Master service: IBM Redis creates <cr-name>-master-svc
        # Confirm via status.masterService if available
        status = cr.get("status", {})
        master_svc = status.get("masterService", "")
        if master_svc:
            details["master_svc"] = master_svc
            if logger:
                logger.debug(
                    f"Redis '{cr_name}' masterService from status: {master_svc}"
                )

        if logger:
            logger.debug(
                f"Redis CR '{cr_name}' details resolved: {details}"
            )

    except ApiException as exc:
        if exc.status != 404:
            raise RuntimeError(
                f"Kubernetes API error reading Redis CR '{cr_name}' "
                f"(status={exc.status}): {exc.reason}"
            ) from exc
        # CR not found — return defaults (caller handles missing-CR error)

    return details


# ---------------------------------------------------------------------------
# Public API — discovery + fetch (called by prerequisites.py generate mode)
# ---------------------------------------------------------------------------

def fetch_cnpg_mg_connection(
    namespace: str,
    logger: Optional[Logger] = None,
    confirmed_cluster_name: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    """Fetch IBM CNPG Model Gateway connection details from live cluster secrets.

    When *confirmed_cluster_name* is provided the discovery step is skipped and
    that name is used directly.  Otherwise the namespace is scanned for a Cluster
    CR whose name contains ``"mg"``; if exactly one is found it is used
    automatically; if multiple are found ``MultipleResourcesFoundError`` is raised
    so the caller can present a selection to the customer.

    Reads (always):
      <cluster>-ca    → data['ca.crt']   (CA certificate, base64)
      <cluster>-app   → data['password'] (app user password, base64)

    The RW host FQDN is taken from status.writeService or derived as:
      <cluster>-rw.<namespace>.svc.cluster.local

    Args:
        namespace:               Kubernetes namespace.
        logger:                  Optional logger.
        confirmed_cluster_name:  Pre-confirmed cluster CR name (skips discovery).

    Returns:
        4-tuple of:
          (host_fqdn, ca_cert_b64, password_b64, cluster_name)

    Raises:
        ClusterResourceNotFoundError: A required secret was not found.
        MultipleResourcesFoundError:  Multiple matching CRs found and no
                                      *confirmed_cluster_name* was provided.
        RuntimeError:                 Kubernetes API call failed.
    """
    k8s = KubernetesUtilities(logger=logger, require_connection=True)

    if confirmed_cluster_name:
        cluster_name = confirmed_cluster_name
    else:
        candidates = discover_cnpg_clusters(namespace, name_hint="mg", logger=logger)
        if not candidates:
            raise ClusterResourceNotFoundError(
                resource_kind="Cluster",
                resource_name="(name contains 'mg')",
                namespace=namespace,
                hint=(
                    "No CNPG Cluster CR with 'mg' in its name was found. "
                    "Deploy ibm_pg_cluster_mg_cr.yaml and wait for readiness."
                ),
            )
        if len(candidates) > 1:
            raise MultipleResourcesFoundError(
                resource_kind="CNPG Cluster", namespace=namespace, candidates=candidates
            )
        cluster_name = candidates[0]
        if logger:
            logger.info(f"Auto-selected CNPG MG cluster: '{cluster_name}'")

    details = get_cnpg_cluster_details(k8s, cluster_name, namespace, logger)
    host_fqdn = details["rw_service"]

    ca_cert_b64 = _get_secret_field(
        k8s=k8s,
        secret_name=details["ca_secret"],
        field_key="ca.crt",
        namespace=namespace,
        logger=logger,
    )
    password_b64 = _get_secret_field(
        k8s=k8s,
        secret_name=details["app_secret"],
        field_key="password",
        namespace=namespace,
        logger=logger,
    )

    if logger:
        logger.info(
            f"Fetched CNPG MG connection: cluster={cluster_name}, host={host_fqdn}, "
            f"ca_cert_len={len(ca_cert_b64)}, password_len={len(password_b64)}"
        )
    return host_fqdn, ca_cert_b64, password_b64, cluster_name


def fetch_cnpg_wdu_connection(
    namespace: str,
    logger: Optional[Logger] = None,
    confirmed_cluster_name: Optional[str] = None,
    confirmed_pooler_name: Optional[str] = None,
) -> Tuple[str, str, str, str, str]:
    """Fetch IBM CNPG WDU connection details from live cluster secrets.

    When *confirmed_cluster_name* is provided the discovery step is skipped.
    Otherwise the namespace is scanned for a Cluster CR whose name contains
    ``"wdu"``.

    The pooler (PgBouncer) service name is derived as:
      If *confirmed_pooler_name* is given it is used directly.
      Otherwise it is synthesised by replacing the ``"cluster"`` segment in the
      cluster CR name with ``"pooler"``, then appending ``-rw``.
      Example: ``ccx-wdu-pg`` → ``ibm-pg-pooler-wdu``

    Returns:
        Tuple of (session_fqdn, pooler_fqdn, ca_cert_b64, password_b64, cluster_name).

    Raises:
        ClusterResourceNotFoundError, MultipleResourcesFoundError, RuntimeError.
    """
    k8s = KubernetesUtilities(logger=logger, require_connection=True)

    if confirmed_cluster_name:
        cluster_name = confirmed_cluster_name
    else:
        candidates = discover_cnpg_clusters(namespace, name_hint="wdu", logger=logger)
        if not candidates:
            raise ClusterResourceNotFoundError(
                resource_kind="Cluster",
                resource_name="(name contains 'wdu')",
                namespace=namespace,
                hint=(
                    "No CNPG Cluster CR with 'wdu' in its name was found. "
                    "Deploy ibm_pg_cluster_wdu_cr.yaml and wait for readiness."
                ),
            )
        if len(candidates) > 1:
            raise MultipleResourcesFoundError(
                resource_kind="CNPG Cluster", namespace=namespace, candidates=candidates
            )
        cluster_name = candidates[0]
        if logger:
            logger.info(f"Auto-selected CNPG WDU cluster: '{cluster_name}'")

    details = get_cnpg_cluster_details(k8s, cluster_name, namespace, logger)
    session_fqdn = details["rw_service"]

    # Resolve pooler service name
    if confirmed_pooler_name:
        pooler_svc = confirmed_pooler_name
    else:
        # Discover the live Pooler CR whose spec.cluster.name == cluster_name.
        # The IBM PG operator creates a service <pooler-cr-name> in the namespace.
        pooler_candidates = discover_cnpg_poolers(namespace, cluster_name, logger)
        if pooler_candidates:
            pooler_cr_name = pooler_candidates[0]
            if len(pooler_candidates) > 1 and logger:
                logger.warning(
                    f"Multiple Poolers found for cluster '{cluster_name}': "
                    f"{pooler_candidates} — using '{pooler_cr_name}'"
                )
            if logger:
                logger.info(
                    f"Discovered Pooler CR '{pooler_cr_name}' for cluster '{cluster_name}'"
                )
        else:
            # No Pooler CR deployed yet — fall back to name derivation so the
            # generated secret contains a plausible value that the customer can
            # update after the Pooler is deployed.
            pooler_cr_name = re.sub(r"cluster", "pooler", cluster_name, flags=re.IGNORECASE)
            if logger:
                logger.warning(
                    f"No Pooler CR found for cluster '{cluster_name}' — "
                    f"falling back to derived name '{pooler_cr_name}'"
                )
        #pooler_svc = f"{pooler_cr_name}-rw.{namespace}.svc.cluster.local"
        pooler_svc = f"{pooler_cr_name}.{namespace}.svc.cluster.local"

    ca_cert_b64 = _get_secret_field(
        k8s=k8s,
        secret_name=details["ca_secret"],
        field_key="ca.crt",
        namespace=namespace,
        logger=logger,
    )
    password_b64 = _get_secret_field(
        k8s=k8s,
        secret_name=details["app_secret"],
        field_key="password",
        namespace=namespace,
        logger=logger,
    )

    if logger:
        logger.info(
            f"Fetched CNPG WDU connection: cluster={cluster_name}, "
            f"session={session_fqdn}, pooler={pooler_svc}, "
            f"ca_cert_len={len(ca_cert_b64)}, password_len={len(password_b64)}"
        )
    return session_fqdn, pooler_svc, ca_cert_b64, password_b64, cluster_name


def fetch_redis_connection(
    namespace: str,
    logger: Optional[Logger] = None,
    confirmed_cr_name: Optional[str] = None,
) -> Tuple[str, str, str]:
    """Fetch IBM Redis Model Gateway connection details from live cluster secrets.

    When *confirmed_cr_name* is provided the discovery step is skipped.
    Otherwise the namespace is scanned for a RedisCP CR whose name contains
    ``"mg"``.

    The password secret name and master service name are read from the live CR.

    Returns:
        Tuple of (master_svc_host, password_b64, cr_name).

    Raises:
        ClusterResourceNotFoundError, MultipleResourcesFoundError, RuntimeError.
    """
    k8s = KubernetesUtilities(logger=logger, require_connection=True)

    if confirmed_cr_name:
        cr_name = confirmed_cr_name
    else:
        candidates = discover_redis_crs(namespace, name_hint="mg", logger=logger)
        if not candidates:
            raise ClusterResourceNotFoundError(
                resource_kind="RedisCP",
                resource_name="(name contains 'mg')",
                namespace=namespace,
                hint=(
                    "No IBM Redis CR with 'mg' in its name was found. "
                    "Deploy ibm_redis_cr.yaml and wait for readiness."
                ),
            )
        if len(candidates) > 1:
            raise MultipleResourcesFoundError(
                resource_kind="Redis CR", namespace=namespace, candidates=candidates
            )
        cr_name = candidates[0]
        if logger:
            logger.info(f"Auto-selected Redis CR: '{cr_name}'")

    details = get_redis_cr_details(k8s, cr_name, namespace, logger)
    host = details["master_svc"]

    password_b64 = _get_secret_field(
        k8s=k8s,
        secret_name=details["password_secret"],
        field_key="password",
        namespace=namespace,
        logger=logger,
    )

    if logger:
        logger.info(
            f"Fetched Redis connection: cr={cr_name}, host={host}, "
            f"password_len={len(password_b64)}"
        )
    return host, password_b64, cr_name

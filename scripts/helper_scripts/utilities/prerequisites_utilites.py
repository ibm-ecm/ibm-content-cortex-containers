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
import base64
import binascii
import inspect
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import warnings

import time
import yaml
# from OpenSSL import SSL
from cryptography import x509
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from cryptography.utils import CryptographyDeprecationWarning
from rich import print
from rich.panel import Panel
from rich.text import Text

warnings.filterwarnings("ignore", category=CryptographyDeprecationWarning)

_CIPHERS = bytes(
    "TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256",
    'utf-8')


# create a private method that reads in json into a dictionary
def read_json(directory, json_file):
    path = os.path.join(directory, json_file)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Create a method to zip a folder and return the path to the zip file
def zip_folder(zip_file_name: str, folder_path: str) -> str:
    """Zip a folder and return the path to the zip file."""
    zip_file = shutil.make_archive(zip_file_name, "zip", folder_path, )
    return zip_file

def collect_visible_folders(directory_path='.'):
    """
    Returns a list of visible (non-hidden) folders using pathlib.

    Filters based on Unix-style dot-files. For Windows attributes, 
    additional checks (not shown here for simplicity) may be needed.
    """
    p = Path(directory_path)
    # Use list comprehension to iterate through items and filter out dot-files
    visible_folders = [item for item in p.iterdir() if item.is_dir() and not item.name.startswith('.')]
    # Return the list of visible folders names
    return [item.name for item in visible_folders]

def collect_visible_files(directory_path='.'):
    """
    Returns a list of visible (non-hidden) files using pathlib.
    Filters based on Unix-style dot-files. For Windows attributes,  
    additional checks (not shown here for simplicity) may be needed.
    """
    p = Path(directory_path)
    # Use list comprehension to iterate through items and filter out dot-files
    visible_files = [item for item in p.iterdir() if item.is_file() and not item.name.startswith('.')]
    # Return the list of visible files names
    return [item.name for item in visible_files]


# Adding idp certificate to trusted certificates folder
def add_idp_to_trusted_certs(ssl_cert_folder, trusted_certs_folder):
    if os.path.exists(ssl_cert_folder):
        ssl_folders = collect_visible_folders(ssl_cert_folder)

        # remove any hidden files that might be picked up and remove the trusted-certs folder
        for folder in ssl_folders:
            if folder.startswith(".") or folder == "trusted-certs":
                ssl_folders.remove(folder)

    idp_folders = list(filter(lambda x: "idp" in x, ssl_folders))

    for item in idp_folders:
        folderpath = os.path.join(ssl_cert_folder, item)
        ssl_certs = collect_visible_files(folderpath)
    
        for cert in ssl_certs:
            if any(ext in cert for ext in [".crt", ".cer", ".cert", ".pem", ".key", ".arm"]):
                cert_file_path = os.path.join(folderpath, cert)
                trusted_idp_cert_path = os.path.join(trusted_certs_folder, cert)
                os.makedirs(trusted_certs_folder, exist_ok=True)
                shutil.copy2(cert_file_path, trusted_idp_cert_path)


# Create a method to create the generatedfiles folder structure and zip it up if it is present
def create_generate_folder(trusted_certs_present, namespace='', create_metrics=True, vault_enabled=False) -> None:
    """
    Create the generated files folder structure.
    
    Args:
        trusted_certs_present: Whether to create trusted certs folder
        namespace: Namespace for the deployment
        create_metrics: Whether to create metrics folder (default True, set False for AI Services only)
        vault_enabled: Whether vault is enabled (if True, skip secrets/ and ssl/ folders)
    """
    generate_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)
    generate_metrics_folder = os.path.join(generate_folder, "metrics")
    generate_vault_folder = os.path.join(generate_folder, "vault")
    generate_vault_json_folder = os.path.join(generate_vault_folder, "json-data")
    generate_vault_spc_folder = os.path.join(generate_vault_folder, "secret-provider-classes")
    
    # Always create base folder.
    # exist_ok=True is required when infrastructure/ already exists from gather mode —
    # rmtree is selective (skips infrastructure/), so the parent dir may still be alive.
    os.makedirs(generate_folder, exist_ok=True)
    
    # Create vault folders if vault is enabled
    if vault_enabled:
        os.makedirs(generate_vault_folder)
        os.makedirs(generate_vault_json_folder)
        os.makedirs(generate_vault_spc_folder)
    else:
        # Create K8s secret folders only when vault is NOT enabled
        generate_secrets_folder = os.path.join(generate_folder, "secrets")
        generate_ssl_secrets_folder = os.path.join(generate_folder, "ssl")
        generate_trusted_secrets_folder = os.path.join(generate_folder, "ssl", "trusted-certs")
        os.makedirs(generate_secrets_folder)
        os.makedirs(generate_ssl_secrets_folder)
        if trusted_certs_present:
            os.makedirs(generate_trusted_secrets_folder)
    
    # Create metrics folder if requested (independent of vault)
    if create_metrics:
        os.makedirs(generate_metrics_folder)

def parse_required_fields(required_fields):
    parsed_fields = {}
    for entry in required_fields:
        section = entry[0][0]
        paramter = entry[0][1]
        # check if section exists
        if section not in parsed_fields:
            parsed_fields[section] = []
        parsed_fields[section].append(paramter)
    return parsed_fields


# Function to check if private key is of pem format
def check_pem_key_format(ssl_cert,passkey=None):
    data = None
    try:
        with open(ssl_cert, 'rb') as file:
            data = file.read()
        # Attempt to load it as a private key
        if passkey:
            serialization.load_pem_private_key(data, password=passkey.encode("utf-8"), backend=default_backend())
        else:
            serialization.load_pem_private_key(data, password=None, backend=default_backend())
        # If successful, it's a valid PEM file
        return True
    except Exception:
        if data is not None:
            try:
                # Attempt to load it as a public key
                serialization.load_pem_public_key(data, backend=default_backend())
                # If successful, it's a valid PEM file
                return True
            except Exception:
                # Not a valid PEM file
                return False
        else:
            # File could not be read
            return False


# Function to check if ssl cert is of pem format
def check_pem_cert_format(ssl_cert):
    try:
        with open(ssl_cert, 'rb') as file:
            data = file.read()
        x509.load_pem_x509_certificate(data, default_backend())
        return True
    except Exception as e:
        return False


# Function to check all cert formats recursively for postgres SSL
def check_ssl_certs_postgres(folder_list, cert_path):
    for cert in folder_list:
        if cert.startswith("."):
            os.remove(os.path.join(cert_path, cert))
        else:
            pem_cert_check = check_pem_cert_format(os.path.join(cert_path, cert))
            if not pem_cert_check:
                pem_key_check = check_pem_key_format(os.path.join(cert_path, cert))
                if not pem_key_check:
                    return False
                else:
                    return True
            else:
                return True

def _check_pg_ssl_subfolder(
    folder: str,
    ssl_cert_folder: str,
    ssl_mode: str,
    missing_cert: dict,
    incorrect_cert: dict,
) -> None:
    """Validate serverca/clientcert/clientkey subfolders for a postgres SSL cert folder.

    This is the same logic used for Content DB postgres, extracted so that both
    WDU (wdu/) and Model Gateway (model-gateway/) can reuse it
    with their own component-specific ssl_mode.

    Args:
        folder:          The ssl-certs sub-folder name (e.g. 'wdu').
        ssl_cert_folder: Root ssl-certs directory path.
        ssl_mode:        'require' | 'verify-ca' | 'verify-full'.
        missing_cert:    Mutable dict accumulating missing-cert findings.
        incorrect_cert:  Mutable dict accumulating bad-format cert findings.
    """
    sub_folder_path = os.path.join(ssl_cert_folder, folder)
    sub_folders = collect_visible_folders(sub_folder_path)

    server_ca = False
    clientkey = False
    clientcert = False

    for sub_folder in sub_folders:
        if "serverca" in sub_folder.lower():
            items = collect_visible_files(os.path.join(sub_folder_path, sub_folder))
            if items:
                server_ca = True
                if not check_ssl_certs_postgres(items, os.path.join(sub_folder_path, sub_folder)):
                    incorrect_cert.setdefault(folder, []).append("serverca")

        if "clientkey" in sub_folder.lower():
            items = collect_visible_files(os.path.join(sub_folder_path, sub_folder))
            if items:
                clientkey = True
                if not check_ssl_certs_postgres(items, os.path.join(sub_folder_path, sub_folder)):
                    incorrect_cert.setdefault(folder, []).append("clientkey")

        if "clientcert" in sub_folder.lower():
            items = collect_visible_files(os.path.join(sub_folder_path, sub_folder))
            if items:
                clientcert = True
                if not check_ssl_certs_postgres(items, os.path.join(sub_folder_path, sub_folder)):
                    incorrect_cert.setdefault(folder, []).append("clientcert")

    mode = ssl_mode.lower()
    if mode == "verify-full":
        for key, present in (("serverca", server_ca), ("clientkey", clientkey), ("clientcert", clientcert)):
            if not present:
                missing_cert.setdefault(folder, []).append(key)
    elif mode == "require":
        if clientcert or clientkey:
            if not clientkey:
                missing_cert.setdefault(folder, []).append("clientkey")
            if not clientcert:
                missing_cert.setdefault(folder, []).append("clientcert")
        elif not server_ca:
            missing_cert.setdefault(folder, []).append("serverca")
    elif mode == "verify-ca":
        if clientcert or clientkey:
            if not server_ca:
                missing_cert.setdefault(folder, []).append("serverca")
            if not clientkey:
                missing_cert.setdefault(folder, []).append("clientkey")
            if not clientcert:
                missing_cert.setdefault(folder, []).append("clientcert")
        elif not server_ca:
            missing_cert.setdefault(folder, []).append("serverca")


# Function to check if ssl certs are added to the respective folders
def check_ssl_folders(db_prop=None, ldap_prop=None, ssl_cert_folder=None,
                      deploy_prop=None, idp_prop=None, scim_prop=None,
                      graphql_prop=None, aiservices_prop=None,
                      mg_use_ibm_cnpg=False,
                      wdu_prop=None, wdu_use_ibm_cnpg=False) -> tuple:
    missing_cert = {}
    incorrect_cert = {}
    mg_cnpg_cert_reminder = False
    # if any ssl cert folders exists that means ssl was enabled for either ldap or DB
    if os.path.exists(ssl_cert_folder):
        ssl_folders = collect_visible_folders(ssl_cert_folder)

        # remove any hidden files that might be picked up and remove the trusted-certs folder
        for folder in ssl_folders.copy():
            if folder == "trusted-certs":
                ssl_folders.remove(folder)

        # Creating list of different ssl folders: ldap, db, idp, scim, graphql, ai providers
        ldap_folders = list(filter(lambda x: "ldap" in x, ssl_folders))
        idp_folders = list(filter(lambda x: "idp" in x, ssl_folders))
        scim_folders = list(filter(lambda x: "scim" in x, ssl_folders))
        graphql_folders = list(filter(lambda x: "graphql" in x, ssl_folders))
        # LWE provider folders: watsonx-onprem, watsonx-onprem-2, etc.
        ai_provider_folders = list(filter(lambda x: x.startswith("ai-provider-") or x.startswith("watsonx-onprem"), ssl_folders))
        # When IBM-managed CNPG is selected, cert injection is handled at generate time
        # (generate_cnpg_redis.py). Skip cert validation and surface a reminder instead.
        if mg_use_ibm_cnpg and "model-gateway" in ssl_folders:
            mg_folders = ["model-gateway"]
            mg_cnpg_cert_reminder = True
        else:
            mg_folders = []
        # WDU IBM CNPG: same pattern — no folder validation needed; cert fetched live.
        # The "wdu" parent dir appears in ssl_folders; its pg_sess/pg_txn children are
        # validated separately in the WDU-specific check below.
        wdu_folders = ["wdu"] if (wdu_use_ibm_cnpg and "wdu" in ssl_folders) else (
            ["wdu"] if "wdu" in ssl_folders else []
        )
        non_db_folders = (ldap_folders + idp_folders + scim_folders + graphql_folders
                          + ai_provider_folders + mg_folders + wdu_folders)
        db_folders = set(ssl_folders) - set(non_db_folders)

        # if db type is not postgres we have a standard folder structure of ssl certs
        # Only check database SSL if db_prop exists (Content operator deployed)
        if db_prop and db_prop.get("DATABASE_SSL_ENABLE"):
            if db_prop.get("DATABASE_TYPE", "").lower() != "postgresql":
                for folder in db_folders:
                    ssl_certs = collect_visible_files(os.path.join(ssl_cert_folder, folder))
                    if not ssl_certs:
                        missing_cert[folder] = ["certificate"]
                    # logic to check if the cert is the right pem format
                    else:
                        for cert in ssl_certs:
                            if cert.startswith("."):
                                os.remove(os.path.join(ssl_cert_folder, folder, cert))
                            else:
                                pem_cert_check = check_pem_cert_format(os.path.join(ssl_cert_folder, folder, cert))
                                if not pem_cert_check:
                                    pem_key_check = check_pem_key_format(os.path.join(ssl_cert_folder, folder, cert))
                                    if not pem_key_check:
                                        incorrect_cert[folder] = ["certificate"]
            else:
                # if db type is postgres we have three sub folders inside the db ssl cert folders which need to be checked for ssl certs
                for folder in db_folders:

                    sub_folder_path = os.path.join(ssl_cert_folder, folder)
                    sub_folders = collect_visible_folders(sub_folder_path)

                    server_ca = False
                    clientkey = False
                    clientcert = False
                    for sub_folder in sub_folders:
                        if "serverca" in sub_folder.lower():
                            server_ca_items = collect_visible_files(os.path.join(sub_folder_path, sub_folder))
                            if server_ca_items:
                                server_ca = True
                                incorrect_cert_present = check_ssl_certs_postgres(server_ca_items,
                                                                                  os.path.join(sub_folder_path,
                                                                                               sub_folder))
                                if not incorrect_cert_present:
                                    if folder not in incorrect_cert:
                                        incorrect_cert[folder] = []
                                        incorrect_cert[folder].append("serverca")
                                    else:
                                        incorrect_cert[folder].append("serverca")

                        if "clientkey" in sub_folder.lower():
                            clientkey_items = collect_visible_files(os.path.join(sub_folder_path, sub_folder))
                            if clientkey_items:
                                clientkey = True
                                incorrect_cert_present = check_ssl_certs_postgres(clientkey_items,
                                                                                  os.path.join(sub_folder_path,
                                                                                               sub_folder))
                                if not incorrect_cert_present:
                                    if folder not in incorrect_cert:
                                        incorrect_cert[folder] = []
                                        incorrect_cert[folder].append("clientkey")
                                    else:
                                        incorrect_cert[folder].append("clientkey")
                        if "clientcert" in sub_folder.lower():
                            clientcert_items = collect_visible_files(os.path.join(sub_folder_path, sub_folder))
                            if clientcert_items:
                                clientcert = True
                                incorrect_cert_present = check_ssl_certs_postgres(clientcert_items,
                                                                                  os.path.join(sub_folder_path,
                                                                                               sub_folder))
                                if not incorrect_cert_present:
                                    if folder not in incorrect_cert:
                                        incorrect_cert[folder] = []
                                        incorrect_cert[folder].append("clientcert")
                                    else:
                                        incorrect_cert[folder].append("clientcert")
                    if db_prop["DATABASE_SSL_ENABLE"]:
                        if db_prop["SSL_MODE"].lower() == "verify-full":
                            # All certs are required for "verify-full" mode
                            if not server_ca:
                                if folder not in missing_cert:
                                    missing_cert[folder] = []
                                    missing_cert[folder].append("serverca")
                                else:
                                    missing_cert[folder].append("serverca")
                            if not clientkey:
                                if folder not in missing_cert:
                                    missing_cert[folder] = []
                                    missing_cert[folder].append("clientkey")
                                else:
                                    missing_cert[folder].append("clientkey")
                            if not clientcert:
                                if folder not in missing_cert:
                                    missing_cert[folder] = []
                                    missing_cert[folder].append("clientcert")
                                else:
                                    missing_cert[folder].append("clientcert")
                        elif db_prop["SSL_MODE"].lower() == "require":
                            # Require mode can be either Client or Server Authentication
                            # Selected Client Authentication
                            if (clientcert or clientkey):
                                if not clientkey:
                                    if folder not in missing_cert:
                                        missing_cert[folder] = []
                                        missing_cert[folder].append("clientkey")
                                    else:
                                        missing_cert[folder].append("clientkey")
                                if not clientcert:
                                    if folder not in missing_cert:
                                        missing_cert[folder] = []
                                        missing_cert[folder].append("clientcert")
                                    else:
                                        missing_cert[folder].append("clientcert")
                            # Selected Server Authentication
                            elif not server_ca:
                                if folder not in missing_cert:
                                    missing_cert[folder] = []
                                    missing_cert[folder].append("serverca")
                                else:
                                    missing_cert[folder].append("serverca")
                        elif db_prop["SSL_MODE"].lower() == "verify-ca" and folder != "ldap":
                            # Verify-ca mode requires a server-ca cert
                            if clientcert or clientkey:
                                if not server_ca:
                                    if folder not in missing_cert:
                                        missing_cert[folder] = []
                                        missing_cert[folder].append("serverca")
                                    else:
                                        missing_cert[folder].append("serverca")

                                if not clientkey:
                                    if folder not in missing_cert:
                                        missing_cert[folder] = []
                                        missing_cert[folder].append("clientkey")
                                    else:
                                        missing_cert[folder].append("clientkey")

                                if not clientcert:
                                    if folder not in missing_cert:
                                        missing_cert[folder] = []
                                        missing_cert[folder].append("clientcert")
                                    else:
                                        missing_cert[folder].append("clientcert")
                            else:
                                if not server_ca:
                                    if folder not in missing_cert:
                                        missing_cert[folder] = []
                                        missing_cert[folder].append("serverca")
                                    else:
                                        missing_cert[folder].append("serverca")


        # base logic for ldap cert folder
        for folder in ldap_folders:
            if ldap_prop[folder.upper()]["LDAP_SSL_ENABLED"]:
                ssl_certs = collect_visible_files(os.path.join(ssl_cert_folder, folder))
                if not ssl_certs:
                    if folder not in missing_cert:
                        missing_cert[folder] = []
                        missing_cert[folder].append("certificate")
                    else:
                        missing_cert[folder].append("certificate")
                else:
                    for cert in ssl_certs:
                        if cert.startswith("."):
                            os.remove(os.path.join(ssl_cert_folder, folder, cert))
                        else:
                            pem_cert_check = check_pem_cert_format(os.path.join(ssl_cert_folder, folder, cert))
                            if not pem_cert_check:
                                pem_key_check = check_pem_key_format(os.path.join(ssl_cert_folder, folder, cert))
                                if not pem_key_check:
                                    incorrect_cert[folder] = ["certificate"]

        # for idp certs we have to check if the ssl is enabled and then check the certs
        for folder in idp_folders:
            if idp_prop[folder.upper()]["IDP_SSL_ENABLED"]:
                ssl_certs = collect_visible_files(os.path.join(ssl_cert_folder, folder))
                if not ssl_certs:
                    if folder not in missing_cert:
                        missing_cert[folder] = []
                        missing_cert[folder].append("certificate")
                    else:
                        missing_cert[folder].append("certificate")
                else:
                    for cert in ssl_certs:
                        if cert.startswith("."):
                            os.remove(os.path.join(ssl_cert_folder, folder, cert))
                        else:
                            pem_cert_check = check_pem_cert_format(os.path.join(ssl_cert_folder, folder, cert))
                            if not pem_cert_check:
                                pem_key_check = check_pem_key_format(os.path.join(ssl_cert_folder, folder, cert))
                                if not pem_key_check:
                                    incorrect_cert[folder] = ["certificate"]

        # for scim certs we have to check if the ssl is enabled and then check the certs
        for folder in scim_folders:
            if scim_prop[folder.upper()]["SCIM_SSL_ENABLED"]:
                ssl_certs = collect_visible_files(os.path.join(ssl_cert_folder, folder))
                if not ssl_certs:
                    if folder not in missing_cert:
                        missing_cert[folder] = []
                        missing_cert[folder].append("certificate")
                    else:
                        missing_cert[folder].append("certificate")
                else:
                    for cert in ssl_certs:
                        if cert.startswith("."):
                            os.remove(os.path.join(ssl_cert_folder, folder, cert))
                        else:
                            pem_cert_check = check_pem_cert_format(os.path.join(ssl_cert_folder, folder, cert))
                            if not pem_cert_check:
                                pem_key_check = check_pem_key_format(os.path.join(ssl_cert_folder, folder, cert))
                                if not pem_key_check:
                                    incorrect_cert[folder] = ["certificate"]

        # for graphql certs - always required when graphql folder exists
        # GraphQL certificates are mandatory for AI Services integration
        for folder in graphql_folders:
            ssl_certs = collect_visible_files(os.path.join(ssl_cert_folder, folder))
            if not ssl_certs:
                if folder not in missing_cert:
                    missing_cert[folder] = []
                    missing_cert[folder].append("certificate")
                else:
                    missing_cert[folder].append("certificate")
            else:
                for cert in ssl_certs:
                    if cert.startswith("."):
                        os.remove(os.path.join(ssl_cert_folder, folder, cert))
                    else:
                        pem_cert_check = check_pem_cert_format(os.path.join(ssl_cert_folder, folder, cert))
                        if not pem_cert_check:
                            pem_key_check = check_pem_key_format(os.path.join(ssl_cert_folder, folder, cert))
                            if not pem_key_check:
                                incorrect_cert[folder] = ["certificate"]

        # for AI provider certs - only check for Lightweight Engine (LWE) providers
        if aiservices_prop:
            provider_ids = aiservices_prop.get("_provider_ids", [])
            # property.py creates watsonx-onprem/ for 1st LWE, watsonx-onprem-2/ for 2nd, etc.
            lwe_idx = 0

            for provider_id in provider_ids:
                provider_config = aiservices_prop.get(provider_id, {})
                provider_url = provider_config.get("PROVIDER_URL", "")
                provider_type = provider_config.get("PROVIDER_TYPE", "").lower()
                enabled = str(provider_config.get("ENABLED", "true")).lower() == "true"

                is_lwe = provider_type in ["watsonx_lwe"]
                if enabled and is_lwe and provider_url and provider_url.startswith("https://") and provider_url != "<Required>":
                    lwe_idx += 1
                    suffix = f"-{lwe_idx}" if lwe_idx > 1 else ""
                    expected_folder = f"watsonx-onprem{suffix}"

                    matching_folders = [f for f in ssl_folders if f.lower() == expected_folder.lower()]
                    
                    if matching_folders:
                        for folder in matching_folders:
                            ssl_certs = collect_visible_files(os.path.join(ssl_cert_folder, folder))
                            if not ssl_certs:
                                if folder not in missing_cert:
                                    missing_cert[folder] = []
                                    missing_cert[folder].append("certificate")
                                else:
                                    missing_cert[folder].append("certificate")
                            else:
                                for cert in ssl_certs:
                                    if cert.startswith("."):
                                        os.remove(os.path.join(ssl_cert_folder, folder, cert))
                                    else:
                                        pem_cert_check = check_pem_cert_format(os.path.join(ssl_cert_folder, folder, cert))
                                        if not pem_cert_check:
                                            pem_key_check = check_pem_key_format(os.path.join(ssl_cert_folder, folder, cert))
                                            if not pem_key_check:
                                                incorrect_cert[folder] = ["certificate"]
                    else:
                        # Provider has HTTPS URL but no SSL folder - add to missing
                        if expected_folder not in missing_cert:
                            missing_cert[expected_folder] = []
                            missing_cert[expected_folder].append("certificate")
                        else:
                            missing_cert[expected_folder].append("certificate")

        # ── WDU external postgres SSL check ──────────────────────────────────
        # Only run when external (BYO) postgres is configured and SSL is enabled.
        # IBM-managed CNPG injects its CA cert at generate time — no check needed.
        # WDU uses per-pooler cert subdirs: ssl-certs/wdu/pg_sess/ and ssl-certs/wdu/pg_txn/.
        # Both are validated independently using the same SSL settings.
        if wdu_prop and not wdu_use_ibm_cnpg:
            # postgres_session is the primary TOML section; fall back to bare postgres.
            _wdu_pg = (
                wdu_prop.get("postgres_session")
                or wdu_prop.get("postgres", {})
            )
            _wdu_ssl = str(_wdu_pg.get("SSL_ENABLED", False)).lower() in ("true", "1", "yes")
            if _wdu_ssl:
                _wdu_mode = str(_wdu_pg.get("SSL_MODE", "require"))
                # Per-pooler layout: ssl-certs/wdu/pg_sess/ and ssl-certs/wdu/pg_txn/
                for _pool_subdir in ("wdu/pg_sess", "wdu/pg_txn"):
                    _pool_path = os.path.join(ssl_cert_folder, _pool_subdir)
                    if os.path.isdir(_pool_path):
                        _check_pg_ssl_subfolder(
                            folder=_pool_subdir,
                            ssl_cert_folder=ssl_cert_folder,
                            ssl_mode=_wdu_mode,
                            missing_cert=missing_cert,
                            incorrect_cert=incorrect_cert,
                        )
                    else:
                        # SSL is enabled but the per-pooler folder was never created.
                        missing_cert.setdefault(_pool_subdir, []).append("serverca")

        # ── MG external postgres SSL check ───────────────────────────────────
        # Same pattern as WDU: only runs for external (BYO) postgres with SSL enabled.
        # IBM-managed CNPG path is handled by the mg_cnpg_cert_reminder path above.
        if not mg_use_ibm_cnpg:
            # model_gateway_prop is not a direct parameter; check via db_folders exclusion.
            # The folder 'model-gateway' is already excluded from db_folders when
            # mg_use_ibm_cnpg=True.  When it is False we validate it here with MG's own
            # SSL settings rather than relying on the Content db_prop.
            _mg_folder = "model-gateway"
            if _mg_folder in ssl_folders:
                # We need the MG property dict to read SSL settings.
                # It is not passed directly; infer from the folder's presence.
                # If a caller passes mg_prop in the future, prefer that; for now
                # we check whether the folder has any certs (presence implies SSL was intended).
                # Full per-mode validation is delegated to _check_pg_ssl_subfolder when
                # the caller passes `mg_ssl_mode` — see the extended signature note below.
                # For backward compat we do a basic non-empty-folder check here only when
                # mg_use_ibm_cnpg=False and no ssl_mode is available from the prop dict.
                _mg_sub = os.path.join(ssl_cert_folder, _mg_folder)
                if os.path.isdir(_mg_sub):
                    _serverca = collect_visible_files(os.path.join(_mg_sub, "serverca")) if os.path.isdir(os.path.join(_mg_sub, "serverca")) else []
                    _clientcert = collect_visible_files(os.path.join(_mg_sub, "clientcert")) if os.path.isdir(os.path.join(_mg_sub, "clientcert")) else []
                    _clientkey = collect_visible_files(os.path.join(_mg_sub, "clientkey")) if os.path.isdir(os.path.join(_mg_sub, "clientkey")) else []
                    # Check cert format validity for any certs that are present
                    for _sub_name, _items in (("serverca", _serverca), ("clientcert", _clientcert), ("clientkey", _clientkey)):
                        for _cert in _items:
                            if not _cert.startswith("."):
                                if not check_pem_cert_format(os.path.join(_mg_sub, _sub_name, _cert)):
                                    if not check_pem_key_format(os.path.join(_mg_sub, _sub_name, _cert)):
                                        incorrect_cert.setdefault(_mg_folder, []).append(_sub_name)

    return missing_cert, incorrect_cert, mg_cnpg_cert_reminder


# Function to check if icc masterkey file is present
def check_icc_masterkey(custom_component_prop, icc_folder):
    # if custom component property file is empty then we know icc is not present and we can skip the check
    if not custom_component_prop:
        return True
    if custom_component_prop and "ICC" not in custom_component_prop.keys():
        return True
    # the file to create the secret has to be in .txt format
    if os.path.exists(icc_folder):
        file_list = collect_visible_files(icc_folder)
        if not file_list:
            return False
        else:
            for file in file_list:
                if file.endswith('.txt'):
                    return True
            return False


# Function to check if there are certs in the trusted cert folder
def check_trusted_certs(trusted_certs_folder):
    # the certs have to be in .pem , .crt , .cert
    invalid_certs = []
    if os.path.exists(trusted_certs_folder):
        file_lists = collect_visible_files(trusted_certs_folder)

        if len(file_lists) > 0:
            # some certs have been added
            for file in file_lists:
                if file.startswith("."):
                    os.remove(os.path.join(trusted_certs_folder, file))
                else:
                    # check if the cert is in the right format
                    # if not then add it to the invalid certs list
                    pem_cert_check = check_pem_cert_format(os.path.join(trusted_certs_folder, file))
                    if not pem_cert_check:
                        pem_key_check = check_pem_key_format(os.path.join(trusted_certs_folder, file))
                        # if the cert is not in the right format then add it to the invalid certs list
                        if not pem_key_check:
                            invalid_certs.append(file)
            return True, invalid_certs
        else:
            return False, invalid_certs
    else:
        return True, invalid_certs


def check_dbname(db_prop):
    incorrect_naming_convention = []
    if db_prop["DATABASE_TYPE"].lower() == "db2":
        for db in db_prop["db_list"]:
            if len(db_prop[db]["DATABASE_NAME"]) > 8:
                incorrect_naming_convention.append(db)
    return incorrect_naming_convention


# Function to check if keystore password is atleast 16characters long for FIPS enabled
def check_keystore_password_length(user_group_prop, deploy_prop):
    # checking if fips support is enabled
    if "FIPS_SUPPORT" in deploy_prop.keys():
        if deploy_prop["FIPS_SUPPORT"]:
            if len(user_group_prop["KEYSTORE_PASSWORD"]) < 16:
                return False
    return True


# Function to check if db password is atleast 16 characters long for FIPS enabled
def check_db_password_length(db_prop, deploy_prop):
    # checking if fips support is enabled
    incorrect_password_dbs = []
    if "FIPS_SUPPORT" in deploy_prop.keys():
        if deploy_prop["FIPS_SUPPORT"] and db_prop["DATABASE_TYPE"].lower() == "postgresql":
            for db in db_prop["db_list"]:
                if len(db_prop[db]["DATABASE_PASSWORD"]) < 16:
                    incorrect_password_dbs.append(db)
    return incorrect_password_dbs


# Function to check if db ssl mode is require for postgres for FIPS enabled
def check_db_ssl_mode(db_prop, deploy_prop):
    # checking if fips support is enabled
    correct_ssl_mode = True
    if "FIPS_SUPPORT" in deploy_prop.keys():
        if deploy_prop["FIPS_SUPPORT"] and db_prop["DATABASE_TYPE"].lower() == "postgresql" and db_prop[
            "DATABASE_SSL_ENABLE"]:
            if db_prop["SSL_MODE"].lower() != "require":
                correct_ssl_mode = False
    return correct_ssl_mode


def get_skopeo_version(logger):
    try:
        # Get the skopeo version
        skopeo_version = subprocess.check_output(["skopeo", "--version"]).decode("utf-8")
        skopeo_version = skopeo_version.split()[2]
        logger.info(f"Skopeo Version: {skopeo_version}")
        return skopeo_version
    except Exception as e:
        logger.info(f"Error: {e}")
        return None


def check_java_version(ccx_version):
    try:
        java_version_output = subprocess.check_output(['java', '-version'], stderr=subprocess.STDOUT, text=True)
        version_match = re.search(r'"(\d+\.\d+\.\d+)', java_version_output)
        java_version = version_match.group(1) if version_match else "Unknown"

        if java_version == "Unknown":
            return False

        return java_version
    except subprocess.CalledProcessError as e:
        return False

def create_ssl_context(client_cert_file=None) :
    if client_cert_file:
        context = ssl.create_default_context(cafile=client_cert_file)
    else:
        context = ssl.create_default_context()
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    context.set_ciphers(_CIPHERS.decode('utf-8'))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context

def resolve_ip_addreses(host, progress):
    try :
        ip_addreses = []
        for address in socket.getaddrinfo(host,None):
            ip = address[4][0]
            if ip not in ip_addreses:
                ip_addreses.append(ip)
        return ip_addreses
    except socket.gaierror as e:
        msg = Text(f"Failed to resolve IP for the host : {host} \nError : {e}", style="bold red")
        if progress:
            progress.log(msg)
        else:
            print(msg)
        return []

def connect_to_server(host, port, ssl=False, client_cert_file=None, pg=False, progress=None, logger=None):
    """
    Method_name: connect_to_server
    Description: Establishes a connection to a server.

    Parameters:
        host (str):                         The hostname or IP address of the server to connect to.
        port (int):                         The port number to connect to on the server.
        ssl (bool, optional):               Whether to use SSL encryption for the connection. Defaults to False.
        client_cert_file (str, optional):   The path to the client certificate file, if SSL encryption
                                            is enabled. Defaults to None.
        pg (bool, optional):                Whether the connection is for PostgreSQL. Defaults to False.
        progress (Any, optional):           An object that provides a logging method for progress updates. Defaults to None.

    Returns:
    Tuple[socket.socket, float, bool]:  A tuple containing the connection object, the round-trip time (RTT),
                                        and a boolean indicating whether the connection was established.

    Raises:
        socket.gaierror: If the hostname is not known.
        Exception: If any other error occurs during the connection process.
    """
    conn = None
    connected = False
    try:
        hostname = host.strip("[]")
        addr_info = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
        # Sort addr_info to prefer IPv6 over IPv4
        addr_info.sort(key=lambda x: 0 if x[0] == socket.AF_INET6 else 1)
        # If SSL is enabled, create an SSL socket
        # Create an SSL context
        if ssl:
            logger.info(f"Connecting to {host}:{port} with SSL")
            if client_cert_file:
                logger.info(f"Using SSL certificate {client_cert_file}")
                context = create_ssl_context(client_cert_file)
            else:
                context = create_ssl_context()
            # Create an SSL socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
                conn = context.wrap_socket(socket.socket(socket.AF_INET),
                           server_hostname=hostname)
            # for family, socktype, proto, _, sockaddr in addr_info:
            #     sock = socket.socket(family,socktype,proto)
        else:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)

        # Connection
        connected = False
        start_time = time.time()
        conn.settimeout(10)
        conn.connect((hostname, port))
        end_time = time.time()

        if ssl:
            # Postgres requires protocol negotiation before SSL since everything's on same port
            # https://www.postgresql.org/docs/current/protocol-flow.html#PROTOCOL-FLOW-SSL
            if pg:
                version_ssl = struct.pack('!I', 1234 << 16 | 5679)
                length = struct.pack('!I', 8)
                packet = length + version_ssl
                sock.sendall(packet)
                sock.recv(1)
            conn.do_handshake()
        connected = True

    # Now you can perform LDAP operations using 'conn' if needed
    except socket.gaierror as e:
        logger.info(msg=f"Connection failed: {e}")
        message = Text(
            f"Hostname \"{host}\" is not known.\n"
            f"Please review the Property Files for all SERVERNAME parameters", style="bold red")
        if progress:
            progress.log(message)
            progress.log()
        else:
            print(message)
        return conn, 0, connected
    except Exception as e:
        logger.info(msg=f"Connection failed: {e}")
        if type(e.args) == list:
            if e.args[0][0][0] == 'SSL routines' and e.args[0][0][2] == 'sslv3 alert handshake failure':
                message = Text(
                    f"SSL protocol used: \"{conn.get_protocol_version_name()}\", is not supported by the server!\n"
                    f"Please review below list of supported protocols:\n"
                    f" - \"TLSv1.2\"\n"
                    f" - \"TLSv1.3\"", style="bold red")
        else:
            if ssl:
                message = Panel.fit(Text(f"SSL Certificate could not be validated. Possibly a self-signed certificate or unrecognized CA certificate."), style="bold yellow")
            else:
                message = Panel.fit(Text(f"Connection failed"), style="bold yellow")

        if progress:
            progress.log(message)
            progress.log()
        else:
            print(message)
        return conn, 0, connected

    # Calculate RTT and format to milliseconds
    rtt = (end_time - start_time) * 1000
    IP_connected = connect_to_server_ip(host,port,ssl,client_cert_file,pg,progress)
    if not IP_connected:

        progress.log(Panel.fit(Text(f"Failed to connect over any one of the Resolved IP"),style="bold red"))

        return conn, rtt, IP_connected
    return conn, rtt, connected

#Verifying that able to establish connection with at least 1 ip resolved by hostname
def connect_to_server_ip(host, port, ssl=False, client_cert_file=None, pg=False, progress=None):
    check_ip_connected = False
    host = host.strip('[]')
    ip_addresses = resolve_ip_addreses(host, progress)
    if progress:
        progress.log("Testing all resolved IP addresses for connection...\n\n"
                     "Only one IP address needs to be reachable for the connection to be successful.")

    else:
        print("\nTesting all resolved IP addresses for connection...\n\n"
              "Only one IP address needs to be reachable for the connection to be successful.")
    for ip in ip_addresses :
        # If SSL is enabled, create an SSL socket
        # Create an SSL context
        if ssl:
            context = create_ssl_context(client_cert_file)
            # Create an SSL socket
            if ":" in ip:
                sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            else :
                sock = socket.socket()
            ip_conn = context.wrap_socket(sock, server_hostname=host)
        else:
            ip_conn = socket.socket()
        try:
            ip_conn.settimeout(10)
            ip_conn.connect((ip, port))
            ip_conn.settimeout(None)
            if ssl:
                # Postgres requires protocol negotiation before SSL since everything's on same port
                # https://www.postgresql.org/docs/current/protocol-flow.html#PROTOCOL-FLOW-SSL
                if pg:
                    version_ssl = struct.pack('!I', 1234 << 16 | 5679)
                    length = struct.pack('!I', 8)
                    packet = length + version_ssl
                    sock.sendall(packet)
                    sock.recv(1)
                ip_conn.do_handshake()
            check_ip_connected = True
            if progress:
                progress.log()
                progress.log(Text(f"Ping returned for IP: {ip} on port: {port}",style="bold green"))
                progress.log()
            else:
                print(Text(f"\nPing returned for IP: {ip} on port: {port}", style="bold green"))
                print()

        except Exception as e:
            if progress:
                progress.log()
                progress.log(Text(f"Ping unanswered for IP: {ip} on port: {port}", style="bold yellow"))
                progress.log()
            else:
                print(Text(f"\nPing unanswered for IP: {ip} on port: {port}", style="bold yellow"))
                print()
            continue
        finally:
            ip_conn.close()
    return check_ip_connected

# Function to check if a program exists
def command_available(command):
    try:
        if shutil.which(command):
            return True
        return False
    except Exception as e:
        return False


# Function to check if username is an email
def is_email(logger, usernames):
    """
    Check if the provided usernames are in email format.
    :param logger: Logger object to log messages
    :param usernames: List of usernames to check
    :return: True if any usernames are in email format, False otherwise
    """
    for username in usernames:
        if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", username):
            logger.info(f"Username {username} is in email format")
            return True
    return False

# # Checks whether we are properly logged into a Kubernetes/OCP cluster
# # 'kubectl config current-context' is not sufficient it will show most recent cluster,
# # but we cannot apply yaml which is needed to test storage classes
# # (!!!) DOES NOT WORK WHEN INSIDE OPERATOR POD
# def kubectl_log_in_check(logger):
#     try:
#         # DBACLD-161187: Changed to general 'kubectl version' command to check if kubectl is logged in
#         subprocess.check_output("kubectl version", shell=True, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
#                                 universal_newlines=True, timeout=5)
#         return True
#     except subprocess.TimeoutExpired:
#         return False
#     except subprocess.CalledProcessError as error:
#         logger.info("Kubectl is not logged into any cluster and " \
#                     + f"will cause errors when checking storage classes; {error}")
#         return False


# method to check to if value in property file is valid
def valid_check(prop_key, prop_value, valid_values, _error_list, _logger):
    try:
        # For sets and boolean validity check
        if type(valid_values) is list:
            if prop_value not in valid_values:
                # Just extra formatting to match what is visible in toml file for strings
                if type(prop_value) is str:
                    prop_value = f"\"{prop_value}\""

                error = f"Incorrect/missing parameter set in silent install file -  {prop_key}={prop_value} | Valid values - {valid_values}"
                _error_list.append(error)
                return False

        # For range of integers check
        elif type(valid_values) is tuple:
            if valid_values[0] > prop_value >= valid_values[1]:
                error = f"Incorrect/missing parameter set in silent install file -  {prop_key}={prop_value} | Valid values - {valid_values}"
                _error_list.append(error)
                return False

        # For boolean values check
        elif type(valid_values) is bool:
            if type(prop_value) is not bool:
                valid_values = "[true,false]"
                error = f"Incorrect/missing parameter set in silent install file -  {prop_key}={prop_value} | Valid values - {valid_values}"
                _error_list.append(error)
                return False

        elif type(valid_values) is str:
            if valid_values == "url":
                # Check if the url is valid
                if prop_value is None or not prop_value.endswith(".well-known/openid-configuration"):
                    error = f"URL is empty or invalid in silent install file -  {prop_key}={prop_value} | Valid values - ends with .well-known/openid-configuration"
                    _error_list.append(error)
                    return False

        return True

    except Exception as e:
        _logger.info(
            f"Exception from silent.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")

    # method to return variables in correct type for a given key from config file
    # Currently can only read one table layer deep


def gather_var(key, _logger, _envfile, _error_list, section_header='', valid_values=True):
    try:
        if section_header == '':
            value = _envfile.get(key)
        else:
            value = _envfile[section_header][key]
            section_header = "[" + section_header + "]"
        _logger.info(f"Gathered variable {section_header + key} with value: {value}")
        # Check that the user/property file input is valid
        if valid_check(prop_key=section_header + key, prop_value=value, valid_values=valid_values, _logger=_logger,
                       _error_list=_error_list):
            return value
        return None

    except Exception as e:
        _logger.info(
            f"Exception from utilities.py script in {inspect.currentframe().f_code.co_name} function -  {str(e)}")

def get_oc_version(logger):
    try:
        # Get the oc version
        process = subprocess.run(["oc", "version", "--output=json"],
                                             capture_output=True,
                                             text=True,
                                             timeout=5)

        if process.returncode == 0:
            oc_version = json.loads(process.stdout)["releaseClientVersion"]
            return oc_version

        oc_version = json.loads(process.stderr)["releaseClientVersion"]
        return oc_version

    except subprocess.TimeoutExpired:
        logger.info("Error: Timeout while getting oc version")
        return ""
    except Exception as e:
        logger.info(f"Error: {e}")
        return ""

def get_ibm_pak_version(logger):
    try:
        process = subprocess.run(["oc", "ibm-pak", "--version"],
                                 capture_output=True,
                                 text=True,
                                 timeout=5)

        ibm_pak_version = process.stdout.strip()
        return ibm_pak_version

    except subprocess.TimeoutExpired:
        logger.info("Error: Timeout while getting oc version")
        return ""
    except Exception as e:
        logger.info(f"Error: {e}")
        return ""

def get_mirror_version(logger):
    try:
        # Get the oc version
        process = subprocess.run(["oc", "mirror", "version", "--output=json"],
                                             capture_output=True,
                                             text=True,
                                             timeout=5)

        if process.returncode == 0:
            mirror_version = json.loads(process.stdout)["clientVersion"]["gitVersion"].split("-")[0]
            return mirror_version
        else:
            return ""

    except subprocess.TimeoutExpired:
        logger.info("Error: Timeout while getting oc mirror version")
        return ""
    except Exception as e:
        logger.info(f"Error: {e}")
        return ""

# Function to check if a specific file path is present
def filepath_validate(filepath):
    if not os.path.exists(filepath):
        return False
    else:
        return True


def write_yaml_to_file(content, path):
    if not isinstance(content, dict):
        content = content.to_dict()
    with open(path, 'w') as f:
        yaml.dump(content, f, default_flow_style=False)


def write_log_to_file(content, path):
    with open(path, 'w') as f:
        f.write(content)


def compress_extract_from_pod(command):
    subprocess.run(command, shell=True, check=True)


# Clear console based on system OS
def clear(console):
    if platform.system() == 'Windows':
        os.system('cls')
    else:
        console.clear()


# Assisted by watsonx Code Assistant 
def split_pem(logger, cert_file_path, tmp_folder, output_prefix="cert"):
    """
    Splits a PEM file into multiple PEM files based on the BEGIN and END blocks.

    Args:
    logger (logging.Logger): A logger object for logging messages.
    cert_file_path (str): The path to the PEM file to be split.
    tmp_folder (str): The temporary folder where the split PEM files will be stored.
    output_prefix (str, optional): The prefix for the output PEM file names. Defaults to "cert".

    Returns:
    list: A list of paths to the split PEM files. If an error occurs, an empty list is returned.
    """
    try:
        with open(cert_file_path, 'r') as pem_file:
            pem_content = pem_file.read()

    except FileNotFoundError:
        logger.exception(f"Error: File not found: {cert_file_path}")
        return []

    # Regex to find all PEM blocks
    pem_blocks = re.findall(r"-----BEGIN [^-]+-----\n(?:.|\n)*?-----END [^-]+-----", pem_content)

    if not pem_blocks:
        logger.info("No PEM blocks found in the file.")
        return []

    cert_list = []

    for i, pem_block in enumerate(pem_blocks):
        file_name = f"{output_prefix}_{i + 1}.pem"
        output_path = os.path.join(tmp_folder, file_name)
        try:
            with open(output_path, 'w') as f:
                f.write(pem_block)
            logger.info(f"Certificate {i + 1} written to {output_path}")
            cert_list.append(output_path)
        except Exception as e:
            logger.exception(f"Error writing to {output_path}: {e}")
    return cert_list

# Function to collect and return the SANs from a certificate
def collect_cert_subject_alt_names(logger, cert_path) -> list:
    try:
        logger.info(f"Validating SANs in certificate: {cert_path}")

        with open(cert_path, 'rb') as cert_file:
            cert_data = cert_file.read()
        cert = x509.load_pem_x509_certificate(cert_data, default_backend())
        san_extension = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        san_list = san_extension.value.get_values_for_type(x509.DNSName) + san_extension.value.get_values_for_type(x509.IPAddress)
        san_list = [str(san) for san in san_list]  # Convert IPAddress objects to strings
        logger.info(f"Extracted SANs: {san_list}")
        return san_list
    except Exception as e:
        logger.info(f"Error extracting SANs from certificate {cert_path}: {e}")
        return []

# Function to clean up and combine PEM files
def clean_and_combine_pem_files(logger, cert_folder, tmp_folder, output_prefix):
    """
    Cleans up the PEM files in the specified folder and combines them into a single PEM file.

    Args:
    logger (logging.Logger): A logger object for logging messages.
    cert_folder (str): The folder containing the PEM files to be cleaned and combined.
    output_file (str): The path to the output file where the combined PEM content will be written.

    Returns:
    cert_path: The path to the combined PEM file if successful, otherwise None.
    """
    try:
        # Only collect visible files in the cert folder
        # Hidden files are skipped
        files = collect_visible_files(cert_folder)
        if not files:
            logger.info(f"No visible files found in {cert_folder}.")
            return None

        ssl_cert_list = []

        for i, cert in enumerate(files):
            # Only consider certificate files
            if any(ext in cert for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                cert_path = os.path.join(cert_folder, cert)
                output_prefix_single = f"{output_prefix}_{i + 1}"
                ssl_cert_list.extend(split_pem(logger, cert_path, tmp_folder, output_prefix_single))

        # Recombine all the split PEM files into a single PEM file
        combined_cert_path = os.path.join(tmp_folder, f"{output_prefix}_combined.pem")
        san_list = []
        with open(combined_cert_path, 'w') as combined_file:
            for cert in ssl_cert_list:
                with open(cert, 'r') as pem_file:
                    # collect SAN from the certs
                    san_list.extend(collect_cert_subject_alt_names(logger, cert))
                    combined_file.write(pem_file.read())
                combined_file.write("\n")  # Add a newline between certificates
        logger.info(f"Combined PEM file created at {combined_cert_path}")

        return combined_cert_path, san_list
    except Exception as e:
        logger.exception(f"Error during PEM file cleanup and combination: {e}")
        return None

def ensure_base64(value: str) -> str:
    """
    Ensure a string is Base64 encoded.
    If already valid Base64, return as is.
    Otherwise, encode it.
    """
    try:
        decoded = base64.b64decode(value, validate=True)
        if base64.b64encode(decoded).decode('utf-8') == value:
            return value  # already base64
        else:
            return base64.b64encode(value.encode('utf-8')).decode('utf-8')
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return base64.b64encode(value.encode('utf-8')).decode('utf-8')


def encode_secret_contents(input_dict: dict) -> dict:
    result = {}
    for key, value in input_dict.items():
        if isinstance(value, str):
            value = value.encode('utf-8')
        result[key] = base64.b64encode(value).decode('utf-8')

    return result

def generate_secure_password(length=24) -> str:
    alphabet = (
        "ABCDEFGHJKLMNPQRSTUVWXYZ"  # No I or O
        "abcdefghijkmnopqrstuvwxyz"  # No l
        "23456789"  # No 0 or 1
    )

    alphabet += "!@#$%^&*()-_=+[]{}|;:,.<>?/"

    password = ''.join(secrets.choice(alphabet) for _ in range(length))
    return password
def decode_if_base64(value: str) -> str:
    """
    If value is valid Base64, return its decoded string.
    Otherwise, return the value as-is.
    """
    try:
        decoded_bytes = base64.b64decode(value, validate=True)
        # Check if re-encoding matches to ensure it's truly base64
        if base64.b64encode(decoded_bytes).decode('utf-8') == value:
            return decoded_bytes.decode('utf-8', errors='ignore')
        else:
            return value
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return value








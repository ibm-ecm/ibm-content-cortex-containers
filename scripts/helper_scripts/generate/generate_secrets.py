###############################################################################
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2023. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
###############################################################################


import base64
import os
import shutil
import json
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend

import jinja2

from ..utilities.prerequisites_utilites import collect_visible_files, collect_visible_folders, split_pem, encode_secret_contents


# Class to generate secrets
class GenerateSecrets:
    _TMP_DIR = os.path.join(os.getcwd(), "helper_scripts", "generate", "tmp")

    def __init__(self, namespace, db_properties=None, ldap_properties=None, idp_properties=None, usergroup_properties=None,
                 customcomponent_properties=None, scim_properties=None, deployment_properties=None, logger=None):
        self._logger = logger
        self._namespace = namespace

        self._db_properties = db_properties
        self._ldap_properties = ldap_properties
        self._usergroup_properties = usergroup_properties
        self._idp_properties = idp_properties
        self._customcomponent_properties = customcomponent_properties
        self._scim_properties = scim_properties
        self._deployment_properties = deployment_properties

        # Extract vault configuration from deployment properties
        self._vault_enabled = deployment_properties.get('VAULT_ENABLED', False) if deployment_properties else False
        self._vault_url = deployment_properties.get('VAULT_URL', None) if deployment_properties else None
        self._vault_role = deployment_properties.get('VAULT_ROLE', f"{namespace}-role") if deployment_properties else f"{namespace}-role"
        self._vault_path = deployment_properties.get('VAULT_PATH', 'secret/data') if deployment_properties else 'secret/data'
        self._vault_cert_path = deployment_properties.get('VAULT_CERT_PATH', '') if deployment_properties else ''

        self._ssl_cert_folder = os.path.join(os.getcwd(), "propertyFile", namespace, "ssl-certs")
        self._trusted_certs_folder = os.path.join(self._ssl_cert_folder, "trusted-certs")


        self._generate_folder = os.path.join(os.getcwd(), "generatedFiles", namespace)
        self._generate_secrets_folder = os.path.join(self._generate_folder, "secrets")
        self._generate_ssl_secrets_folder = os.path.join(self._generate_folder, "ssl")
        self._generate_trusted_secrets_folder = os.path.join(self._generate_ssl_secrets_folder, "trusted-certs")
        self._generate_vault_folder = os.path.join(self._generate_folder, "vault")
        self._generate_vault_json_folder = os.path.join(self._generate_vault_folder, "json-data")
        self._generate_vault_spc_folder = os.path.join(self._generate_vault_folder, "secret-provider-classes")
        self._icc_folder = os.path.join(os.getcwd(), "propertyFile",namespace, "icc")

        self._secret_template_folder = os.path.join(os.getcwd(), "helper_scripts", "generate", "templates")


        # Load all jinja templates
        self._template_loader = jinja2.FileSystemLoader(self._secret_template_folder)
        self._template_env = jinja2.Environment(loader=self._template_loader, trim_blocks=True)

        self.__create_tmp_folder()

    def __create_tmp_folder(self):
        try:
            if not os.path.exists(self._TMP_DIR):
                os.makedirs(self._TMP_DIR)
            else:
                self._logger.info(f"The folder {self._TMP_DIR} already exists")
                # Delete and recreate the TMP folder 
                shutil.rmtree(self._TMP_DIR)
                os.makedirs(self._TMP_DIR)
        except Exception as e:
            self._logger.exception(
                f"Exception from validate.py script in function -  {str(e)}")
        return self._TMP_DIR

    # Function to XOR password
    def xor_password(self, data, xorkey=0x5F):
        """XORs a password with a key.The key used here is _"""

        # Convert password to bytes
        password_bytes = data.encode()

        # XOR each byte of the password with the key
        xor_result_bytes = bytes([b ^ xorkey for b in password_bytes])

        # Encode the XORed bytes using base64
        xor_encoded_bytes = base64.b64encode(xor_result_bytes)

        # Convert the encoded bytes to a string and prepend with "{xor}"
        xor_result_string = "{xor}" + xor_encoded_bytes.decode()
        return xor_result_string

    def render_ssl_secret_template(self, values, secret_name):
        """
        Renders an SSL secret template using the provided values and secret name.

        Parameters:
        values (dict): A dictionary containing the variables to be substituted in the template.
        secret_name (str): The name of the secret to be created.

        Returns:
        str: The rendered secret content for the secret.
        """
        template = self._template_env.get_template('secret.j2')

        # Render the template with the provided values
        rendered_secret = template.render(
            values=values,
            secret_name=secret_name)

        return rendered_secret

    def render_secretproviderclass_template(self, secret_name, secret_keys, vault_url, vault_role, vault_path, vault_cert_path="", secret_store_type="secret", owned_by="content-operator"):
        """
        Renders a SecretProviderClass template for HashiCorp Vault integration.
        
        Parameters:
        secret_name (str): The name of the secret
        secret_keys (list): List of keys that should be in the secret
        vault_url (str): The Vault server URL
        vault_role (str): The Vault Kubernetes authentication role name
        vault_path (str): The Vault secret path (e.g., secret/data)
        vault_cert_path (str): Optional path to Vault CA certificate
        secret_store_type (str): Type of secret store - "secret" or "certificate" (default: "secret")
        owned_by (str): Which operator owns this secret - "content-operator" or "ai-services-operator" (default: "content-operator")
        
        Returns:
        str: The rendered SecretProviderClass YAML content
        """
        template = self._template_env.get_template('secretproviderclass.j2')
        
        # Build objects list for Vault
        objects = []
        for key in secret_keys:
            objects.append({
                'objectName': key,
                'secretPath': f"{vault_path}/{secret_name}",
                'secretKey': key
            })
        
        # Render the template with the provided values
        rendered_spc = template.render(
            secret_name=secret_name,
            vault_url=vault_url,
            vault_role=vault_role,
            vault_cert_path=vault_cert_path,
            objects=objects,
            secret_store_type=secret_store_type,
            owned_by=owned_by
        )
        
        return rendered_spc

    def create_vault_secret_json(self, data, secret_name, secret_folder=None):
        """
        Creates a JSON file containing secret data for importing into Vault.
        The data values are NOT base64 encoded - they are plain text for Vault storage.
        Adds a _comment metadata field to document the secret.
        
        Parameters:
        data (dict): Dictionary containing the secret key-value pairs
        secret_name (str): The name of the secret
        secret_folder (str): The folder where the JSON file will be saved (defaults to vault json-data folder)
        
        Returns:
        None
        """
        import json
        
        # Use the dedicated vault JSON folder if no folder specified
        if secret_folder is None:
            secret_folder = self._generate_vault_json_folder
        
        json_filename = secret_name + "-vault-data.json"
        json_filepath = os.path.join(secret_folder, json_filename)
        
        # Create a clean data dictionary with plain text values (not base64 encoded)
        # The data coming in should already be plain text
        clean_data = {}
        for key, value in data.items():
            # Ensure we're storing plain text values
            if isinstance(value, str):
                clean_data[key] = value
            else:
                clean_data[key] = str(value)
        
        # Add _comment metadata field to the beginning of the JSON
        json_with_comment = {
            "_comment": f"Vault secret data for: {secret_name}. Import to path: {self._vault_path}/{secret_name}"
        }
        # Add all secret data after the comment
        json_with_comment.update(clean_data)
        
        # Write JSON file with proper formatting
        with open(json_filepath, 'w') as file:
            json.dump(json_with_comment, file, indent=2)
            self._logger.info(f"Created Vault secret JSON: {json_filename}")

    def render_secret_template(self, values, secret_name):
        """
        Renders a Jinja2 template for a secret with the provided values.

        Parameters:
        values (dict): A dictionary containing the variable values to be substituted in the template.
        secret_name (str): The name of the secret to be used in the template.

        Returns:
        str: The rendered secret string.
        """
        # Get the template from the environment
        template = self._template_env.get_template('secret.j2')

        # Render the template with the provided values
        rendered_secret = template.render(
            values=values,
            secret_name=secret_name
        )

        return rendered_secret

    def create_scim_ssl_secrets(self):
        """
        This function creates SSL secrets for SCIM (System for Cross-domain Identity Management) components.
        It checks if the SSL certificate folder exists, collects visible files, and processes each SCIM component
        to create SSL secrets.

        Returns:
        None
        """
        scim_ssl = {}

        for scim in self._scim_properties['_scim_ids']:
            scim_ssl[scim.lower()] = self._scim_properties[scim]["SCIM_SSL_ENABLED"]
        scim_ssl_enabled = any([value for value in scim_ssl.values()])

        if os.path.exists(self._ssl_cert_folder):
            self._logger.info("Creating SCIM ssl secrets")
            ssl_cert_folder = self._ssl_cert_folder
            ssl_folders = collect_visible_folders(ssl_cert_folder)

            # remove any hidden files that might be picked up and remove the trusted-certs folder
            for folder in ssl_folders:
                if folder.startswith(".") or folder == "trusted-certs":
                    ssl_folders.remove(folder)

            scim_folders = list(filter(lambda x: "scim" in x, ssl_folders))

            for item in scim_folders:
                folderpath = os.path.join(ssl_cert_folder, item)
                ssl_certs = collect_visible_files(folderpath)

                # processing data to generate ldap ssl secrets
                # only create the ldap ssl secret if ldap ssl is enabled
                # create the ldap ssl secret only if the ldap server has ssl enabled
                if scim_ssl_enabled and "scim" in item:
                    if scim_ssl[item]:
                        self.create_ssl_secret(folderpath=folderpath, ssl_certs=ssl_certs, item=item)


    def create_idp_ssl_secrets(self):
        # if SSL is enabled on the Database or the LDAP server then we need to create ssl secrets

        # if any of the ldap servers have ssl enabled then we need to create ssl secrets
        # Check is any of the ldap server has ssl enabled
        for idp in self._idp_properties['_idp_ids']:
            if self._idp_properties[idp]["IDP_SSL_ENABLED"]:

                if os.path.exists(self._ssl_cert_folder):
                    self._logger.info(f"Creating IDP ssl secrets for ID: {idp}")
                    ssl_cert_folder = self._ssl_cert_folder
                    ssl_folders = collect_visible_folders(ssl_cert_folder)

                # remove any hidden files that might be picked up and remove the trusted-certs folder
                for folder in ssl_folders:
                    if folder.startswith(".") or folder == "trusted-certs":
                        ssl_folders.remove(folder)



                folderpath = os.path.join(ssl_cert_folder, idp.lower())
                ssl_certs = collect_visible_files(folderpath)

                # IDP SSL secret is used by both Content and AI Services operators
                self.create_ssl_secret(folderpath=folderpath, ssl_certs=ssl_certs, item=idp.lower(),
                                     owned_by="content-operator,ai-services-operator")


    def create_ldap_ssl_secrets(self):
        # if SSL is enabled on the Database or the LDAP server then we need to create ssl secrets

        # if any of the ldap servers have ssl enabled then we need to create ssl secrets
        # Check is any of the ldap server has ssl enabled
        ldap_ssl = {}

        for ldap in self._ldap_properties['_ldap_ids']:
            ldap_ssl[ldap.lower()] = self._ldap_properties[ldap]["LDAP_SSL_ENABLED"]
        ldap_ssl_enabled = any([value for value in ldap_ssl.values()])

        if os.path.exists(self._ssl_cert_folder):
            self._logger.info("Creating ssl secrets")
            ssl_cert_folder = self._ssl_cert_folder
            ssl_folders = collect_visible_folders(ssl_cert_folder)

            # remove any hidden files that might be picked up and remove the trusted-certs folder
            for folder in ssl_folders:
                if folder.startswith(".") or folder == "trusted-certs":
                    ssl_folders.remove(folder)

            ldap_folders = list(filter(lambda x: "ldap" in x, ssl_folders))

            # iterating through folders gcd, os , ldap2 etc
            for item in ldap_folders:
                folderpath = os.path.join(ssl_cert_folder, item)
                ssl_certs = collect_visible_files(folderpath)

                # processing data to generate ldap ssl secrets
                # only create the ldap ssl secret if ldap ssl is enabled
                # create the ldap ssl secret only if the ldap server has ssl enabled
                if ldap_ssl_enabled and "ldap" in item:
                    if ldap_ssl[item]:
                        self.create_ssl_secret(folderpath=folderpath, ssl_certs=ssl_certs, item=item)

    # function to create ssl secrets
    def create_ssl_db_secrets(self):
        # if SSL is enabled on the Database or the LDAP server then we need to create ssl secrets
        # if any ssl cert folders exists that means ssl was enabled for either ldap or DB

        if os.path.exists(self._ssl_cert_folder):
            self._logger.info("Creating ssl secrets")
            ssl_cert_folder = self._ssl_cert_folder
            ssl_folders = collect_visible_folders(ssl_cert_folder)
            
            self._logger.info(ssl_folders)

            # Exclude non-database folders: ldap, idp, scim, graphql, ai-provider-* (LWE providers), and trusted-certs
            db_folders = list(filter(lambda x: not any(ex in x.lower() for ex in ["ldap", "idp", "scim", "graphql", "ai-provider-", "trusted-certs"]), ssl_folders))

            if "CPE" in self._deployment_properties.keys():
                if not self._deployment_properties["CPE"]:
                    db_folders.remove("gcd")
                    db_folders = list(filter(lambda x: "os" not in x, db_folders))

            if "BAN" in self._deployment_properties.keys():
                if not self._deployment_properties["BAN"]:
                    db_folders = list(filter(lambda x: "icn" not in x, db_folders))

            # processing data to generate db ssl secrets
            for item in db_folders:
                folderpath = os.path.join(ssl_cert_folder, item)
                ssl_certs = collect_visible_files(folderpath)
                data = {}

                # if DB type is postgres we need to go through multiple folders which have multiple certs
                if self._db_properties["DATABASE_TYPE"] == "postgresql":
                    postgres_cert_folders = collect_visible_folders(folderpath)
                    # Use these three variables to decide if certs are present and if all are empty we will use dbpassword to create ssl cert
                    clientkey_present = True
                    clientcert_present = True
                    servercert_present = True

                    # check if we have cert auth or server auth
                    for postgres_folder in postgres_cert_folders:
                        # sometimes there are folders that start with . (hidden folders)
                        if postgres_folder.startswith("."):
                            continue
                        current_postgres_folder = os.path.join(folderpath, postgres_folder)
                        # listing the certs present in the sub folder
                        postgres_cert = collect_visible_files(current_postgres_folder)
                        sub_folder_cert = ""
                        for folder_item in postgres_cert:
                            if any(ext in folder_item for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                                sub_folder_cert = folder_item
                        # checking to see which subfolders are empty or not
                        if "clientkey" in postgres_folder:
                            if not sub_folder_cert:
                                clientkey_present = False
                        if "clientcert" in postgres_folder:
                            if not sub_folder_cert:
                                clientcert_present = False
                        if "serverca" in postgres_folder:
                            if not sub_folder_cert:
                                servercert_present = False

                    # if client_auth is false that means server auth is true
                    client_auth = False
                    if clientkey_present and clientcert_present:
                        client_auth = True
                    # parsing through the 3 postgres ssl sub folders to generate the secret parameters
                    for postgres_folder in postgres_cert_folders:
                        # skipping hidden folders in case its present
                        if postgres_folder.startswith("."):
                            continue
                        current_postgres_folder = os.path.join(folderpath, postgres_folder)
                        # listing the certs present in the sub folder
                        postgres_cert = collect_visible_files(current_postgres_folder)
                        sub_folder_cert = ""
                        # finding only pem or cert files to use
                        for folder_item in postgres_cert:
                            if any(ext in folder_item for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                                sub_folder_cert = folder_item
                        if client_auth:
                            if "clientkey" in postgres_folder:
                                # Read binary data from SSL certificate file
                                if sub_folder_cert:
                                    with open(os.path.join(current_postgres_folder, sub_folder_cert), "rb") as file:
                                        binary_data = file.read()
                                    data['clientkey.pem'] = binary_data

                            if "clientcert" in postgres_folder:
                                # Read binary data from SSL certificate file
                                if sub_folder_cert:
                                    with open(os.path.join(current_postgres_folder, sub_folder_cert), "rb") as file:
                                        binary_data = file.read()
                                    data['clientcert.pem'] = binary_data

                            # for modes other thatn require serverca is a must
                            if self._db_properties["SSL_MODE"].lower() != "require":
                                if "serverca" in postgres_folder:
                                    # Read binary data from SSL certificate file
                                    if sub_folder_cert:
                                        with open(os.path.join(current_postgres_folder, sub_folder_cert),
                                                  "rb") as file:
                                            binary_data = file.read()
                                        data['serverca.pem'] = binary_data

                        else:
                            # server auth is picked so that will be the parameter generated
                            if "serverca" in postgres_folder:
                                # Read binary data from SSL certificate file
                                if sub_folder_cert:
                                    with open(os.path.join(current_postgres_folder, sub_folder_cert),
                                              "rb") as file:
                                        binary_data = file.read()
                                    data['serverca.pem'] = binary_data

                                # dbpass = self._db_properties[item.upper()]["DATABASE_PASSWORD"]
                                # data["stringData"]["DBPassword"] = str(self.xor_password(dbpass))

                            if self._db_properties["SSL_MODE"].lower() != "require":
                                if "clientcert" in postgres_folder:
                                    # Read binary data from SSL certificate file
                                    if sub_folder_cert:
                                        with open(os.path.join(current_postgres_folder, sub_folder_cert),
                                                  "rb") as file:
                                            binary_data = file.read()
                                        data['clientcert.pem'] = binary_data

                                if "clientkey" in postgres_folder:
                                    # Read binary data from SSL certificate file
                                    if sub_folder_cert:
                                        with open(os.path.join(current_postgres_folder, sub_folder_cert),
                                                  "rb") as file:
                                            binary_data = file.read()
                                        data['clientkey.pem'] = binary_data

                    # adding ssl mode as a parameter for the secret
                    ssl_mode = self._db_properties["SSL_MODE"].lower()
                    data["sslmode"] = ssl_mode

                    secret_name = f"ibm-{item}-ssl-secret"
                    
                    # If Vault is enabled, create ONLY SecretProviderClass and JSON
                    if self._vault_enabled:
                        self._logger.info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
                        secret_keys = list(data.keys())
                        self.create_secretproviderclass(
                            secret_name=secret_name,
                            secret_keys=secret_keys,
                            secret_store_type="secret",
                            owned_by="content-operator"
                        )
                        # Create vault JSON with base64-encoded binary data
                        vault_data = {}
                        for key, value in data.items():
                            if isinstance(value, bytes):
                                vault_data[key] = base64.b64encode(value).decode('utf-8')
                            else:
                                vault_data[key] = value
                        self.create_vault_secret_json(vault_data, secret_name)
                    else:
                        # Create standard Kubernetes Secret only when vault is NOT enabled
                        secret_filename = secret_name + ".yaml"
                        sslsecret_filepath = os.path.join(self._generate_ssl_secrets_folder, secret_filename)

                        encoded_secret_data = encode_secret_contents(data)

                        rendered_secret = self.render_secret_template(encoded_secret_data, secret_name)

                        # write the secret data into a yaml
                        with open(sslsecret_filepath, 'w+') as file:
                            file.write(rendered_secret)
                            self._logger.info(f"Created ssl secret: {secret_name}")

                # For all other DB types the ssl secrets are created using the same logic as we did to create ldap ssl secrets
                else:
                    self.create_ssl_secret(folderpath=folderpath, ssl_certs=ssl_certs, item=item)

    def create_ssl_secret(self, folderpath, ssl_certs, item, prefix="cert-", owned_by="content-operator"):
        """
        This function creates an SSL secret from a list of certificate files.
        If Vault is enabled, also creates SecretProviderClass and JSON for Vault import.

        Parameters:
        folderpath (str): The path to the folder containing the SSL certificate files.
        ssl_certs (list): A list of certificate file names (without extension) to be included in the secret.
        item (str): A unique identifier for the secret.
        prefix (str): Prefix for temporary certificate files (default: "cert-")
        owned_by (str): Which operator owns this secret (default: "content-operator")

        Returns:
        None

        The function reads each certificate file in the provided folder, splits multi-file PEM certificates,
        encodes the certificate data in base64, and writes it into a YAML secret file. The secret file is
        named using the format "ibm-<item>-ssl-secret.yaml" and is saved in the directory specified by
        `_generate_ssl_secrets_folder`. The function also logs the creation of the secret.
        """
        data = ""
        for i, cert in enumerate(ssl_certs):
            if any(ext in cert for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                certfolderpath = os.path.join(folderpath, cert)
                # Split the certificate to separate files
                cert_list = split_pem(self._logger, certfolderpath, self._TMP_DIR, f'{prefix}{i}')

                for k, cert in enumerate(cert_list):
                    self._logger.info("Reading the file " + cert)
                    # Read binary data from SSL certificate file
                    with open(cert, "r") as file:
                        cert_data = file.read()
                    # Append the encoded data to the encoded_data variable
                    data = data + cert_data + '\n'

        secret_name = f"ibm-{item}-ssl-secret"
        
        # If Vault is enabled, create ONLY SecretProviderClass and JSON
        if self._vault_enabled:
            self._logger.info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
            
            # Create SecretProviderClass (uses default SPC folder)
            secret_keys = ['tls.crt']
            self.create_secretproviderclass(
                secret_name=secret_name,
                secret_keys=secret_keys,
                secret_store_type="certificate",
                owned_by=owned_by
            )
            
            # Create Vault JSON with plain text certificate (uses default JSON folder)
            vault_data = {
                'tls.crt': data  # Plain text certificate data
            }
            self.create_vault_secret_json(vault_data, secret_name)
        else:
            # Create standard Kubernetes Secret only when vault is NOT enabled
            # Encode the certificate to base64
            encoded_data = base64.b64encode(data.encode()).decode('utf-8')
            secret_filename = secret_name + ".yaml"
            sslsecret_filepath = os.path.join(self._generate_ssl_secrets_folder, secret_filename)

            secret_data = {
                'tls.crt': encoded_data,
            }

            rendered_secret = self.render_ssl_secret_template(secret_data, secret_name)

            # write the secret data into a yaml
            with open(sslsecret_filepath, 'w+') as file:
                file.write(rendered_secret)
                self._logger.info(f"Created ssl secret: {secret_name}")

    def create_secretproviderclass(self, secret_name, secret_keys, secret_folder=None, vault_url=None, vault_role=None, vault_path=None, vault_cert_path="", secret_store_type="secret", owned_by="content-operator"):
        """
        Creates a SecretProviderClass for HashiCorp Vault integration.
        
        Args:
        secret_name (str): The name of the secret (also used as SecretProviderClass name)
        secret_keys (list): List of keys that should be in the secret
        secret_folder (str): The folder where the SecretProviderClass YAML will be saved (defaults to vault SPC folder)
        vault_url (str): The Vault server URL (defaults to instance vault_url)
        vault_role (str): The Vault Kubernetes authentication role name (defaults to instance vault_role)
        vault_path (str): The Vault secret path (defaults to instance vault_path)
        vault_cert_path (str): Optional path to Vault CA certificate (defaults to instance vault_cert_path)
        secret_store_type (str): Type of secret store - "secret" or "certificate" (default: "secret")
        owned_by (str): Which operator owns this secret - "content-operator" or "ai-services-operator" (default: "content-operator")
        
        Returns:
        None
        """
        # Use the dedicated vault SPC folder if no folder specified
        if secret_folder is None:
            secret_folder = self._generate_vault_spc_folder
        
        # Use instance vault configuration if not provided
        if vault_url is None:
            vault_url = self._vault_url
        if vault_role is None:
            vault_role = self._vault_role
        if vault_path is None:
            vault_path = self._vault_path
        if not vault_cert_path:
            vault_cert_path = self._vault_cert_path
        
        spc_filename = secret_name + ".yaml"
        spc_filepath = os.path.join(secret_folder, spc_filename)
        
        rendered_spc = self.render_secretproviderclass_template(
            secret_name=secret_name,
            secret_keys=secret_keys,
            vault_url=vault_url,
            vault_role=vault_role,
            vault_path=vault_path,
            vault_cert_path=vault_cert_path,
            secret_store_type=secret_store_type,
            owned_by=owned_by
        )
        
        # Write the SecretProviderClass data into a yaml
        with open(spc_filepath, 'w+') as file:
            file.write(rendered_spc)
            self._logger.info(f"Created SecretProviderClass: {secret_name}")

    def create_component_secret(self, data, secret_name, secret_folder, vault_enabled=False, vault_url=None, vault_role=None, vault_path=None, vault_cert_path="", secret_store_type="secret", owned_by="content-operator"):
        """
        Creates a Kubernetes secret or SecretProviderClass from a given dictionary of data and a secret name.

        Args:
        data (dict): A dictionary containing the data to be included in the secret.
        secret_name (str): The name to be given to the created secret.
        secret_folder (str): The folder where the secret YAML will be saved.
        vault_enabled (bool): Whether to create SecretProviderClass for Vault instead of K8s Secret.
        vault_url (str): The Vault server URL (required if vault_enabled is True).
        vault_role (str): The Vault Kubernetes authentication role name (required if vault_enabled is True).
        vault_path (str): The Vault secret path (required if vault_enabled is True).
        vault_cert_path (str): Optional path to Vault CA certificate.
        secret_store_type (str): Type of secret store - "secret" or "certificate" (default: "secret")
        owned_by (str): Which operator owns this secret - "content-operator" or "ai-services-operator" (default: "content-operator")

        Returns:
        None

        The function generates a filename for the secret by appending ".yaml" to the secret name.
        It then constructs the full file path by joining the generated filename with the secrets folder path.

        If vault_enabled is True, it creates a SecretProviderClass for Vault integration.
        Otherwise, it creates a standard Kubernetes Secret.

        Finally, it writes the rendered secret data into a YAML file at the specified file path.
        A logging message is also printed to indicate the creation of the component secret.
        """
        if vault_enabled and vault_url and vault_role and vault_path:
            # Create SecretProviderClass for Vault (uses default SPC folder)
            secret_keys = list(data.keys())
            self.create_secretproviderclass(
                secret_name=secret_name,
                secret_keys=secret_keys,
                vault_url=vault_url,
                vault_role=vault_role,
                vault_path=vault_path,
                vault_cert_path=vault_cert_path,
                secret_store_type=secret_store_type,
                owned_by=owned_by
            )
            # Also create JSON file with secret data for Vault import (uses default JSON folder)
            self.create_vault_secret_json(
                data=data,
                secret_name=secret_name
            )
        else:
            # Create standard Kubernetes Secret
            secret_filename = secret_name + ".yaml"
            secret_filepath = os.path.join(secret_folder, secret_filename)

            # This function makes sure all values are encoded in base64 so that we can create templates with data and not string data
            encoded_secret_data = encode_secret_contents(data)

            rendered_secret = self.render_secret_template(encoded_secret_data, secret_name)

            # write the secret data into a yaml
            with open(secret_filepath, 'w+') as file:
                file.write(rendered_secret)
                self._logger.info(f"Created component secret: {secret_name}")

    # function to create ban secret
    def create_ban_secret(self):
        self._logger.info("Creating BAN secret")

        secret_name = "ibm-ban-secret"

        # Only XOR encode passwords when vault is NOT enabled
        db_password = self._db_properties['ICN']['DATABASE_PASSWORD']
        if not self._vault_enabled:
            db_password = self.xor_password(db_password)

        data = {
            "navigatorDBUsername": self._db_properties['ICN']['DATABASE_USERNAME'],
            "navigatorDBPassword": db_password,
            "ltpaPassword": self._usergroup_properties['LTPA_PASSWORD'],
            "keystorePassword": self._usergroup_properties['KEYSTORE_PASSWORD'],
            "appLoginUsername": self._usergroup_properties['ICN_LOGIN_USER'],
            "appLoginPassword": self._usergroup_properties['ICN_LOGIN_PASSWORD']
        }

        # check if java sendmail details are present
        if self._customcomponent_properties:
            if "SENDMAIL" in self._customcomponent_properties.keys():
                self._logger.info("Adding JMAIL parameters")
                jmail_password = self._customcomponent_properties["SENDMAIL"]["JAVAMAIL_PASSWORD"]
                if not self._vault_enabled:
                    jmail_password = self.xor_password(jmail_password)
                data["jMailUsername"] = self._customcomponent_properties["SENDMAIL"]["JAVAMAIL_USERNAME"]
                data["jMailPassword"] = jmail_password

        self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                     vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                     vault_role=self._vault_role, vault_path=self._vault_path,
                                     vault_cert_path=self._vault_cert_path,
                                     secret_store_type="secret", owned_by="content-operator")

    # Function to generate ldap_secret
    def create_ldap_secret(self):
        self._logger.info("Creating LDAP secret")

        secret_name = "ldap-bind-secret"

        data = {}

        for ldap in self._ldap_properties['_ldap_ids']:
            ldap_password = self._ldap_properties[ldap]["LDAP_BIND_DN_PASSWORD"]
            # Only XOR encode passwords when vault is NOT enabled
            if not self._vault_enabled:
                ldap_password = self.xor_password(ldap_password)
            
            if ldap.lower() == "ldap":
                data['ldapUsername'] = self._ldap_properties[ldap]["LDAP_BIND_DN"]
                data['ldapPassword'] = ldap_password
            else:
                data['ldap' + self._ldap_properties[ldap]["LDAP_ID"] + 'Username'] = self._ldap_properties[ldap][
                    "LDAP_BIND_DN"]
                data['ldap' + self._ldap_properties[ldap]["LDAP_ID"] + 'Password'] = ldap_password

        self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                     vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                     vault_role=self._vault_role, vault_path=self._vault_path,
                                     vault_cert_path=self._vault_cert_path,
                                     secret_store_type="secret", owned_by="content-operator")

    # Function to generate scim_secret
    def create_scim_secret(self):
        for scim in self._scim_properties['_scim_ids']:
            self._logger.info(f"Creating SCIM secret for {scim}")
            secret_name = f"ibm-{scim.lower()}-secret"

            # Only XOR encode passwords when vault is NOT enabled
            scim_password = self._scim_properties[scim]["SCIM_CLIENT_SECRET"]
            if not self._vault_enabled:
                scim_password = self.xor_password(scim_password)

            data = {
                'scimPassword': scim_password,
                'scimUsername': self._scim_properties[scim]["SCIM_CLIENT_ID"]
            }

            self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                         vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                         vault_role=self._vault_role, vault_path=self._vault_path,
                                         vault_cert_path=self._vault_cert_path,
                                         secret_store_type="secret", owned_by="content-operator")

    def create_idp_secret(self):

        for idp in self._idp_properties['_idp_ids']:
            self._logger.info(f"Creating IDP secret for {idp}")
            secret_name = f"ibm-{idp.lower()}-oidc-secret"

            # Only XOR encode passwords when vault is NOT enabled
            client_secret = self._idp_properties[idp]["CLIENT_SECRET"]
            if not self._vault_enabled:
                client_secret = self.xor_password(client_secret)

            data = {
                'client_id': self._idp_properties[idp]["CLIENT_ID"],
                'client_secret': client_secret
            }

            self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                         vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                         vault_role=self._vault_role, vault_path=self._vault_path,
                                         vault_cert_path=self._vault_cert_path,
                                         secret_store_type="secret", owned_by="content-operator")

    # Function to generate fncm_secret
    def create_fncm_secret(self):
        self._logger.info("Creating FNCM secret")

        secret_name = 'ibm-fncm-secret'

        # Only XOR encode passwords when vault is NOT enabled
        gcd_password = self._db_properties["GCD"]["DATABASE_PASSWORD"]
        if not self._vault_enabled:
            gcd_password = self.xor_password(gcd_password)

        data = {
            "ltpaPassword": self._usergroup_properties['LTPA_PASSWORD'],
            "keystorePassword": self._usergroup_properties['KEYSTORE_PASSWORD'],
            "appLoginUsername": self._usergroup_properties['FNCM_LOGIN_USER'],
            "appLoginPassword": self._usergroup_properties['FNCM_LOGIN_PASSWORD'],
            "gcdDBUsername": self._db_properties["GCD"]["DATABASE_USERNAME"],
            "gcdDBPassword": gcd_password
        }

        for os_id in self._db_properties["_os_ids"]:
            os_label = self._db_properties[os_id]["OS_LABEL"]
            os_password = self._db_properties[os_id]["DATABASE_PASSWORD"]
            if not self._vault_enabled:
                os_password = self.xor_password(os_password)
            data[f"{os_label}DBUsername"] = self._db_properties[os_id]["DATABASE_USERNAME"]
            data[f"{os_label}DBPassword"] = os_password

        self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                     vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                     vault_role=self._vault_role, vault_path=self._vault_path,
                                     vault_cert_path=self._vault_cert_path,
                                     secret_store_type="secret", owned_by="content-operator")

    # Function to generate ier secret
    def create_ier_secret(self):
        self._logger.info("Creating IER secret")

        secret_name = 'ibm-ier-secret'

        data = {
            "keystorePassword": self._usergroup_properties['KEYSTORE_PASSWORD']
        }

        self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                     vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                     vault_role=self._vault_role, vault_path=self._vault_path,
                                     vault_cert_path=self._vault_cert_path,
                                     secret_store_type="secret", owned_by="content-operator")

    # Function to generate iccsap secret
    def create_iccsap_secret(self):
        self._logger.info("Creating ICCSAP secret")

        secret_name = 'ibm-iccsap-secret'

        data = {
            "keystorePassword": self._usergroup_properties['KEYSTORE_PASSWORD']
        }

        self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                     vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                     vault_role=self._vault_role, vault_path=self._vault_path,
                                     vault_cert_path=self._vault_cert_path,
                                     secret_store_type="secret", owned_by="content-operator")

    # Function to generate icc related secrets
    def create_icc_secrets(self):
        # function creates the icc-masterkey-txt and ibm-icc-secret
        try:
            self._logger.info("Creating ICC secrets")

            secret_name = 'ibm-icc-secret'

            # Only XOR encode passwords when vault is NOT enabled
            archive_password = self._customcomponent_properties["ICC"]["ARCHIVE_PASSWORD"]
            if not self._vault_enabled:
                archive_password = self.xor_password(archive_password)

            data = {
                'archiveUserId': self._customcomponent_properties["ICC"]["ARCHIVE_USER_ID"],
                'archivePassword': archive_password,

            }

            self.create_component_secret(data, secret_name, self._generate_secrets_folder,
                                        vault_enabled=self._vault_enabled, vault_url=self._vault_url,
                                        vault_role=self._vault_role, vault_path=self._vault_path,
                                        vault_cert_path=self._vault_cert_path)

            # creating the masterkey secret
            secret_name = 'icc-masterkey-txt'
            file_list = collect_visible_files(self._icc_folder)
            binary_data = None
            for file in file_list:
                if file.endswith('.txt'):
                    masterkeypath = os.path.join(self._icc_folder, file)
                    # Read binary data from masterkey file
                    with open(masterkeypath, "rb") as file:
                        binary_data = file.read()
                    break

            if binary_data:
                if self._vault_enabled:
                    # For vault, create SecretProviderClass and JSON with base64-encoded data
                    self._logger.info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
                    secret_keys = ['MasterKey.txt']
                    self.create_secretproviderclass(
                        secret_name=secret_name,
                        secret_keys=secret_keys,
                        secret_store_type="secret",
                        owned_by="content-operator"
                    )
                    # Store as base64 in vault JSON (binary data needs to be base64 encoded)
                    encoded_data = base64.b64encode(binary_data).decode('utf-8')
                    vault_data = {
                        'MasterKey.txt': encoded_data
                    }
                    self.create_vault_secret_json(vault_data, secret_name)
                else:
                    # For K8s, create regular secret with base64 encoding
                    encoded_data = base64.b64encode(binary_data).decode('utf-8')
                    data = {
                        'MasterKey.txt': encoded_data,
                    }
                    rendered_secret = self.render_ssl_secret_template(data, secret_name)
                    file_name = f"{secret_name}.yaml"
                    iccmasterkey_filepath = os.path.join(self._generate_secrets_folder, file_name)
                    with open(iccmasterkey_filepath, 'w+') as file:
                        file.write(rendered_secret)
                        self._logger.info(f"Created ICC masterkey secret: {secret_name}")

        except Exception as e:
            self._logger.exception(
                f"Error found in create_icc_secrets function in generate_secrets script --- {str(e)}")

    def create_trusted_secrets(self):
        """
        This function creates Kubernetes secrets for trusted SSL certificates.

        It searches for SSL certificate files in the specified trusted certificates folder.
        It then splits the certificate files into separate files if necessary, reads their binary data,
        encodes the data in base64, and creates a Kubernetes secret for each certificate.

        Parameters:
        self (object): An instance of the class containing the method. It should have the following attributes:
            - _trusted_certs_folder (str): The path to the folder containing trusted SSL certificates.
            - _TMP_DIR (str): The path to a temporary directory.
            - _generate_trusted_secrets_folder (str): The path to the folder where the secrets will be generated.
            - _logger (logging.Logger): A logger object for logging messages.

        Returns:
        None
        """
        try:
            if not os.path.exists(self._trusted_certs_folder):
                return

            trusted_certs = collect_visible_files(self._trusted_certs_folder)

            for i, cert in enumerate(trusted_certs):
                if any(ext in cert for ext in [".crt", ".cer", ".pem", ".cert", ".key", ".arm"]):
                    certfolderpath = os.path.join(self._trusted_certs_folder, cert)
                    # Split the certificate to separate files
                    cert_list = split_pem(self._logger, certfolderpath, self._TMP_DIR, f'trusted-{i}')
                    data = ""
                    for k, split_cert in enumerate(cert_list):
                        self._logger.info("Reading the file " + split_cert)
                        # Read binary data from SSL certificate file
                        with open(split_cert, "r") as file:
                            cert_data = file.read()
                        # Append the encoded data to the encoded_data variable
                        data = data + cert_data + '\n'

                # Encode the certificate to base64 
                encoded_data = base64.b64encode(data.encode()).decode('utf-8')
                secret_name = f"trusted-cert-{i + 1}-secret"
                secret_filename = f"{secret_name}.yaml"
                sslsecret_filepath = os.path.join(self._generate_trusted_secrets_folder, secret_filename)

                data = {
                    'tls.crt': encoded_data,
                }

                rendered_secret = self.render_ssl_secret_template(data, secret_name)

                # write the secret data into a yaml
                with open(sslsecret_filepath, 'w+') as file:
                    file.write(rendered_secret)
                    self._logger.info(f"Created trusted secret: {secret_name}")
        except Exception as e:
            self._logger.exception(
                f"Error found in create_trusted_secrets function in generate_secrets script --- {str(e)}")

    def _fetch_jwks_public_key(self, jwks_endpoint):
        """
        Fetch the public key from the JWKS endpoint.
        
        Parameters:
        jwks_endpoint (str): The JWKS endpoint URL
        
        Returns:
        dict: The first key from the JWKS response, or None if failed
        """
        try:
            self._logger.info(f"Fetching public key from JWKS endpoint: {jwks_endpoint}")
            
            # Disable SSL verification warnings for self-signed certificates
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            
            response = requests.get(jwks_endpoint, verify=False, timeout=10)
            response.raise_for_status()
            
            jwks_data = response.json()
            
            if 'keys' not in jwks_data or len(jwks_data['keys']) == 0:
                self._logger.error("No keys found in JWKS response")
                return None
            
            # Find the key with "use": "sig" (signature verification)
            for key in jwks_data['keys']:
                if key.get('use') == 'sig':
                    self._logger.info(f"Found signing key with kid: {key.get('kid', 'N/A')}")
                    return key
            
            # Fallback: if no key has "use": "sig", return the first key
            self._logger.warning("No key with 'use': 'sig' found, using first key as fallback")
            return jwks_data['keys'][0]
            
        except requests.exceptions.RequestException as e:
            self._logger.warning(
                f"Unable to reach JWKS endpoint for IDP public key retrieval: {jwks_endpoint}. "
                f"Reason: {str(e)}"
            )
            return None
        except Exception as e:
            self._logger.warning(
                f"Unable to process JWKS response from {jwks_endpoint}. "
                f"Reason: {str(e)}"
            )
            return None

    def _jwks_to_pem(self, jwk):
        """
        Convert a JWK (JSON Web Key) to PEM format.
        
        Parameters:
        jwk (dict): The JWK dictionary containing the public key components
        
        Returns:
        str: The public key in PEM format, or None if conversion failed
        """
        try:
            from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
            
            # Extract the modulus (n) and exponent (e) from the JWK
            n = int.from_bytes(
                base64.urlsafe_b64decode(jwk['n'] + '=='),
                byteorder='big'
            )
            e = int.from_bytes(
                base64.urlsafe_b64decode(jwk['e'] + '=='),
                byteorder='big'
            )
            
            # Create RSA public key
            public_numbers = RSAPublicNumbers(e, n)
            public_key = public_numbers.public_key(default_backend())
            
            # Convert to PEM format
            pem = public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo
            )
            
            return pem.decode('utf-8')
            
        except Exception as e:
            self._logger.exception(f"Error converting JWK to PEM: {str(e)}")
            return None

    def create_idp_public_key_secret(self):
        """
        Create a Kubernetes secret containing the IDP public key in PEM format.
        The public key is fetched from the JWKS endpoint specified in the IDP properties.
        
        Returns:
        bool: True if secret was created successfully, False otherwise
        """
        try:
            if not self._idp_properties:
                self._logger.warning("No IDP properties found, skipping public key secret creation")
                return False
            
            # Iterate through all IDP configurations
            for idp in self._idp_properties.get('_idp_ids', []):
                idp_config = self._idp_properties.get(idp, {})
                jwks_endpoint = idp_config.get('JWKS_ENDPOINT')
                
                if not jwks_endpoint:
                    self._logger.warning(f"No JWKS_ENDPOINT found for IDP {idp}, skipping public key secret")
                    continue
                
                self._logger.info(f"Creating IDP public key secret for {idp}")
                
                # Fetch the public key from JWKS endpoint
                jwk = self._fetch_jwks_public_key(jwks_endpoint)
                if not jwk:
                    self._logger.warning(
                        f"Skipping IDP public key secret for {idp}: unable to retrieve a signing key "
                        f"from the configured JWKS endpoint"
                    )
                    continue
                
                # Convert JWK to PEM format
                pem_key = self._jwks_to_pem(jwk)
                if not pem_key:
                    self._logger.error(f"Failed to convert JWK to PEM for IDP {idp}")
                    continue
                
                # Create the secret
                secret_name = f"ibm-{idp.lower()}-public-key-secret"
                
                # If Vault is enabled, create ONLY SecretProviderClass and JSON
                if self._vault_enabled:
                    self._logger.info(f"Vault enabled - generating SecretProviderClass for {secret_name}")
                    secret_keys = ['public.pem']
                    # IDP public key secret is only used by AI Services operator
                    self.create_secretproviderclass(
                        secret_name=secret_name,
                        secret_keys=secret_keys,
                        secret_store_type="certificate",
                        owned_by="ai-services-operator"
                    )
                    vault_data = {
                        'public.pem': pem_key  # Plain text PEM
                    }
                    self.create_vault_secret_json(vault_data, secret_name)
                else:
                    # Create standard Kubernetes Secret only when vault is NOT enabled
                    # Encode the PEM key in base64 for the secret
                    encoded_pem = base64.b64encode(pem_key.encode()).decode('utf-8')
                    
                    secret_filename = f"{secret_name}.yaml"
                    secret_filepath = os.path.join(self._generate_ssl_secrets_folder, secret_filename)
                    
                    data = {
                        'public.pem': encoded_pem
                    }
                    
                    rendered_secret = self.render_ssl_secret_template(data, secret_name)
                    
                    # Write the secret to file
                    with open(secret_filepath, 'w+') as file:
                        file.write(rendered_secret)
                        self._logger.info(f"Created IDP public key secret: {secret_name}")
                
                return True
            
            return False
            
        except Exception as e:
            self._logger.exception(f"Error creating IDP public key secret: {str(e)}")
            return False

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

import copy
import os

import xmltodict
from tomlkit import comment
from tomlkit import document
from tomlkit import nl
from tomlkit import string
from tomlkit import table
from tomlkit.toml_file import TOMLFile

from ..utilities.prerequisites_utilites import read_json


# Create a class Property that accepts a dictionary of key value pairs
# - Create a java property file
# - Accept a current directory path
# - Create a set of containing folder
# - Backup existing property file if they exist

class Property:

    def __init__(self, gather_obj, path, logger, console):
        self._logger = logger
        self._console = console
        self._gather = gather_obj
        self._namespace = gather_obj.namespace
        self._working_directory = path
        self._property_folder = os.path.join(self._working_directory, 'propertyFile', self._namespace)
        self._ssl_directory_folder = os.path.join(self._property_folder, 'ssl-certs')
        self._icc_directory_folder = os.path.join(self._property_folder, 'icc')
        self._trusted_certs_directory_folder = os.path.join(self._property_folder, 'ssl-certs', 'trusted-certs')

        # Create a dictionary of properties
        self._json_directory = os.path.dirname(__file__)
        self._db_properties = read_json(self._json_directory, "db_property.json")
        self._ldap_properties = read_json(self._json_directory, "ldap_property.json")
        self._idp_properties = read_json(self._json_directory, "idp_property.json")
        self._common_credentials = read_json(self._json_directory, "common_credentials.json")
        self._p8_credentials = read_json(self._json_directory, "p8_credentials.json")
        self._icn_credentials = read_json(self._json_directory, "icn_credentials.json")
        self._ingress_properties = read_json(self._json_directory, "ingress_property.json")
        self._init_properties = read_json(self._json_directory, "init_properties.json")
        self._os_init_properties = read_json(self._json_directory, "os_init.json")
        self._verify_properties = read_json(self._json_directory, "verify_property.json")
        self._deployment_properties = read_json(self._json_directory, "deployment_property.json")
        self._storage_properties = read_json(self._json_directory, "storage_property.json")
        
        # Pre-fill storage class from migrated FNCMCluster settings if available
        if hasattr(gather_obj, '_fncm_migration_settings') and gather_obj._fncm_migration_settings:
            migrated_storage_class = gather_obj._fncm_migration_settings.get('storage_class', '')
            if migrated_storage_class and migrated_storage_class != 'Unknown':
                # For AI Services, we only need SLOW_FILE_STORAGE_CLASSNAME
                self._storage_properties["SLOW_FILE_STORAGE_CLASSNAME"]['value'] = migrated_storage_class
                logger.info(f"Pre-filled storage class from Content deployment: {migrated_storage_class}")
        
        self._egress_properties = read_json(self._json_directory, "egress_property.json")
        self._component_properties = read_json(self._json_directory, "component_property.json")
        self._sendmail_custom_properties = read_json(self._json_directory, "sendmail_customproperty.json")
        self._icc_custom_properties = read_json(self._json_directory, "icc_customproperty.json")
        self._tm_custom_properties = read_json(self._json_directory, "tm_customproperty.json")
        self._scim_properties = read_json(self._json_directory, "scim_property.json")
        self._aiservices_properties = read_json(self._json_directory, "aiservices_property.json")
        self._aiservices_integration_properties = read_json(self._json_directory, "aiservices_integration_property.json")

    def move_ldap(self, path, move_dict, ldap_properties_list):
        if move_dict["LDAP"]:
            for i in range(self._gather.ldap_number):
                if i == 0:
                    key = "LDAP"
                else:
                    key = "LDAP{}".format(i + 1)
                self.__parse_ldap_xml(os.path.join(path, move_dict["LDAP"][i]), ldap_properties_list[i])

        return ldap_properties_list

    def __parse_ldap_xml(self, filename, ldap_properties):
        ldap_data = self.__parse_xml(filename)

        for prop in ldap_data['configuration']['property']:
            if prop['@name'] == "LDAPServerHost":
                ldap_properties["LDAP_SERVER"]['value'] = prop['value']

            if prop['@name'] == "LDAPServerPort":
                ldap_properties["LDAP_PORT"]['value'] = prop['value']

            if prop['@name'] == "LDAPBindDN":
                ldap_properties["LDAP_BIND_DN"]['value'] = prop['value']

            if prop['@name'] == "LDAPBaseDN":
                ldap_properties["LDAP_BASE_DN"]['value'] = prop['value']
                ldap_properties["LDAP_GROUP_BASE_DN"]['value'] = prop['value']

            if prop['@name'] == "LDAPUserFilter":
                ldap_properties["LC_USER_FILTER"]['value'] = prop['value']

            if prop['@name'] == "LDAPGroupFilter":
                ldap_properties["LC_GROUP_FILTER"]['value'] = prop['value']

            if prop['@name'] == "LDAPUserIDMap":
                mapping = prop['value']

                if ":" in mapping:
                    ldap_properties["LDAP_USER_NAME_ATTRIBUTE"]['value'] = mapping
                    ldap_properties["LDAP_USER_DISPLAY_NAME_ATTR"]['value'] = mapping.split(":")[1]
                else:
                    ldap_properties["LDAP_USER_NAME_ATTRIBUTE"]['value'] = f"*:{mapping}"
                    ldap_properties["LDAP_USER_DISPLAY_NAME_ATTR"]['value'] = mapping


            if prop['@name'] == "LDAPGroupIDMap":
                ldap_properties["LDAP_GROUP_NAME_ATTRIBUTE"]['value'] = prop['value']
                ldap_properties["LDAP_GROUP_DISPLAY_NAME_ATTR"]['value'] = prop['value'].split(":")[1]

        return ldap_properties

    def move_database(self, path, move_dict, db_properties):
        if move_dict["GCD"]:
            self.__parse_database_xml(os.path.join(path, move_dict["GCD"][0]), "GCD", db_properties)
        if move_dict["OS"]:
            for i in range(self._gather.os_number):
                if i == 0:
                    key = "OS"
                else:
                    key = "OS{}".format(i + 1)
                self.__parse_database_xml(os.path.join(path, move_dict["OS"][i]), key, db_properties)
        if move_dict["ICN"]:
            self.__parse_database_xml(os.path.join(path, move_dict["ICN"][0]), "ICN", db_properties)

        return db_properties

    def __parse_database_xml(self, filename, key, db_properties):
        db_data = self.__parse_xml(filename)

        for prop in db_data['configuration']['property']:
            if prop['@name'] == "DatabaseServerName":
                db_properties[key]["DATABASE_SERVERNAME"]['value'] = prop['value']

            if prop['@name'] == "DatabasePortNumber":
                db_properties[key]["DATABASE_PORT"]['value'] = prop['value']

            if prop['@name'] == "DatabaseName":
                db_properties[key]["DATABASE_NAME"]['value'] = prop['value']

            if prop['@name'] == "DatabaseUsername":
                db_properties[key]["DATABASE_USERNAME"]['value'] = prop['value']

            if prop['@name'] == "JDBCDataSourceName":
                db_properties[key]["DATASOURCE_NAME"]['value'] = prop['value']

            if prop['@name'] == "JDBCDataSourceXAName":
                db_properties[key]["DATASOURCE_NAME_XA"]['value'] = prop['value']

            if prop['@name'] == "TableSpaceName":
                db_properties[key]["TABLESPACE_NAME"]['value'] = prop['value']

            if prop['@name'] == "DatabaseSchema":
                db_properties[key]["SCHEMA_NAME"]['value'] = prop['value']

        if 'ORACLE_JDBC_URL' in db_properties[key]: 
            host_name = db_properties[key]['DATABASE_SERVERNAME']['value']
            db_name = db_properties[key]['DATABASE_NAME']['value'],
            port = db_properties[key]['DATABASE_PORT']['value']
            jdbc_url = self.__create_oracle_jdbc_url(host_name, db_name, port)
            db_properties[key]["ORACLE_JDBC_URL"]['value'] = jdbc_url

        return db_properties

    # Create a method to parse a xml file and return a dictionary
    @staticmethod
    def __parse_xml(filename):
        with open(filename, 'r') as file:
            return xmltodict.parse(file.read())

    # Create a property that gets the property folder
    @property
    def property_folder(self):
        return self._property_folder

    def create_property_structure(self):
        self.__create_property_folder()
        self.__create_ssl_folder()
        self.__create_trusted_certs_folder()
        if self._gather.icc_support:
            self.__create_icc_folder()

    # Create a method that makes a list of directories in the directory path
    def __create_property_folder(self):
        # Create a directory if it does not exist
        if not os.path.exists(self._property_folder):
            os.makedirs(self._property_folder)

    # Create a method that makes a directory path for icc support
    def __create_icc_folder(self):
        # Create a directory if it does not exist
        if not os.path.exists(self._icc_directory_folder):
            os.makedirs(self._icc_directory_folder)

    # Create a method that makes a directory path for icc support
    def __create_trusted_certs_folder(self):
        # Create a directory if it does not exist
        if not os.path.exists(self._trusted_certs_directory_folder):
            os.makedirs(self._trusted_certs_directory_folder)

    # Create a method that creates ssl folders
    def __create_ssl_folder(self):
        # Create a directory if it does not exist
        if not os.path.exists(self._ssl_directory_folder):
            os.makedirs(self._ssl_directory_folder)
        if len(self._gather.ssl_directory_list) > 0:
            for directory in self._gather.ssl_directory_list:
                # Skip graphql folder if both Content and AI Services are deployed (they share the endpoint)
                if directory == "graphql" and self._gather.has_content_operator() and self._gather.has_ai_services_operator():
                    continue
                    
                # Create a directory if it does not exist
                if not os.path.exists(os.path.join(self._ssl_directory_folder, directory)):
                    os.makedirs(os.path.join(self._ssl_directory_folder, directory))
                # Exclude non-database folders: ldap, idp, scim, graphql, and ai-provider-* (LWE providers)
                excluded_folders = ("ldap", "idp", "scim", "graphql", "ai-provider-")
                if not any(name in directory for name in excluded_folders):
                    if self._gather.db_type == "postgresql":
                        serverca_path = os.path.join(self._ssl_directory_folder, directory, 'serverca')
                        clientcert_path = os.path.join(self._ssl_directory_folder, directory, 'clientcert')
                        clientkey_path = os.path.join(self._ssl_directory_folder, directory, 'clientkey')
                        
                        if not os.path.exists(serverca_path):
                            os.makedirs(serverca_path)
                        if not os.path.exists(clientcert_path):
                            os.makedirs(clientcert_path)
                        if not os.path.exists(clientkey_path):
                            os.makedirs(clientkey_path)

    def __populate_deployment_dict(self):
        try:
            # Create a copy of the user group dictionary
            deployment_dict = copy.deepcopy(self._deployment_properties)
            deployment_dict['CCX_Version']['value'] = self._gather.ccx_version
            deployment_dict['LICENSE']['value'] = self._gather.license_model
            deployment_dict['PLATFORM']['value'] = self._gather.platform
            deployment_dict['FIPS_SUPPORT']['value'] = self._gather.fips_support
            deployment_dict['GENERATE_NETWORK_POLICIES']['value'] = self._gather.np_support
            deployment_dict['VAULT_ENABLED']['value'] = self._gather.vault_enabled
            if self._gather.vault_enabled and self._gather.vault_url:
                deployment_dict['VAULT_URL']['value'] = self._gather.vault_url
            return deployment_dict

        except Exception as e:
            self._logger.exception(
                "Exception from property script in __populate_deployment_dict function -  {}".format(str(e)))

    def __populate_egress_dict(self):
        try:
            # Create a copy of the deployment property file properties
            egress_dict = copy.deepcopy(self._egress_properties)

            egress_dict.pop("RESTRICTED_INTERNET_ACCESS")

            # If OCP then remove the options to customize and defaults are loaded in the operator
            # If both np_support and egress_support are false then remove the k8 api and dns options

            if self._gather.platform in ["OCP"] or not (self._gather.np_support or self._gather.egress_support):
                egress_dict.pop('K8_API_NAMESPACE')
                egress_dict.pop('K8_API_PORT')
                egress_dict.pop('K8_DNS_NAMESPACE')
                egress_dict.pop('K8_DNS_PORT')

            return egress_dict

        except Exception as e:
            self._logger.exception(
                "Exception from property script in __populate_egress_dict function -  {}".format(str(e)))

    def __populate_scim_dict(self):
        try:
            # Create a copy of the user group dictionary
            scim_dict = copy.deepcopy(self._scim_properties)
            scim_dict['SCIM_ENABLE']['value'] = self._gather.scim_support

            return scim_dict

        except Exception as e:
            self._logger.exception(
                "Exception from property script in __populate_scim_dict function -  {}".format(str(e)))

    def __populate_component_dict(self):
        try:
            # Create a copy of the user group dictionary
            component_dict = copy.deepcopy(self._component_properties)

            if len(self._gather.optional_components) > 0:
                ecm_components = ["cpe", "graphql", "ban", "css", "cmis", "tm", "es", "ier", "iccsap", "ccxmo"]
                for component in ecm_components:
                    if component in self._gather.optional_components:
                        component_dict[component.upper()]['value'] = True

            return component_dict

        except Exception as e:
            self._logger.exception(
                "Exception from property script in __populate_component_dict function -  {}".format(str(e)))

    def create_deployment_propertyfile(self):
        # Create a file
        deployment_doc = document()
        deployment_doc.add(comment("####################################################"))
        deployment_doc.add(comment("##          License, Platform and Version        ##"))
        deployment_doc.add(comment("####################################################"))

        deployment_properties = self.__populate_deployment_dict()

        # Write non-vault properties first
        vault_properties = {}
        for key, value in deployment_properties.items():
            if key.startswith('VAULT_'):
                vault_properties[key] = value
            else:
                self.__write_property(doc=deployment_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])
        
        # Write vault properties with header if any exist
        if vault_properties:
            deployment_doc.add(nl())
            deployment_doc.add(comment("####################################################"))
            deployment_doc.add(comment("##          Secret Management (Vault)            ##"))
            deployment_doc.add(comment("####################################################"))
            
            for key, value in vault_properties.items():
                self.__write_property(doc=deployment_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])

        # Only include optional components section if Content operator is deployed
        if self._gather.has_content_operator():
            deployment_doc.add(nl())
            deployment_doc.add(comment("####################################################"))
            deployment_doc.add(comment("##              Optional Components               ##"))
            deployment_doc.add(comment("####################################################"))

            component_properties = self.__populate_component_dict()

            for key, value in component_properties.items():
                self.__write_property(doc=deployment_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])

        # File Storage section - always include but adjust based on deployment type
        deployment_doc.add(nl())
        deployment_doc.add(comment("####################################################"))
        deployment_doc.add(comment("##                   File Storage                 ##"))
        deployment_doc.add(comment("####################################################"))

        if self._gather.has_content_operator():
            # Content deployment needs all three storage classes
            for key, value in self._storage_properties.items():
                self.__write_property(doc=deployment_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])
        else:
            # AI Services only needs one storage class
            self.__write_property(doc=deployment_doc,
                                  key="SLOW_FILE_STORAGE_CLASSNAME",
                                  value=self._storage_properties["SLOW_FILE_STORAGE_CLASSNAME"]['value'],
                                  note=["Storage class name for AI Services file storage."])


        egress_properties = self.__populate_egress_dict()

        if self._gather.platform not in ["OCP"] and egress_properties:
            deployment_doc.add(nl())
            deployment_doc.add(comment("####################################################"))
            deployment_doc.add(comment("##                   Egress Properties            ##"))
            deployment_doc.add(comment("####################################################"))

            for key, value in egress_properties.items():
                self.__write_property(doc=deployment_doc,
                                    key=key,
                                    value=value['value'],
                                    note=value['comment'])

        # Create a file
        f = TOMLFile(os.path.join(self._property_folder, 'ccx-deployment.toml'))
        f.write(deployment_doc)

    def create_ingress_propertyfile(self):
        # Create a file
        ingress_doc = document()
        ingress_doc.add(comment("####################################################"))
        ingress_doc.add(comment("##                 Ingress Properties             ##"))
        ingress_doc.add(comment("####################################################"))

        for key, value in self._ingress_properties.items():
            self.__write_property(doc=ingress_doc,
                                  key=key,
                                  value=value['value'],
                                  note=value['comment'])

        # Create a file
        f = TOMLFile(os.path.join(self._property_folder, 'ccx-ingress.toml'))
        f.write(ingress_doc)

    # method to create the custom component propertyfile
    def create_custom_component_propertyfile(self):
        # Create a file
        custom_property_doc = document()

        ban_features = [self._gather.sendmail_support]

        # compute if header section needs to generated
        # this section of the file is for sendmail support details
        if any(ban_features):
            custom_property_doc.add(comment("####################################################"))
            custom_property_doc.add(comment("##          IBM Content Navigator Options         ##"))
            custom_property_doc.add(comment("####################################################"))

            if self._gather.sendmail_support:
                sendmail_section = table()
                for key, value in self._sendmail_custom_properties.items():
                    self.__write_property_table(section=sendmail_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                custom_property_doc.add(nl())
                custom_property_doc.add("SENDMAIL", sendmail_section)
                custom_property_doc.add(nl())

        # compute if header section needs to generated
        css_features = [self._gather.icc_support]

        # this section of the file is for ICC for Email support details
        if any(css_features):
            custom_property_doc.add(nl())
            custom_property_doc.add(comment("####################################################"))
            custom_property_doc.add(comment("##      IBM Content Search Services Options       ##"))
            custom_property_doc.add(comment("####################################################"))

            if self._gather.icc_support:
                icc_section = table()
                for key, value in self._icc_custom_properties.items():
                    self.__write_property_table(section=icc_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                custom_property_doc.add(nl())
                custom_property_doc.add("ICC", icc_section)
                custom_property_doc.add(nl())

        # compute if header section needs to generated
        tm_features = [self._gather.tm_custom_groups]
        # this section of the file is for taskmanager custom groups support details
        if any(tm_features):
            custom_property_doc.add(comment("####################################################"))
            custom_property_doc.add(comment("##            IBM Task Manager Options            ##"))
            custom_property_doc.add(comment("####################################################"))

            if self._gather.tm_custom_groups:
                custom_groups_section = table()
                for key, value in self._tm_custom_properties.items():
                    self.__write_property_table(section=custom_groups_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                custom_property_doc.add(nl())
                custom_property_doc.add("PERMISSIONS", custom_groups_section)
                custom_property_doc.add(nl())

        # Create a file
        f = TOMLFile(os.path.join(self._property_folder, 'content_components_options.toml'))
        f.write(custom_property_doc)

    # Create a method that create a user group file
    def create_user_group_propertyfile(self):
        # Create a file
        user_doc = document()
        user_doc.add(comment("####################################################"))
        user_doc.add(comment("##           Common Credential Properties         ##"))
        user_doc.add(comment("####################################################"))

        for key, value in self._common_credentials.items():
            self.__write_property(doc=user_doc,
                                  key=key,
                                  value=value['value'],
                                  note=value['comment'])

        user_doc.add(nl())
        if "cpe" in self._gather.optional_components:
            user_doc.add(comment("####################################################"))
            user_doc.add(comment("##           P8 CPE Credential Properties         ##"))
            user_doc.add(comment("####################################################"))

            for key, value in self._p8_credentials.items():
                self.__write_property(doc=user_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])

            user_doc.add(nl())
        if "ban" in self._gather.optional_components:
            user_doc.add(comment("####################################################"))
            user_doc.add(comment("##          Navigator Credential Properties       ##"))
            user_doc.add(comment("####################################################"))

            for key, value in self._icn_credentials.items():
                self.__write_property(doc=user_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])
            user_doc.add(nl())

        if self._gather.content_initialize:
            init = self.__populate_init_dict()

            user_doc.add(nl())
            user_doc.add(comment("####################################################"))
            user_doc.add(comment("##         Initialize and Verify Properties       ##"))
            user_doc.add(comment("####################################################"))

            for key, value in init.items():
                self.__write_property(doc=user_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])

            verify = self.__populate_verify_dict()

            for key, value in verify.items():
                self.__write_property(doc=user_doc,
                                      key=key,
                                      value=value['value'],
                                      note=value['comment'])

            os_init = self.__populate_os_init_dict()

            # Adjust the db properties for OS
            for i in range(self._gather.os_number):
                if i == 0:
                    suffix = 'OS'
                else:
                    suffix = f"OS{i + 1}"

                os_section = table()
                # loop through the db_properties dictionary
                for key, value in os_init.items():
                    self.__write_property_table(section=os_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                user_doc.add(f"{suffix}", os_section)

        f = TOMLFile(os.path.join(self._property_folder, 'content_user_group.toml'))
        f.write(user_doc)

    # Create a private that copy and changes the user group dictionary
    def __populate_init_dict(self):
        try:
            # Create a copy of the user group dictionary
            init_dict = copy.deepcopy(self._init_properties)

            if self._gather.content_initialize:
                init_dict['CONTENT_INITIALIZATION_ENABLE']['value'] = True

            return init_dict

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_db_propertyfile function -  {}".format(str(e)))

    def __populate_verify_dict(self):
        try:
            # Create a copy of the user group dictionary
            verify_dict = copy.deepcopy(self._verify_properties)

            if self._gather.content_verification:
                verify_dict['CONTENT_VERIFICATION_ENABLE']['value'] = True

            return verify_dict

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in populate_verify_dict function -  {}".format(str(e)))

    def __populate_os_init_dict(self):
        try:
            # Create a copy of the user group dictionary
            os_init_dict = copy.deepcopy(self._os_init_properties)

            if "ier" in self._gather.optional_components:
                os_init_dict['CPE_OBJ_STORE_OS_PE_WORKFLOW_ENABLE']['value'] = True

            return os_init_dict

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in populate_os_init_dict function -  {}".format(str(e)))

    # Create a method that creates a db property file
    def create_db_propertyfile(self, db_properties):
        try:

            user_doc = document()
            user_doc.add(comment("####################################################"))
            user_doc.add(comment("##           Common Database Properties           ##"))
            user_doc.add(comment("####################################################"))

            self.__write_property(doc=user_doc,
                                  key='DATABASE_TYPE',
                                  value=db_properties['DATABASE_TYPE']['value'],
                                  note=db_properties['DATABASE_TYPE']['comment'])

            self.__write_property(doc=user_doc,
                                  key='DATABASE_SSL_ENABLE',
                                  value=db_properties['DATABASE_SSL_ENABLE']['value'],
                                  note=db_properties['DATABASE_SSL_ENABLE']['comment'])

            if self._gather.db_type == 'postgresql' and self._gather.db_ssl:
                self.__write_property(doc=user_doc,
                                      key='SSL_MODE',
                                      value=db_properties['SSL_MODE']['value'],
                                      note=db_properties['SSL_MODE']['comment'])

            user_doc.add(nl())
            if "cpe" in self._gather.optional_components:
                user_doc.add(comment("####################################################"))
                user_doc.add(comment("##         Property Section for GCD database      ##"))
                user_doc.add(comment("####################################################"))

                gcd_section = table()
                for key, value in db_properties['GCD'].items():
                    if self._gather.db_type == 'oracle' and (key in ['DATABASE_SERVERNAME', 'DATABASE_PORT']):
                        continue
                    self.__write_property_table(section=gcd_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                user_doc.add("GCD", gcd_section)

                # Adjust the db properties for OS
                for i in range(self._gather.os_number):
                    if i == 0:
                        suffix = 'OS'
                    else:
                        suffix = f"OS{i + 1}"

                    user_doc.add(nl())
                    user_doc.add(comment("####################################################"))
                    user_doc.add(comment("##         Property Section for {} database      ##".format(suffix)))
                    user_doc.add(comment("####################################################"))

                    os_section = table()
                    # loop through the db_properties dictionary
                    for key, value in db_properties[suffix].items():
                        if self._gather.db_type == 'oracle' and (key in ['DATABASE_SERVERNAME', 'DATABASE_PORT']):
                            continue
                        self.__write_property_table(section=os_section,
                                                    key=key,
                                                    value=value['value'],
                                                    note=value['comment'])

                    user_doc.add(f"{suffix}", os_section)

                user_doc.add(nl())
            if "ban" in self._gather.optional_components:
                user_doc.add(comment("####################################################"))
                user_doc.add(comment("##         Property Section for ICN database      ##"))
                user_doc.add(comment("####################################################"))

                icn_section = table()
                # loop through the db_properties dictionary
                for key, value in db_properties['ICN'].items():
                    if self._gather.db_type == 'oracle' and (key in ['DATABASE_SERVERNAME', 'DATABASE_PORT']):
                        continue
                    self.__write_property_table(section=icn_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                user_doc.add("ICN", icn_section)

            f = TOMLFile(os.path.join(self._property_folder, 'content_db_server.toml'))
            f.write(user_doc)


        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_db_propertyfile function -  {}".format(str(e)))

    def populate_db_propertyfile(self):
        try:

            database_port = {'db2': "50000",
                             'db2HADR': "50000",
                             'db2rds': "50000",
                             'db2rdsHADR': "50000",
                             'oracle': "1521",
                             'oracle_ssl': "2484",
                             'sqlserver': "1433",
                             'postgresql': "5432"}

            # Remove extra DB parameters
            if self._gather.db_type != 'oracle':
                self._db_properties.pop('ORACLE_JDBC_URL')

            # DB2 HADR both require the parameters HADR_STANDBY_SERVERNAME , HADR_STANDBY_PORT
            if self._gather.db_type != 'db2HADR':
                self._db_properties.pop('HADR_STANDBY_SERVERNAME')
                self._db_properties.pop('HADR_STANDBY_PORT')

            # Create a copy of the db dictionary
            db_properties_dict = {'DATABASE_TYPE': copy.deepcopy(self._db_properties['DATABASE_TYPE']),
                                  'DATABASE_SSL_ENABLE': copy.deepcopy(self._db_properties['DATABASE_SSL_ENABLE']),
                                  'SSL_MODE': copy.deepcopy(self._db_properties['SSL_MODE']),
                                  'GCD': copy.deepcopy(self._db_properties),
                                  'ICN': copy.deepcopy(self._db_properties)}

            if self._gather.db_ssl and self._gather.db_type == 'oracle':
                db_port = database_port['oracle_ssl']
            else:
                db_port = database_port[self._gather.db_type]

            # Add OS to the db_properties_dict
            for i in range(self._gather.os_number):
                if i == 0:
                    db_properties_dict['OS'] = copy.deepcopy(self._db_properties)
                else:
                    db_properties_dict[f"OS{i + 1}"] = copy.deepcopy(self._db_properties)

            # Adjust the db common properties
            db_properties_dict['DATABASE_TYPE']['value'] = self._gather.db_type
            db_properties_dict['DATABASE_SSL_ENABLE']['value'] = self._gather.db_ssl
            db_properties_dict['SSL_MODE']['value'] = "require"

            # Adjust the db properties for GCD
            db_properties_dict['GCD'].pop('DATABASE_TYPE')
            db_properties_dict['GCD'].pop('DATABASE_SSL_ENABLE')
            db_properties_dict['GCD'].pop('OS_LABEL')
            db_properties_dict['GCD'].pop('SSL_MODE')
            db_properties_dict['GCD'].pop('TABLESPACE_NAME')
            db_properties_dict['GCD'].pop('SCHEMA_NAME')
            db_properties_dict['GCD']['DATABASE_PORT']['value'] = db_port
            db_properties_dict['GCD']['DATASOURCE_NAME']['value'] = "FNGCDDS"
            db_properties_dict['GCD']['DATASOURCE_NAME_XA']['value'] = "FNGCDDSXA"
            if self._gather.db_type == 'oracle':
                jdbc_url = self.__create_oracle_jdbc_url()
                db_properties_dict['GCD']['ORACLE_JDBC_URL']['value'] = jdbc_url

            # Adjust the db properties for ICN
            db_properties_dict['ICN'].pop('DATABASE_TYPE')
            db_properties_dict['ICN'].pop('DATABASE_SSL_ENABLE')
            db_properties_dict['ICN'].pop('OS_LABEL')
            db_properties_dict['ICN'].pop('SSL_MODE')
            db_properties_dict['ICN'].pop('DATASOURCE_NAME_XA')
            db_properties_dict['ICN']['TABLESPACE_NAME']['value'] = "ICNDB"
            db_properties_dict['ICN']['SCHEMA_NAME']['value'] = "ICNDB"
            db_properties_dict['ICN']['DATABASE_PORT']['value'] = db_port
            db_properties_dict['ICN']['DATASOURCE_NAME']['value'] = "ECMClientDS"
            if self._gather.db_type == 'oracle':
                jdbc_url = self.__create_oracle_jdbc_url()
                db_properties_dict['ICN']['ORACLE_JDBC_URL']['value'] = jdbc_url

            # Adjust the db properties for OS
            for i in range(self._gather.os_number):
                if i == 0:
                    db_properties_dict['OS'].pop('DATABASE_TYPE')
                    db_properties_dict['OS'].pop('DATABASE_SSL_ENABLE')
                    db_properties_dict['OS']['OS_LABEL']['value'] = 'os'
                    db_properties_dict['OS'].pop('SSL_MODE')
                    db_properties_dict['OS'].pop('TABLESPACE_NAME')
                    db_properties_dict['OS'].pop('SCHEMA_NAME')
                    db_properties_dict['OS']['DATABASE_PORT']['value'] = db_port
                    db_properties_dict['OS']['DATASOURCE_NAME']['value'] = "FNOS1DS"
                    db_properties_dict['OS']['DATASOURCE_NAME_XA']['value'] = "FNOS1DSXA"
                    if self._gather.db_type == 'oracle':
                        jdbc_url = self.__create_oracle_jdbc_url()
                        db_properties_dict['OS']['ORACLE_JDBC_URL']['value'] = jdbc_url
                else:
                    db_properties_dict[f"OS{i + 1}"].pop('DATABASE_TYPE')
                    db_properties_dict[f"OS{i + 1}"].pop('DATABASE_SSL_ENABLE')
                    db_properties_dict[f"OS{i + 1}"]['OS_LABEL']['value'] = f"os{i + 1}"
                    db_properties_dict[f"OS{i + 1}"].pop('SSL_MODE')
                    db_properties_dict[f"OS{i + 1}"].pop('TABLESPACE_NAME')
                    db_properties_dict[f"OS{i + 1}"].pop('SCHEMA_NAME')
                    db_properties_dict[f"OS{i + 1}"]['DATABASE_PORT']['value'] = db_port
                    db_properties_dict[f"OS{i + 1}"]['DATASOURCE_NAME']['value'] = f"FNOS{i + 1}DS"
                    db_properties_dict[f"OS{i + 1}"]['DATASOURCE_NAME_XA']['value'] = f"FNOS{i + 1}DSXA"
                    if self._gather.db_type == 'oracle':
                        jdbc_url = self.__create_oracle_jdbc_url()
                        db_properties_dict[f"OS{i + 1}"]['ORACLE_JDBC_URL']['value'] = jdbc_url

            return db_properties_dict

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_db_propertyfile function -  {}".format(str(e)))

    # Create a private method that creates the jdbc oracle url
    def __create_oracle_jdbc_url(self, host_name = "<Required>", db_name = "<Required>", port_name = "<Required>") -> str:
        try:
            if self._gather.db_ssl and self._gather.db_type == 'oracle':
                jdbc_url = 'jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCPS)(HOST={host})(PORT={port}))(' \
                           'CONNECT_DATA=(SERVICE_NAME={dbname})))'.format(
                    host=host_name,
                    dbname=db_name, 
                    port=port_name)
            else:
                jdbc_url = 'jdbc:oracle:thin:@(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST={host})(PORT={port}))(' \
                           'CONNECT_DATA=(SERVICE_NAME={dbname})))'.format(
                    host=host_name,
                    dbname=db_name, 
                    port=port_name)
            return jdbc_url

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_oracle_jdbc_url function -  {}".format(str(e)))

    def create_idp_propertyfile(self, idp_properties_list):
        try:

            # Create a file
            idp_doc = document()
            idp_doc.add(comment("####################################################"))
            idp_doc.add(comment("##                  IDP Properties                ##"))
            idp_doc.add(comment("####################################################"))
            idp_doc.add(nl())

            idp_section = table()

            suffix = 'IDP'
            # loop through the ldap_properties dictionary
            for key, value in idp_properties_list[0].items():
                self.__write_property_table(section=idp_section,
                                            key=key,
                                            value=value['value'],
                                            note=value['comment'])

            idp_doc.add(suffix, idp_section)

            for i in range(1, self._gather.idp_number):
                suffix = f"IDP{i + 1}"

                idp_section = table()

                idp_doc.add(nl())
                idp_doc.add(comment("####################################################"))
                idp_doc.add(comment(f"##               {suffix} Properties             ##"))
                idp_doc.add(comment("####################################################"))

                # loop through the db_properties dictionary
                for key, value in idp_properties_list[i].items():
                    self.__write_property_table(section=idp_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                idp_doc.add(suffix, idp_section)

            f = TOMLFile(os.path.join(self._property_folder, 'ccx-identity_provider.toml'))
            f.write(idp_doc)

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_idp_propertyfile function -  {}".format(str(e)))

    # Create a method that creates a ldap property file
    def create_ldap_propertyfile(self, ldap_properties_list):
        try:

            # Create a file
            ldap_doc = document()
            ldap_doc.add(comment("####################################################"))
            ldap_doc.add(comment("##                 LDAP Properties                ##"))
            ldap_doc.add(comment("####################################################"))
            ldap_doc.add(nl())

            ldap_section = table()

            suffix = 'LDAP'

            # loop through the ldap_properties dictionary
            for key, value in ldap_properties_list[0].items():
                self.__write_property_table(section=ldap_section,
                                            key=key,
                                            value=value['value'],
                                            note=value['comment'])

            ldap_doc.add(suffix, ldap_section)

            for i in range(1, self._gather.ldap_number):
                suffix = f"LDAP{i + 1}"

                ldap_section = table()

                ldap_doc.add(nl())
                ldap_doc.add(comment("####################################################"))
                ldap_doc.add(comment(f"##               {suffix} Properties              ##"))
                ldap_doc.add(comment("####################################################"))

                # loop through the db_properties dictionary
                for key, value in ldap_properties_list[i].items():
                    self.__write_property_table(section=ldap_section,
                                                key=key,
                                                value=value['value'],
                                                note=value['comment'])

                ldap_doc.add(suffix, ldap_section)

            f = TOMLFile(os.path.join(self._property_folder, 'content_ldap_server.toml'))
            f.write(ldap_doc)

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_ldap_propertyfile function -  {}".format(str(e)))

    # Create a private method that writes properties to a file
    @staticmethod
    def __write_property(doc, key, value, note):

        doc.add(nl())
        for i in note:
            doc.add(comment(f'{i}'))
        cred_list = ['PASSWORD', 'SECRET', 'USERNAME', 'GROUPS_NAME', 'ADMIN_USER', 'LOGIN_USER', 'CLIENT_ID', 'BIND_DN', 'USER_ID', "NAMES"]
        if any(ele in key for ele in cred_list):
            if isinstance(value, list):
                for i in range(len(value)):
                    value[i] = string(value[i], multiline=True)
            else:
                value = string(value, multiline=True)

        doc.add(key, value)

    @staticmethod
    def __write_property_table(section, key, value, note, ):
        section.add(nl())
        for i in note:
            section.add(comment(f'{i}'))
        cred_list = ['PASSWORD', 'SECRET', 'USERNAME', 'GROUPS_NAME', 'ADMIN_USER', 'LOGIN_USER', 'BIND_DN', 'USER_ID', "NAMES", 'API_KEY', 'SPACE_ID', 'PROJECT_ID']
        if any(ele in key for ele in cred_list):
            if isinstance(value, list):
                for i in range(len(value)):
                    value[i] = string(value[i], multiline=True)
            else:
                value = string(value, multiline=True)

        section.add(key, value)

    def populate_idp_propertyfile(self):
        try:
            idp_properties_list = []
            
            # Check if we have migrated IDP settings from an existing FNCMCluster deployment
            migration_settings = self._gather.fncm_migration_settings
            migrated_idp = None
            
            if migration_settings and migration_settings.get('found'):
                migrated_idp = migration_settings.get('idp_config', {})
                if migrated_idp and migrated_idp.get('provider_name'):
                    self._logger.info("Using migrated IDP settings from FNCMCluster CR")

            for i in range(self._gather.idp_number):
                idp_dict = self._gather.idp_info[i].to_dict()
                idp_prop = copy.deepcopy(self._idp_properties)

                idp_prop['PROVIDER_NAME']['value'] = idp_dict['id']
                idp_prop['DISPLAY_NAME']['value'] = "{} SSO Login".format(idp_dict['id'])

                # Use migrated discovery URL if available and matches this IDP
                if migrated_idp and migrated_idp.get('provider_name') == idp_dict['id']:
                    if migrated_idp.get('discovery_url'):
                        idp_dict['discovery_url'] = migrated_idp['discovery_url']
                        idp_dict['discovery_enabled'] = True
                        self._logger.info(f"Pre-filled discovery URL from migrated settings: {migrated_idp['discovery_url']}")
                        
                        # Add comment about migration source
                        if 'comment' not in idp_prop['DISCOVERY_ENDPOINT']:
                            idp_prop['DISCOVERY_ENDPOINT']['comment'] = []
                        idp_prop['DISCOVERY_ENDPOINT']['comment'].insert(0,
                            f"Migrated from FNCMCluster CR '{migration_settings.get('cr_name')}' in namespace '{migration_settings.get('namespace')}'")

                if idp_dict['discovery_enabled']:
                    idp_prop['DISCOVERY_ENDPOINT']['value'] = idp_dict["discovery_url"]
                    idp_prop['IDP_SSL_ENABLED']['value'] = idp_dict["ssl_enabled"]
                else:
                    idp_prop.pop('DISCOVERY_ENDPOINT')

                if idp_dict['token_url']:
                    idp_prop['TOKEN_ENDPOINT']['value'] = idp_dict['token_url']

                if idp_dict["issuer"]:
                    idp_prop['ISSUER']['value'] = idp_dict["issuer"]

                if idp_dict['introspect_url'] and idp_dict['validation_method'] == "introspect":
                    idp_prop['INTROSPECT_ENDPOINT']['value'] = idp_dict['introspect_url']
                    idp_prop.pop('USERINFO_ENDPOINT')

                if idp_dict['userinfo_url'] and idp_dict['validation_method'] == "userinfo":
                    idp_prop['USERINFO_ENDPOINT']['value'] = idp_dict['userinfo_url']
                    idp_prop.pop('INTROSPECT_ENDPOINT')

                if idp_dict['revoke_url']:
                    idp_prop['REVOCATION_ENDPOINT']['value'] = idp_dict['revoke_url']
                else:
                    idp_prop.pop('REVOCATION_ENDPOINT')

                if idp_dict['jwks_url']:
                    idp_prop['JWKS_ENDPOINT']['value'] = idp_dict['jwks_url']

                idp_prop['VALIDATION_METHOD']['value'] = idp_dict['validation_method']
                idp_prop['USER_IDENTIFIER']['value'] = idp_dict['user_identifier']
                idp_prop['UNIQUE_USER_IDENTIFIER']['value'] = idp_dict['unique_user_identifier']
                idp_prop['USER_IDENTIFIER_TO_CREATE_SUBJECT']['value'] = idp_dict['user_identifier_to_sub']
                
                # Populate client credentials from idp_dict
                if idp_dict.get('client_id'):
                    idp_prop['CLIENT_ID']['value'] = idp_dict['client_id']
                if idp_dict.get('client_secret'):
                    idp_prop['CLIENT_SECRET']['value'] = idp_dict['client_secret']

                idp_properties_list.append(idp_prop)

            return idp_properties_list


        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_ldap_propertyfile function -  {}".format(str(e)))

    def create_scim_propertyfile(self, scim_properties):
        try:

            # Create a file
            scim_doc = document()
            scim_doc.add(comment("####################################################"))
            scim_doc.add(comment("##                  SCIM Properties               ##"))
            scim_doc.add(comment("####################################################"))
            scim_doc.add(nl())

            scim_section = table()

            suffix = 'SCIM'
            # loop through the ldap_properties dictionary
            for key, value in scim_properties.items():
                self.__write_property_table(section=scim_section,
                                            key=key,
                                            value=value['value'],
                                            note=value['comment'])

            scim_doc.add(suffix, scim_section)

            f = TOMLFile(os.path.join(self._property_folder, 'content_scim_server.toml'))
            f.write(scim_doc)

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_scim_propertyfile function -  {}".format(str(e)))

    def populate_scim_propertyfile(self):
        try:

            idp_dict = self._gather.idp_info[0].to_dict()
            scim_prop = copy.deepcopy(self._scim_properties)

            scim_prop['DISPLAY_NAME']['value'] = "SCIM"
            scim_prop['SCIM_SSL_ENABLED']['value'] = True
            scim_prop['TOKEN_ENDPOINT']['value'] = idp_dict.get("token_url", "<Required>")

            return scim_prop

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in populate_scim_propertyfile function -  {}".format(str(e)))

    def populate_ldap_propertyfile(self):
        try:
            ldap_properties_list = []
            # Create a copy of the ldap properties dictionary
            for i in range(self._gather.ldap_number):
                ldap_dict = self._gather.ldap_info[i].to_dict()
                ldap_prop = copy.deepcopy(self._ldap_properties)

                ldap_prop['LDAP_TYPE']['value'] = ldap_dict['type']
                ldap_prop['LDAP_SSL_ENABLED']['value'] = ldap_dict['ssl']
                ldap_prop['LDAP_ID']['value'] = ldap_dict['id']

                if ldap_dict['type'] != 'Microsoft Active Directory':
                    ldap_prop.pop('LC_AD_GC_HOST')
                    ldap_prop.pop('LC_AD_GC_PORT')

                if ldap_dict['type'] == 'Microsoft Active Directory':
                    default_value = read_json(self._json_directory, "ad_ldap_property.json")
                elif ldap_dict['type'] == 'IBM Security Verify Directory':
                    default_value = read_json(self._json_directory, "tds_ldap_property.json")
                elif ldap_dict['type'] in ['Oracle Internet Directory', 'Oracle Unified Directory',
                                           'Oracle Directory Server Enterprise Edition']:
                    default_value = read_json(self._json_directory, "oracle_ldap_property.json")
                elif ldap_dict['type'] == 'NetIQ eDirectory':
                    default_value = read_json(self._json_directory, "novell_ldap_property.json")
                elif ldap_dict['type'] == 'CA eTrust':
                    default_value = read_json(self._json_directory, "ca_ldap_property.json")

                for key, value in default_value.items():
                    ldap_prop[key]['value'] = value['value']

                if ldap_dict['ssl']:
                    ldap_prop['LDAP_PORT']['value'] = "636"
                else:
                    ldap_prop['LDAP_PORT']['value'] = "389"

                ldap_properties_list.append(ldap_prop)

            return ldap_properties_list

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_ldap_propertyfile function -  {}".format(str(e)))

    def create_aiservices_propertyfile(self, aiservices_data):
        """
        Create AI Services property file with multi-provider support.
        
        Args:
            aiservices_data: Either a list of provider dictionaries (new format)
                           or a dictionary (legacy format)
        """
        try:
            # Check if this is the new multi-provider format (list) or legacy format (dict)
            if isinstance(aiservices_data, list):
                # New multi-provider format
                self._create_multiprovider_propertyfile(aiservices_data)
            else:
                # Legacy single-provider format
                self._create_legacy_propertyfile(aiservices_data)
                
        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_aiservices_propertyfile function -  {}".format(str(e)))
    
    def _create_multiprovider_propertyfile(self, providers_list):
        """Create multi-provider AI Services property file."""
        try:
            aiservices_doc = document()
            aiservices_doc.add(comment("####################################################"))
            aiservices_doc.add(comment("##    AI Services Multi-Provider Configuration    ##"))
            aiservices_doc.add(comment("####################################################"))
            aiservices_doc.add(nl())
            aiservices_doc.add(comment("This file supports multiple AI providers with their own model configurations"))
            aiservices_doc.add(nl())

            # Track if we've set a default model yet (only first provider's first model should be default)
            default_model_set = False
            
            # Create a section for each provider
            for idx, provider_info in enumerate(providers_list, start=1):
                provider_key = f"PROVIDER_{idx}"
                provider_type = provider_info['provider_type']
                provider_number = provider_info.get('provider_number', idx)
                
                # Load the appropriate JSON template based on provider type
                if provider_type == "WATSONX_SAAS":
                    template = read_json(self._json_directory, "aiservices_provider_watsonx_saas.json")
                elif provider_type == "WATSONX_LWE":
                    template = read_json(self._json_directory, "aiservices_provider_watsonx_lwe.json")
                elif provider_type == "MICROSOFT_FOUNDRY":
                    template = read_json(self._json_directory, "aiservices_provider_microsoft_foundry.json")
                else:
                    self._logger.error(f"Unknown provider type: {provider_type}")
                    continue
                
                # Create provider section
                provider_section = table()
                
                # Add provider-level properties (excluding models)
                for key, value in template.items():
                    if key != "models":
                        self.__write_property_table(
                            section=provider_section,
                            key=key,
                            value=value['value'],
                            note=value['comment']
                        )
                
                # Add the provider section to the document
                aiservices_doc.add(provider_key, provider_section)
                aiservices_doc.add(nl())
                
                # Add models as array of tables
                if "models" in template and template["models"]:
                    # Get the first model template
                    model_template = template["models"][0]
                    
                    # Create model array using tomlkit's array of tables
                    from tomlkit import aot, table as toml_table
                    models_array = aot()
                    
                    # Create a model entry as a table
                    model_entry = toml_table()
                    for model_key, model_value in model_template.items():
                        # Override DEFAULT value: only first provider's first model should be true
                        if model_key == "DEFAULT":
                            if not default_model_set:
                                # First model across all providers - set to true
                                self.__write_property_table(
                                    section=model_entry,
                                    key=model_key,
                                    value="true",
                                    note=model_value['comment']
                                )
                                default_model_set = True
                            else:
                                # All other models - set to false
                                self.__write_property_table(
                                    section=model_entry,
                                    key=model_key,
                                    value="false",
                                    note=model_value['comment']
                                )
                        else:
                            # Add other model properties normally
                            self.__write_property_table(
                                section=model_entry,
                                key=model_key,
                                value=model_value['value'],
                                note=model_value['comment']
                            )
                    
                    # Add the model entry to the array
                    models_array.append(model_entry)
                    
                    # Add the models array to the provider section
                    provider_section.add("models", models_array)
                    aiservices_doc.add(nl())

            # Write the TOML file
            f = TOMLFile(os.path.join(self._property_folder, 'aiservices_providers.toml'))
            f.write(aiservices_doc)
            
            self._logger.info(f"Created multi-provider AI Services property file with {len(providers_list)} provider(s)")

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in _create_multiprovider_propertyfile function -  {}".format(str(e)))
    
    def _create_legacy_propertyfile(self, aiservices_properties):
        """Create legacy single-provider AI Services property file."""
        try:
            aiservices_doc = document()
            aiservices_doc.add(comment("####################################################"))
            aiservices_doc.add(comment("##         AI Services Provider Properties        ##"))
            aiservices_doc.add(comment("####################################################"))
            aiservices_doc.add(nl())

            aiservices_section = table()

            # Loop through the aiservices_properties dictionary
            for key, value in aiservices_properties.items():
                self.__write_property_table(section=aiservices_section,
                                          key=key,
                                          value=value['value'],
                                          note=value['comment'])

            aiservices_doc.add('AI_PROVIDER', aiservices_section)

            f = TOMLFile(os.path.join(self._property_folder, 'aiservices_providers.toml'))
            f.write(aiservices_doc)
            
            self._logger.info("Created legacy AI Services property file")

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in _create_legacy_propertyfile function -  {}".format(str(e)))

    def populate_aiservices_propertyfile(self):
        """
        Populate AI Services property file with multi-provider configuration.
        Returns list of provider configurations based on gather.model_providers.
        """
        try:
            # Check if we have multi-provider configuration
            if hasattr(self._gather, 'model_providers') and self._gather.model_providers:
                # Add SSL folders for LWE providers to ssl_directory_list
                for idx, provider_info in enumerate(self._gather.model_providers, start=1):
                    provider_type = provider_info.get('provider_type', '')
                    
                    if provider_type == "WATSONX_LWE":
                        # Load the template to get the default PROVIDER_ID value
                        template = read_json(self._json_directory, "aiservices_provider_watsonx_lwe.json")
                        provider_id = template.get("PROVIDER_ID", {}).get("value", "watsonx-onprem")
                        ssl_folder_name = f"ai-provider-{provider_id.lower()}"
                        
                        if ssl_folder_name not in self._gather.ssl_directory_list:
                            self._gather.ssl_directory_list.append(ssl_folder_name)
                            self._logger.info(f"Added SSL folder for LWE provider: {ssl_folder_name}")
                
                # Return the list of providers from gather
                return self._gather.model_providers
            
            # Fallback to legacy single-provider configuration
            aiservices_prop = copy.deepcopy(self._aiservices_properties)
            
            # Get WatsonX type from gather object
            watsonx_type = self._gather.watsonx_type if hasattr(self._gather, 'watsonx_type') else "SAAS"
            
            # Set deployment type based on WatsonX selection
            if watsonx_type == "SAAS":
                aiservices_prop['DEPLOYMENT_TYPE']['value'] = "saas"
                if 'USERNAME' in aiservices_prop:
                    aiservices_prop.pop('USERNAME')
            elif watsonx_type == "LWE":
                aiservices_prop['DEPLOYMENT_TYPE']['value'] = "lightweightengine"
                if 'SPACE_ID' in aiservices_prop:
                    aiservices_prop.pop('SPACE_ID')
                if 'PROJECT_ID' in aiservices_prop:
                    aiservices_prop.pop('PROJECT_ID')
            else:
                aiservices_prop['DEPLOYMENT_TYPE']['value'] = "saas"
                if 'USERNAME' in aiservices_prop:
                    aiservices_prop.pop('USERNAME')
            
            aiservices_prop['ENABLE_REDIS']['value'] = "false"
            
            return aiservices_prop

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in populate_aiservices_propertyfile function -  {}".format(str(e)))
            return None
    def create_aiservices_integration_propertyfile(self, aiservices_integration_properties):
        """Create AI Services Integration property file for GraphQL and integration configuration."""
        try:
            integration_doc = document()
            integration_doc.add(comment("####################################################"))
            integration_doc.add(comment("##       AI Services Integration Properties       ##"))
            integration_doc.add(comment("####################################################"))
            integration_doc.add(nl())

            # Loop through the aiservices_integration_properties dictionary
            # Write properties at root level without section header
            for key, value in aiservices_integration_properties.items():
                self.__write_property(integration_doc,
                                    key=key,
                                    value=value['value'],
                                    note=value['comment'])

            f = TOMLFile(os.path.join(self._property_folder, 'aiservices_integration.toml'))
            f.write(integration_doc)

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in create_aiservices_integration_propertyfile function -  {}".format(str(e)))

    def populate_aiservices_integration_propertyfile(self):
        """Populate AI Services Integration property file with default values including namespace."""
        try:
            integration_prop = copy.deepcopy(self._aiservices_integration_properties)
            
            # Set default values with namespace prefilled
            namespace = self._namespace
            
            # Check if we have migrated settings from an existing FNCMCluster deployment
            migration_settings = self._gather.fncm_migration_settings
            
            # Check if Content operator is deployed with AI Services
            content_deployed = self._gather.has_content_operator()
            
            if migration_settings and migration_settings.get('found'):
                # Use migrated settings from existing FNCMCluster CR
                self._logger.info("Using migrated settings from FNCMCluster CR for AI Services integration")
                
                # GraphQL Endpoint - use migrated value with full path
                graphql_endpoint = migration_settings.get('graphql_endpoint', '')
                if graphql_endpoint:
                    # Ensure the endpoint has the full GraphQL path
                    if not graphql_endpoint.endswith('/content-services-graphql/graphql'):
                        graphql_endpoint = graphql_endpoint.rstrip('/') + '/content-services-graphql/graphql'
                    integration_prop['GRAPHQL_ENDPOINT']['value'] = graphql_endpoint
                    integration_prop['GRAPHQL_ENDPOINT']['comment'] = [
                        "The GraphQL server endpoint URL (migrated from existing deployment).",
                        f"Source: FNCMCluster CR '{migration_settings.get('cr_name')}' in namespace '{migration_settings.get('namespace')}'",
                        "The URL must end with: /content-services-graphql/graphql",
                        "Example: https://content-graphql-svc.namespace.svc.cluster.local:9443/content-services-graphql/graphql"
                    ]
                
                # Object Store - use migrated value
                object_store = migration_settings.get('object_store', 'OS1')
                integration_prop['OBJECT_STORE']['value'] = object_store
                integration_prop['OBJECT_STORE']['comment'] = [
                    f"The Object Store ID to use for AI Services (migrated from existing deployment: {object_store}).",
                    "This should match one of the Symbolic Object Store IDs defined in your Content Platform Engine configuration.",
                    "Example: OS1, OS2, etc."
                ]
                
                # Navigator URL - use migrated value if available, otherwise mark as required
                navigator_url = migration_settings.get('navigator_url', '<Required>')
                integration_prop['NAVIGATOR_EXTERNAL_URL']['value'] = navigator_url
                if navigator_url and navigator_url != '<Required>':
                    integration_prop['NAVIGATOR_EXTERNAL_URL']['comment'] = [
                        "The external URL for IBM Content Navigator (migrated from existing deployment).",
                        "This URL is used for CORS (Cross-Origin Resource Sharing) configuration in AI Services.",
                        "Verify this URL is correct for external access.",
                        "Example: https://navigator.company.com, https://ban.example.com:9443"
                    ]
                else:
                    integration_prop['NAVIGATOR_EXTERNAL_URL']['comment'] = [
                        "The external URL for IBM Content Navigator.",
                        "IMPORTANT: This value could not be automatically determined from the existing deployment.",
                        "You must provide the full external URL that users access Navigator from.",
                        "This URL is used for CORS (Cross-Origin Resource Sharing) configuration in AI Services.",
                        "Example: https://navigator.company.com, https://ban.example.com:9443"
                    ]
                
                # Auth mode - default to dual
                integration_prop['AUTH_MODE']['value'] = "dual"
                integration_prop['AUTH_MODE']['comment'] = [
                    "Authentication mode for AI Services.",
                    "The possible values are: 'dual', 'jwt', 'debug'.",
                    "Recommended: dual (supports both JWT and basic authentication)",
                    "Example: dual"
                ]
                
            elif content_deployed:
                # Content is deployed in same cluster - use internal service endpoint
                integration_prop['GRAPHQL_ENDPOINT']['value'] = f"https://content-graphql-svc.{namespace}.svc.cluster.local:9443/content-services-graphql/graphql"
                integration_prop['GRAPHQL_ENDPOINT']['comment'] = [
                    "The GraphQL server endpoint URL.",
                    "IMPORTANT: Since Content operator is deployed with AI Services,",
                    "you must provide the internal GraphQL service endpoint URL.",
                    "The URL must end with: /content-services-graphql/graphql",
                    "Example: https://your-content-host.example.com/content-services-graphql/graphql"
                ]
                
                integration_prop['AUTH_MODE']['value'] = "dual"
                integration_prop['OBJECT_STORE']['value'] = "OS1"
                
                # Set Navigator external URL - required for CORS configuration
                integration_prop['NAVIGATOR_EXTERNAL_URL']['value'] = "<Required>"
                integration_prop['NAVIGATOR_EXTERNAL_URL']['comment'] = [
                    "The external URL for IBM Content Navigator.",
                    "This URL is used for CORS (Cross-Origin Resource Sharing) configuration in AI Services.",
                    "Provide the full external URL that users access Navigator from.",
                    "Example: https://navigator.company.com, https://ban.example.com:9443"
                ]
            else:
                # Content is NOT deployed - user must provide external GraphQL endpoint
                integration_prop['GRAPHQL_ENDPOINT']['value'] = "<Required>"
                integration_prop['GRAPHQL_ENDPOINT']['comment'] = [
                    "The GraphQL server endpoint URL.",
                    "IMPORTANT: Since Content operator is not deployed with AI Services,",
                    "you must provide the external or internal GraphQL endpoint URL.",
                    "The URL must end with: /content-services-graphql/graphql",
                    "If using HTTPS, place the SSL certificate in: propertyFile/<namespace>/ssl-certs/graphql/",
                    "Example: https://your-content-host.example.com/content-services-graphql/graphql"
                ]
                
                integration_prop['AUTH_MODE']['value'] = "dual"
                integration_prop['OBJECT_STORE']['value'] = "OS1"
                
                # Set Navigator external URL - required for CORS configuration
                integration_prop['NAVIGATOR_EXTERNAL_URL']['value'] = "<Required>"
                integration_prop['NAVIGATOR_EXTERNAL_URL']['comment'] = [
                    "The external URL for IBM Content Navigator.",
                    "This URL is used for CORS (Cross-Origin Resource Sharing) configuration in AI Services.",
                    "Provide the full external URL that users access Navigator from.",
                    "Example: https://navigator.company.com, https://ban.example.com:9443"
                ]
            
            return integration_prop

        except Exception as e:
            self._logger.exception(
                "Exception from gather script in populate_aiservices_integration_propertyfile function -  {}".format(str(e)))


import json
import os
import yaml
from datetime import datetime, timezone
from pathlib import Path

from surface_cdms.version import get_surface_version, normalize_surface_version


# path to ansible project folder
django_app_dir = os.path.dirname(os.path.dirname(__file__))

# path to ansible project folder
project_dir = os.path.join(django_app_dir, 'ansible', 'surface_app',)

# path to remote connection file
connection_password_file_path = os.path.join(project_dir, 'env', 'connection_password')

# path to root user password file
sudo_password_file_path = os.path.join(project_dir, 'env', 'become_password')

# path to sudo password used for local installs
local_sudo_password_path = os.path.join(os.path.dirname(django_app_dir ),'wx_playbook', 'env', 'become_password')

# path to surface variables file (for user in the playbooks)
variable_file_path = os.path.join(project_dir, 'env', 'extravars',)

# path to production.env file
prod_env_file_path = os.path.join(project_dir, 'env', 'production.env',)

# path .env file
env_file_path = os.path.join(project_dir, 'env', '.env',)

# path to countries spatial analysis folder
spatial_analysis_path = os.path.join(django_app_dir, 'static', 'surface_app', 'spatial_analysis')

# path to countries fixtures folder
fixtures_path = os.path.join(django_app_dir, 'static', 'surface_app', 'fixtures')

# path to remote hosts path
hosts_file_path = os.path.join(project_dir, 'inventory', 'hosts')

# path to lrgs install jar file
lrgs_install_jar = os.path.join(project_dir, 'env', 'lrgs', 'lrgs-client-install-6-2-RC03.jar',)

# path lrgs installation script
lrgs_installation_script = os.path.join(project_dir, 'env', 'lrgs', 'LRGS-installation-script',)

# path to SURFACE CDMS local metadata directory
surface_cdms_metadata_dir = os.path.join(Path.home(), ".surface-cdms")

# path to local install metadata file
surface_cdms_install_metadata_path = os.path.join(surface_cdms_metadata_dir,"install.json",)


def replace_text_in_file(file_path, search_text, replace_text):
    try:
        # Read the content of the file
        with open(file_path, 'r') as file:
            file_content = file.read()
        
        # Replace the search text with the replacement text
        new_content = file_content.replace(search_text, replace_text)
        
        # Write the modified content back to the file
        with open(file_path, 'w') as file:
            file.write(new_content)
    except:
        pass


def write_install_metadata(surface_repo_path):
    """
    Write local SURFACE CDMS install metadata.

    This file allows future CLI commands such as:

        surface up
        surface down
        surface restart
        surface logs
        surface containers

    to know where the installed SURFACE Docker Compose project lives.
    """

    normalized_surface_repo_path = surface_repo_path.rstrip("/") + "/"

    metadata = {
        "surface_cdms_version": normalize_surface_version(get_surface_version()),
        "surface_repo_path": normalized_surface_repo_path,
        "compose_file": os.path.join(normalized_surface_repo_path, "docker-compose.yml"),
        "install_status": "installing",
        "install_started_at": datetime.now(timezone.utc).isoformat(),
    }

    os.makedirs(surface_cdms_metadata_dir, exist_ok=True)

    with open(surface_cdms_install_metadata_path, "w") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)
        metadata_file.write("\n")


def update_install_metadata_status(status):
    """
    Update the local install metadata status.

    Expected statuses:
        installing
        installed
        failed
        uninstalled
    """

    if not os.path.exists(surface_cdms_install_metadata_path):
        return

    with open(surface_cdms_install_metadata_path, "r") as metadata_file:
        metadata = json.load(metadata_file)

    metadata["install_status"] = status

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    if status == "installed":
        metadata["installed_at"] = now_iso
    elif status == "failed":
        metadata["failed_at"] = now_iso
    elif status == "uninstalled":
        metadata["uninstalled_at"] = now_iso

    install_started_at = metadata.get("install_started_at")

    if install_started_at and status in ["installed", "failed"]:
        try:
            started_at = datetime.fromisoformat(install_started_at)
            duration_seconds = int((now - started_at).total_seconds())

            metadata["install_duration_seconds"] = duration_seconds
            metadata["install_duration_minutes"] = round(duration_seconds / 60, 2)

        except (ValueError, TypeError):
            metadata["install_duration_seconds"] = None
            metadata["install_duration_minutes"] = None

    with open(surface_cdms_install_metadata_path, "w") as metadata_file:
        json.dump(metadata, metadata_file, indent=2)
        metadata_file.write("\n")


# Mainly used for playbook execution.
# mainly for used in the playbook execution
def write_out_surface_variables(form):
    """
        Append SURFACE installation variables to the Ansible extra-vars YAML file.

        Append mode is used because the installer writes the SURFACE artifact path
        to this file separately. The installer clears the file before each
        `surface install` run.
    """

    # holds vars to be written out
    surface_variables_dict = {}

    # ------------------------------------------------------------------
    # Installation path configuration
    # ------------------------------------------------------------------

    # User chooses the parent directory where SURFACE should be installed.
    surface_install_parent_path = form.cleaned_data["surface_repo_path"].strip()

    # User chooses the parent directory where SURFACE should be installed.
    surface_install_parent_path = form.cleaned_data["surface_repo_path"].strip()

    if not surface_install_parent_path.endswith("/"):
        surface_install_parent_path += "/"

    # The artifact contains a top-level "surface/" folder, so after extraction
    # the actual SURFACE repo/app path will be parent + "surface/".
    surface_repo_path = f"{surface_install_parent_path}surface/"

    # update the var dict
    surface_variables_dict.update(
        {
            "with_data": str(form.cleaned_data["with_data"]),
            "surface_install_parent_path": surface_install_parent_path,
            "surface_repo_path": surface_repo_path,
        }
    )

    # Save install metadata for future CLI management commands.
    write_install_metadata(surface_repo_path)

    # ------------------------------------------------------------------
    # Data dump configuration
    # ------------------------------------------------------------------

    ftp_host = form.cleaned_data["dump_ftp_host"]
    ftp_port = form.cleaned_data["dump_ftp_port"]
    ftp_username = form.cleaned_data["dump_ftp_username"]
    ftp_password = form.cleaned_data["dump_ftp_password"]
    ftp_data_dump = form.cleaned_data["dump_ftp_dump_path"]

    dump_via_ftp = all(
        [
            ftp_host,
            ftp_port,
            ftp_username,
            ftp_password,
            ftp_data_dump,
        ]
    )

    if dump_via_ftp:
        data_dump_filename = ftp_data_dump.strip("/").split("/")[-1]

        surface_variables_dict.update(
            {
                "dump_via_ftp": "true",
                "ftp_host": ftp_host,
                "ftp_port": ftp_port,
                "ftp_username": ftp_username,
                "ftp_password": ftp_password,
                "ftp_data_dump": ftp_data_dump,
                "data_file_name": data_dump_filename,
                "data_path": os.path.join(
                    surface_repo_path,
                    "backup_restore_dumps",
                    data_dump_filename,
                ),
            }
        )
    else:
        data_path = form.cleaned_data["data_path"]
        data_dump_filename = data_path.strip("/").split("/")[-1]

        surface_variables_dict.update(
            {
                "dump_via_ftp": "false",
                "data_file_name": data_dump_filename,
                "data_path": data_path,
            }
        )

    # ------------------------------------------------------------------
    # Administrator configuration
    # ------------------------------------------------------------------

    surface_variables_dict.update(
        {
            "admin": form.cleaned_data["admin"].strip(),
            "admin_email": form.cleaned_data["admin_email"].strip(),
            "admin_password": form.cleaned_data["admin_password"],
        }
    )

    # ------------------------------------------------------------------
    # Environment file paths
    # ------------------------------------------------------------------

    surface_variables_dict.update(
        {
            "prod_env_path": prod_env_file_path,
            "env_path": env_file_path,
        }
    )

    # ------------------------------------------------------------------
    # Country-specific files
    # ------------------------------------------------------------------

    iso3_code = form.cleaned_data["selected_country"]

    surface_variables_dict.update(
        {
            "spatial_analysis_files_path": os.path.join(
                spatial_analysis_path,
                f"{iso3_code}_spatial_analysis",
            ),
            "fixtures_files_path": os.path.join(
                fixtures_path,
                f"{iso3_code}_fixtures",
            ),
        }
    )

    # ------------------------------------------------------------------
    # LRGS configuration
    # ------------------------------------------------------------------

    lrgs_input_username = str(form.cleaned_data["lrgs_user"]).strip()
    lrgs_input_password = str(form.cleaned_data["lrgs_password"]).strip()

    enable_lrgs = bool(
        lrgs_input_username
        and lrgs_input_password
    )

    surface_variables_dict["enable_lrgs"] = "true" if enable_lrgs else "false"

    if enable_lrgs:
        lrgs_client_path = os.path.join(
            surface_repo_path,
            "api",
            "LrgsClient",
        )

        surface_variables_dict.update(
            {
                "LRGSClient_path": lrgs_client_path,
                "lrgs_decj": os.path.join(
                    lrgs_client_path,
                    "bin",
                    "decj",
                ),
                "lrgs_getDcpMessages": os.path.join(
                    lrgs_client_path,
                    "bin",
                    "getDcpMessages",
                ),
                "lrgs_msgaccess": os.path.join(
                    lrgs_client_path,
                    "bin",
                    "msgaccess",
                ),
                "lrgs_rtstat": os.path.join(
                    lrgs_client_path,
                    "bin",
                    "rtstat",
                ),
                "lrgs_install_jar": lrgs_install_jar,
                "lrgs_installation_script": lrgs_installation_script,
            }
        )


    # ------------------------------------------------------------------
    # Safely append the variables as valid YAML
    # ------------------------------------------------------------------

    with open(variable_file_path, "a", encoding="utf-8") as variable_file:
        variable_file.write("\n")

        yaml.safe_dump(
            surface_variables_dict,
            variable_file,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )


def write_out_production_variables(form):
    # clear production.env of any previously entered settings
    with open(prod_env_file_path, 'r') as file:
        prod_lines = file.readlines()

    prod_index = None
    for index, line in enumerate(prod_lines):
        if line.strip() == '# USER MODIFIED SETTINGS':
            prod_index = index
            break

    if prod_index is not None:
        # Keep everything before the "# USER MODIFIED SETTINGS" section (inclusive)
        prod_new_lines = prod_lines[:prod_index + 1]

        # Write the modified contents back to the file
        with open(prod_env_file_path, 'w') as file:
            file.writelines(prod_new_lines)

    # Write out production.env variables
    with open(prod_env_file_path, 'a') as prod:
        prod.write('\n\n')
        prod.write(f'LRGS_USER={form.cleaned_data["lrgs_user"].strip()}\n')
        prod.write(f'LRGS_PASSWORD={form.cleaned_data["lrgs_password"]}\n')
        
        prod.write('\n')
        prod.write(f'TIMEZONE_NAME={form.cleaned_data["timezone_name"].strip()}\n')
        prod.write(f'TIMEZONE_OFFSET={form.cleaned_data["timezone_offset"]}\n')

        prod.write('\n')
        prod.write(f'MAP_LATITUDE={form.cleaned_data["map_latitude"]}\n')
        prod.write(f'MAP_LONGITUDE={form.cleaned_data["map_longitude"]}\n')
        prod.write(f'MAP_ZOOM={form.cleaned_data["map_zoom"]}\n')

        prod.write('\n')
        prod.write(f'SPATIAL_ANALYSIS_INITIAL_LATITUDE={form.cleaned_data["spatial_analysis_initial_latitude"]}\n')
        prod.write(f'SPATIAL_ANALYSIS_INITIAL_LONGITUDE={form.cleaned_data["spatial_analysis_initial_longitude"]}\n')
        prod.write(f'SPATIAL_ANALYSIS_FINAL_LATITUDE={form.cleaned_data["spatial_analysis_final_latitude"]}\n')
        prod.write(f'SPATIAL_ANALYSIS_FINAL_LONGITUDE={form.cleaned_data["spatial_analysis_final_longitude"]}\n')

        # SURFACE production version
        prod.write(f"\nSURFACE_CDMS_VERSION={normalize_surface_version(get_surface_version())}\n\n")

        # writing a variable called transmit_wis2_regional and transmit_wis2_local if the options are filled in
        # Check if wis2box_topic_hierarchy has content (after stripping whitespace)
        topic_hierarchy_entered = bool(form.cleaned_data.get("wis2box_topic_hierarchy", "").strip())

        # # Check if regional fields have content (after stripping whitespace)
        # regional_fields_filled = all(
        #     form.cleaned_data.get(field, "").strip() for field in ["wis2box_user_regional", "wis2box_password_regional", "wis2box_endpoint_regional"]
        # )

        # # Check if local fields have content (after stripping whitespace)
        # local_fields_filled = all(
        #     form.cleaned_data.get(field, "").strip() for field in ["wis2box_user_local", "wis2box_password_local", "wis2box_endpoint_local"]
        # )

        # # Set enable flags based on conditions
        # enable_wis2box_regional = "true" if topic_hierarchy_entered and regional_fields_filled else "false"
        # enable_wis2box_local = "true" if topic_hierarchy_entered and local_fields_filled else "false"

        # # Write to file
        # prod.write(f'\nENABLE_WIS2BOX_REGIONAL={enable_wis2box_regional}\n')
        # prod.write(f'ENABLE_WIS2BOX_LOCAL={enable_wis2box_local}\n')

        # Write other fields
        # prod.write(f'\nWIS2BOX_USER_REGIONAL={form.cleaned_data["wis2box_user_regional"]}\n')
        # prod.write(f'WIS2BOX_PASSWORD_REGIONAL={form.cleaned_data["wis2box_password_regional"]}\n')
        # prod.write(f'WIS2BOX_ENDPOINT_REGIONAL={form.cleaned_data["wis2box_endpoint_regional"]}\n')

        # prod.write(f'\nWIS2BOX_USER_LOCAL={form.cleaned_data["wis2box_user_local"]}\n')
        # prod.write(f'WIS2BOX_PASSWORD_LOCAL={form.cleaned_data["wis2box_password_local"]}\n')
        # prod.write(f'WIS2BOX_ENDPOINT_LOCAL={form.cleaned_data["wis2box_endpoint_local"]}\n')

        prod.write(f'SURFACE_SECRET_ENCRYPTION_KEY={form.cleaned_data["surface_encryption_key"]}\n')
        prod.write(f'SURFACE_SECRET_KEY={form.cleaned_data["surface_secret_key"]}\n')
        prod.write(f'SURFACE_DB_PASSWORD={form.cleaned_data["surface_database_password"]}\n')
        prod.write(f'POSTGRES_PASSWORD={form.cleaned_data["surface_database_password"]}\n')

        prod.write(f'\nWIS2BOX_TOPIC_HIERARCHY={form.cleaned_data["wis2box_topic_hierarchy"]}\n')


# used to write out vars to .env
def write_out_env(form):
    # write out surface variables
    with open(env_file_path, 'w') as ef:
        # write SURFACE port
        ef.write(f'NGINX_PORT={form.cleaned_data["surface_port"]}\n')


def write_out_host_connection_details(form, install_type):
    # write out remote host connection details 
    if install_type.install_type == 'remote':
        
        # Read the contents of the hosts file
        with open(hosts_file_path, 'r') as file:
            lines = file.readlines()

        # Find the index of the [remote] section
        remote_index = None
        for index, line in enumerate(lines):
            if line.strip() == '[remote]':
                remote_index = index
                break

        # If the [remote] section is found, modify the content
        if remote_index is not None:
            # Keep everything before the [remote] section and add the new content
            new_lines = lines[:remote_index + 1]
            new_lines.append(f'\n{form.cleaned_data["host"].strip()}')

            # Write the modified contents back to the file
            with open(hosts_file_path, 'w') as file:
                file.writelines(new_lines)

        # write out remote connection password to the connection password file
        with open(connection_password_file_path, 'w') as connection_password_file:
            connection_password_file.write(form.cleaned_data["remote_connect_password"])

        # write root password to the sudo password file
        with open(sudo_password_file_path, 'w') as sudo_password_file:
            sudo_password_file.write(form.cleaned_data["root_password"])

    else:

        # on local installs write out a misc value to the connection password file
        with open(connection_password_file_path, 'w') as connection_password_file:
            connection_password_file.write('connection_password')

        # write root password to the sudo password file
        with open(sudo_password_file_path, 'w') as sudo_password_file:
            # path to where local sudo password is stored
            with open(local_sudo_password_path, 'r') as local_sudo_password:
                # write sudo password out
                sudo_password_file.write(local_sudo_password.read())


def process_form(form, install_type):

    # read username from file
    with open(os.path.join(project_dir, 'env', 'user'), 'r') as file_object:
      # Read the entire file content into a string
      username = file_object.read().strip()

    if install_type.install_type == "remote":
        # modify ansible cfg file with the root username
        replace_text_in_file(os.path.join(project_dir, 'project', 'ansible.cfg'), f'become_user={username}', 'become_user=root')
    else:
        # modify ansible cfg file with the current username
        replace_text_in_file(os.path.join(project_dir, 'project', 'ansible.cfg'), 'become_user=root', f'become_user={username}')

    write_out_host_connection_details(form, install_type)

    write_out_surface_variables(form)

    write_out_production_variables(form)

    write_out_env(form)

    # set the required playbook file
    if install_type.install_type == 'remote':
        playbook_name = 'remote_install_surface.yml' # for remote installations
    else:
        playbook_name = 'install_surface.yml' # for local installations

    return project_dir, playbook_name
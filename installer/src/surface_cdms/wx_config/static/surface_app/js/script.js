// Globals
var map = null;

// Automatically populate timezone based on the users location
// document.addEventListener("DOMContentLoaded", function() {
//     // Detect the user's timezone name using Moment.js
//     var timezoneName = moment.tz.guess();

//     // Calculate the timezone offset in minutes
//     var timezoneOffsetMinutes = moment.tz(timezoneName).utcOffset();

//     // Set the form fields with the detected values
//     document.querySelector('[name="timezone_name"]').value = timezoneName;
//     document.querySelector('[name="timezone_offset"]').value = timezoneOffsetMinutes;
// });


// Show or hide the backup data file path input based on the "Start with Backup data" choice
const backupDataPath = document.getElementById('backup-data-path');
const startWithBackupRadioButtons = document.querySelectorAll('input[name="with_data"]');

// Set the initial visibility of the backup data file path based on the default value
const initialBackupValue = document.querySelector('input[name="with_data"]:checked').value;
backupDataPath.style.display = initialBackupValue === 'yes' ? 'block' : 'none';


// Add event listeners to radio buttons
startWithBackupRadioButtons.forEach(input => {
    input.addEventListener('change', function() {
        if (this.value === 'yes') {
        backupDataPath.style.display = 'block';
        } else {
        backupDataPath.style.display = 'none';
        }
    });
});


// Function to initialize the map
function initializeMap(var_lat, var_lng, var_zoom) {
    // Proper removal of the previous map
    if (map) {
        map.off();      // remove all event listeners
        map.remove();   // fully destroy it
    }

    map = L.map('initial-map').setView([var_lat, var_lng], var_zoom);

    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 15,
        attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    var marker;

    // set the marker on the map initially
    if (marker) {
        marker.setLatLng([var_lat, var_lng]);
    } else {
        marker = L.marker([var_lat, var_lng]).addTo(map);
    }

    // set a marker on map clicks
    function onMapClick(e) {
        if (marker) {
            marker.setLatLng(e.latlng);
        } else {
            marker = L.marker(e.latlng).addTo(map);
        }
        document.querySelector('[name="map_latitude"]').value = e.latlng.lat;
        document.querySelector('[name="map_longitude"]').value = e.latlng.lng;
    }

    map.on('click', onMapClick);

    // Add event listener to update map zoom level
    map.on('zoomend', function() {
        var zoomLevel = map.getZoom(); // Get the current zoom level of the map
        document.querySelector('[name="map_zoom"]').value = zoomLevel; // Set the value of the input field
    });

    // Get the zoom element
    const zoomElement = document.getElementById('zoomField');

    // Add an event listener to the input element
    zoomElement.addEventListener('keypress', function(event) {

        if (event.key == "Enter") {
            const zoomValue = event.target.value; // Get the current value of the input element

            map.setZoom(zoomValue); // Set the zoom level of the map when user updates the zoom form
        }
        
    });
}


// Function to scroll to the bottom of the page
function scrollToBottom() {
    window.scrollTo({
        top: document.body.scrollHeight,
        behavior: 'smooth'
    });
}

// Function to scroll to the top of the page
function scrollToTop() {
    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}


// Logic for hiding and showing passwords
const passwordInputs = document.querySelectorAll(".password-field input[type='password']");
const toggleButtons = document.querySelectorAll(".password-field i");
toggleButtons.forEach((button, index) => {
    button.addEventListener("click", function() {
        const passwordInput = passwordInputs[index];
        if (passwordInput.type === "password") {
        passwordInput.type = "text";
        button.textContent = " Hide Password";
        button.classList.remove("fa-eye")
        button.classList.add("fa-eye-slash")
        } else {
        passwordInput.type = "password";
        button.textContent = " Show Password";
        button.classList.remove("fa-eye-slash")
        button.classList.add("fa-eye")
        }
    });
});


// next and continue buttons
let currentTab = 0;
const tabs = document.querySelectorAll('.tabcontent');
const tabLinks = document.querySelectorAll('.tablinks');
document.addEventListener('DOMContentLoaded', () => {
    showTab(currentTab);
});

// logic to display the different tabs
function showTab(n) {
    tabs.forEach((tab, index) => {
        tab.style.display = (index === n) ? 'block' : 'none';
    });
    tabLinks.forEach((tabLink, index) => {
        tabLink.className = tabLink.className.replace(' active', '');
        if (index === n) tabLink.className += ' active';
    });
    document.querySelector('.btn-back').style.display = (n === 0) ? 'none' : '';
    document.querySelector('.btn-continue').style.display = (n === tabs.length - 1) ? 'none' : '';

    // Get all elements with the ID 'next-continue-btn'
    var continueBtn = document.getElementById('next-continue-btn');

    if (currentTab == 0) {
        continueBtn.classList.remove('next-btn-class');
        continueBtn.classList.add('btn-continue-class');
    } else {
        continueBtn.classList.remove('btn-continue-class');
        continueBtn.classList.add('next-btn-class');
    }

    // Get all elements with the ID 'submit-btn'
    var submitBtn = document.getElementById('submitBtn');

    if (currentTab == 4 && check_filled_fields()) {
        submitBtn.classList.remove('hide');
    } else {
        submitBtn.classList.add('hide');
    }

    // copying form values to the summary page when the user gets to the summary page
    if (currentTab == 4) {
        const formFields = [
                            { id: 'surface_repo_path', summaryId: 'summary4' },
                            // { id: 'data_path', summaryId: 'summary5' },
                            { id: 'admin', summaryId: 'summary6' },
                            { id: 'admin_password', summaryId: 'summary7' },
                            { id: 'admin_email', summaryId: 'summary8' },
                            { id: 'map_latitude', summaryId: 'summary9' },
                            { id: 'map_longitude', summaryId: 'summary10' },
                            { id: 'map_zoom', summaryId: 'summary11' },
                            { id: 'spatial_analysis_initial_latitude', summaryId: 'summary12' },
                            { id: 'spatial_analysis_initial_longitude', summaryId: 'summary13' },
                            { id: 'spatial_analysis_final_latitude', summaryId: 'summary14' },
                            { id: 'spatial_analysis_final_longitude', summaryId: 'summary15' },
                            { id: 'wis2box_topic_hierarchy', summaryId: 'summary16' },
                            { id: 'surface_encryption_key', summaryId: 'summary17' },
                            { id: 'selected_country', summaryId: 'summary18' },
                            { id: 'surface_port', summaryId: 'summary19' },
                            { id: 'surface_database_password', summaryId: 'summary20' },
                            { id: 'surface_secret_key', summaryId: 'summary21' },
                        ];

        // "{% if install_type == 'remote' %}"
        //     formFields.push(
        //                     { id: 'host', summaryId: 'summary1' }, 
        //                     { id: 'remote_connect_password', summaryId: 'summary2' }, 
        //                     { id: 'root_password', summaryId: 'summary3' },
        //                 )
        // "{% endif %}"

        formFields.forEach(field => {
        const inputField = document.querySelector(`[name="${field.id}"]`);

        if (inputField) {
            document.getElementById(field.summaryId).value = inputField.value;
        }
        });
    }

}

// facilitate clicking the tab headers to change tabs
function selectTab(tab_id) {
    currentTab = tab_id;

    showTab(currentTab);

}

// control for the next button
function nextTab() {
if (currentTab < tabs.length - 1) {
    currentTab++;

    showTab(currentTab);
}
}

// control for the previous button
function prevTab() {
    if (currentTab > 0) {
        currentTab--;

        showTab(currentTab);
    }
}

// check form completion, if completed show the submit button
function check_filled_fields() {
    // reuquired entries
    var surface_install_path_entry = document.querySelector("#id_surface_repo_path").value;
    var encryption_key_entry = document.querySelector("#id_surface_encryption_key").value;
    var admin_name_entry = document.querySelector("#id_admin").value;
    var admin_email_entry = document.querySelector("#id_admin_email").value;
    var admin_password_entry = document.querySelector("#id_admin_password").value;
    var timezone_name_entry = document.querySelector("#id_timezone_name").value;
    var timezone_offset_entry = document.querySelector("#id_timezone_offset").value;
    var map_lat_entry = document.querySelector("#id_map_latitude").value;
    var map_lng_entry = document.querySelector("#id_map_longitude").value;
    var map_zoom_entry = document.querySelector("#zoomField").value;
    var spatial_init_lat_entry = document.querySelector("#id_spatial_analysis_initial_latitude").value;
    var spatial_init_lng_entry = document.querySelector("#id_spatial_analysis_initial_longitude").value;
    var spatial_fin_lat_entry = document.querySelector("#id_spatial_analysis_final_latitude").value;
    var spatial_fin_lng_entry = document.querySelector("#id_spatial_analysis_final_longitude").value;
    var topic_hierarchy_entry = document.querySelector("#id_wis2box_topic_hierarchy").value;
    var selected_country_entry = document.querySelector("#id_selected_country").value;
    var lrgs_username_entry = document.querySelector("#id_lrgs_user").value;
    var lrgs_password_entry = document.querySelector("#id_lrgs_password").value;
    var surface_port_entry = document.querySelector("#id_surface_port").value;
    var surface_database_password_entry = document.querySelector("#id_surface_database_password").value;
    var surface_secret_key_entry = document.querySelector("#id_surface_secret_key").value;

    // remote install mandatory entries
    var remote_host_entry = "";
    var remote_host_password = "";
    var remote_host_conn_password = ""
    var remote_host_root_password = "";

    // optional entries
    var dump_file_path_entry = document.querySelector("#id_data_path").value;
    var dump_ftp_host_entry = document.querySelector("#id_dump_ftp_host").value;
    var dump_ftp_port_entry = document.querySelector("#id_dump_ftp_port").value;
    var dump_ftp_username_entry = document.querySelector("#id_dump_ftp_username").value;
    var dump_ftp_password_entry = document.querySelector("#id_dump_ftp_password").value;
    var dump_ftp_dump_path_entry = document.querySelector("#id_dump_ftp_dump_path").value;
    
    // enable lrgs option
    var enable_lrgs_toggle = document.getElementById("toggle-lrgs").checked;

    // enable ftp pull option
    var enable_ftp_toggle = document.getElementById("toggle-ftp").checked;

    // local / remote install type option
    var local_install = true;
    if (document.querySelector("#id_host")) {
        var local_install = false;

        // remote install mandatory entries
        var remote_host_entry = document.querySelector("#id_host").value;
        var remote_host_conn_password = document.querySelector("#id_remote_connect_password").value;
        var remote_host_root_password = document.querySelector("#id_root_password").value;
    }

    // backup data option
    var backup_data_option = true;
    if (document.querySelector(`input[name="with_data"]:checked`).value == "no") {
        backup_data_option = false;
    }


    // Ensure all requred information is filled
    if(encryption_key_entry && admin_name_entry && admin_email_entry && admin_password_entry && 
        timezone_name_entry && timezone_offset_entry && map_lat_entry && map_lng_entry && 
        map_zoom_entry && spatial_init_lat_entry && spatial_init_lng_entry && spatial_fin_lat_entry && 
        spatial_fin_lng_entry && topic_hierarchy_entry && selected_country_entry && surface_install_path_entry &&
        surface_database_password_entry && surface_port_entry && surface_secret_key_entry ) 
    {
        // check if lrgs option has been enabled. If it has, confirm the lrgs user name and lrgs password are filled
        if (enable_lrgs_toggle) {
            if (!lrgs_username_entry || !lrgs_password_entry) {
                return false;
            }
        }

        // check unique remote install options, if remote install option has been selected.
        if (!local_install) {
            if (!remote_host_entry || !remote_host_conn_password || !remote_host_root_password) {

                return false;
   
            }
        }

        // check for options related to the backup data options
        if (backup_data_option && !enable_ftp_toggle) {
            // check that the data path has been added if local install and backup data option has been set to "yes"
            if (!dump_file_path_entry) {
                return false
            }
        }

        // check if ftp option has been enabled. If it has, confirm the ftp details
        if (enable_ftp_toggle) {
            if (!dump_ftp_host_entry || !dump_ftp_port_entry || !dump_ftp_username_entry || !dump_ftp_password_entry || !dump_ftp_dump_path_entry) {
                return false;
            }
        }

        return true;
    }


    return false;
}


// JavaScript to toggle visibility of the LRGS details div
document.getElementById("toggle-lrgs").addEventListener("change", function() {
    var detailsDiv = document.getElementById("lrgs-details");
    if (this.checked) {
        detailsDiv.style.display = "block";
    } else {
        detailsDiv.style.display = "none";

        // reset the lrgs username and password when the option is disabled
        document.querySelector("#id_lrgs_user").value = "";
        document.querySelector("#id_lrgs_password").value = "";
    }
});


// JavaScript to toggle visibility of the retrieve dump via FTP div
document.getElementById("toggle-ftp").addEventListener("change", function() {
    var FTPdetailsDiv = document.getElementById("ftp-details");
    var ManDetailsDiv = document.getElementById("manual-dump-details");

    if (this.checked) {
        FTPdetailsDiv.style.display = "block";
        ManDetailsDiv.style.display = "none";

        // reset the data dump file option
        document.querySelector("#id_data_path").value = "";
    } else {
        FTPdetailsDiv.style.display = "none";
        ManDetailsDiv.style.display = "block";

        // reset the ftp details when the option is disabled
        document.querySelector("#id_dump_ftp_host").value = "";
        document.querySelector("#id_dump_ftp_port").value = "";
        document.querySelector("#id_dump_ftp_username").value = "";
        document.querySelector("#id_dump_ftp_password").value = "";
        document.querySelector("#id_dump_ftp_dump_path").value = "";
    }
});


// Fxn to generate the surface encryption key
function generateEncryptionKey() {
    fetch('gen-key/')
    .then(response => response.json())
    .then(data => {
        if (data.key) {
            document.querySelector("#id_surface_encryption_key").value = data.key;
        } else {
            alert("Failed to generate key.");
        }
    })
    .catch(error => console.error("Error fetching encryption key:", error));
}

// Fxn to generate the surface database password
function generateSecretKey() {
    fetch('gen-sec-key/')
    .then(response => response.json())
    .then(data => {
        if (data.key) {
            document.querySelector("#id_surface_secret_key").value = data.key;
        } else {
            alert("Failed to generate password.");
        }
    })
    .catch(error => console.error("Error fetching generated key:", error));
}

// Fxn to generate the surface database password
function generateDatabasePassword() {
    fetch('gen-pwd/')
    .then(response => response.json())
    .then(data => {
        if (data.pwd) {
            document.querySelector("#id_surface_database_password").value = data.pwd;
        } else {
            alert("Failed to generate password.");
        }
    })
    .catch(error => console.error("Error fetching generated password:", error));
}

// Fxn to reset the population details
function reset_populate_details() {
    // if the country selector is set to blank reset all country options
    // topic heirarchy
    document.querySelector("#id_wis2box_topic_hierarchy").value = '';

    // timezone information
    document.querySelector("#id_timezone_name").value = '';
    document.querySelector("#id_timezone_offset").value = '';

    // map details
    document.querySelector("#id_map_latitude").value = '';
    document.querySelector("#id_map_longitude").value = '';
    document.querySelector("#zoomField").value = '';

    // spatial analysis details
    document.querySelector("#id_spatial_analysis_initial_latitude").value = '';
    document.querySelector("#id_spatial_analysis_initial_longitude").value = '';
    document.querySelector("#id_spatial_analysis_final_latitude").value = '';
    document.querySelector("#id_spatial_analysis_final_longitude").value = '';
}

// Fxn to retrieve & fill country details country
function retrieve_populate_details(iso3_code) {
    fetch(`retr-details/?iso3_code=${iso3_code}`)
    .then(response => response.json())
    .then(data => {
        if (data) {
            // set the topic heirarchy
            document.querySelector("#id_wis2box_topic_hierarchy").value = data.topic_hierarchy;

            // timezone information
            document.querySelector("#id_timezone_name").value = data.timezone_name;
            document.querySelector("#id_timezone_offset").value = data.timezone_offset;

            // map details
            document.querySelector("#id_map_latitude").value = data.country_center_lat;
            document.querySelector("#id_map_longitude").value = data.country_center_lng;
            document.querySelector("#zoomField").value = parseInt(data.map_zoom);

            // spatial analysis details
            document.querySelector("#id_spatial_analysis_initial_latitude").value = data.spatial_analysis.INITIAL_LATITUDE;
            document.querySelector("#id_spatial_analysis_initial_longitude").value = data.spatial_analysis.INITIAL_LONGITUDE;
            document.querySelector("#id_spatial_analysis_final_latitude").value = data.spatial_analysis.FINAL_LATITUDE;
            document.querySelector("#id_spatial_analysis_final_longitude").value = data.spatial_analysis.FINAL_LONGITUDE;

            initializeMap(parseFloat(data.country_center_lat), parseFloat(data.country_center_lng), parseInt(data.map_zoom)); // re-initialeze the map with the updated data

        } else {
            alert("Failed to retrieving country details.");
        }
    })
    .catch(error => console.error("Error fetching encryption key country details", error));
}

// get csrftoken
function getCookie(name) {
  let cookieValue = null;
  if (document.cookie && document.cookie !== "") {
    const cookies = document.cookie.split(";");
    for (let cookie of cookies) {
      cookie = cookie.trim();
      if (cookie.startsWith(name + "=")) {
        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
        break;
      }
    }
  }
  return cookieValue;
}


// test the ftp connection to make sure the file exists on the ftp server
document.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("test-ftp-button");
    const result = document.getElementById("test-ftp-result");
    const spinner = document.querySelector(".ftp-spinner");

    button.addEventListener("click", () => {
        // Hide result and show spinner
        result.style.display = "none";
        spinner.style.display = "inline-block";

        // Gather form data
        const data = new FormData();
        data.append("host", document.getElementById("id_dump_ftp_host").value);
        data.append("port", document.getElementById("id_dump_ftp_port").value);
        data.append("username", document.getElementById("id_dump_ftp_username").value);
        data.append("password", document.getElementById("id_dump_ftp_password").value);
        data.append("dump_path", document.getElementById("id_dump_ftp_dump_path").value);

        // Send request
        fetch("test-ftp/", {
            method: "POST",
            headers: {
                "X-CSRFToken": getCookie("csrftoken"),
            },
            body: data,
        })
        .then(response => response.json())
        .then(data => {
            spinner.style.display = "none";
            result.textContent = data.message;
            result.style.color = data.status === "success" ? "green" : "red";
            result.style.display = "block";
        })
        .catch(() => {
            spinner.style.display = "none";
            result.textContent = "An error occurred";
            result.style.color = "red";
            result.style.display = "block";
        });
    });
});


// Map overlay elements
const container = document.getElementById('mapContainer');
const overlay = document.getElementById('mapOverlay');
const closeBtn = document.getElementById('closeEdit');
const mapEl = document.getElementById('initial-map');


// force map container and children to low z-index so overlay/close can sit above
function lowerMapInternalZIndices() {
    try {
    mapEl.style.zIndex = '1';
    // Try to lower any canvas or WebGL elements inside the map (mapbox/leaflet etc.)
    const inners = mapEl.querySelectorAll('canvas, .mapboxgl-canvas, .leaflet-pane, .leaflet-map-pane');
    inners.forEach(el => {
    el.style.zIndex = '1';
    });
    } catch (err) {
    // ignore - defensive
    console.warn('could not lower internal z-indices', err);
    }
}


// When user clicks the overlay: enable map interaction (enter "editing" mode)
overlay.addEventListener('click', (e) => {
    e.preventDefault();
    container.classList.add('editing');
    overlay.setAttribute('aria-hidden', 'true');
    closeBtn.setAttribute('aria-hidden', 'false');

    // ensure z-index adjustments were applied
    lowerMapInternalZIndices();

    // Move keyboard focus to the map container so keyboard navigation (if any) works.
    mapEl.focus?.();
});


// Close edit -> show overlay again
closeBtn.addEventListener('click', (e) => {
    e.preventDefault();
    container.classList.remove('editing');
    overlay.setAttribute('aria-hidden', 'false');
    closeBtn.setAttribute('aria-hidden', 'true');
});


// initial defensive z-index lowering in case the map init already added elements
lowerMapInternalZIndices();


// Close edit when clicking outside the map container
document.addEventListener('click', (e) => {
    const clickedInside = container.contains(e.target);
    if (!clickedInside && container.classList.contains('editing')) {
    container.classList.remove('editing');
    overlay.setAttribute('aria-hidden', 'false');
    closeBtn.setAttribute('aria-hidden', 'true');
    }
});
  
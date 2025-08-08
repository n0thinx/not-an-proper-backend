import os
import re
import json
from django.shortcuts import render, redirect
from django.conf import settings
from .forms import MultiFileUploadForm
from ntc_templates.parse import parse_output
from activity_log.utils import log_activity
from collections import OrderedDict, Counter
from django.http import FileResponse, Http404, HttpResponse
import logging # Add this line at the top of your file if not already present.

# Configure logging if not already configured (optional, but good practice)
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


# --- Global Configurations ---
# Set NTC_TEMPLATES_DIR environment variable to point to your parser_app/templates directory
os.environ["NTC_TEMPLATES_DIR"] = os.path.join(settings.BASE_DIR, "parser_app", "templates")
ALLOWED_EXTENSIONS = [".txt", ".log"]

# --- Platform Detection Patterns ---
env_patterns = OrderedDict([
    ("huawei_vrp", (r"(Huawei Versatile Routing Platform|VRP \(R\))", r"display")),
    ("huawei_yunshan", (r"Huawei YunShan OS", r"display")),
    ("cisco_ios", (r"Cisco IOS", r"show")),
    ("aruba_aoscx", (r"ArubaOS-CX", r"show")),
])

# --- TextFSM Templates Mapping per Platform and Command ---
textfsm_templates = {
    "cisco_ios": {
        "show version": "show_version",
        "show inventory": "show_inventory",
        "show interfaces": "show_interfaces",
        "show processes memory sorted": "show_processes_memory_sorted",
    },
    "aruba_aoscx": {
        "show system": "show_system",
        "show inventory": "show_inventory",
        "show interface": "show_interface",
    },
    "huawei_vrp": {
        "display version": "display_version",
        "display interface": "display_interface",
    },
    "huawei_yunshan": {
        "display version": "display_version",
        "display interface": "display_interface",
    },
}

# Cisco-specific CPU patterns (regex parsing from 'show processes cpu history')
CISCO_CPU_START_REGEX = 'last 60 minutes'
CISCO_CPU_END_REGEX = 'last 72 hours'

def detect_platform(text):
    """Detect platform from the full file content with both platform marker and command keyword."""
    for platform_key, (platform_pattern, required_command_pattern) in env_patterns.items():
        if re.search(platform_pattern, text, re.IGNORECASE):
            if re.search(required_command_pattern, text, re.IGNORECASE):
                return platform_key
    return "unknown"

def parse_command(platform, command, data):
    """Parses a given command output using NTC templates for the specified platform."""
    try:
        return parse_output(platform=platform, command=command, data=data)
    except Exception as e:
        logger.warning(f"Failed to parse command '{command}' for platform '{platform}': {e}")
        return []

def download_json(request):
    """Allows authenticated users to download the parsed JSON output."""
    if not request.user.is_authenticated:
        return redirect("/login")

    user_folder = os.path.join(settings.MEDIA_ROOT, request.user.username)
    json_filename = os.path.join(user_folder, "parsed_output.json")

    logger.debug(f"Checking for file at: {json_filename}")

    if os.path.exists(json_filename):
        json_file = open(json_filename, 'rb')
        return FileResponse(json_file, as_attachment=True, filename='parsed_output.json')
    else:
        logger.error("JSON file not found.")
        raise Http404("JSON file not found.")

def extract_cisco_cpu_usage(text):
    """
    Extracts Cisco IOS CPU usage data (max and average) from 'show processes cpu history'
    using regex parsing.
    """
    cpu_data = {"cpu_max": "N/A", "cpu_avg": "N/A"}

    find_cpu = re.search(CISCO_CPU_START_REGEX + '(.*?)' + CISCO_CPU_END_REGEX, text, re.DOTALL)

    if find_cpu:
        cpu_usage_values = []
        cpu_history_section = (find_cpu.group(1).split("\n", 2)[-1]).rsplit("\n", 13)[0]

        cpu_first_row = cpu_history_section.splitlines()[-2]
        cpu_second_row = cpu_history_section.splitlines()[-1]

        arr_first_row = list(cpu_first_row[4:])
        arr_second_row = list(cpu_second_row[4:])

        if not arr_first_row and arr_second_row:
            cpu_usage_values = [c.strip() for c in arr_second_row if c.strip()]
        elif arr_first_row and arr_second_row:
            for i in range(min(len(arr_first_row), len(arr_second_row))):
                combined_char = arr_first_row[i] + arr_second_row[i]
                cpu_usage_values.append(combined_char.strip())

        try:
            valid_cpu_values = [int(val) for val in cpu_usage_values if val.isdigit()]
            if valid_cpu_values:
                cpu_data["cpu_max"] = str(max(valid_cpu_values))
            else:
                cpu_data["cpu_max"] = "No numeric CPU max found"
        except ValueError:
            cpu_data["cpu_max"] = "Error parsing CPU max"
            logger.warning(f"Error converting Cisco CPU max value to int: {cpu_usage_values}")

        cpu_row_avg_section = ((find_cpu.group(1).split("\n", 2)[-1]).rsplit("\n", 3)[0]).splitlines()[-10:]
        avg_raw_line = [i for i in cpu_row_avg_section if '#' in i]

        if avg_raw_line:
            extracted_avg = re.sub("[^0-9]", "", avg_raw_line[0])
            try:
                numeric_avg = int(extracted_avg)
                if numeric_avg < 10:
                    cpu_data["cpu_avg"] = "1"
                else:
                    cpu_data["cpu_avg"] = str(numeric_avg)
            except ValueError:
                cpu_data["cpu_avg"] = "Error parsing average CPU"
                logger.warning(f"Error converting Cisco average CPU value to int: {extracted_avg}")
        else:
            cpu_data["cpu_avg"] = "1"
    else:
        cpu_data["cpu_max"] = 'Cannot find max CPU (regex failed)'
        cpu_data["cpu_avg"] = 'Cannot find average CPU (regex failed)'

    return cpu_data

def calculate_cisco_memory_usage(memory_data):
    """
    Calculates memory usage percentage from parsed Cisco 'show processes memory sorted' data.
    Assumes memory_data is a dictionary with 'memory_total' and 'memory_used'.
    """
    if not isinstance(memory_data, dict):
        return {"memory_usage_percent": "N/A"}

    try:
        memory_total = int(memory_data.get("memory_total", 0))
        memory_used = int(memory_data.get("memory_used", 0))
        if memory_total == 0:
            memory_percent = 0
        else:
            memory_percent = round((memory_used / memory_total) * 100, 2)
        return {"memory_usage_percent": memory_percent}
    except (KeyError, ValueError, TypeError) as e:
        logger.error(f"Error calculating Cisco memory usage: {e}, data: {memory_data}")
        return {"memory_usage_percent": "N/A"}

def process_aruba_system_data(system_data):
    """
    Processes parsed 'show system' output from Aruba to extract CPU and Memory.
    Assumes system_data is a dictionary (from parsed output list [0]).
    Expected keys in system_data for CPU: 'cpu_max', 'cpu_avg'.
    Expected keys in system_data for Memory: 'memory_usage_percent'.
    """
    result = {
        "cpu_max": "N/A",  # Initialize with N/A
        "cpu_avg": "N/A",  # Initialize with N/A
        "memory_usage_percent": "N/A" # Initialize with N/A
    }

    if not isinstance(system_data, dict):
        # logger.warning("Input system_data is not a dictionary.") # Uncomment if you have logger
        return result

    # --- Process CPU data ---
    # Attempt to get 'cpu_max' (current CPU utilization)
    if "cpu" in system_data:
        cpu_value = str(system_data["cpu"]).strip()
        if cpu_value.isdigit():
            result["cpu_max"] = cpu_value
            result["cpu_avg"] = cpu_value
        # else: # Uncomment if you have logger
        #     logger.debug(f"cpu_max is not a digit: '{cpu_max_value}'")

    # # Attempt to get 'cpu_avg' (average 5-minute CPU utilization)
    # if "cpu_avg" in system_data:
    #     cpu_avg_value = str(system_data["cpu_avg"]).strip()
    #     if cpu_avg_value.isdigit():
    #         result["cpu_avg"] = cpu_avg_value
    #     # else: # Uncomment if you have logger
    #     #     logger.debug(f"cpu_avg is not a digit: '{cpu_avg_value}'")

    # --- Process Memory data ---
    # Attempt to get 'memory_usage_percent'
    if "memory_usage_percent" in system_data:
        memory_percent_value = str(system_data["memory_usage_percent"]).strip()
        if memory_percent_value.isdigit():
            result["memory_usage_percent"] = memory_percent_value
        # else: # Uncomment if you have logger
        #     logger.debug(f"memory_usage_percent is not a digit: '{memory_percent_value}'")

    return result


def process_huawei_cpu_data(cpu_data):
    """
    Processes parsed 'display cpu-usage' output from Huawei to extract CPU usage.
    Assumes cpu_data is a dictionary (from parsed output list [0]).
    Expected keys: 'cpu_usage_rate' or 'cpu_usage_average'.
    """
    result = {"cpu_avg": "N/A"}
    if not isinstance(cpu_data, dict):
        return result

    cpu_keys = ["cpu_usage_rate", "cpu_usage_average", "cpu_usage"]
    for key in cpu_keys:
        if key in cpu_data and str(cpu_data[key]).replace('.', '', 1).isdigit():
            try:
                cpu_val = int(float(cpu_data[key]))
                result["cpu_avg"] = str(cpu_val)
                break
            except ValueError:
                pass
    return result

def process_huawei_memory_data(memory_data):
    """
    Processes parsed 'display memory usage' output from Huawei to extract memory usage.
    Assumes memory_data is a dictionary (from parsed output list [0]).
    Expected keys: 'total_memory', 'used_memory'.
    """
    result = {"memory_usage_percent": "N/A"}
    if not isinstance(memory_data, dict):
        return result

    try:
        memory_total = int(memory_data.get("total_memory", memory_data.get("memory_total", 0)))
        memory_used = int(memory_data.get("used_memory", memory_data.get("memory_used", 0)))
        if memory_total > 0:
            memory_percent = round((memory_used / memory_total) * 100, 2)
            result["memory_usage_percent"] = memory_percent
    except (ValueError, TypeError) as e:
        logger.warning(f"Error processing Huawei memory data: {e}, data: {memory_data}")

    return result

def deduplicate_serial_and_hardware(data):
    """Recursively deduplicates 'serial' and 'hardware' lists within the parsed data."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in ["serial", "hardware"] and isinstance(value, list):
                seen = set()
                deduplicated_list = []
                for item in value:
                    if isinstance(item, dict):
                        item_hash = tuple(sorted(item.items()))
                        if item_hash not in seen:
                            seen.add(item_hash)
                            deduplicated_list.append(item)
                    elif item not in seen:
                        seen.add(item)
                        deduplicated_list.append(item)
                data[key] = deduplicated_list
            else:
                deduplicate_serial_and_hardware(value)
    elif isinstance(data, list):
        for item in data:
            deduplicate_serial_and_hardware(item)

def upload_file(request):
    """Handles file uploads, parses them, and stores the structured data."""
    if not request.user.is_authenticated:
        return redirect("/login")

    user_folder = os.path.join(settings.MEDIA_ROOT, request.user.username)
    os.makedirs(user_folder, exist_ok=True)
    json_filename = os.path.join(user_folder, "parsed_output.json")

    if request.method == "POST":
        form = MultiFileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_files = request.FILES.getlist("files")
            parsed_results = {}

            for uploaded_file in uploaded_files:
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                if file_extension not in ALLOWED_EXTENSIONS:
                    logger.warning(f"Skipping unsupported file extension: {uploaded_file.name}")
                    continue

                file_path = os.path.join(user_folder, uploaded_file.name)
                with open(file_path, "wb") as f:
                    for chunk in uploaded_file.chunks():
                        f.write(chunk)
                logger.info(f"Saved uploaded file: {uploaded_file.name}")

                with open(file_path, "r", encoding="utf8", errors="ignore") as f:
                    raw_text_content = f.read()

                device_platform = detect_platform(raw_text_content)
                parsed_data_for_file = {}
                device_specific_cpu_mem_data = {"cpu_max": "N/A", "cpu_avg": "N/A", "memory_usage_percent": "N/A"}

                platform_specific_templates = textfsm_templates.get(device_platform, {})

                if not platform_specific_templates:
                    logger.warning(f"No TextFSM templates found for detected platform: '{device_platform}' for file '{uploaded_file.name}'")
                    parsed_results[uploaded_file.name] = {
                        "model": device_platform,
                        "data": {"Error": f"No templates configured for {device_platform}"},
                    }
                    continue

                # --- Step 1: Parse all commands using TextFSM for the detected platform ---
                for command, template_name in platform_specific_templates.items():
                    parsed_output = parse_command(device_platform, command, raw_text_content)
                    parsed_data_for_file[command] = parsed_output
                    logger.debug(f"Parsed '{command}' for {uploaded_file.name}: {parsed_output}")

                # --- Step 2: Extract/Calculate CPU & Memory based on platform and parsed data ---
                if device_platform == "cisco_ios":
                    # Cisco CPU: Use regex on raw text
                    cisco_cpu_results = extract_cisco_cpu_usage(raw_text_content)
                    device_specific_cpu_mem_data.update(cisco_cpu_results)

                    # Cisco Memory: Use TextFSM parsed data then calculate
                    memory_list = parsed_data_for_file.get("show processes memory sorted", [])
                    if memory_list and isinstance(memory_list, list) and memory_list[0]:
                        calculated_mem = calculate_cisco_memory_usage(memory_list[0])
                        device_specific_cpu_mem_data["memory_usage_percent"] = calculated_mem.get("memory_usage_percent")
                        parsed_data_for_file["show processes memory sorted"][0].update(calculated_mem)

                elif device_platform == "aruba_aoscx":
                    # Aruba CPU & Memory: Both from 'show system' TextFSM parsed data
                    system_list = parsed_data_for_file.get("show system", [])
                    if system_list and isinstance(system_list, list) and system_list[0]:
                        aruba_cpu_mem_results = process_aruba_system_data(system_list[0])
                        device_specific_cpu_mem_data.update(aruba_cpu_mem_results)
                        # Add or ensure this line exists: Update the original parsed data with the extracted values
                        parsed_data_for_file["show system"][0].update(aruba_cpu_mem_results)
                    # else: # Uncomment if you want logging for no system data
                    #     logger.warning("No valid 'show system' data found for aruba_aoscx.")

                elif device_platform == "huawei_vrp":
                    # Huawei CPU: From 'display cpu-usage' TextFSM parsed data
                    cpu_usage_list = parsed_data_for_file.get("display cpu-usage", [])
                    if cpu_usage_list and isinstance(cpu_usage_list, list) and cpu_usage_list[0]:
                        huawei_cpu_results = process_huawei_cpu_data(cpu_usage_list[0])
                        device_specific_cpu_mem_data.update(huawei_cpu_results)
                        parsed_data_for_file["display cpu-usage"][0].update(huawei_cpu_results)

                    # Huawei Memory: From 'display memory usage' TextFSM parsed data
                    memory_usage_list = parsed_data_for_file.get("display memory usage", [])
                    if memory_usage_list and isinstance(memory_usage_list, list) and memory_usage_list[0]:
                        huawei_mem_results = process_huawei_memory_data(memory_usage_list[0])
                        device_specific_cpu_mem_data.update(huawei_mem_results)
                        parsed_data_for_file["display memory usage"][0].update(huawei_mem_results)
                        
                elif device_platform == "huawei_yunshan":
                    # Huawei CPU: From 'display cpu-usage' TextFSM parsed data
                    cpu_usage_list = parsed_data_for_file.get("display cpu-usage", [])
                    if cpu_usage_list and isinstance(cpu_usage_list, list) and cpu_usage_list[0]:
                        huawei_cpu_results = process_huawei_cpu_data(cpu_usage_list[0])
                        device_specific_cpu_mem_data.update(huawei_cpu_results)
                        parsed_data_for_file["display cpu-usage"][0].update(huawei_cpu_results)

                    # Huawei Memory: From 'display memory usage' TextFSM parsed data
                    memory_usage_list = parsed_data_for_file.get("display memory usage", [])
                    if memory_usage_list and isinstance(memory_usage_list, list) and memory_usage_list[0]:
                        huawei_mem_results = process_huawei_memory_data(memory_usage_list[0])
                        device_specific_cpu_mem_data.update(huawei_mem_results)
                        parsed_data_for_file["display memory usage"][0].update(huawei_mem_results)

                # --- Step 3: Deduplicate serial/hardware and store combined CPU/Memory data ---
                deduplicate_serial_and_hardware(parsed_data_for_file)
                parsed_data_for_file["Calculated_CPU_Memory"] = device_specific_cpu_mem_data

                parsed_results[uploaded_file.name] = {
                    "model": device_platform,
                    "data": parsed_data_for_file,
                }

            uploaded_names = ", ".join([f.name for f in uploaded_files])
            log_activity(request.user, f"Uploaded files: {uploaded_names}")

            with open(json_filename, "w", encoding="utf-8") as json_file:
                json.dump(parsed_results, json_file, indent=4)

            return redirect("summary_view")

    else:
        form = MultiFileUploadForm()

    return render(request, "parser_app/upload.html", {"form": form})

def load_data(request):
    """Loads parsed data from the user's JSON file."""
    user_folder = os.path.join(settings.MEDIA_ROOT, request.user.username)
    json_file_path = os.path.join(user_folder, "parsed_output.json")

    if os.path.exists(json_file_path):
        with open(json_file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError as e:
                logger.error(f"Error decoding JSON file {json_file_path}: {e}")
                return {}
    return {}

def summary_view(request):
    """Displays a summary view for uploaded devices, including version information."""
    parsed_data = load_data(request)

    if not parsed_data:
        return redirect("upload_file")

    summary = {}
    for filename, details in parsed_data.items():
        device_platform = details.get("model", "unknown")
        version_data = {}

        version_list = []
        if device_platform == "cisco_ios":
            version_list = details.get("data", {}).get("show version", [])
        elif device_platform == "aruba_aoscx":
            version_list = details.get("data", {}).get("show system", [])
        elif device_platform == "huawei_vrp":
            version_list = details.get("data", {}).get("display version", [])
        elif device_platform == "huawei_yunshan":
            version_list = details.get("data", {}).get("display version", [])

        if version_list and isinstance(version_list, list) and version_list[0]:
            version_data = version_list[0]
            
            # OPTIONAL CLEANUP: Strip whitespace from string values
            # This is good practice as your JSON shows trailing spaces for hardware and uptime
            for key, value in version_data.items():
                if isinstance(value, str):
                    version_data[key] = value.strip()

        else:
            logger.warning(f"No valid version data found or parsed for {filename} (Platform: {device_platform})")
            version_data = {"parse_error": "No version data parsed or found"}

        version_data['platform_name'] = device_platform

        summary[filename] = version_data

    if summary and all(isinstance(val, dict) and 'parse_error' in val for val in summary.values()):
        return redirect("upload_file")

    return render(request, "parser_app/summary.html", {"summary": summary})

def cpu_memory_usage_view(request):
    """Displays combined CPU and Memory usage for all uploaded devices."""
    parsed_data = load_data(request)

    if not parsed_data:
        return redirect("upload_file")

    combined = {}

    for filename, details in parsed_data.items():
        calculated_data = details.get("data", {}).get("Calculated_CPU_Memory", {})

        combined[filename] = {
            "cpu_max": calculated_data.get("cpu_max", "N/A"),
            "cpu_avg": calculated_data.get("cpu_avg", "N/A"),
            "memory_usage_percent": calculated_data.get("memory_usage_percent", "N/A"),
        }

    if not any(entry.get("cpu_avg") != "N/A" or entry.get("memory_usage_percent") != "N/A" for entry in combined.values()):
        logger.warning("No CPU or Memory data found in any uploaded files for display.")
        return redirect("upload_file")

    return render(request, "parser_app/cpu_memory_usage.html", {"devices": combined})

def inventory_view(request):
    """Displays inventory information for uploaded devices, with optional hostname filtering."""
    parsed_data = load_data(request)
    hostname_filter = request.GET.get("hostname")

    filtered_data = {}
    for filename, details in parsed_data.items():
        if hostname_filter and hostname_filter != filename:
            continue

        device_platform = details.get("model")
        inventory = []
        if device_platform == "cisco_ios":
            inventory = details.get("data", {}).get("show inventory", [])
        elif device_platform == "aruba_aoscx":
            inventory = details.get("data", {}).get("show inventory", [])
        elif device_platform == "huawei_vrp":
            inventory = details.get("data", {}).get("display device", [])
        elif device_platform == "huawei_yunshan":
            inventory = details.get("data", {}).get("display device", [])

        filtered_data[filename] = inventory

    return render(request, "parser_app/inventory.html", {
        "inventory_data": filtered_data,
        "hostnames": list(parsed_data.keys()),
        "selected_hostname": hostname_filter
    })

def interfaces_view(request):
    """Displays interface information for uploaded devices, with optional hostname filtering and summary statistics."""
    parsed_data = load_data(request)
    hostname_filter = request.GET.get("hostname")

    filtered_data = {}
    link_status_counts = Counter()
    speed_counts = Counter()

    for filename, details in parsed_data.items():
        if hostname_filter and hostname_filter != filename:
            continue

        device_platform = details.get("model")
        interfaces = []
        if device_platform == "cisco_ios":
            interfaces = details.get("data", {}).get("show interfaces", [])
        elif device_platform == "aruba_aoscx":
            interfaces = details.get("data", {}).get("show interface", [])
        elif device_platform == "huawei_vrp":
            interfaces = details.get("data", {}).get("display interface", [])
        elif device_platform == "huawei_yunshan":
            interfaces = details.get("data", {}).get("display interface", [])

        filtered_data[filename] = interfaces

        for iface in interfaces:
            link_status = iface.get("link_status", iface.get("status", "unknown")).lower() or "unknown"
            speed = iface.get("speed", iface.get("bandwidth", "unknown")).lower() or "unknown"

            link_status_counts[link_status] += 1
            speed_counts[speed] += 1

    return render(request, "parser_app/interfaces.html", {
        "interface_data": filtered_data,
        "hostnames": list(parsed_data.keys()),
        "selected_hostname": hostname_filter,
        "link_status_labels": list(link_status_counts.keys()),
        "link_status_values": list(link_status_counts.values()),
        "speed_labels": list(speed_counts.keys()),
        "speed_values": list(speed_counts.values()),
    })
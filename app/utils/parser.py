import os
import re
import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from collections import OrderedDict, Counter
from ntc_templates.parse import parse_output

logger = logging.getLogger(__name__)

# Platform Detection Patterns
ENV_PATTERNS = OrderedDict([
    ("huawei_vrp", (r"(Huawei Versatile Routing Platform|VRP \(R\))", r"display")),
    ("huawei_yunshan", (r"Huawei YunShan OS", r"display")),
    ("cisco_ios", (r"Cisco IOS", r"show")),
    ("cisco_nxos", (r"Cisco Nexus Operating System|NX-OS", r"show")),
    ("aruba_aoscx", (r"ArubaOS-CX", r"show")),
])

# TextFSM Templates Mapping per Platform and Command
TEXTFSM_TEMPLATES = {
    "cisco_ios": {
        "show version": "show_version",
        "show inventory": "show_inventory",
        "show interfaces": "show_interfaces",
        "show processes memory sorted": "show_processes_memory_sorted",
        "show processes cpu history": "show_processes_cpu_history",
    },
    "cisco_nxos": {
        "show version": "show_version",
        "show inventory": "show_inventory",
        "show interface": "show_interface",
        "show system resources": "show_system_resources",
    },
    "aruba_aoscx": {
        "show system": "show_system",
        "show inventory": "show_inventory",
        "show interface": "show_interface",
    },
    "huawei_vrp": {
        "display version": "display_version",
        "display interface": "display_interface",
        "display cpu-usage": "display_cpu_usage",
        "display memory usage": "display_memory_usage",
        "display device": "display_device",
    },
    "huawei_yunshan": {
        "display version": "display_version",
        "display interface": "display_interface",
        "display cpu-usage": "display_cpu_usage",
        "display memory usage": "display_memory_usage",
        "display device": "display_device",
    },
}

# Cisco-specific CPU patterns
CISCO_CPU_START_REGEX = 'last 60 minutes'
CISCO_CPU_END_REGEX = 'last 72 hours'

def detect_platform(text: str) -> str:
    """Detect platform from the full file content with both platform marker and command keyword."""
    for platform_key, (platform_pattern, required_command_pattern) in ENV_PATTERNS.items():
        if re.search(platform_pattern, text, re.IGNORECASE):
            if re.search(required_command_pattern, text, re.IGNORECASE):
                return platform_key
    return "unknown"

def parse_command(platform: str, command: str, data: str) -> List[Dict[str, Any]]:
    """Parses a given command output using NTC templates for the specified platform."""
    try:
        return parse_output(platform=platform, command=command, data=data)
    except Exception as e:
        logger.warning(f"Failed to parse command '{command}' for platform '{platform}': {e}")
        return []

def extract_cisco_cpu_usage(text: str) -> Dict[str, str]:
    """Extract Cisco IOS CPU usage data from 'show processes cpu history'."""
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

def calculate_cisco_memory_usage(memory_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate memory usage percentage from parsed Cisco memory data."""
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

def process_aruba_system_data(system_data: Dict[str, Any]) -> Dict[str, str]:
    """Process parsed 'show system' output from Aruba to extract CPU and Memory."""
    result = {
        "cpu_max": "N/A",
        "cpu_avg": "N/A",
        "memory_usage_percent": "N/A"
    }

    if not isinstance(system_data, dict):
        return result

    if "cpu" in system_data:
        cpu_value = str(system_data["cpu"]).strip()
        if cpu_value.isdigit():
            result["cpu_max"] = cpu_value
            result["cpu_avg"] = cpu_value

    if "memory_usage_percent" in system_data:
        memory_percent_value = str(system_data["memory_usage_percent"]).strip()
        if memory_percent_value.isdigit():
            result["memory_usage_percent"] = memory_percent_value

    return result

def process_huawei_cpu_data(cpu_data: Dict[str, Any]) -> Dict[str, str]:
    """Process parsed 'display cpu-usage' output from Huawei to extract CPU usage."""
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

def process_huawei_memory_data(memory_data: Dict[str, Any]) -> Dict[str, str]:
    """Process parsed 'display memory usage' output from Huawei to extract memory usage."""
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

def deduplicate_serial_and_hardware(data: Any) -> None:
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

def parse_network_file(file_content: str, filename: str) -> Dict[str, Any]:
    """Parse network device file and return structured data."""
    device_platform = detect_platform(file_content)
    parsed_data_for_file = {}
    device_specific_cpu_mem_data = {
        "cpu_max": "N/A", 
        "cpu_avg": "N/A", 
        "memory_usage_percent": "N/A"
    }

    platform_specific_templates = TEXTFSM_TEMPLATES.get(device_platform, {})

    if not platform_specific_templates:
        logger.warning(f"No TextFSM templates found for detected platform: '{device_platform}' for file '{filename}'")
        return {
            "platform": device_platform,
            "data": {"Error": f"No templates configured for {device_platform}"},
            "filename": filename
        }

    # Parse all commands using TextFSM for the detected platform
    for command, template_name in platform_specific_templates.items():
        parsed_output = parse_command(device_platform, command, file_content)
        parsed_data_for_file[command] = parsed_output
        logger.debug(f"Parsed '{command}' for {filename}: {parsed_output}")

    # Extract/Calculate CPU & Memory based on platform and parsed data
    if device_platform == "cisco_ios":
        # Cisco CPU: Use regex on raw text
        cisco_cpu_results = extract_cisco_cpu_usage(file_content)
        device_specific_cpu_mem_data.update(cisco_cpu_results)

        # Cisco Memory: Use TextFSM parsed data then calculate
        memory_list = parsed_data_for_file.get("show processes memory sorted", [])
        if memory_list and isinstance(memory_list, list) and memory_list[0]:
            calculated_mem = calculate_cisco_memory_usage(memory_list[0])
            device_specific_cpu_mem_data["memory_usage_percent"] = calculated_mem.get("memory_usage_percent")
            parsed_data_for_file["show processes memory sorted"][0].update(calculated_mem)

    elif device_platform == "cisco_nxos":
        # Cisco NX-OS: Extract from system resources
        system_resources = parsed_data_for_file.get("show system resources", [])
        if system_resources and isinstance(system_resources, list) and system_resources[0]:
            sys_data = system_resources[0]
            if "cpu_usage_percent" in sys_data:
                device_specific_cpu_mem_data["cpu_avg"] = str(sys_data["cpu_usage_percent"])
                device_specific_cpu_mem_data["cpu_max"] = str(sys_data["cpu_usage_percent"])
            if "memory_usage_percent" in sys_data:
                device_specific_cpu_mem_data["memory_usage_percent"] = str(sys_data["memory_usage_percent"])

    elif device_platform == "aruba_aoscx":
        # Aruba CPU & Memory: Both from 'show system' TextFSM parsed data
        system_list = parsed_data_for_file.get("show system", [])
        if system_list and isinstance(system_list, list) and system_list[0]:
            aruba_cpu_mem_results = process_aruba_system_data(system_list[0])
            device_specific_cpu_mem_data.update(aruba_cpu_mem_results)
            parsed_data_for_file["show system"][0].update(aruba_cpu_mem_results)

    elif device_platform in ["huawei_vrp", "huawei_yunshan"]:
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

    # Deduplicate serial/hardware and store combined CPU/Memory data
    deduplicate_serial_and_hardware(parsed_data_for_file)
    parsed_data_for_file["Calculated_CPU_Memory"] = device_specific_cpu_mem_data

    return {
        "platform": device_platform,
        "data": parsed_data_for_file,
        "filename": filename
    }
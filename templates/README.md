# NTC Templates Directory

This directory contains TextFSM templates for parsing network device outputs.

The templates are organized by platform and command. The ntc-templates library will automatically discover templates placed in this directory when the `NTC_TEMPLATES_DIR` environment variable is set to point to this location.

## Supported Platforms

- cisco_ios
- cisco_nxos
- aruba_aoscx
- huawei_vrp
- huawei_yunshan

## Template Structure

Templates should follow the naming convention:
`{platform}_{command}.textfsm`

For example:
- `cisco_ios_show_version.textfsm`
- `aruba_aoscx_show_system.textfsm`
- `huawei_vrp_display_version.textfsm`

## Adding Custom Templates

1. Create a new TextFSM template file with the appropriate naming convention
2. Place it in this directory
3. The parser will automatically discover and use the template

For more information about TextFSM template syntax, visit:
https://github.com/google/textfsm/wiki/TextFSM
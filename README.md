# WODE-ISO-Carver
WODE ISO Carver is a digital forensics utility written in Python designed to recover Wii and GameCube ISO images from storage units formatted with the proprietary WFS (Wii File System). This format is commonly used by ODDE (Optical Disc Drive Emulators) hardware such as the WODE Jukebox and WiiKey Fusion.

# Overview
Standard Wii management tools (wit, wwt, Wii Backup Manager) typically fail to recognize these disks because they lack a standard partition table or a WBFS header. The WODE hardware writes ISO images as raw data blocks following a proprietary header (0xA55A). This script performs data carving to identify and extract these images based on internal volume signatures.

# Features
- Smart Data Carving: Identifies ISOs via magic numbers (0x5D1C9EA3 for Wii and 0xC2339F3D for GameCube).
- JSON Indexing: Scans the disk once and caches results in wode_index.json for instantaneous subsequent access.
- macOS Optimized: Utilizes rdisk nodes and diskutil for high-speed raw access and precise telemetry.
- Manual Mode: Direct extraction via specific byte offsets.
- CLI Telemetry: Real-time MB/s, ETA, and progress percentage.

# Requirements
- Python 3.10+
- Superuser Privileges: Required for raw block device access (/dev/rdisk).
- Environment: macOS or Linux.

# Usage
## 1. Identify the Source Disk
Locate the disk node (e.g., /dev/rdisk12). In macOS, always use the rdisk node for significantly higher I/O performance.

## 2. Standard Execution (Scan + Extract)
The script will index the disk, save the JSON cache, and prompt for selection.
```sudo python3 WODE-ISO-Carver.py --disk /dev/rdisk12 --dest "/path/to/destination/"```

## 3. Manual Offset Extraction
If the game offset is already known:
```sudo python3 WODE-ISO-Carver.py --offset 209715200 --id "ZeldaTP"```

## 4. Advanced CLI Flags
- ```--force-scan```: Ignores the existing JSON cache and re-scans the device.
- ```--skip-scan```: Only executes if a valid wode_index.json is found in the destination.

# Technical Specifications
The script identifies volumes by scanning for the following signatures:
| Platform | Magic Number (Hex) | Relative Offset | Standard Size |
| :--- | :--- | :--- | :--- |
| Wii | 5D 1C 9E A3 | 0x18 | 4,699,979,776 bytes |
| GameCube | C2 33 9F 3D | 0x1C | 1,459,978,240 bytes |

# Troubleshooting: The 75 b2 Pattern
If the initial sector dump reveals a repeating 75 b2 pattern, the SSD controller is likely in a Locked or Panic state. This is often resolved by a power cycle (physically reconnecting the USB bridge) to allow the controller to report the standard MBR (0xAA55).

# License
Distributed under the MIT License.

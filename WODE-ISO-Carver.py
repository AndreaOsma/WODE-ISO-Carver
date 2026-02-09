import os
import time
import sys
import shutil
import subprocess
import re
import json
import argparse

# --- SYSTEM CONFIGURATION ---
DEFAULT_DISK = ""
DEFAULT_DEST = "./extracted_games/"
WII_MAGIC = b"\x5D\x1C\x9E\xA3"
GC_MAGIC  = b"\xC2\x33\x9F\x3D"
WII_SIZE  = 4699979776 
GC_SIZE   = 1459978240
CHUNK_SIZE = 1024 * 1024 * 32 
SECTOR_SIZE = 512

def format_time(seconds):
    """Returns a formatted time string (HH:MM:SS)"""
    if seconds < 0: return "00:00:00"
    return time.strftime("%H:%M:%S", time.gmtime(seconds))

def get_macos_disk_size(disk_path):
    """Retrieves physical disk size using macOS diskutil"""
    try:
        standard_disk = disk_path.replace('rdisk', 'disk')
        cmd = ['diskutil', 'info', standard_disk]
        output = subprocess.check_output(cmd).decode('utf-8')
        match = re.search(r'Disk Size:.*?(\d+) Bytes', output)
        return int(match.group(1)) if match else 0
    except Exception:
        return 0

def extract_iso(disk_path, offset, size, dest_path):
    """Performs sector-aligned data extraction from block device"""
    print(f"[*] Extracting ISO image at offset {offset}...")
    try:
        with open(disk_path, "rb") as f:
            # Align seek to hardware sector boundaries for rdisk compatibility
            aligned_offset = (offset // SECTOR_SIZE) * SECTOR_SIZE
            diff = offset - aligned_offset
            
            f.seek(aligned_offset)
            if diff > 0:
                f.read(diff) # Discard alignment padding
                
            start_time = time.time()
            with open(dest_path, "wb") as out:
                written = 0
                while written < size:
                    to_read = min(CHUNK_SIZE, size - written)
                    data = f.read(to_read)
                    if not data: break
                    out.write(data)
                    written += len(data)
                    
                    elapsed = time.time() - start_time
                    speed = (written / (1024**2)) / elapsed if elapsed > 0 else 0
                    eta = (size - written) / (written / elapsed) if written > 0 else 0
                    
                    bar = "█" * int(25 * written // size)
                    sys.stdout.write(f"\r    [{bar:25s}] {(written/size)*100:6.2f}% | {speed:5.1f} MB/s | ETA: {format_time(eta)}")
                    sys.stdout.flush()
            print(f"\n[+] Extraction completed: {dest_path}")
    except Exception as e:
        sys.stderr.write(f"\n[!] Error during extraction: {e}\n")

def main():
    parser = argparse.ArgumentParser(description="WODE ISO Carver - Digital Forensics Tool for WFS Recovery")
    parser.add_argument("--disk", default=DEFAULT_DISK, help="Source block device (e.g., /dev/rdisk12)")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="Destination directory")
    parser.add_argument("--offset", type=int, help="Manual offset for direct extraction")
    parser.add_argument("--id", default="MANUAL", help="Game ID for manual mode")
    parser.add_argument("--force-scan", action="store_true", help="Ignore JSON cache and force full scan")
    parser.add_argument("--skip-scan", action="store_true", help="Abort if no JSON index is found")
    
    args = parser.parse_args()
    
    if not args.disk and args.offset is None:
        sys.stderr.write("[!] Error: No source disk specified. Use --disk or --offset.\n")
        sys.exit(1)

    if not os.path.exists(args.dest):
        os.makedirs(args.dest, exist_ok=True)

    index_file = os.path.join(args.dest, "wode_index.json")
    found_games = []

    if args.offset is not None:
        print(f"[*] MANUAL MODE: Target offset {args.offset}")
        target_file = os.path.join(args.dest, f"{args.id}_Dump.iso")
        extract_iso(args.disk, args.offset, WII_SIZE, target_file)
        return

    # --- CACHE MANAGEMENT ---
    if not args.force_scan and os.path.exists(index_file):
        print(f"[*] Loading cached index: {index_file}")
        try:
            with open(index_file, 'r') as jf:
                found_games = json.load(jf)
        except Exception as e:
            sys.stderr.write(f"[!] Warning: Failed to load cache. {e}\n")
    
    # --- INDEXING PHASE ---
    if not found_games and not args.skip_scan:
        print(f"[*] Initiating robust sector-aligned scan on {args.disk}...")
        total_size = get_macos_disk_size(args.disk)
        
        try:
            with open(args.disk, "rb") as f:
                offset = 0
                scan_start = time.time()
                while True:
                    remaining = total_size - offset if total_size > 0 else CHUNK_SIZE
                    if remaining <= 0: break
                    
                    current_chunk_size = min(CHUNK_SIZE, remaining)
                    current_pos = f.tell()
                    chunk = f.read(current_chunk_size)
                    if not chunk: break
                    
                    # Search for magic signatures within memory buffer
                    pos_wii = chunk.find(WII_MAGIC)
                    pos_gc = chunk.find(GC_MAGIC)
                    
                    if pos_wii != -1 or pos_gc != -1:
                        is_wii = (pos_wii != -1)
                        local_pos = pos_wii if is_wii else pos_gc
                        
                        relative_iso_start = local_pos - (24 if is_wii else 28)
                        iso_start = current_pos + relative_iso_start
                        
                        # In-memory metadata extraction to avoid unaligned I/O errors
                        try:
                            header = chunk[relative_iso_start : relative_iso_start+128]
                            gid = header[:6].decode('ascii', errors='ignore').strip()
                            gname = header[32:96].decode('ascii', errors='ignore').strip('\x00').strip()
                        except Exception:
                            gid, gname = "UNK", "Unknown"

                        found_games.append({
                            'offset': iso_start, 'id': gid, 'name': gname,
                            'type': 'WII' if is_wii else 'GC',
                            'size': WII_SIZE if is_wii else GC_SIZE
                        })
                        
                        # Skip ISO content and align to next hardware sector
                        next_pos = iso_start + (WII_SIZE if is_wii else GC_SIZE)
                        aligned_next = (next_pos // SECTOR_SIZE) * SECTOR_SIZE
                        
                        if total_size > 0 and aligned_next >= total_size: break
                        f.seek(aligned_next)
                        offset = aligned_next
                        continue

                    offset += len(chunk)
                    if total_size > 0:
                        elapsed = time.time() - scan_start
                        speed = offset / elapsed if elapsed > 0 else 1
                        eta = (total_size - offset) / speed
                        sys.stdout.write(f"\r    Indexing: {(offset/total_size)*100:6.2f}% | V: {speed/(1024**2):.1f} MB/s | ETA: {format_time(eta)}")
                        sys.stdout.flush()

                with open(index_file, 'w') as jf:
                    json.dump(found_games, jf, indent=4)
                print(f"\n[*] Index persistent storage updated.")
        except Exception as e:
            sys.stderr.write(f"\n[!] Critical scan error: {e}\n"); return
    elif args.skip_scan and not found_games:
        print("[*] Scan skipped by user. No cached data available.")
        return

    # --- SELECTION MENU ---
    if not found_games: return
    print("\n" + "="*65)
    print(f"{'INDEXED TITLES':^65}")
    print("="*65)
    for i, g in enumerate(found_games, 1):
        print(f"{i:2d}. [{g['type']}] {g['id']:6s} | {g['name']}")
    print("="*65)
    
    try:
        choice = input("\nEnter selection (ID, comma-separated list, or 'all'): ").strip().lower()
        if choice in ['q', 'exit', 'quit']: return
        
        to_extract = found_games if choice == 'all' else []
        if not to_extract:
            indices = [int(i.strip()) - 1 for i in choice.split(',')]
            to_extract = [found_games[i] for i in indices if 0 <= i < len(found_games)]
    except (ValueError, IndexError):
        sys.stderr.write("[!] Error: Invalid selection provided.\n"); return

    # --- BATCH EXTRACTION ---
    print(f"\n[*] Processing batch: {len(to_extract)} files targeted.\n")
    for g in to_extract:
        clean_name = "".join([c for c in g['name'] if c.isalnum() or c in (' ', '_', '-')]).replace(' ', '_')
        dest = os.path.join(args.dest, f"{g['id']}_{clean_name}.iso")
        if not os.path.exists(dest):
            extract_iso(args.disk, g['offset'], g['size'], dest)
        else:
            print(f"[-] Skip: {g['name']} already exists.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Process terminated by user.")
        sys.exit(0)

import os
import time
import sys
import shutil
import subprocess
import re
import json
import argparse

# --- DEFAULT CONFIGURATION ---
DEFAULT_DISK = ""
DEFAULT_DEST = "./extracted_games/"
WII_MAGIC = b"\x5D\x1C\x9E\xA3"
GC_MAGIC  = b"\xC2\x33\x9F\x3D"
WII_SIZE  = 4699979776 
GC_SIZE   = 1459978240
CHUNK_SIZE = 1024 * 1024 * 32 

def format_time(seconds):
    if seconds < 0: return "00:00:00"
    return time.strftime("%H:%M:%S", time.gmtime(seconds))

def get_macos_disk_size(disk_path):
    try:
        standard_disk = disk_path.replace('rdisk', 'disk')
        cmd = ['diskutil', 'info', standard_disk]
        output = subprocess.check_output(cmd).decode('utf-8')
        match = re.search(r'Disk Size:.*?(\d+) Bytes', output)
        return int(match.group(1)) if match else 0
    except: return 0

def extract_iso(disk_path, offset, size, dest_path):
    print(f"Extrayendo ISO en offset {offset}...")
    try:
        with open(disk_path, "rb") as f:
            f.seek(offset)
            start_time = time.time()
            with open(dest_path, "wb") as out:
                written = 0
                while written < size:
                    data = f.read(min(CHUNK_SIZE, size - written))
                    if not data: break
                    out.write(data)
                    written += len(data)
                    
                    elapsed = time.time() - start_time
                    speed = (written / (1024**2)) / elapsed if elapsed > 0 else 0
                    eta = (size - written) / (written / elapsed) if written > 0 else 0
                    
                    bar = "█" * int(25 * written // size)
                    sys.stdout.write(f"\r    [{bar:25s}] {(written/size)*100:6.2f}% | {speed:5.1f} MB/s | ETA: {format_time(eta)}")
                    sys.stdout.flush()
            print(f"\nFinalizado: {dest_path}")
    except Exception as e:
        print(f"\nError en extracción: {e}", file=sys.stderr)

def main():
    parser = argparse.ArgumentParser(description="WODE ISO Carver para Power Users")
    parser.add_argument("--disk", default=DEFAULT_DISK, help="Ruta del dispositivo (ej. /dev/rdisk12)")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="Carpeta de destino")
    parser.add_argument("--offset", type=int, help="Offset manual para saltar indexación")
    parser.add_argument("--id", default="MANUAL", help="ID para el modo manual")
    parser.add_argument("--force-scan", action="store_true", help="Ignora el JSON y escanea")
    parser.add_argument("--skip-scan", action="store_true", help="Salta el escaneo si no hay JSON")
    
    args = parser.parse_args()
    
    # Validación de seguridad
    if not args.disk and args.offset is None:
        print("Error: Debes especificar un disco con --disk o usar el modo manual con --offset.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.dest):
        os.makedirs(args.dest, exist_ok=True)

    index_file = os.path.join(args.dest, "wode_index.json")

    # --- MODO MANUAL ---
    if args.offset is not None:
        print(f"MODO MANUAL: Extrayendo desde offset {args.offset}")
        filename = os.path.join(args.dest, f"{args.id}_Manual_Dump.iso")
        extract_iso(args.disk, args.offset, WII_SIZE, filename)
        return

    # --- LÓGICA DE INDEXACIÓN ---
    found_games = []
    if not args.force_scan and os.path.exists(index_file):
        print(f"Cargando índice desde {index_file}...")
        with open(index_file, 'r') as jf:
            found_games = json.load(jf)
    
    if not found_games and not args.skip_scan:
        print("No hay índice. Iniciando escaneo completo...")
        total_size = get_macos_disk_size(args.disk)
        try:
            with open(args.disk, "rb") as f:
                offset = 0
                scan_start = time.time()
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk: break
                    
                    pos_wii = chunk.find(WII_MAGIC)
                    pos_gc = chunk.find(GC_MAGIC)
                    
                    if pos_wii != -1 or pos_gc != -1:
                        is_wii = (pos_wii != -1)
                        local_pos = pos_wii if is_wii else pos_gc
                        iso_start = offset + local_pos - (24 if is_wii else 28)
                        
                        f.seek(iso_start)
                        header = f.read(128)
                        gid = header[:6].decode('ascii', errors='ignore').strip()
                        gname = header[32:96].decode('ascii', errors='ignore').strip('\x00').strip()
                        
                        found_games.append({
                            'offset': iso_start, 'id': gid, 'name': gname,
                            'type': 'WII' if is_wii else 'GC',
                            'size': WII_SIZE if is_wii else GC_SIZE
                        })
                        offset = iso_start + (WII_SIZE if is_wii else GC_SIZE)
                        f.seek(offset)
                        continue

                    offset += CHUNK_SIZE
                    if total_size > 0:
                        elapsed = time.time() - scan_start
                        speed = offset / elapsed if elapsed > 0 else 1
                        eta = (total_size - offset) / speed
                        sys.stdout.write(f"\r   Progress: {(offset/total_size)*100:6.2f}% | V: {speed/(1024**2):.1f} MB/s | ETA: {format_time(eta)}")
                        sys.stdout.flush()

                with open(index_file, 'w') as jf:
                    json.dump(found_games, jf, indent=4)
                print(f"\nÍndice guardado.")
        except Exception as e:
            print(f"\nError: {e}", file=sys.stderr); return
    elif args.skip_scan and not found_games:
        print("Indexación saltada por el usuario. No hay nada que extraer.")
        return

    # --- MENÚ Y EXTRACCIÓN ---
    if not found_games: return
    print(f"\n{'='*65}\nJUEGOS DISPONIBLES\n{'='*65}")
    for i, g in enumerate(found_games, 1):
        print(f"{i:2d}. [{g['type']}] {g['id']} - {g['name']}")
    print(f"{'='*65}")
    
    choice = input("\nElige número, lista (1,3) o 'all' (o 'q' para salir): ").strip().lower()
    if choice == 'q': return
    
    to_extract = found_games if choice == 'all' else []
    if not to_extract:
        try:
            indices = [int(i.strip()) - 1 for i in choice.split(',')]
            to_extract = [found_games[i] for i in indices if 0 <= i < len(found_games)]
        except: print("Selección inválida.", file=sys.stderr); return

    for g in to_extract:
        clean_name = "".join([c for c in g['name'] if c.isalnum() or c in (' ', '_', '-')]).replace(' ', '_')
        dest = os.path.join(args.dest, f"{g['id']}_{clean_name}.iso")
        if not os.path.exists(dest):
            extract_iso(args.disk, g['offset'], g['size'], dest)
        else:
            print(f"{g['name']} ya existe. Saltando...")

if __name__ == "__main__":
    main()

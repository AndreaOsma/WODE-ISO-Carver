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
SECTOR_SIZE = 512

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
            # En macOS rdisk, el seek debe estar alineado
            aligned_offset = (offset // SECTOR_SIZE) * SECTOR_SIZE
            diff = offset - aligned_offset
            
            f.seek(aligned_offset)
            # Descartamos el gap de alineacion si existe
            if diff > 0:
                f.read(diff)
                
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
            print(f"\nFinalizado: {dest_path}")
    except Exception as e:
        sys.stderr.write(f"\nError en extraccion: {e}\n")

def main():
    parser = argparse.ArgumentParser(description="WODE ISO Carver para Power Users")
    parser.add_argument("--disk", default=DEFAULT_DISK, help="Ruta del dispositivo (ej. /dev/rdisk12)")
    parser.add_argument("--dest", default=DEFAULT_DEST, help="Carpeta de destino")
    parser.add_argument("--offset", type=int, help="Offset manual para saltar indexacion")
    parser.add_argument("--id", default="MANUAL", help="ID para el modo manual")
    parser.add_argument("--force-scan", action="store_true", help="Ignora el JSON y escanea")
    parser.add_argument("--skip-scan", action="store_true", help="Salta el escaneo si no hay JSON")
    
    args = parser.parse_args()
    
    if not args.disk and args.offset is None:
        sys.stderr.write("Error: Debes especificar un disco con --disk o usar el modo manual con --offset.\n")
        sys.exit(1)

    if not os.path.exists(args.dest):
        os.makedirs(args.dest, exist_ok=True)

    index_file = os.path.join(args.dest, "wode_index.json")
    found_games = []

    if args.offset is not None:
        print(f"MODO MANUAL: Extrayendo desde offset {args.offset}")
        filename = os.path.join(args.dest, f"{args.id}_Manual_Dump.iso")
        extract_iso(args.disk, args.offset, WII_SIZE, filename)
        return

    if not args.force_scan and os.path.exists(index_file):
        print(f"Cargando indice desde {index_file}...")
        with open(index_file, 'r') as jf:
            found_games = json.load(jf)
    
    if not found_games and not args.skip_scan:
        print("Iniciando escaneo robusto (alineado)...")
        total_size = get_macos_disk_size(args.disk)
        
        try:
            with open(args.disk, "rb") as f:
                offset = 0
                scan_start = time.time()
                while True:
                    # Evitamos sobrepasar el final del disco para prevenir Errno 22
                    remaining = total_size - offset if total_size > 0 else CHUNK_SIZE
                    if remaining <= 0: break
                    current_chunk_size = min(CHUNK_SIZE, remaining)
                    
                    current_pos = f.tell()
                    chunk = f.read(current_chunk_size)
                    if not chunk: break
                    
                    # Busqueda de firmas en el buffer
                    pos_wii = chunk.find(WII_MAGIC)
                    pos_gc = chunk.find(GC_MAGIC)
                    
                    if pos_wii != -1 or pos_gc != -1:
                        is_wii = (pos_wii != -1)
                        local_pos = pos_wii if is_wii else pos_gc
                        
                        # El inicio real de la ISO es relativo a la firma
                        relative_iso_start = local_pos - (24 if is_wii else 28)
                        iso_start = current_pos + relative_iso_start
                        
                        # Extraemos metadatos del buffer (evita lecturas desalineadas)
                        try:
                            h_start = relative_iso_start
                            header = chunk[h_start:h_start+128]
                            gid = header[:6].decode('ascii', errors='ignore').strip()
                            gname = header[32:96].decode('ascii', errors='ignore').strip('\x00').strip()
                        except:
                            gid, gname = "UNK", "Unknown"

                        found_games.append({
                            'offset': iso_start, 'id': gid, 'name': gname,
                            'type': 'WII' if is_wii else 'GC',
                            'size': WII_SIZE if is_wii else GC_SIZE
                        })
                        
                        # Saltar ISO y alinear al siguiente sector de 512 bytes
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
                        sys.stdout.write(f"\r   Progress: {(offset/total_size)*100:6.2f}% | V: {speed/(1024**2):.1f} MB/s | ETA: {format_time(eta)}")
                        sys.stdout.flush()

                with open(index_file, 'w') as jf:
                    json.dump(found_games, jf, indent=4)
                print(f"\nIndice guardado.")
        except Exception as e:
            sys.stderr.write(f"\nError durante escaneo: {e}\n"); return

    if not found_games: return
    print(f"\n{'='*65}\nJUEGOS DISPONIBLES\n{'='*65}")
    for i, g in enumerate(found_games, 1):
        print(f"{i:2d}. [{g['type']}] {g['id']} - {g['name']}")
    print(f"{'='*65}")
    
    choice = input("\nElige numero, lista (1,3) o 'all' (o 'q' para salir): ").strip().lower()
    if choice == 'q': return
    
    to_extract = found_games if choice == 'all' else []
    if not to_extract:
        try:
            indices = [int(i.strip()) - 1 for i in choice.split(',')]
            to_extract = [found_games[i] for i in indices if 0 <= i < len(found_games)]
        except: sys.stderr.write("Seleccion invalida.\n"); return

    for g in to_extract:
        clean_name = "".join([c for c in g['name'] if c.isalnum() or c in (' ', '_', '-')]).replace(' ', '_')
        dest = os.path.join(args.dest, f"{g['id']}_{clean_name}.iso")
        if not os.path.exists(dest):
            extract_iso(args.disk, g['offset'], g['size'], dest)
        else:
            print(f"{g['name']} ya existe. Saltando...")

if __name__ == "__main__":
    main()

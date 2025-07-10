# transwacom.py
import socket
import sys
import os


import subprocess
import argparse
import json
import time

REMOTE_HOST = "192.168.0.2"        # IP del host destino (ajusta según tu red)
REMOTE_PORT = 3333                 # Puerto en el host destino

def autodetect_wacom_device():
    try:
        result = subprocess.run(["libwacom-list-local-devices"], capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith("- /dev/input/") or line.startswith("/dev/input/"):
                # YAML:   - /dev/input/event11: 'Wacom ...'
                dev = line.split()[0].replace("-", "").strip()
                dev = dev.split(":")[0]
                if os.path.exists(dev):
                    return dev
            if line.startswith("nodes:"):
                # Buscar la siguiente línea con el path
                idx = lines.index(line)
                for l in lines[idx+1:]:
                    l = l.strip()
                    if l.startswith("- /dev/input/"):
                        dev = l.split()[0].replace("-", "").strip()
                        dev = dev.split(":")[0]
                        if os.path.exists(dev):
                            return dev
        # Fallback: buscar event* en la salida
        for line in lines:
            if "/dev/input/event" in line:
                dev = line.split()[0].replace("-", "").strip()
                dev = dev.split(":")[0]
                if os.path.exists(dev):
                    return dev
    except Exception as e:
        print(f"Error autodetectando tableta: {e}")
    return None


def server_mode(remote_host=REMOTE_HOST, remote_port=REMOTE_PORT):
    wacom_device = autodetect_wacom_device()
    if not wacom_device:
        print("No se pudo detectar automáticamente la tableta Wacom.")
        sys.exit(1)
    print(f"Usando dispositivo: {wacom_device}")
    try:
        wacom = open(wacom_device, "rb")
    except Exception as e:
        print(f"No se pudo abrir {wacom_device}: {e}")
        sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((remote_host, remote_port))
    except Exception as e:
        print(f"No se pudo conectar a {remote_host}:{remote_port}: {e}")
        sys.exit(1)

    print("Enviando datos de la tableta...")
    try:
        while True:
            data = wacom.read(1024)
            if not data:
                break
            sock.sendall(data)
    except KeyboardInterrupt:
        print("Daemon detenido por el usuario.")
    finally:
        wacom.close()
        sock.close()


def main():
    parser = argparse.ArgumentParser(description="transwacom: reenvía eventos de tableta Wacom por red.")
    parser.add_argument('--server', action='store_true', help='Modo servidor: lee la tableta y reenvía eventos')
    parser.add_argument('--host', type=str, default=REMOTE_HOST, help='Host destino (modo servidor)')
    parser.add_argument('--port', type=int, default=REMOTE_PORT, help='Puerto destino (modo servidor)')
    args = parser.parse_args()

    if args.server:
        # Opcional: demonizar el proceso
        if os.fork() > 0:
            sys.exit(0)
        server_mode(args.host, args.port)
    else:
        print("Modo cliente aún no implementado. Usa --server para enviar eventos.")

if __name__ == "__main__":
    main()
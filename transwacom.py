# transwacom.py
import socket
import sys
import os
import subprocess
import argparse
import json
import time
import struct

try:
    import evdev
    from evdev import InputDevice, UInput, ecodes as e, AbsInfo
    EVDEV_AVAILABLE = True
except ImportError:
    EVDEV_AVAILABLE = False
    print("Advertencia: python-evdev no está instalado. El modo cliente no funcionará.")

REMOTE_HOST = "192.168.0.2"        # IP del host destino (ajusta según tu red)
REMOTE_PORT = 3333                 # Puerto por defecto

def autodetect_input_devices():
    """Detecta dispositivos de entrada (Wacom, joysticks, etc.)"""
    devices = []
    
    # Detectar tabletas Wacom
    try:
        result = subprocess.run(["libwacom-list-local-devices"], capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        for line in lines:
            line = line.strip()
            if line.startswith('- /dev/input/event'):
                dev = line[1:].strip().split(':')[0].strip()
                if os.path.exists(dev):
                    devices.append(('wacom', dev, line.split(':')[1].strip().strip("'")))
    except Exception as e:
        print(f"No se encontraron tabletas Wacom: {e}")
    
    # Detectar joysticks/gamepads
    try:
        for event_file in os.listdir('/dev/input'):
            if event_file.startswith('event'):
                dev_path = f'/dev/input/{event_file}'
                try:
                    device = InputDevice(dev_path)
                    capabilities = device.capabilities()
                    
                    # Es un joystick si tiene ejes X/Y y botones
                    if (e.EV_ABS in capabilities and 
                        e.EV_KEY in capabilities and
                        (e.ABS_X in capabilities.get(e.EV_ABS, []) or 
                         e.ABS_RX in capabilities.get(e.EV_ABS, []))):
                        devices.append(('joystick', dev_path, device.name))
                    device.close()
                except:
                    pass
    except Exception as e:
        print(f"Error detectando joysticks: {e}")
    
    return devices


def server_mode(device_path, remote_host, remote_port):
    """Modo servidor: lee dispositivo de entrada y reenvía eventos por red"""
    print(f"Usando dispositivo: {device_path}")
    
    if not EVDEV_AVAILABLE:
        # Fallback: leer datos binarios directamente
        try:
            device = open(device_path, "rb")
        except Exception as e:
            print(f"No se pudo abrir {device_path}: {e}")
            sys.exit(1)
    else:
        # Usar evdev para leer eventos estructurados
        try:
            device = InputDevice(device_path)
        except Exception as e:
            print(f"No se pudo abrir {device_path}: {e}")
            sys.exit(1)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((remote_host, remote_port))
        print(f"Conectado a {remote_host}:{remote_port}")
    except Exception as e:
        print(f"No se pudo conectar a {remote_host}:{remote_port}: {e}")
        sys.exit(1)

    print("Enviando eventos del dispositivo...")
    try:
        if not EVDEV_AVAILABLE:
            # Modo binario simple
            while True:
                data = device.read(1024)
                if not data:
                    break
                sock.sendall(data)
        else:
            # Modo evdev estructurado
            for event in device.read_loop():
                event_data = {
                    'type': event.type,
                    'code': event.code,
                    'value': event.value,
                    'timestamp': event.timestamp()
                }
                msg = json.dumps(event_data).encode() + b'\n'
                sock.sendall(msg)
    except KeyboardInterrupt:
        print("Daemon detenido por el usuario.")
    finally:
        if hasattr(device, 'close'):
            device.close()
        sock.close()


def create_virtual_device(device_type='wacom'):
    """Crea un dispositivo virtual usando uinput"""
    if not EVDEV_AVAILABLE:
        print("Error: python-evdev es requerido para el modo cliente.")
        sys.exit(1)
    
    if device_type == 'wacom':
        # Configuración para tableta Wacom
        cap = {
            e.EV_ABS: [
                (e.ABS_X, AbsInfo(value=0, min=0, max=15360, fuzz=0, flat=0, resolution=100)),
                (e.ABS_Y, AbsInfo(value=0, min=0, max=10240, fuzz=0, flat=0, resolution=100)),
                (e.ABS_PRESSURE, AbsInfo(value=0, min=0, max=2047, fuzz=0, flat=0, resolution=0)),
                (e.ABS_TILT_X, AbsInfo(value=0, min=-64, max=63, fuzz=0, flat=0, resolution=0)),
                (e.ABS_TILT_Y, AbsInfo(value=0, min=-64, max=63, fuzz=0, flat=0, resolution=0)),
                (e.ABS_DISTANCE, AbsInfo(value=0, min=0, max=63, fuzz=0, flat=0, resolution=0)),
            ],
            e.EV_KEY: [
                e.BTN_TOOL_PEN, e.BTN_TOOL_RUBBER, e.BTN_TOUCH,
                e.BTN_STYLUS, e.BTN_STYLUS2
            ]
        }
        name = 'Virtual Wacom Tablet'
    
    elif device_type == 'joystick':
        # Configuración para joystick/gamepad
        cap = {
            e.EV_ABS: [
                (e.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (e.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (e.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (e.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (e.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (e.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (e.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                (e.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            ],
            e.EV_KEY: [
                e.BTN_A, e.BTN_B, e.BTN_X, e.BTN_Y,
                e.BTN_TL, e.BTN_TR, e.BTN_TL2, e.BTN_TR2,
                e.BTN_SELECT, e.BTN_START, e.BTN_MODE,
                e.BTN_THUMBL, e.BTN_THUMBR
            ]
        }
        name = 'Virtual Gamepad'
    
    else:
        print(f"Tipo de dispositivo '{device_type}' no soportado")
        sys.exit(1)
    
    try:
        ui = UInput(cap, name=name)
        print(f"Dispositivo virtual '{name}' creado en: {ui.device.path}")
        return ui
    except Exception as e:
        print(f"Error creando dispositivo virtual: {e}")
        print("Asegúrate de tener permisos para /dev/uinput (grupo input)")
        sys.exit(1)


def client_mode(listen_port, device_type='wacom'):
    """Modo cliente: recibe eventos por red y los inyecta en dispositivo virtual"""
    virtual_device = create_virtual_device(device_type)
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(('0.0.0.0', listen_port))
        sock.listen(1)
        print(f"Esperando conexión en puerto {listen_port}...")
    except Exception as e:
        print(f"Error configurando servidor: {e}")
        sys.exit(1)
    
    try:
        while True:
            conn, addr = sock.accept()
            print(f"Conectado desde {addr}")
            
            buffer = b''
            try:
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    
                    buffer += data
                    while b'\n' in buffer:
                        line, buffer = buffer.split(b'\n', 1)
                        if line:
                            try:
                                event_data = json.loads(line.decode())
                                # Inyectar evento en dispositivo virtual
                                virtual_device.write(event_data['type'], event_data['code'], event_data['value'])
                                if event_data['type'] == e.EV_SYN:
                                    virtual_device.syn()
                            except Exception as e:
                                print(f"Error procesando evento: {e}")
                                
            except Exception as e:
                print(f"Error en conexión: {e}")
            finally:
                conn.close()
                print("Conexión cerrada")
                
    except KeyboardInterrupt:
        print("Servidor detenido por el usuario.")
    finally:
        virtual_device.close()
        sock.close()
def main():
    parser = argparse.ArgumentParser(description="transwacom: reenvía eventos de dispositivos de entrada por red.")
    parser.add_argument('--server', action='store_true', help='Modo servidor: lee dispositivo y reenvía eventos')
    parser.add_argument('--client', action='store_true', help='Modo cliente: recibe eventos y crea dispositivo virtual')
    parser.add_argument('--host', type=str, default=REMOTE_HOST, help='Host destino (modo servidor)')
    parser.add_argument('--port', type=int, default=REMOTE_PORT, help='Puerto (default: 3333)')
    parser.add_argument('--device', type=str, help='Path del dispositivo específico (ej: /dev/input/event11)')
    parser.add_argument('--list', action='store_true', help='Listar dispositivos detectados')
    parser.add_argument('--type', choices=['wacom', 'joystick'], default='wacom', 
                       help='Tipo de dispositivo virtual (modo cliente)')
    parser.add_argument('--daemon', action='store_true', help='Ejecutar como daemon (solo modo servidor)')
    
    args = parser.parse_args()
    
    if args.list:
        print("Dispositivos detectados:")
        devices = autodetect_input_devices()
        if not devices:
            print("  No se encontraron dispositivos.")
        else:
            for dev_type, path, name in devices:
                print(f"  {dev_type}: {path} - {name}")
        return
    
    if args.server and args.client:
        print("Error: No puedes usar --server y --client al mismo tiempo.")
        sys.exit(1)
    
    if not args.server and not args.client:
        print("Error: Debes especificar --server o --client.")
        parser.print_help()
        sys.exit(1)
    
    if args.server:
        if args.device:
            device_path = args.device
        else:
            # Autodetectar dispositivo
            devices = autodetect_input_devices()
            if not devices:
                print("No se encontraron dispositivos. Usa --device para especificar uno manualmente.")
                sys.exit(1)
            device_path = devices[0][1]  # Usar el primer dispositivo encontrado
            print(f"Autodetectado: {devices[0][2]} ({device_path})")
        
        if args.daemon:
            if os.fork() > 0:
                sys.exit(0)
        
        server_mode(device_path, args.host, args.port)
    
    elif args.client:
        client_mode(args.port, args.type)

if __name__ == "__main__":
    main()
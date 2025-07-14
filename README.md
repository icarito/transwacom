# TransWacom

**Network Input Device Sharing for Linux**

TransWacom is a Linux application that enables sharing input devices (Wacom tablets, joysticks, controllers) between machines on a local network through an intuitive system tray interface.

## 🚀 Key Features

- **System Tray GUI**: Easy-to-use tray application with right-click menu
- **Auto-Discovery**: Automatically finds other devices on the network using mDNS
- **Multi-Device Support**: Wacom tablets, Xbox/PlayStation controllers, generic joysticks
- **Authorization System**: Access control with trusted hosts and authorization notifications
- **Smart Configuration**: Automatically configures Wacom tablets (relative mode, local disable)
- **Intelligent Recovery**: Restores original device state when disconnecting
- **Connection Monitoring**: Detects network failures and automatically restores devices
- **Unified Architecture**: Each machine can both share and receive devices simultaneously

## � System Requirements

- **Operating System**: Linux (uses evdev and uinput)
- **Python**: 3.8 or higher
- **Permissions**: Access to `/dev/input` and `/dev/uinput`
- **Network**: Local Area Network (LAN) connection
- **GUI Dependencies**: For system tray functionality

## 🔧 Installation

### Prerequisites

- **Operating System**: Linux (uses evdev and uinput)
- **Python**: 3.8 or higher
- **System packages**: Install required system dependencies

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install python3-gi python3-dev libcairo2-dev libgirepository1.0-dev

# Fedora/RHEL
sudo dnf install python3-gobject python3-devel cairo-devel gobject-introspection-devel

# Arch Linux
sudo pacman -S python-gobject python-cairo gobject-introspection
```

### Install TransWacom

#### Option 1: Install from PyPI (when published)
```bash
pip install transwacom
```

#### Option 2: Install from source
```bash
git clone <repository-url>
cd transwacom
pip install .
```

#### Option 3: Development installation
```bash
git clone <repository-url>
cd transwacom
pip install -e ".[dev]"
```

### Setup Permissions (Required)

TransWacom needs access to input devices and the ability to create virtual devices:

```bash
# Add user to input group
sudo usermod -a -G input $USER

# Setup uinput permissions
echo 'KERNEL=="uinput", GROUP="input", MODE="0660"' | sudo tee /etc/udev/rules.d/99-transwacom.rules
sudo udevadm control --reload-rules
sudo modprobe uinput

# Logout and login again to apply group changes
```

## 🎯 Usage

### System Tray Application (Recommended)

Start the system tray application:

```bash
transwacom-tray
# or if installed in development mode
python3 tray_app_unified.py
```

The application will appear in your system tray. Right-click the tray icon to access the menu:

#### Tray Menu Functions:
- **📱 Local Devices**: List of available devices to share
- **🌐 Available Consumers**: Other machines on the network where you can send devices
- **🔗 Active Connections**: Current incoming and outgoing connections
- **❌ Disconnect**: Options to close specific connections

#### Sharing a Device:
1. Select **"Local Devices → [Device] → Share with → [Target Machine]"**
2. The target machine will show an authorization notification
3. If accepted, the device will be shared automatically

#### Receiving a Device:
1. When someone tries to connect, a notification will appear
2. Click **"Accept"** to allow the connection
3. A virtual device will be created automatically

### Command Line Interface

#### List available devices:
```bash
transwacom --list-devices
```

#### Unified mode (server + client):
```bash
transwacom --unified
```

#### Discover machines on network:
```bash
transwacom --host --discover
```

#### Connect directly to a machine:
```bash
transwacom --host --connect 192.168.1.100:3333 --device /dev/input/event11
```

#### Consumer mode only:
```bash
transwacom --consumer --port 3333
```

## ⚙️ Configuration

TransWacom automatically creates a configuration file at `~/.config/transwacom/config.yml`:

```yaml
general:
  machine_name: "My-PC"
  machine_id: "unique-machine-id"

consumer:
  network:
    port: 3333
    mdns_name: "My-PC-TransWacom"
  trusted_hosts:
    "Desktop-PC":
      host_id: "other-machine-id"
      auto_accept: true
  devices:
    wacom_enabled: true
    joystick_enabled: true

host:
  relative_mode: true
  disable_local: true
  trusted_consumers: {}
```

### Configuration Options:

- **`machine_name`**: Name that appears on other machines
- **`port`**: TCP port for connections (default 3333)
- **`auto_accept`**: Automatically accept connections from trusted hosts
- **`relative_mode`**: Use relative mode for Wacom tablets (recommended)
- **`disable_local`**: Disable local device while sharing
- **`wacom_enabled/joystick_enabled`**: Device types to accept

## 🏗️ Architecture

### Components:
- **Host**: Machine with physical device (TCP client)
- **Consumer**: Machine that receives device (TCP server)
- **Unified App**: Can act as both host and consumer simultaneously

### Network Protocol:
- **mDNS**: For automatic discovery (`_input-consumer._tcp.local`)
- **TCP**: For input event transmission
- **JSON**: Structured message format

### Operation Flow:
1. Consumer publishes mDNS service and listens for connections
2. Host discovers available consumers
3. User selects device and target in the menu
4. Consumer shows authorization notification
5. If accepted: handshake → virtual device creation → event streaming
6. Host configures device (relative mode, disable local)
7. Real-time input event transmission
8. Automatic recovery on connection loss

## 🎮 Use Cases

### Digital Artists:
- Use Wacom tablet on desktop from mobile laptop
- Share tablet between multiple workstations

### Gaming:
- Send controllers from main PC to Steam Deck
- Use remote controllers for gaming on multiple devices

### Presentations:
- Use tablet for annotations on PC connected to projector
- Remote presentation control

### Development:
- Test applications with different input types
- Device emulation for testing

## 🛠️ Development

### Project Structure:
```
transwacom/
├── transwacom.py              # Main entry point
├── tray_app_unified.py        # Unified tray application
├── device_detector.py         # Input device detection
├── host_input.py             # Host event capture
├── consumer_device_emulation.py # Virtual device emulation
├── transnetwork.py           # Network protocol and mDNS
├── config_manager.py         # Configuration management
├── pyproject.toml            # Modern Python project configuration
├── requirements.txt          # Python dependencies
└── README.md               # This file
```

### Development Setup:
```bash
git clone <repository-url>
cd transwacom
pip install -e ".[dev]"
```

### Code Quality Tools:
```bash
# Format code
black .
isort .

# Type checking
mypy .

# Linting
flake8 .

# Run tests
pytest
```

### Module APIs:

#### Device Detection
```python
from device_detector import create_detector
detector = create_detector()
devices = detector.detect_all_devices()
```

#### Network Communication
```python
from transnetwork import create_network
network = create_network()
network.discover_consumers(callback)
```

#### Input Capture
```python
from host_input import create_host_input_manager
input_mgr = create_host_input_manager()
input_mgr.start_capture(device_path, event_callback)
```

#### Device Emulation
```python
from consumer_device_emulation import create_device_emulation_manager
emulation_mgr = create_device_emulation_manager()
emulation_mgr.create_virtual_device("wacom")
```

### Contributing:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 🐛 Troubleshooting

### Permission Errors:
```
PermissionError: [Errno 13] Permission denied: '/dev/input/eventX'
```
**Solution**: Ensure you're in the `input` group and restart your session.

### No Devices Found:
- Verify devices are connected and working
- Run `transwacom --list-devices` for debugging
- Some devices may require root permissions

### Network Issues:
- Verify both machines are on the same local network
- Check that port (default 3333) is not blocked by firewall
- mDNS may not work on some corporate networks

### Wacom Tablet Issues:
- Ensure Wacom driver is installed
- Verify `xsetwacom` is available for automatic configuration
- Use `--no-relative-mode` if you prefer absolute mode

### Connection Recovery:
The application automatically detects connection failures and restores device states. If devices get stuck in a bad state:

```bash
# Restore Wacom tablet manually
xinput enable "Wacom Device Name"
xsetwacom set "Wacom Device Name" mode absolute
```

### Debug Mode:
```bash
transwacom-tray --debug
```

## 📝 License

This project is licensed under the GNU General Public License v3.0 or later - see the [LICENSE](LICENSE) file for details.

## 🙏 Credits

TransWacom uses the following excellent libraries:
- **evdev**: Python interface for Linux input events
- **zeroconf**: Python implementation of mDNS/Bonjour
- **pystray**: Cross-platform system tray applications
- **PyYAML**: YAML parser for configuration files
- **Pillow**: Python Imaging Library for icons
- **PyGObject**: Python bindings for GTK+ and desktop notifications

---

**Need help?** Open an issue in the repository or check the installation troubleshooting section above.

Inicia la aplicación de bandeja del sistema:

```bash
python transwacom.py --applet
# o simplemente
python tray_app_unified.py
```

La aplicación aparecerá en la bandeja del sistema con un ícono. Haz clic derecho para acceder al menú:

#### Funciones del Menú:
- **📱 Dispositivos Locales**: Lista de dispositivos disponibles para compartir
- **🌐 Consumidores Disponibles**: Otros equipos en la red donde puedes enviar dispositivos
- **🔗 Conexiones Activas**: Conexiones entrantes y salientes actuales
- **❌ Desconectar**: Opciones para cerrar conexiones específicas

#### Compartir un Dispositivo:
1. Selecciona **"Dispositivos Locales → [Dispositivo] → Compartir con → [Equipo Destino]"**
2. El equipo destino mostrará una notificación de autorización
3. Si se acepta, el dispositivo se compartirá automáticamente

#### Recibir un Dispositivo:
1. Cuando alguien intente conectarse, aparecerá una notificación
2. Haz clic en **"Aceptar"** para permitir la conexión
3. El dispositivo virtual se creará automáticamente

### Modo Línea de Comandos

#### Ver dispositivos disponibles:
```bash
python transwacom.py --list-devices
```

#### Modo Unificado (servidor + cliente):
```bash
python transwacom.py --unified
```

#### Descubrir equipos en la red:
```bash
python transwacom.py --host --discover
```

#### Conectar directamente a un equipo:
```bash
python transwacom.py --host --connect 192.168.1.100:3333 --device /dev/input/event11
```

#### Solo recibir conexiones:
```bash
python transwacom.py --consumer --port 3333
```

## ⚙️ Configuración

TransWacom crea automáticamente un archivo de configuración en `~/.config/transwacom/config.yml`:

```yaml
general:
  machine_name: "Mi-PC"
  machine_id: "unique-machine-id"

consumer:
  network:
    port: 3333
    mdns_name: "Mi-PC-TransWacom"
  trusted_hosts:
    "PC-Escritorio":
      host_id: "other-machine-id"
      auto_accept: true
  devices:
    wacom_enabled: true
    joystick_enabled: true

host:
  relative_mode: true
  disable_local: true
  trusted_consumers: {}
```

### Opciones de Configuración:

- **`machine_name`**: Nombre que aparece en otros equipos
- **`port`**: Puerto TCP para conexiones (por defecto 3333)
- **`auto_accept`**: Aceptar automáticamente conexiones de hosts confiables
- **`relative_mode`**: Usar modo relativo para tabletas Wacom (recomendado)
- **`disable_local`**: Desactivar dispositivo local mientras se comparte
- **`wacom_enabled/joystick_enabled`**: Tipos de dispositivos a aceptar

## 🔌 Arquitectura del Sistema

### Componentes:
- **Host**: Máquina con dispositivo físico (cliente TCP)
- **Consumer**: Máquina que recibe dispositivo (servidor TCP)
- **Aplicación Unificada**: Puede actuar como host y consumer simultáneamente

### Protocolo de Red:
- **mDNS**: Para descubrimiento automático (`_input-consumer._tcp.local`)
- **TCP**: Para transmisión de eventos de entrada
- **JSON**: Formato de mensajes estructurado

### Flujo de Operación:
1. Consumer publica servicio mDNS y escucha conexiones
2. Host descubre consumers disponibles
3. Usuario selecciona dispositivo y destino en el menú
4. Consumer muestra notificación de autorización
5. Si se acepta: handshake → dispositivo virtual → streaming de eventos
6. Host configura dispositivo (modo relativo, desactivar local)
7. Transmisión en tiempo real de eventos de entrada

## 🎮 Casos de Uso

### Para Artistas Digitales:
- Usar tableta Wacom en desktop desde laptop para trabajo móvil
- Compartir tableta entre múltiples estaciones de trabajo

### Para Gaming:
- Enviar controladores desde PC principal a Steam Deck
- Usar controladores remotos para gaming en múltiples dispositivos

### Para Presentaciones:
- Usar tableta para anotaciones en PC conectado a proyector
- Control remoto de presentaciones

### Para Desarrollo:
- Probar aplicaciones con diferentes tipos de entrada
- Emulación de dispositivos para testing

## 🛠️ Desarrollo

### Estructura del Proyecto:
```
transwacom/
├── transwacom.py              # Punto de entrada principal
├── tray_app_unified.py        # Aplicación de bandeja unificada
├── device_detector.py         # Detección de dispositivos de entrada
├── host_input.py             # Captura de eventos del host
├── consumer_device_emulation.py # Emulación de dispositivos virtuales
├── transnetwork.py           # Protocolo de red y mDNS
├── config_manager.py         # Gestión de configuración
├── requirements.txt          # Dependencias Python
└── README.md                # Este archivo
```

### Ejecutar Tests:
```bash
cd tests
python -m pytest
```

### Contribuir:
1. Fork el repositorio
2. Crea una rama para tu feature
3. Realiza tests
4. Envía un pull request

## 🐛 Resolución de Problemas

### Error de Permisos:
```
PermissionError: [Errno 13] Permission denied: '/dev/input/eventX'
```
**Solución**: Asegúrate de estar en el grupo `input` y reinicia la sesión.

### No se encuentran dispositivos:
- Verifica que los dispositivos estén conectados y funcionando
- Ejecuta `python transwacom.py --list-devices` para debug
- Algunos dispositivos pueden requerir permisos de superusuario

### Problemas de Red:
- Verifica que ambos equipos estén en la misma red local
- Revisa que el puerto (por defecto 3333) no esté bloqueado por firewall
- mDNS puede no funcionar en algunas redes corporativas

### Tableta Wacom no funciona correctamente:
- Asegúrate de que el driver Wacom esté instalado
- Verifica que `xsetwacom` esté disponible para configuración automática
- Usa `--no-relative-mode` si prefieres modo absoluto

### Restaurar configuración original:
```bash
# En caso de que el dispositivo quede en mal estado
xinput enable "Wacom Device Name"
xsetwacom set "Wacom Device Name" mode absolute
```

## 📄 Licencia

[Incluir información de licencia]

## 🤝 Créditos

TransWacom utiliza las siguientes librerías:
- **evdev**: Interfaz Python para eventos de entrada de Linux
- **zeroconf**: Implementación Python de mDNS/Bonjour
- **pystray**: Aplicaciones de bandeja del sistema multiplataforma
- **PyYAML**: Parser YAML para archivos de configuración
- **Pillow**: Biblioteca de imágenes Python para iconos

---

**¿Necesitas ayuda?** Abre un issue en el repositorio o consulta la documentación adicional en la carpeta `docs/`.

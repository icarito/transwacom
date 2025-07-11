# TransWacom - Documentación de Interfaces de Módulos

## Resumen de la Refactorización

El código original `transwacom.py` ha sido refactorizado en 5 módulos especializados siguiendo la especificación, manteniendo toda la funcionalidad existente pero con una arquitectura modular y clara.

## Módulos Principales

### 1. `device_detector.py` - Detección de Dispositivos

**Propósito**: Detecta automáticamente dispositivos de entrada (tabletas Wacom, joysticks).

**Clases Principales**:
- `DeviceInfo`: Información sobre un dispositivo detectado
- `DeviceDetector`: Detector principal de dispositivos

**API Pública**:
```python
# Crear detector
detector = create_detector()

# Detectar todos los dispositivos
devices = detector.detect_all_devices()  # List[DeviceInfo]

# Obtener dispositivos por tipo
wacom_devices = detector.get_devices_by_type('wacom')
joystick_devices = detector.get_devices_by_type('joystick')

# Obtener información de dispositivo específico
device = detector.get_device_by_path('/dev/input/event11')

# Obtener ID de Wacom para configuración
wacom_id = detector.get_wacom_device_id('/dev/input/event11')
```

**DeviceInfo**: Representa información de un dispositivo:
- `device_type`: 'wacom' o 'joystick'
- `path`: Ruta del dispositivo (ej. '/dev/input/event11')
- `name`: Nombre descriptivo
- `capabilities`: Lista de capacidades específicas
- `to_dict()`: Conversión a diccionario para JSON

### 2. `config_manager.py` - Gestión de Configuración

**Propósito**: Maneja configuración persistente y sistema de autorizaciones con archivos YAML.

**Clase Principal**:
- `ConfigManager`: Gestor de configuración con persistencia

**API Pública**:
```python
# Crear gestor de configuración
config = create_config_manager()

# Información de la máquina
machine_id = config.machine_id          # Fingerprint único
machine_name = config.machine_name      # Nombre del equipo

# Gestión de confianza (Host)
config.add_trusted_consumer(name, consumer_id, allowed_devices, auto_accept)
config.remove_trusted_consumer(name)
is_trusted = config.is_consumer_trusted(name, consumer_id)
should_auto = config.should_auto_accept_consumer(name)

# Gestión de confianza (Consumer)
config.add_trusted_host(name, host_id, auto_accept)
config.remove_trusted_host(name)
is_trusted = config.is_host_trusted(name, host_id)
should_auto = config.should_auto_accept_host(name)

# Configuración de red
port = config.get_consumer_port()
config.set_consumer_port(port)
mdns_name = config.get_mdns_name()

# Configuración de comportamiento
relative_mode = config.should_use_relative_mode()
disable_local = config.should_disable_local()
```

**Archivo de Configuración** (`~/.config/transwacom/transwacom.yaml`):
```yaml
host:
  trusted_consumers:
    "Laptop-Gaming":
      consumer_id: "abc123..."
      auto_accept: true
      allowed_devices: ["wacom", "joystick"]
  relative_mode: true
  disable_local: true

consumer:
  network:
    port: 3333
    mdns_name: "Mi-PC"
  trusted_hosts:
    "Desktop-Main":
      host_id: "def456..."
      auto_accept: true
  devices:
    wacom_enabled: true
    joystick_enabled: true
```

### 3. `transnetwork.py` - Protocolo de Red y mDNS

**Propósito**: Maneja comunicación TCP con protocolo JSON y descubrimiento mDNS.

**Clases Principales**:
- `NetworkProtocol`: Protocolo de mensajes JSON
- `TransNetwork`: Gestión de red y mDNS
- `DiscoveredConsumer`: Información de consumer descubierto
- `ConnectionInfo`: Información de conexión activa

**API Pública**:
```python
# Crear gestor de red
network = create_network()

# Protocolo de mensajes
protocol = network.protocol
handshake = protocol.create_handshake(host_name, host_id, devices)
events = protocol.create_event_message(device_type, events_list)
auth = protocol.create_auth_response(accepted, consumer_name, consumer_id)

# Host (cliente TCP)
# Descubrir consumers
def on_discovery(consumer: DiscoveredConsumer):
    print(f"Found: {consumer.name} at {consumer.address}:{consumer.port}")

network.discover_consumers(on_discovery)

# Conectar a consumer
sock = network.connect_to_consumer(address, port, handshake_data)
success = network.send_events(sock, device_type, events)
network.disconnect_from_consumer(sock, reason)

# Consumer (servidor TCP)
# Publicar servicio mDNS
network.publish_consumer_service(name, port, capabilities)

# Crear servidor
def auth_callback(handshake): return True  # Authorization logic
def event_callback(device_type, events): pass  # Event processing
server_sock = network.create_consumer_server(port, auth_callback, event_callback)
```

**Mensajes del Protocolo**:
```json
// Handshake
{
  "type": "handshake",
  "host_name": "PC-Desktop",
  "host_id": "abc123...",
  "devices": [{"type": "wacom", "name": "Wacom Serial", "capabilities": ["pressure"]}],
  "version": "1.0"
}

// Eventos
{
  "type": "event",
  "device_type": "wacom",
  "events": [{"code": "ABS_X", "value": 1500, "timestamp": 1234567890.123}],
  "timestamp": 1234567890.123
}

// Respuesta de autorización
{
  "type": "auth_response",
  "accepted": true,
  "consumer_name": "Laptop-Gaming",
  "consumer_id": "def456..."
}
```

### 4. `host_input.py` - Captura de Entrada

**Propósito**: Captura eventos de dispositivos físicos en el Host y maneja configuración de Wacom.

**Clases Principales**:
- `InputEvent`: Representa un evento de entrada
- `WacomController`: Controla configuración de tabletas Wacom
- `InputCapture`: Captura eventos de un dispositivo específico
- `HostInputManager`: Gestiona múltiples capturas

**API Pública**:
```python
# Crear gestor de entrada
input_manager = create_host_input_manager()

# Callback para eventos
def event_callback(device_type: str, events: List[InputEvent]):
    for event in events:
        print(f"{event.code}: {event.value} @ {event.timestamp}")

# Iniciar captura
success = input_manager.start_capture(
    device_path="/dev/input/event11",
    event_callback=event_callback,
    relative_mode=True,    # Modo relativo para Wacom
    disable_local=True     # Desactivar localmente
)

# Detener captura
input_manager.stop_capture(device_path)
input_manager.stop_all_captures()

# Información
active_devices = input_manager.get_active_devices()
device_info = input_manager.get_device_info(device_path)
is_capturing = input_manager.is_capturing(device_path)
```

**InputEvent**: Evento de entrada procesado:
- `code`: Código del evento (ej. 'ABS_X', 'KEY_BTN_TOUCH')
- `value`: Valor del evento
- `timestamp`: Marca de tiempo
- `to_dict()`: Conversión para transmisión por red

**WacomController**: Control específico de Wacom:
- `disable_local_input()`: Desactiva entrada local
- `enable_local_input()`: Reactiva entrada local
- `set_relative_mode()`: Modo relativo (como ratón)
- `restore_absolute_mode()`: Modo absoluto (tableta)
- `cleanup()`: Restaura configuración original

### 5. `consumer_device_emulation.py` - Emulación de Dispositivos

**Propósito**: Crea dispositivos virtuales usando uinput en el Consumer.

**Clases Principales**:
- `VirtualDevice`: Dispositivo virtual base
- `WacomVirtualDevice`: Tableta Wacom virtual
- `JoystickVirtualDevice`: Joystick/gamepad virtual
- `DeviceEmulationManager`: Gestor de dispositivos virtuales

**API Pública**:
```python
# Crear gestor de emulación
emulation_manager = create_device_emulation_manager()

# Crear dispositivos virtuales
success = emulation_manager.create_virtual_device('wacom', 'My Virtual Wacom')
success = emulation_manager.create_virtual_device('joystick', 'My Virtual Gamepad')

# Procesar eventos
events = [
    {'code': 'ABS_X', 'value': 1000},
    {'code': 'ABS_Y', 'value': 2000},
    {'code': 'SYN_REPORT', 'value': 0}
]
emulation_manager.process_events('wacom', events)

# Gestión
emulation_manager.destroy_virtual_device('wacom')
emulation_manager.destroy_all_devices()

# Información
active_devices = emulation_manager.get_active_devices()
device_info = emulation_manager.get_device_info('wacom')
capabilities = emulation_manager.get_capabilities()  # ['wacom', 'joystick']
```

## `transwacom.py` Refactorizado

El archivo principal ahora usa los módulos y proporciona dos interfaces principales:

### Clases Principales
- `TransWacomHost`: Implementación del lado Host
- `TransWacomConsumer`: Implementación del lado Consumer

### Funcionalidad Host
```python
host = TransWacomHost()

# Listar dispositivos
host.list_devices()

# Descubrimiento interactivo
host.run_discovery()  # Descubre consumers y muestra menú

# Conexión directa
host.connect_to_consumer(address, port, device_path)
host.disconnect()
```

### Funcionalidad Consumer
```python
consumer = TransWacomConsumer()

# Iniciar servicio
consumer.start_service(port=3333)  # Inicia servidor TCP y mDNS
consumer.stop_service()
```

## Uso desde Línea de Comandos

### Modo Host
```bash
# Descubrimiento interactivo
python transwacom.py --host --discover

# Conexión directa
python transwacom.py --host --connect 192.168.1.100:3333 --device /dev/input/event11

# Listar dispositivos
python transwacom.py --list-devices

# Con opciones específicas
python transwacom.py --host --connect 192.168.1.100:3333 --no-relative-mode --no-disable-local
```

### Modo Consumer
```bash
# Iniciar consumer
python transwacom.py --consumer --port 3333

# Con puerto específico
python transwacom.py --consumer --port 5555
```

### Compatibilidad con Versión Original
```bash
# Los comandos originales siguen funcionando
python transwacom.py --server --host 192.168.1.100 --device /dev/input/event11
python transwacom.py --client --port 3333
```

## Dependencias

```
evdev>=1.3.0       # Eventos de entrada
zeroconf>=0.38.0   # mDNS discovery
pyyaml>=6.0        # Configuración YAML
```

Dependencias opcionales futuras:
```
pystray            # System tray GUI
Pillow             # Iconos para tray
```

## Ejemplos de Uso

Ver `examples.py` para ejemplos detallados de uso de cada módulo independientemente.

## Flujo de Operación Completo

1. **Consumer** inicia servicio: `python transwacom.py --consumer`
   - Carga configuración desde YAML
   - Publica servicio mDNS `_input-consumer._tcp.local.`
   - Inicia servidor TCP en puerto configurado
   - Muestra estado en consola

2. **Host** descubre consumers: `python transwacom.py --host --discover`
   - Detecta dispositivos de entrada disponibles
   - Busca consumers via mDNS
   - Muestra menú interactivo para selección

3. **Conexión establecida**:
   - Host envía handshake con información de dispositivos
   - Consumer evalúa autorización (manual o automática según configuración)
   - Si acepta: consumer responde y crea dispositivos virtuales
   - Host configura dispositivo físico (modo relativo, desactivar local)

4. **Streaming de eventos**:
   - Host captura eventos del dispositivo físico
   - Convierte eventos a formato JSON estándar
   - Envía por TCP al consumer
   - Consumer procesa eventos en dispositivos virtuales

5. **Desconexión**:
   - Host restaura configuración original del dispositivo
   - Consumer destruye dispositivos virtuales
   - Ambos limpian recursos de red

## Ventajas de la Refactorización

- **Modularidad**: Cada módulo tiene responsabilidades claras
- **Testabilidad**: Módulos pueden ser probados independientemente
- **Extensibilidad**: Fácil agregar nuevos tipos de dispositivos o protocolos
- **Mantenibilidad**: Código más organizado y documentado
- **Configurabilidad**: Sistema de configuración robusto con YAML
- **Seguridad**: Sistema de autorización con fingerprints de máquina
- **Compatibilidad**: Mantiene compatibilidad con interfaz original

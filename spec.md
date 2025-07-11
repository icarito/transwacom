# TransWacom - Especificación de Sistema de Compartición de Dispositivos

## Resumen
Sistema para compartir dispositivos de entrada (tabletas Wacom, joysticks) por red con GUI de system tray.

## Arquitectura y Nomenclatura

### Componentes
- **Host**: Máquina con dispositivo físico (Cliente TCP, inicia conexiones)
- **Consumer**: Máquina que emula dispositivo (Servidor TCP, escucha conexiones)

### Módulos a Crear
```
transwacom/
├── tray_app.py                    # GUI principal (pystray)
├── host_input.py                  # Captura eventos del dispositivo físico
├── consumer_device_emulation.py   # Emulación con uinput
├── transnetwork.py               # Protocolo TCP y mDNS
├── config_manager.py             # Configuración y autorizaciones
└── device_detector.py            # Auto-detección de dispositivos
```

## Protocolo de Red

### mDNS Discovery
- **Consumer** publica: `_input-consumer._tcp.local.`
- **TXT Records**: `version=1.0`, `name=NombrePC`, `capabilities=wacom,joystick`
- **Host** descubre y muestra lista en tray menu

### Datos JSON sobre TCP
```json
// Handshake
{
  "type": "handshake",
  "host_name": "PC-Desktop",
  "devices": [{"type": "wacom", "name": "Wacom Serial", "capabilities": ["pressure"]}]
}

// Eventos
{
  "type": "event", 
  "device_type": "wacom",
  "events": [{"code": "ABS_X", "value": 1500}]
}
```

## Flujo de Operación

1. **Consumer** inicia, publica servicio mDNS, muestra tray
2. **Host** ve Consumer en menu, hace clic para conectar  
3. **Consumer** recibe conexión, muestra notificación de autorización
4. Si acepta: handshake → creación dispositivos virtuales → streaming
5. **Host** configura dispositivo (modo relativo, desactivar local)

## GUI System Tray

### Host Menu
```
🖊️ TransWacom Host
├── 📱 Dispositivos: Wacom (✓), Xbox Controller (✗)
├── 🌐 Consumers: Laptop-Gaming, Desktop-Studio  
├── ⚙️ Configuración
└── ❌ Salir
```

### Consumer Menu  
```
🖥️ TransWacom Consumer
├── 📶 Estado: Disponible (puerto 3333)
├── 🔗 Conexiones: Wacom desde Juan-Desktop
├── ⚙️ Configuración  
└── ❌ Salir
```

## Configuración y Autorizaciones

### Archivo YAML
```yaml
host:
  trusted_consumers:
    "Laptop-Gaming":
      auto_accept: true
      allowed_devices: ["wacom", "joystick"]

consumer:
  network:
    port: 3333
    mdns_name: "Mi-PC"
  trusted_hosts:
    "Desktop-Main":
      auto_accept: true
```

### Sistema de Confianza
- Primera conexión: Consumer muestra notificación con [Accept][Decline][Trust]
- Hosts confiables: auto-conexión
- Fingerprinting: ID único por máquina

## Gestión de Dispositivos

### Host (host_input.py)
- Auto-detección con `libwacom-list-local-devices`
- Configuración automática: modo relativo, desactivar local
- Restauración al desconectar

### Consumer (consumer_device_emulation.py)  
- Creación dispositivos virtuales (uinput)
- Soporte tabletas: presión, inclinación, botones
- Soporte gamepads: sticks, triggers, d-pad

## Dependencias
```
pystray           # System tray
evdev            # Input events  
zeroconf         # mDNS
Pillow           # Iconos
pyyaml           # Configuración
```

## Casos de Uso
- **Artista**: Tableta en desktop → laptop móvil
- **Gaming**: Controllers en PC → Steam Deck  
- **Presentaciones**: Tableta para anotaciones → PC proyector

## Notas de Implementación
- Solo red local (LAN)
- Linux únicamente (uinput/evdev)
- Consumer requiere permisos para /dev/uinput
- Restauración automática al desconectar
- Manejo de múltiples dispositivos simultáneos

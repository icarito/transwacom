#!/usr/bin/env python3
"""
TransWacom - System Tray GUI Application
Simplified unified application where all agents are consumers that can share and receive devices.
"""
import argparse
import sys
import time
import threading
import logging
import signal
import socket
import errno
import traceback
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
from functools import partial, wraps

# GUI dependencies
try:
    import pystray
    from PIL import Image, ImageDraw
    import gi
    gi.require_version('Notify', '0.7')
    from gi.repository import Notify
    GUI_AVAILABLE = True
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None
    Notify = None
    GUI_AVAILABLE = False

# TransWacom modules
from device_detector import create_detector
from config_manager import create_config_manager
from transnetwork import create_network, DiscoveredConsumer
from host_input import create_host_input_manager, InputEvent
from consumer_device_emulation import create_device_emulation_manager
from zeroconf import ServiceListener

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global reference to the app for signal handling
_current_app = None

# Constants
DEVICE_CHECK_INTERVAL = 5.0
DISCOVERY_UPDATE_INTERVAL = 30.0
MENU_UPDATE_DELAY = 0.5


def signal_handler(signum, frame):
    """Handle interrupt signals to ensure proper cleanup."""
    global _current_app
    logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    
    if _current_app:
        # The _quit method handles all cleanup and stops the icon loop.
        # This is more graceful than emergency_cleanup() + sys.exit().
        _current_app._quit()
    # Let the application exit naturally after the main loop is stopped.


class TrayIcon:
    """Base class for system tray icons."""
    
    def __init__(self):
        self.icon = None
        self.is_running = False
        
        if not GUI_AVAILABLE:
            raise RuntimeError("GUI dependencies not available. Install with: pip install pystray Pillow plyer")
        
    def create_icon_image(self, color: str = "blue", status: str = "idle") -> Image.Image:
        """Create a simple icon image."""
        # Use a simple approach - create basic geometric shapes
        image = Image.new('RGB', (64, 64), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)
        
        # Define colors
        colors = {
            "blue": (70, 130, 180),
            "green": (60, 179, 113), 
            "orange": (255, 140, 0),
            "red": (220, 20, 60),
            "gray": (128, 128, 128)
        }
        
        main_color = colors.get(color, colors["blue"])
        
        # Draw main rectangle
        draw.rectangle([8, 8, 56, 56], fill=main_color, outline=(50, 50, 50))
        
        # Draw "TW" text for TransWacom
        try:
            draw.text((20, 25), "TW", fill=(255, 255, 255))
        except:
            # Fallback if font issues
            draw.rectangle([20, 25, 25, 35], fill=(255, 255, 255))
            draw.rectangle([30, 25, 35, 35], fill=(255, 255, 255))
        
        # Draw status indicator
        if status == "connected":
            draw.ellipse([48, 8, 60, 20], fill=colors["green"])
        elif status == "error":
            draw.ellipse([48, 8, 60, 20], fill=colors["red"])
        elif status == "available":
            draw.ellipse([48, 8, 60, 20], fill=colors["orange"])
            
        return image
    


    _glib_loop_started = False
    _active_notifications = []  # Para evitar GC prematuro

    def _ensure_glib_loop(self):
        """Inicia el loop de GLib en un hilo si no está corriendo."""
        if not self._glib_loop_started:
            try:
                import gi
                from gi.repository import GLib
                import threading
                def run_loop():
                    logger.info("[GLib] MainLoop iniciado en hilo de fondo")
                    loop = GLib.MainLoop()
                    loop.run()
                t = threading.Thread(target=run_loop, daemon=True)
                t.start()
                self._glib_loop_started = True
            except Exception as e:
                logger.error(f"No se pudo iniciar el loop de GLib: {e}")

    def show_notification(self, title: str, message: str, timeout: int = 5, actions: Optional[list] = None):
        """
        Show desktop notification using GTK3 Notify.
        If actions is provided, it should be a list of tuples: (action_id, label, callback)
        """
        try:
            logger.info(f"[NOTIFY] Mostrando notificación: {title} - {message} (acciones: {bool(actions)})")
            self._ensure_glib_loop()
            if Notify is None:
                raise RuntimeError("Notify (gi.repository) is not available")
            # Init libnotify if not already
            if not Notify.is_initted():
                Notify.init("TransWacom")
            notification = Notify.Notification.new(title, message)
            notification.set_timeout(timeout * 1000)  # ms
            # Guardar referencia para evitar GC
            self._active_notifications.append(notification)
            # Add actions if provided
            if actions:
                for action_id, label, callback in actions:
                    logger.info(f"[NOTIFY] Agregando acción: {action_id} - {label}")
                    notification.add_action(action_id, label, callback, None)
            notification.show()
            logger.info(f"[NOTIFY] Notificación mostrada (obj: {id(notification)})")
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")
    
    def start(self):
        """Start the tray icon."""
        if self.icon:
            self.is_running = True
            self.icon.run()
    
    def stop(self):
        """Stop the tray icon."""
        self.is_running = False
        if self.icon:
            self.icon.stop()


class TransWacomTrayApp(TrayIcon):
    """Unified TransWacom application - all agents are consumers that can share and receive devices."""
    
    def __init__(self):
        super().__init__()
        self.config = create_config_manager()
        self.detector = create_detector()
        self.network = create_network()
        self.input_manager = create_host_input_manager()
        self.device_manager = create_device_emulation_manager()
        
        # State
        self.discovered_consumers: Dict[str, Any] = {}
        self.outgoing_connections: Dict[str, Any] = {}  # Connections we initiated (as host)
        self.incoming_connections: List[str] = []  # Connections to us (as consumer)
        self.local_devices = []
        self.is_listening = False
        self.port = self.config.get_consumer_port()
        self.server_socket = None
        self._updating_menu = False
        self._menu_update_timer = None
        
        # Auto-update setup
        self._stale_check_timer = None
        self._device_check_timer = None
        
        # Setup network discovery
        self._setup_discovery()
        
        # Setup server
        self._setup_server()
        
        # Create tray icon
        self._create_tray_icon()
        
        # Start services
        self._start_services()
        
        # Start auto-updates
        self._start_auto_updates()
        
    def _setup_discovery(self):
        """Setup mDNS discovery for other consumers."""
        try:
            my_mdns_name = self.config.get_mdns_name()

            def on_consumer_discovered(consumer: DiscoveredConsumer):
                # Filter out ourselves by comparing the advertised name and port
                if consumer.name == my_mdns_name and consumer.port == self.port:
                    logger.debug(f"Ignoring self in discovery: {consumer.name}")
                    return
                    
                is_new = consumer.unique_id not in self.discovered_consumers
                has_changed = not is_new and self.discovered_consumers[consumer.unique_id]['consumer'] != consumer

                if is_new or has_changed:
                    logger.info(f"Discovered/Updated consumer: {consumer.name} at {consumer.address}:{consumer.port}")
                    self._schedule_menu_update()

                # Always update the timestamp to keep it fresh
                self.discovered_consumers[consumer.unique_id] = {
                    'consumer': consumer,
                    'timestamp': time.time()
                }
                
            # Start discovery
            success = self.network.discover_consumers(on_consumer_discovered)

            # WORKAROUND: Patch the internal zeroconf listener to prevent crashes.
            # The root cause is a missing `update_service` method in the listener
            # inside the `transnetwork` module. This patch makes `update_service`
            # behave like `add_service`, fixing both the crash and the stale consumer issue.
            if success and hasattr(self.network, 'listener') and self.network.listener is not None:
                listener = self.network.listener
                # Check if the update_service method is the default, unimplemented one from the base class.
                # This is more robust than checking for `__func__` which can fail with Cython-compiled methods.
                if isinstance(listener, ServiceListener) and type(listener).update_service is ServiceListener.update_service:
                    logger.info("Applying workaround: Patching zeroconf listener's update_service to prevent crashes.")
                    listener.update_service = listener.add_service

            if not success:
                logger.warning("mDNS discovery not available - will work only with manual connections")
        except Exception as e:
            logger.error(f"Failed to setup discovery: {e}")
    
    def _setup_server(self):
        """Setup TCP server for incoming connections."""
        try:
            # FIX: The callback should return the host_name on success (a truthy value)
            # or None on failure. This gives the network layer the necessary info
            # to register the connection properly in its active_connections list.
            def auth_callback(handshake: dict) -> Optional[str]:
                host_name = handshake.get('host_name', 'Unknown')
                host_id = handshake.get('host_id', '')
                devices = handshake.get('devices', [])
                device_names = [d.get('name', 'Unknown Device') for d in devices]

                # Si es host confiable y auto-aceptar, no preguntar
                if self.config.is_host_trusted(host_name, host_id):
                    if self.config.should_auto_accept_host(host_name):
                        logger.info(f"Auto-accepting trusted host: {host_name}")
                        self._add_incoming_connection(host_name) # Update UI
                        return host_name # Return hostname on success

                # Sin trusted: pedir confirmación interactiva
                logger.info(f"Esperando autorización del usuario para {host_name} ({', '.join(device_names)})")
                user_decision = {'result': None} # Can store hostname, False, or None
                event = threading.Event()


                # Usar GLib.idle_add para asegurar ejecución en hilo principal de Python
                import gi
                from gi.repository import GLib

                def on_accept(notification, action, data=None):
                    logger.info(f"[NOTIFY] CALLBACK: Usuario aceptó la conexión de {host_name}")
                    def set_accept():
                        logger.info(f"[NOTIFY] set_accept ejecutado para {host_name}")
                        user_decision['result'] = host_name # Store hostname on accept
                        self._add_incoming_connection(host_name)
                        event.set()
                    GLib.idle_add(set_accept)

                def on_reject(notification, action, data=None):
                    logger.info(f"[NOTIFY] CALLBACK: Usuario rechazó la conexión de {host_name}")
                    def set_reject():
                        logger.info(f"[NOTIFY] set_reject ejecutado para {host_name}")
                        user_decision['result'] = False # Use False for explicit rejection
                        event.set()
                    GLib.idle_add(set_reject)

                actions = [
                    ("accept", "Aceptar", on_accept),
                    ("reject", "Rechazar", on_reject)
                ]
                self.show_notification(
                    "Nueva Conexión",
                    f"{host_name} quiere compartir: {', '.join(device_names)}",
                    timeout=30,
                    actions=actions
                )

                # Esperar la decisión del usuario (máximo 30s)
                event.wait(timeout=30)
                
                if user_decision['result'] is False or user_decision['result'] is None:
                    logger.info(f"Solicitud de conexión de {host_name} rechazada o sin respuesta")
                    return None
                else:
                    return user_decision['result'] # Return hostname or None
            
            def event_callback(device_type: str, events: list):
                try:
                    self.device_manager.process_events(device_type, events)
                except Exception as e:
                    logger.error(f"Failed to process events: {e}")
            
            self.server_socket = self.network.create_consumer_server(
                self.port, 
                auth_callback, 
                event_callback
            )
            
            self.is_listening = True
            logger.info(f"Consumer server started on port {self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
    
    def _start_services(self):
        """Start mDNS advertising and other services."""
        try:
            # Determine capabilities
            capabilities = []
            consumer_config = self.config.config.get('consumer', {})
            devices_config = consumer_config.get('devices', {})
            
            if devices_config.get('wacom_enabled', True):
                capabilities.append('wacom')
            if devices_config.get('joystick_enabled', True):
                capabilities.append('joystick')
            
            # Start advertising
            mdns_name = self.config.get_mdns_name()
            success = self.network.publish_consumer_service(
                mdns_name,
                self.port,
                capabilities
            )
            
            if success:
                logger.info(f"mDNS service published: {mdns_name}")
            else:
                logger.warning("mDNS advertising not available")
            
        except Exception as e:
            logger.error(f"Failed to start services: {e}")
    
    def _start_auto_updates(self):
        """Start automatic background updates."""
        def update_devices():
            try:
                # Compare based on a stable representation to avoid updates from new object instances
                new_devices = self.detector.detect_all_devices()
                new_device_paths = sorted([d.path for d in new_devices])
                old_device_paths = sorted([d.path for d in self.local_devices])
                
                if new_device_paths != old_device_paths:
                    self.local_devices = new_devices
                    logger.info(f"Device list changed. New count: {len(self.local_devices)}")
                    self._update_icon_status()
                    self._schedule_menu_update()
            except Exception as e:
                logger.error(f"Error updating devices: {e}")
            finally:
                # Schedule next update
                self._device_check_timer = threading.Timer(DEVICE_CHECK_INTERVAL, update_devices)
                self._device_check_timer.start()

        def check_stale_consumers():
            try:
                now = time.time()
                # A consumer is stale if not seen for 2.5x the discovery interval
                stale_timeout = DISCOVERY_UPDATE_INTERVAL * 2.5
                stale_keys = [
                    key for key, data in self.discovered_consumers.items()
                    if now - data.get('timestamp', 0) > stale_timeout
                ]
                if stale_keys:
                    logger.info(f"Removing {len(stale_keys)} stale consumer(s): {', '.join(stale_keys)}")
                    for key in stale_keys:
                        del self.discovered_consumers[key]
                    self._schedule_menu_update()
            except Exception as e:
                logger.error(f"Error checking for stale consumers: {e}")
            finally:
                self._stale_check_timer = threading.Timer(DISCOVERY_UPDATE_INTERVAL, check_stale_consumers)
                self._stale_check_timer.start()

        # Initial device scan
        update_devices()
        check_stale_consumers()
    
    def _add_incoming_connection(self, host_name: str):
        """Add an incoming connection to the active list."""
        if host_name not in self.incoming_connections:
            self.incoming_connections.append(host_name)
            
            self.show_notification(
                "Conexión Establecida",
                f"Recibiendo dispositivos de {host_name}"
            )
            
            self._update_icon_status()
            self._schedule_menu_update()
    
    def _update_icon_status(self):
        """Update the tray icon based on current status."""
        if self.outgoing_connections or self.incoming_connections:
            # Connected
            image = self.create_icon_image("green", "connected")
        elif self.local_devices:
            # Available to share
            image = self.create_icon_image("blue", "available")
        else:
            # Idle
            image = self.create_icon_image("gray", "idle")
        
        if self.icon:
            self.icon.icon = image
    
    def _create_tray_icon(self):
        """Create the system tray icon."""
        image = self.create_icon_image("blue", "idle")
        self.icon = pystray.Icon(
            "TransWacom",
            image,
            "TransWacom",
            menu=self._create_menu()
        )
        # Ajustar el color inicial según el estado real
        self._update_icon_status()
    
    def _create_menu_connection_items(self) -> List[pystray.MenuItem]:
        """Create menu items for active connections."""
        items = []
        if self.incoming_connections:
            for host in self.incoming_connections:
                items.append(pystray.MenuItem(
                    f"📥 Recibiendo de: {host}",
                    partial(self._disconnect_incoming, host),
                    enabled=True
                ))
        
        if self.outgoing_connections:
            for consumer_id, info in self.outgoing_connections.items():
                consumer_name = info.get('name', 'Unknown')
                device_name = info.get('device_name', 'Unknown Device')
                items.append(pystray.MenuItem(
                    f"📤 Enviando {device_name} a {consumer_name}",
                    partial(self._disconnect_outgoing, consumer_id)
                ))
        return items

    def _create_menu_device_items(self) -> List[pystray.MenuItem]:
        """Create menu items for local devices that can be shared."""
        items = []
        if self.local_devices:
            for device in self.local_devices:
                if any(info.get('device_path') == device.path for info in self.outgoing_connections.values()):
                    continue
                    
                available_consumers = [
                    data['consumer'] for data in self.discovered_consumers.values()
                    if data['consumer'].unique_id not in self.outgoing_connections
                ]
                
                if available_consumers:
                    submenu_items = [
                        pystray.MenuItem(
                            f"📤 {consumer.name}",
                            partial(self._connect_device_to_consumer, device, consumer)
                        ) for consumer in available_consumers
                    ]
                    device_menu = pystray.Menu(*submenu_items)
                    items.append(pystray.MenuItem(f"🖊️ {device.name}", device_menu))
                else:
                    items.append(pystray.MenuItem(f"🖊️ {device.name} (sin consumidores)", None, enabled=False))
        #else:
        #    items.append(pystray.MenuItem("No hay dispositivos disponibles", None, enabled=False))
        return items

    def _create_menu_incoming_mgmt_items(self) -> List[pystray.MenuItem]:
        """Create menu items for managing incoming connections."""
        items = []
        if self.incoming_connections:
            items.append(pystray.MenuItem("Desconectar conexiones entrantes:", None, enabled=False))
            for host in self.incoming_connections:
                items.append(pystray.MenuItem(
                    f"❌ {host}",
                    partial(self._disconnect_incoming, host)
                ))
        return items

    def _create_menu(self) -> pystray.Menu:
        """Create the simplified tray menu."""
        try:
            menu_items = [
                pystray.MenuItem("🖊️ TransWacom", None, enabled=False),
                pystray.Menu.SEPARATOR
            ]
            
            connection_items = self._create_menu_connection_items()
            
            # If we have connections, add separator
            if connection_items:
                menu_items.extend(connection_items)
                menu_items.append(pystray.Menu.SEPARATOR)
            
            device_items = self._create_menu_device_items()
            menu_items.extend(device_items)
            
            menu_items.append(pystray.Menu.SEPARATOR)
            menu_items.append(pystray.MenuItem("❌ Salir", self._quit))
            
            return pystray.Menu(*menu_items)
            
        except Exception as e:
            logger.error(f"Error creating menu: {e}")
            # Fallback minimal menu
            return pystray.Menu(
                pystray.MenuItem("TransWacom", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Error en menú", None, enabled=False),
                pystray.MenuItem("Salir", self._quit)
            )
    
    def _connect_device_to_consumer(self, device, consumer: DiscoveredConsumer, *args, **kwargs):
        """Connect a device to a consumer."""
        def connect_async():
            try:
                logger.info(f"Connecting device {device.name} to consumer {consumer.name}")
                success = self._perform_connection(device, consumer)
                if success:
                    self.show_notification(
                        "Conexión Exitosa",
                        f"Compartiendo {device.name} con {consumer.name}"
                    )
                else:
                    self.show_notification(
                        "Error de Conexión",
                        f"No se pudo conectar {device.name} a {consumer.name}"
                    )
            except Exception as e:
                logger.error(f"Connection error: {e}")
                self.show_notification(
                    "Error de Conexión",
                    f"Error conectando a {consumer.name}: {str(e)}"
                )
        
        # Run connection in background thread
        threading.Thread(target=connect_async, daemon=True).start()
    
    def _perform_connection(self, device, consumer: DiscoveredConsumer) -> bool:
        """Perform the actual connection to consumer."""
        try:
            # Prepare handshake data
            machine_name = self.config.machine_name
            machine_id = self.config.machine_id
            device_dict = device.to_dict()
            
            handshake_data = self.network.protocol.create_handshake(
                host_name=machine_name,
                host_id=machine_id,
                devices=[device_dict]
            )
            
            # Connect to consumer
            connection = self.network.connect_to_consumer(
                consumer.address, 
                consumer.port,
                handshake_data
            )
            
            if connection:
                # Store connection info
                self.outgoing_connections[consumer.unique_id] = {
                    'connection': connection,
                    'consumer': consumer,
                    'device': device,
                    'device_path': device.path,
                    'device_name': device.name,
                    'name': consumer.name
                }
                
                # Start input capture
                def event_callback(device_type: str, events: List[InputEvent]):
                    if consumer.unique_id in self.outgoing_connections:
                        logger.debug(f"Sending {len(events)} events of type {device_type}")
                        event_dicts = [event.to_dict() for event in events]
                        success = self.network.send_events(connection, device_type, event_dicts)
                        if not success:
                            logger.warning(f"Lost connection to {consumer.name}")
                            self._disconnect_outgoing(consumer.unique_id)
                
                # Configure capture settings
                relative_mode = self.config.should_use_relative_mode()
                # Forzar desactivar local siempre desde el tray
                disable_local = True
                logger.info(f"[TRAY] Llamando a start_capture con disable_local={disable_local}, relative_mode={relative_mode}")
                success = self.input_manager.start_capture(
                    device.path, event_callback, relative_mode, disable_local
                )
                
                if success:
                    self._update_icon_status()
                    self._schedule_menu_update()
                    return True
                else:
                    # Clean up failed connection
                    self.network.disconnect_from_consumer(connection)
                    del self.outgoing_connections[consumer.unique_id]
                    return False
            
            return False
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False
    
    def _disconnect_outgoing(self, consumer_id: str, *args, **kwargs):
        """Disconnect an outgoing connection."""
        if consumer_id in self.outgoing_connections:
            del self.outgoing_connections[consumer_id]
            self.show_notification(
                "Conexión Finalizada",
                f"Se ha desconectado del consumidor {consumer_id}"
            )
            self._update_icon_status()
            self._schedule_menu_update()
    
    def _disconnect_incoming(self, host_name: str, *args, **kwargs):
        """Disconnect an incoming connection."""
        if host_name in self.incoming_connections:
            self.incoming_connections.remove(host_name)
            # Agregar registro para depuración
            logger.info(f"Intentando desconectar {host_name}. Conexiones activas: {list(self.network.active_connections.keys())}")
            # Buscar el socket asociado al host_name
            # BUGFIX: La clave de active_connections es la dirección del par (IP:puerto), no el hostname.
            # Debemos buscar en los detalles de la conexión, donde el hostname debería estar almacenado.
            peer_addr = next((addr for addr, conn_info in self.network.active_connections.items() if conn_info.get('host_name') == host_name), None)
            if peer_addr and peer_addr in self.network.active_connections:
                sock = self.network.active_connections[peer_addr]['socket']
                self.network.disconnect_from_consumer(sock)  # Cerrar conexión de red
            else:
                logger.warning(f"No se encontró una conexión activa para {host_name} o ya fue cerrada.")
            self.show_notification(
                "Conexión Finalizada",
                f"Se ha desconectado de {host_name}"
            )
            self._update_icon_status()
            self._schedule_menu_update()
    
    def _schedule_menu_update(self):
        """Schedule a menu update with a small delay to avoid rapid updates, only if menu is visible."""
        if self._menu_update_timer:
            self._menu_update_timer.cancel()
        self._menu_update_timer = threading.Timer(MENU_UPDATE_DELAY, self._update_menu)
        self._menu_update_timer.start()
    
    def _update_menu(self):
        """Update the tray menu."""
        if self.icon and not self._updating_menu:
            self._updating_menu = True
            try:
                self.icon.menu = self._create_menu()
            except Exception as e:
                logger.error(f"Error updating menu: {e}")
            finally:
                self._updating_menu = False
    
    def _cleanup_resources(self, full_shutdown: bool = False):
        """Common cleanup logic for stopping services and connections."""
        logger.info("Cleaning up resources...")
        
        # Cancel timers
        if self._menu_update_timer: self._menu_update_timer.cancel()
        if self._device_check_timer: self._device_check_timer.cancel()
        if self._stale_check_timer: self._stale_check_timer.cancel()
        
        # Stop all captures first to release local physical devices (host part)
        if hasattr(self, 'input_manager'):
            self.input_manager.stop_all_captures()

        # Destroy all emulated devices to clean up virtual ones (consumer part)
        if hasattr(self, 'device_manager'):
            self.device_manager.destroy_all_devices()
        
        # Close outgoing connections
        for info in self.outgoing_connections.values():
            try:
                self.network.disconnect_from_consumer(info['connection'])
            except Exception as e:
                logger.error(f"Error closing outgoing connection: {e}")
        self.outgoing_connections.clear()
        
        # Clear incoming connections state
        self.incoming_connections.clear()
        
        if full_shutdown:
            # Stop server
            if self.server_socket:
                try: self.server_socket.close()
                except Exception as e: logger.error(f"Error stopping server: {e}")
            
            # Stop advertising and discovery
            try: self.network.unpublish_consumer_service()
            except Exception as e: logger.error(f"Error stopping advertising: {e}")
            
            try: self.network.stop_discovery()
            except Exception as e: logger.error(f"Error stopping discovery: {e}")

    def _quit(self, icon=None, item=None):
        """Quit the application."""
        logger.info("Quitting application...")
        self._cleanup_resources(full_shutdown=True)
        logger.info("Stopping tray application...")
        self.stop()
    
    def _emergency_cleanup(self):
        """Emergency cleanup to restore device states."""
        logger.info("Performing emergency cleanup...")
        try:
            self._cleanup_resources(full_shutdown=False)
            logger.info("Emergency cleanup completed")
        except Exception as e:
            logger.error(f"Error during emergency cleanup: {e}")


def main():
    """Main entry point for the tray application."""
    global _current_app
    
    parser = argparse.ArgumentParser(description='TransWacom System Tray Application')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Check GUI availability
    if not GUI_AVAILABLE:
        print("Error: GUI dependencies not available.")
        print("Install with: pip install pystray Pillow plyer")
        sys.exit(1)
    
    # Register signal handlers for proper cleanup
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Create unified app
        app = TransWacomTrayApp()
        _current_app = app  # Store global reference for signal handling
        logger.info("Starting TransWacom unified application")
        
        # Start the application
        logger.info("Starting system tray application...")
        app.start()
        
    except KeyboardInterrupt:
        logger.info("Application interrupted by user (KeyboardInterrupt)")
        if _current_app:
            _current_app._quit()
    except Exception as e:
        logger.error(f"Application error: {e}")
        if _current_app:
            _current_app._emergency_cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
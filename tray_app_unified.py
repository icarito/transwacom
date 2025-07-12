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
    from plyer import notification
    GUI_AVAILABLE = True
except ImportError:
    pystray = None
    Image = None
    ImageDraw = None  
    notification = None
    GUI_AVAILABLE = False

# TransWacom modules
from device_detector import create_detector
from config_manager import create_config_manager
from transnetwork import create_network, DiscoveredConsumer
from host_input import create_host_input_manager, InputEvent
from consumer_device_emulation import create_device_emulation_manager

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
    logger.info(f"Received signal {signum}, cleaning up...")
    
    if _current_app:
        try:
            # Force cleanup
            _current_app._emergency_cleanup()
        except Exception as e:
            logger.error(f"Error during emergency cleanup: {e}")
    
    sys.exit(0)


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
    
    def show_notification(self, title: str, message: str, timeout: int = 5):
        """Show desktop notification."""
        try:
            notification.notify(
                title=title,
                message=message,
                timeout=timeout,
                app_name="TransWacom"
            )
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
        self.discovered_consumers: Dict[str, DiscoveredConsumer] = {}
        self.outgoing_connections: Dict[str, Any] = {}  # Connections we initiated (as host)
        self.incoming_connections: List[str] = []  # Connections to us (as consumer)
        self.local_devices = []
        self.is_listening = False
        self.port = self.config.get_consumer_port()
        self.server_socket = None
        self._updating_menu = False
        self._menu_update_timer = None
        
        # Auto-update setup
        self._discovery_timer = None
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
            def on_consumer_discovered(consumer: DiscoveredConsumer):
                # Filter out ourselves
                if consumer.address == "127.0.0.1" and consumer.port == self.port:
                    return
                    
                self.discovered_consumers[consumer.unique_id] = consumer
                logger.info(f"Discovered consumer: {consumer.name} at {consumer.address}:{consumer.port}")
                self._schedule_menu_update()
                
            # Start discovery
            success = self.network.discover_consumers(on_consumer_discovered)
            if not success:
                logger.warning("mDNS discovery not available - will work only with manual connections")
        except Exception as e:
            logger.error(f"Failed to setup discovery: {e}")
    
    def _setup_server(self):
        """Setup TCP server for incoming connections."""
        try:
            def auth_callback(handshake: dict) -> bool:
                host_name = handshake.get('host_name', 'Unknown')
                host_id = handshake.get('host_id', '')
                devices = handshake.get('devices', [])
                
                # Show authorization notification
                device_names = [d.get('name', 'Unknown Device') for d in devices]
                
                self.show_notification(
                    "Nueva Conexión",
                    f"{host_name} quiere compartir: {', '.join(device_names)}",
                    timeout=15
                )
                
                # Check if host is trusted
                if self.config.is_host_trusted(host_name, host_id):
                    if self.config.should_auto_accept_host(host_name):
                        logger.info(f"Auto-accepting trusted host: {host_name}")
                        self._add_incoming_connection(host_name)
                        return True
                
                # For now, auto-accept (in a real implementation, show dialog)
                logger.info(f"Accepting connection request from {host_name} for devices: {device_names}")
                self._add_incoming_connection(host_name)
                return True
            
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
                new_devices = self.detector.detect_all_devices()
                if new_devices != self.local_devices:
                    self.local_devices = new_devices
                    logger.debug(f"Updated device list: {len(self.local_devices)} devices")
                    self._schedule_menu_update()
            except Exception as e:
                logger.error(f"Error updating devices: {e}")
            finally:
                # Schedule next update
                self._device_check_timer = threading.Timer(DEVICE_CHECK_INTERVAL, update_devices)
                self._device_check_timer.start()
        
        def update_discovery():
            try:
                # Restart discovery periodically to catch new consumers
                self.network.stop_discovery() # type: ignore
                time.sleep(0.1)
                self._setup_discovery()
            except Exception as e:
                logger.error(f"Error updating discovery: {e}")
            finally:
                # Schedule next discovery update
                self._discovery_timer = threading.Timer(DISCOVERY_UPDATE_INTERVAL, update_discovery)
                self._discovery_timer.start()
        
        # Initial device scan
        update_devices()
        
        # Start discovery updates
        update_discovery()
    
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
    
    def _create_menu_connection_items(self) -> List[pystray.MenuItem]:
        """Create menu items for active connections."""
        items = []
        if self.incoming_connections:
            for host in self.incoming_connections:
                items.append(pystray.MenuItem(f"📥 Recibiendo de: {host}", None, enabled=False))
        
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
                    consumer for consumer in self.discovered_consumers.values()
                    if consumer.unique_id not in self.outgoing_connections
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
        else:
            items.append(pystray.MenuItem("No hay dispositivos disponibles", None, enabled=False))
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
            
            # Incoming connections management
            incoming_mgmt_items = self._create_menu_incoming_mgmt_items()
            if incoming_mgmt_items:
                menu_items.append(pystray.Menu.SEPARATOR)
                menu_items.extend(incoming_mgmt_items)
            
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
            try:
                info = self.outgoing_connections.pop(consumer_id)
                
                # Stop input capture
                self.input_manager.stop_capture(info['device_path'])
                
                # Close network connection
                self.network.disconnect_from_consumer(info['connection'])

                self.show_notification(
                    "Desconectado",
                    f"Desconectado de {info['name']}"
                )
                
                self._update_icon_status()
                self._schedule_menu_update()
                
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
                # If pop failed or something else went wrong, ensure state is clean
                if consumer_id in self.outgoing_connections:
                    del self.outgoing_connections[consumer_id]
    
    def _disconnect_incoming(self, host_name: str, *args, **kwargs):
        """Disconnect an incoming connection."""
        if host_name in self.incoming_connections:
            try:
                self.incoming_connections.remove(host_name)
                # Desconexión real del socket
                self.network.disconnect_incoming_host(host_name)
                self.show_notification(
                    "Desconectado",
                    f"Desconectado de {host_name}"
                )
                self._update_icon_status()
                self._schedule_menu_update()
            except Exception as e:
                logger.error(f"Error disconnecting incoming: {e}")
    
    def _schedule_menu_update(self):
        """Schedule a menu update with a small delay to avoid rapid updates, only if menu is visible."""
        # pystray no expone si el menú está abierto, así que solo actualizamos si el icono está visible
        if self.icon and hasattr(self.icon, 'visible') and not self.icon.visible:
            return  # No actualizar si el icono no está visible
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
        if self._discovery_timer: self._discovery_timer.cancel()
        
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

    def _quit(self, icon, item):
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
        logger.info("Application interrupted by user")
        if _current_app:
            _current_app._emergency_cleanup()
    except Exception as e:
        logger.error(f"Application error: {e}")
        if _current_app:
            _current_app._emergency_cleanup()
        sys.exit(1)


if __name__ == "__main__":
    main()
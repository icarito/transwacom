#!/usr/bin/env python3
"""
TransWacom - System Tray GUI Application
Main GUI application with system tray interface for both Host and Consumer modes.
"""
import argparse
import sys
import time
import threading
import logging
import signal
import socket
from typing import Dict, List, Optional, Callable, Any
from pathlib import Path
from functools import partial

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


class HostTrayApp(TrayIcon):
    """Host mode system tray application."""
    
    def __init__(self):
        super().__init__()
        self.config = create_config_manager()
        self.detector = create_detector()
        self.network = create_network()
        self.input_manager = create_host_input_manager()
        
        # State
        self.discovered_consumers: Dict[str, DiscoveredConsumer] = {}
        self.active_connection = None
        self.active_socket = None  # Store the actual socket for connection monitoring
        self.local_devices = []
        self._updating_menu = False  # Flag to prevent recursion
        self._menu_update_timer = None  # Timer for delayed updates
        self._connection_monitor_timer = None  # Timer for connection monitoring
        
        # Setup network discovery
        self._setup_discovery()
        
        # Create tray icon
        self._create_tray_icon()
        
        # Start device detection
        self._update_devices()
        
    def _setup_discovery(self):
        """Setup mDNS discovery for consumers."""
        try:
            def on_consumer_discovered(consumer: DiscoveredConsumer):
                logger.info(f"Discovered consumer: {consumer.name} at {consumer.address}:{consumer.port}")
                self.discovered_consumers[consumer.name] = consumer
                self._schedule_menu_update()
                
            # Start discovery
            success = self.network.discover_consumers(on_consumer_discovered)
            if not success:
                logger.warning("mDNS discovery not available")
        except Exception as e:
            logger.error(f"Failed to setup discovery: {e}")
    
    def _update_devices(self):
        """Update the list of local devices."""
        try:
            self.local_devices = self.detector.detect_all_devices()
            logger.info(f"Detected {len(self.local_devices)} local devices")
            self._schedule_menu_update()
        except Exception as e:
            logger.error(f"Failed to detect devices: {e}")
    
    def _create_tray_icon(self):
        """Create the system tray icon."""
        image = self.create_icon_image("blue", "idle")
        
        self.icon = pystray.Icon(
            "TransWacom Host",
            image,
            "TransWacom Host",
            menu=self._create_menu()
        )
    
    def _create_menu(self) -> pystray.Menu:
        """Create the tray menu."""
        try:
            menu_items = []
            
            # Title
            menu_items.append(pystray.MenuItem("🖊️ TransWacom Host", None, enabled=False))
            menu_items.append(pystray.Menu.SEPARATOR)
            
            # Device status
            if self.active_connection:
                menu_items.append(pystray.MenuItem("📶 Estado: Conectado", None, enabled=False))
            else:
                menu_items.append(pystray.MenuItem("📶 Estado: Disponible", None, enabled=False))
            
            menu_items.append(pystray.Menu.SEPARATOR)
            
            # Devices section
            menu_items.append(pystray.MenuItem("📱 Dispositivos Locales:", None, enabled=False))
            if self.local_devices:
                for i, device in enumerate(self.local_devices):
                    if i >= 5:  # Limit to first 5 devices
                        menu_items.append(pystray.MenuItem(f"  ... y {len(self.local_devices)-5} más", None, enabled=False))
                        break
                    status = "✓" if self.active_connection else "○"
                    device_name = f"  {status} {device.name}"
                    menu_items.append(pystray.MenuItem(device_name, None, enabled=False))
            else:
                menu_items.append(pystray.MenuItem("  No hay dispositivos", None, enabled=False))
            
            menu_items.append(pystray.Menu.SEPARATOR)
            
            # Consumer section  
            menu_items.append(pystray.MenuItem("🌐 Consumers:", None, enabled=False))
            if self.discovered_consumers:
                consumer_count = len(self.discovered_consumers)
                if consumer_count > 0:
                    # Show only first consumer and count
                    first_consumer_name = list(self.discovered_consumers.keys())[0]
                    menu_items.append(pystray.MenuItem(f"  📺 {first_consumer_name}", None, enabled=False))
                    
                    if consumer_count > 1:
                        menu_items.append(pystray.MenuItem(f"  ... y {consumer_count-1} más", None, enabled=False))
                    
                    # Simple connection option
                    if self.local_devices and not self.active_connection:
                        menu_items.append(pystray.MenuItem("� Conectar al primero", self._connect_simple))
            else:
                menu_items.append(pystray.MenuItem("  Buscando...", None, enabled=False))
            
            menu_items.append(pystray.Menu.SEPARATOR)
            
            # Actions
            if self.active_connection:
                menu_items.append(pystray.MenuItem("❌ Desconectar", self._disconnect))
            
            menu_items.append(pystray.MenuItem("🔄 Actualizar", self._refresh_devices))
            menu_items.append(pystray.MenuItem("⚙️ Configuración", self._open_config))
            menu_items.append(pystray.MenuItem("❌ Salir", self._quit))
            
            return pystray.Menu(*menu_items)
            
        except Exception as e:
            logger.error(f"Error creating menu: {e}")
            # Fallback minimal menu
            return pystray.Menu(
                pystray.MenuItem("TransWacom Host", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Error en menú", None, enabled=False),
                pystray.MenuItem("Salir", self._quit)
            )
    
    def _create_consumer_submenu(self, consumer: DiscoveredConsumer) -> pystray.Menu:
        """Create submenu for a specific consumer."""
        submenu_items = []
        
        # Consumer info
        submenu_items.append(pystray.MenuItem(f"📍 {consumer.address}:{consumer.port}", None, enabled=False))
        submenu_items.append(pystray.MenuItem(f"🔧 {', '.join(consumer.capabilities)}", None, enabled=False))
        submenu_items.append(pystray.Menu.SEPARATOR)
        
        # Connect actions for each device
        if self.local_devices and not self.active_connection:
            for device in self.local_devices:
                submenu_items.append(pystray.MenuItem(f"📱 Conectar {device.name}", self._connect_device_simple))
        elif self.active_connection:
            submenu_items.append(pystray.MenuItem("✓ Conectado", None, enabled=False))
            submenu_items.append(pystray.MenuItem("❌ Desconectar", self._disconnect))
        else:
            submenu_items.append(pystray.MenuItem("No hay dispositivos disponibles", None, enabled=False))
        
        return pystray.Menu(*submenu_items)
    
    def _connect_simple(self, icon, item):
        """Simple connection - connects first device to first consumer."""
        try:
            if self.local_devices and self.discovered_consumers and not self.active_connection:
                device = self.local_devices[0]
                consumer = list(self.discovered_consumers.values())[0]
                logger.info(f"Simple connect: {device.name} -> {consumer.name}")
                self._connect_device_to_consumer(device, consumer)
            else:
                logger.warning("Cannot connect: missing devices or consumers, or already connected")
        except Exception as e:
            logger.error(f"Simple connect error: {e}")

    def _connect_to_first_consumer(self, icon, item):
        """Connect first device to first consumer."""
        self._connect_simple(icon, item)

    def _connect_device_simple(self, icon, item):
        """Simple device connection - connects first device to context consumer."""
        if self.local_devices:
            device = self.local_devices[0]
            # This is a simplified version - in a real implementation, 
            # we'd need to pass the consumer context differently
            if self.discovered_consumers:
                consumer = list(self.discovered_consumers.values())[0]
                self._connect_device_to_consumer(device, consumer)

    def _connect_device_to_consumer(self, device, consumer: DiscoveredConsumer):
        """Connect a device to a consumer."""
        def connect_async():
            try:
                logger.info(f"Connecting device {device.name} to consumer {consumer.name}")
                
                # Attempt connection using the simplified API
                success = self._perform_connection(device, consumer)
                
                if success:
                    self.active_connection = True  # Simplified state tracking
                    self.show_notification(
                        "Conexión Exitosa",
                        f"{device.name} conectado a {consumer.name}"
                    )
                    # Update icon to show connected state
                    self.icon.icon = self.create_icon_image("green", "connected")
                else:
                    self.show_notification(
                        "Error de Conexión",
                        f"No se pudo conectar {device.name} a {consumer.name}"
                    )
                
                self._schedule_menu_update()
                
            except Exception as e:
                logger.error(f"Connection error: {e}")
                self.show_notification(
                    "Error",
                    f"Error al conectar: {str(e)}"
                )
        
        # Run connection in background thread
        threading.Thread(target=connect_async, daemon=True).start()
    
    def _perform_connection(self, device, consumer: DiscoveredConsumer) -> bool:
        """Perform the actual connection to consumer."""
        try:
            logger.debug(f"Starting connection process for {device.name} -> {consumer.name}")
            
            # Prepare handshake data
            logger.debug("Getting machine name and ID from config...")
            machine_name = self.config.machine_name
            machine_id = self.config.machine_id
            logger.debug(f"Machine name: {machine_name}, ID: {machine_id}")
            
            logger.debug("Converting device to dict...")
            device_dict = device.to_dict()
            logger.debug(f"Device dict: {device_dict}")
            
            logger.debug("Creating handshake data...")
            handshake_data = self.network.protocol.create_handshake(
                host_name=machine_name,
                host_id=machine_id,
                devices=[device_dict]
            )
            logger.debug(f"Handshake data created: {handshake_data}")
            
            # Connect to consumer
            logger.debug(f"Connecting to consumer at {consumer.address}:{consumer.port}")
            connection = self.network.connect_to_consumer(
                consumer.address, 
                consumer.port,
                handshake_data
            )
            
            if connection:
                logger.debug("Connection established, setting up input capture...")
                
                # Store socket for connection monitoring
                self.active_socket = connection
                
                # Start input capturing for this device
                def event_callback(device_type: str, events):
                    try:
                        event_dicts = [event.to_dict() for event in events]
                        success = self.network.send_events(connection, device_type, event_dicts)
                        if not success:
                            logger.warning("Failed to send events - connection may be lost")
                            self._handle_connection_lost()
                    except Exception as e:
                        logger.error(f"Error sending events: {e}")
                        self._handle_connection_lost()
                
                logger.debug("Getting config settings for input manager...")
                use_relative = self.config.should_use_relative_mode()
                disable_local = self.config.should_disable_local()
                logger.debug(f"Relative mode: {use_relative}, Disable local: {disable_local}")
                
                logger.debug("Starting input capture...")
                success = self.input_manager.start_capture(
                    device.path,
                    event_callback,
                    use_relative,
                    disable_local
                )
                
                if success:
                    # Start connection monitoring
                    self._start_connection_monitoring()
                
                logger.debug(f"Input capture started: {success}")
                return success
            
            logger.debug("Connection failed - no connection returned")
            return False
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def _disconnect(self, icon, item):
        """Disconnect from consumer."""
        try:
            if self.active_connection:
                # Stop connection monitoring
                self._stop_connection_monitoring()
                
                # Stop input captures
                self.input_manager.stop_all_captures()
                
                # Clean up socket
                if self.active_socket:
                    try:
                        self.network.disconnect_from_consumer(self.active_socket)
                    except Exception as e:
                        logger.error(f"Error during socket cleanup: {e}")
                    self.active_socket = None
                
                # Update state
                self.active_connection = None
                self.icon.icon = self.create_icon_image("blue", "idle")
                self.show_notification("TransWacom", "Desconectado")
                self._schedule_menu_update()
        except Exception as e:
            logger.error(f"Disconnect error: {e}")

    def _start_connection_monitoring(self):
        """Start monitoring the active connection."""
        if self._connection_monitor_timer:
            self._connection_monitor_timer.cancel()
        
        def monitor():
            try:
                if self.active_socket and self.active_connection:
                    # Check if socket is still valid
                    if not self._is_socket_connected(self.active_socket):
                        logger.warning("Connection monitoring detected lost connection")
                        self._handle_connection_lost()
                        return
                    
                    # Schedule next check
                    self._connection_monitor_timer = threading.Timer(2.0, monitor)  # Check every 2 seconds
                    self._connection_monitor_timer.start()
            except Exception as e:
                logger.error(f"Error in connection monitoring: {e}")
                self._handle_connection_lost()
        
        # Start monitoring with initial delay
        self._connection_monitor_timer = threading.Timer(2.0, monitor)
        self._connection_monitor_timer.start()
        logger.debug("Connection monitoring started")

    def _stop_connection_monitoring(self):
        """Stop connection monitoring."""
        if self._connection_monitor_timer:
            self._connection_monitor_timer.cancel()
            self._connection_monitor_timer = None
            logger.debug("Connection monitoring stopped")

    def _is_socket_connected(self, sock) -> bool:
        """Check if a socket is still connected."""
        try:
            # Try to get socket error status
            error = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
            if error:
                return False
            
            # Try to send a small amount of data with MSG_DONTWAIT
            # This is a non-blocking operation to test the connection
            sock.send(b'', socket.MSG_DONTWAIT)
            return True
        except socket.error as e:
            # Common errors that indicate disconnection
            import errno
            if e.errno in (errno.ENOTCONN, errno.ECONNRESET, errno.EPIPE, errno.ECONNABORTED):
                return False
            # For other errors, assume still connected (might be temporary)
            return True
        except Exception:
            return False

    def _handle_connection_lost(self):
        """Handle lost connection with automatic recovery."""
        try:
            logger.warning("Connection lost detected - performing automatic recovery")
            
            # Prevent multiple simultaneous recovery attempts
            if not hasattr(self, '_recovering') or not self._recovering:
                self._recovering = True
                
                # Stop connection monitoring
                self._stop_connection_monitoring()
                
                # Force stop input captures to restore device states
                logger.info("Restoring input devices after connection loss...")
                self.input_manager.stop_all_captures()
                
                # Clean up connection state
                if self.active_socket:
                    try:
                        self.active_socket.close()
                    except Exception:
                        pass
                    self.active_socket = None
                
                self.active_connection = None
                
                # Update UI
                self.icon.icon = self.create_icon_image("red", "error")
                self.show_notification(
                    "Conexión Perdida", 
                    "Se perdió la conexión con el consumer. Dispositivos restaurados.",
                    timeout=10
                )
                
                self._schedule_menu_update()
                
                # Reset recovery flag after a delay
                def reset_recovery():
                    self._recovering = False
                
                threading.Timer(5.0, reset_recovery).start()
                
        except Exception as e:
            logger.error(f"Error handling connection loss: {e}")
            try:
                # Emergency cleanup
                self._emergency_cleanup()
            except Exception as cleanup_error:
                logger.error(f"Emergency cleanup also failed: {cleanup_error}")
    
    def _refresh_devices(self, icon, item):
        """Refresh device list."""
        self._update_devices()
        self.show_notification("TransWacom", "Lista de dispositivos actualizada")
    
    def _open_config(self, icon, item):
        """Open configuration (placeholder)."""
        self.show_notification("TransWacom", "Configuración: Funcionalidad próximamente")
    
    def _schedule_menu_update(self):
        """Schedule a menu update with a small delay to avoid rapid updates."""
        if self._menu_update_timer:
            self._menu_update_timer.cancel()
        
        self._menu_update_timer = threading.Timer(0.5, self._update_menu)
        self._menu_update_timer.start()
    
    def _update_menu(self):
        """Update the tray menu."""
        if self.icon and not self._updating_menu:
            self._updating_menu = True
            try:
                self.icon.menu = self._create_menu()
                logger.debug("Menu updated successfully")
            except Exception as e:
                logger.error(f"Error updating menu: {e}")
            finally:
                self._updating_menu = False
    
    def _quit(self, icon, item):
        """Quit the application."""
        logger.info("Quitting application...")
        
        # Cancel any pending menu updates
        if self._menu_update_timer:
            self._menu_update_timer.cancel()
        
        # Stop connection monitoring
        self._stop_connection_monitoring()
        
        # Ensure all captures are stopped (even if no active connection)
        try:
            logger.info("Stopping all input captures...")
            self.input_manager.stop_all_captures()
        except Exception as e:
            logger.error(f"Error stopping captures: {e}")
        
        # Handle active connection
        if self.active_connection:
            logger.info("Disconnecting active connection...")
            self._disconnect(icon, item)
        
        logger.info("Stopping tray application...")
        self.stop()
    
    def _emergency_cleanup(self):
        """Emergency cleanup to restore device states."""
        logger.info("Performing emergency cleanup...")
        
        try:
            # Stop connection monitoring
            if hasattr(self, '_connection_monitor_timer') and self._connection_monitor_timer:
                self._connection_monitor_timer.cancel()
                self._connection_monitor_timer = None
            
            # Force stop all input captures to restore device states
            if hasattr(self, 'input_manager'):
                logger.info("Stopping all input captures...")
                self.input_manager.stop_all_captures()
            
            # Clean up connection state
            if hasattr(self, 'active_socket') and self.active_socket:
                try:
                    self.active_socket.close()
                except Exception:
                    pass
                self.active_socket = None
            
            # Clear active connection
            if hasattr(self, 'active_connection'):
                self.active_connection = None
                
            logger.info("Emergency cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during emergency cleanup: {e}")
            # Even if cleanup fails, try to restore Wacom state directly
            try:
                import subprocess
                logger.info("Attempting direct Wacom restore...")
                subprocess.run(["xsetwacom", "--list", "devices"], 
                             capture_output=True, text=True, timeout=5)
                # This will help identify if xsetwacom is available
                subprocess.run(["bash", "-c", "xsetwacom --list devices | head -1 | cut -f1 | xargs -I {} xsetwacom --set {} Mode Absolute"], 
                             capture_output=True, text=True, timeout=5)
                logger.info("Direct Wacom restore attempted")
            except Exception as restore_error:
                logger.error(f"Direct Wacom restore failed: {restore_error}")


class ConsumerTrayApp(TrayIcon):
    """Consumer mode system tray application."""
    
    def __init__(self):
        super().__init__()
        self.config = create_config_manager()
        self.network = create_network()
        self.device_manager = create_device_emulation_manager()
        
        # State
        self.active_connections: List[str] = []
        self.is_listening = False
        self.port = self.config.get_consumer_port()
        self.server_socket = None
        self._updating_menu = False  # Flag to prevent recursion
        
        # Setup network server
        self._setup_server()
        
        # Create tray icon
        self._create_tray_icon()
        
        # Start mDNS advertising
        self._start_advertising()
        
    def _setup_server(self):
        """Setup TCP server for incoming connections."""
        try:
            def auth_callback(handshake: dict) -> bool:
                """Handle incoming connection request."""
                return self._handle_connection_request(handshake)
            
            def event_callback(device_type: str, events: list):
                """Handle received input events."""
                self._handle_events_received(device_type, events)
            
            self.server_socket = self.network.create_consumer_server(
                self.port, 
                auth_callback, 
                event_callback
            )
            
            self.is_listening = True
            logger.info(f"Consumer server started on port {self.port}")
            
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
    
    def _start_advertising(self):
        """Start mDNS advertising."""
        try:
            capabilities = []
            consumer_config = self.config.config.get('consumer', {})
            devices_config = consumer_config.get('devices', {})
            
            if devices_config.get('wacom_enabled', True):
                capabilities.append('wacom')
            if devices_config.get('joystick_enabled', True):
                capabilities.append('joystick')
            
            mdns_name = self.config.get_mdns_name()
            success = self.network.publish_consumer_service(
                mdns_name,
                self.port,
                capabilities
            )
            
            if success:
                logger.info(f"Started advertising as '{mdns_name}' with capabilities: {capabilities}")
            
        except Exception as e:
            logger.error(f"Failed to start advertising: {e}")
    
    def _handle_connection_request(self, handshake: dict) -> bool:
        """Handle incoming connection request - show authorization dialog."""
        host_name = handshake.get('host_name', 'Unknown')
        host_id = handshake.get('host_id', '')
        devices = handshake.get('devices', [])
        
        # Check if host is trusted
        if self.config.is_host_trusted(host_name, host_id):
            if self.config.should_auto_accept_host(host_name):
                logger.info(f"Auto-accepting connection from trusted host: {host_name}")
                self._add_connection(host_name)
                return True
        
        # Show notification for authorization
        device_names = [d.get('name', 'Unknown Device') for d in devices]
        
        self.show_notification(
            "Nueva Conexión",
            f"{host_name} quiere conectar: {', '.join(device_names)}",
            timeout=15
        )
        
        # For now, auto-accept (in real implementation, show dialog)
        # TODO: Implement proper authorization dialog
        logger.info(f"Connection request from {host_name} for devices: {device_names}")
        self._add_connection(host_name)
        return True
    
    def _add_connection(self, host_name: str):
        """Add a connection to the active list."""
        if host_name not in self.active_connections:
            self.active_connections.append(host_name)
            
            self.show_notification(
                "Conexión Establecida",
                f"Conectado con {host_name}"
            )
            
            # Update icon
            self.icon.icon = self.create_icon_image("green", "connected")
            self._update_menu()
    
    def _handle_events_received(self, device_type: str, events: list):
        """Handle received input events."""
        try:
            # Process events through device manager
            self.device_manager.process_events(device_type, events)
        except Exception as e:
            logger.error(f"Failed to process events: {e}")
    
    def _create_tray_icon(self):
        """Create the system tray icon."""
        status = "available" if self.is_listening else "error"
        image = self.create_icon_image("blue", status)
        
        self.icon = pystray.Icon(
            "TransWacom Consumer",
            image,
            "TransWacom Consumer",
            menu=self._create_menu()
        )
    
    def _create_menu(self) -> pystray.Menu:
        """Create the tray menu."""
        try:
            menu_items = []
            
            # Title
            menu_items.append(pystray.MenuItem("🖥️ TransWacom Consumer", None, enabled=False))
            menu_items.append(pystray.Menu.SEPARATOR)
            
            # Status
            if self.is_listening:
                status_text = f"📶 Disponible (puerto {self.port})"
            else:
                status_text = "📶 Error - No escuchando"
            menu_items.append(pystray.MenuItem(status_text, None, enabled=False))
            
            menu_items.append(pystray.Menu.SEPARATOR)
            
            # Active connections
            if self.active_connections:
                menu_items.append(pystray.MenuItem("🔗 Conexiones:", None, enabled=False))
                for i, connection in enumerate(self.active_connections):
                    if i >= 3:  # Limit display
                        remaining = len(self.active_connections) - 3
                        menu_items.append(pystray.MenuItem(f"  ... y {remaining} más", None, enabled=False))
                        break
                    connection_text = f"  📱 {connection}"
                    menu_items.append(pystray.MenuItem(connection_text, None, enabled=False))
            else:
                menu_items.append(pystray.MenuItem("🔗 Sin conexiones", None, enabled=False))
            
            menu_items.append(pystray.Menu.SEPARATOR)
            
            # Actions
            menu_items.append(pystray.MenuItem("⚙️ Configuración", self._open_config))
            menu_items.append(pystray.MenuItem("❌ Salir", self._quit))
            
            return pystray.Menu(*menu_items)
            
        except Exception as e:
            logger.error(f"Error creating consumer menu: {e}")
            # Fallback minimal menu
            return pystray.Menu(
                pystray.MenuItem("TransWacom Consumer", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Error en menú", None, enabled=False),
                pystray.MenuItem("Salir", self._quit)
            )
    
    def _disconnect_host(self, host_name: str):
        """Disconnect a specific host."""
        try:
            if host_name in self.active_connections:
                self.active_connections.remove(host_name)
                self.show_notification(
                    "Desconexión",
                    f"Desconectado de {host_name}"
                )
                
                # Update icon
                if not self.active_connections:
                    self.icon.icon = self.create_icon_image("blue", "available")
                
                self._update_menu()
        except Exception as e:
            logger.error(f"Failed to disconnect host: {e}")
    
    def _open_config(self, icon, item):
        """Open configuration (placeholder)."""
        self.show_notification("TransWacom", "Configuración: Funcionalidad próximamente")
    
    def _update_menu(self):
        """Update the tray menu."""
        if self.icon and not self._updating_menu:
            self._updating_menu = True
            try:
                self.icon.menu = self._create_menu()
            finally:
                self._updating_menu = False
    
    def _quit(self, icon, item):
        """Quit the application."""
        # Clean up connections
        self.active_connections.clear()
        
        # Stop server
        if self.server_socket:
            self.server_socket.close()
        
        # Stop advertising
        self.network.unpublish_consumer_service()
        
        self.stop()
    
    def _emergency_cleanup(self):
        """Emergency cleanup for consumer."""
        logger.info("Performing consumer emergency cleanup...")
        
        try:
            # Clean up connections
            if hasattr(self, 'active_connections'):
                self.active_connections.clear()
            
            # Stop server
            if hasattr(self, 'server_socket') and self.server_socket:
                self.server_socket.close()
            
            # Stop advertising
            if hasattr(self, 'network'):
                self.network.unpublish_consumer_service()
                
            logger.info("Consumer emergency cleanup completed")
            
        except Exception as e:
            logger.error(f"Error during consumer emergency cleanup: {e}")


def main():
    """Main entry point for the tray application."""
    global _current_app
    
    parser = argparse.ArgumentParser(description='TransWacom System Tray Application')
    parser.add_argument('mode', choices=['host', 'consumer'], help='Operating mode')
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
        if args.mode == 'host':
            app = HostTrayApp()
            _current_app = app  # Store global reference for signal handling
            logger.info("Starting TransWacom Host")
        else:
            app = ConsumerTrayApp()
            _current_app = app  # Store global reference for signal handling
            logger.info("Starting TransWacom Consumer")
        
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

#!/usr/bin/env python3
"""
TransWacom - Share input devices over network
Refactored modular version using the new architecture.
"""
import argparse
import sys
import time
from typing import List, Optional

# Import our modules
from device_detector import create_detector
from config_manager import create_config_manager
from transnetwork import create_network, DiscoveredConsumer
from host_input import create_host_input_manager, InputEvent
from consumer_device_emulation import create_device_emulation_manager

DEFAULT_PORT = 3333

class TransWacomHost:
    """Host implementation - captures and sends input events."""
    
    def __init__(self):
        self.config = create_config_manager()
        self.detector = create_detector()
        self.network = create_network()
        self.input_manager = create_host_input_manager()
        self.active_connection = None
        
    def list_devices(self):
        """List all detected input devices."""
        print("Detected devices:")
        devices = self.detector.detect_all_devices()
        
        if not devices:
            print("  No devices found.")
            return
        
        for device in devices:
            print(f"  {device}")
            if device.capabilities:
                print(f"    Capabilities: {', '.join(device.capabilities)}")
    
    def connect_to_consumer(self, address: str, port: int, device_path: str) -> bool:
        """Connect to a consumer and start sharing a device."""
        # Get device info
        devices = self.detector.detect_all_devices()
        device_info = None
        
        for device in devices:
            if device.path == device_path:
                device_info = device
                break
        
        if not device_info:
            print(f"Device {device_path} not found")
            return False
        
        # Prepare handshake data
        handshake_data = self.network.protocol.create_handshake(
            host_name=self.config.machine_name,
            host_id=self.config.machine_id,
            devices=[device_info.to_dict()]
        )
        
        # Connect to consumer
        sock = self.network.connect_to_consumer(address, port, handshake_data)
        if not sock:
            return False
        
        self.active_connection = sock
        
        # Start input capture
        def event_callback(device_type: str, events: List[InputEvent]):
            if self.active_connection:
                event_dicts = [event.to_dict() for event in events]
                success = self.network.send_events(self.active_connection, device_type, event_dicts)
                if not success:
                    print("Lost connection to consumer")
                    self.disconnect()
        
        # Configure capture settings from config
        relative_mode = self.config.should_use_relative_mode()
        disable_local = self.config.should_disable_local()
        
        success = self.input_manager.start_capture(
            device_path, event_callback, relative_mode, disable_local
        )
        
        if success:
            print(f"Successfully connected and sharing {device_info.name}")
            return True
        else:
            self.disconnect()
            return False
    
    def disconnect(self):
        """Disconnect from consumer."""
        if self.active_connection:
            self.network.disconnect_from_consumer(self.active_connection)
            self.active_connection = None
        
        self.input_manager.stop_all_captures()
        print("Disconnected from consumer")
    
    def run_discovery(self):
        """Run interactive discovery mode."""
        discovered_consumers = []
        
        def on_discovery(consumer: DiscoveredConsumer):
            discovered_consumers.append(consumer)
            print(f"Found consumer: {consumer.name} at {consumer.address}:{consumer.port}")
            print(f"  Capabilities: {', '.join(consumer.capabilities)}")
        
        print("Starting discovery...")
        if not self.network.discover_consumers(on_discovery):
            print("Discovery failed (mDNS not available)")
            return
        
        print("Press Ctrl+C to stop discovery and show menu...")
        
        try:
            time.sleep(10)  # Discover for 10 seconds
        except KeyboardInterrupt:
            pass
        
        self.network.stop_discovery()
        
        if not discovered_consumers:
            print("No consumers found")
            return
        
        # Show interactive menu
        self._show_consumer_menu(discovered_consumers)
    
    def _show_consumer_menu(self, consumers: List[DiscoveredConsumer]):
        """Show interactive consumer selection menu."""
        devices = self.detector.detect_all_devices()
        
        if not devices:
            print("No input devices detected")
            return
        
        print("\nAvailable consumers:")
        for i, consumer in enumerate(consumers):
            print(f"  {i+1}. {consumer.name} ({consumer.address}:{consumer.port})")
        
        print("\nAvailable devices:")
        for i, device in enumerate(devices):
            print(f"  {i+1}. {device}")
        
        try:
            consumer_choice = int(input("Select consumer (number): ")) - 1
            device_choice = int(input("Select device (number): ")) - 1
            
            if 0 <= consumer_choice < len(consumers) and 0 <= device_choice < len(devices):
                consumer = consumers[consumer_choice]
                device = devices[device_choice]
                
                print(f"Connecting to {consumer.name} with {device.name}...")
                self.connect_to_consumer(consumer.address, consumer.port, device.path)
                
                # Keep connection alive
                try:
                    print("Connected! Press Ctrl+C to disconnect...")
                    while self.active_connection:
                        time.sleep(1)
                except KeyboardInterrupt:
                    self.disconnect()
            else:
                print("Invalid selection")
                
        except (ValueError, KeyboardInterrupt):
            print("Cancelled")


class TransWacomConsumer:
    """Consumer implementation - receives events and creates virtual devices."""
    
    def __init__(self):
        self.config = create_config_manager()
        self.network = create_network()
        self.device_manager = create_device_emulation_manager()
        self.server_socket = None
        
    def start_service(self, port: Optional[int] = None):
        """Start the consumer service."""
        if port is None:
            port = self.config.get_consumer_port()
        
        # Create authorization callback
        def auth_callback(handshake: dict) -> bool:
            host_name = handshake.get('host_name', 'Unknown')
            host_id = handshake.get('host_id', '')
            
            print(f"Authorization request from: {host_name} (ID: {host_id[:8]}...)")
            
            # Check if host is trusted
            if self.config.is_host_trusted(host_name, host_id):
                if self.config.should_auto_accept_host(host_name):
                    print(f"Auto-accepting trusted host: {host_name}")
                    return True
            
            # Interactive authorization for unknown hosts
            try:
                response = input(f"Accept connection from {host_name}? [y/N/t(rust)]: ").lower()
                if response == 't':
                    # Add to trusted hosts
                    self.config.add_trusted_host(host_name, host_id, auto_accept=True)
                    print(f"Added {host_name} to trusted hosts")
                    return True
                elif response == 'y':
                    return True
                else:
                    print("Connection rejected")
                    return False
            except KeyboardInterrupt:
                print("Connection rejected")
                return False
        
        # Create event callback
        def event_callback(device_type: str, events: list):
            self.device_manager.process_events(device_type, events)
        
        # Start server
        self.server_socket = self.network.create_consumer_server(port, auth_callback, event_callback)
        
        # Publish mDNS service
        capabilities = self.device_manager.get_capabilities()
        mdns_name = self.config.get_mdns_name()
        self.network.publish_consumer_service(mdns_name, port, capabilities)
        
        print(f"Consumer service started on port {port}")
        print(f"mDNS name: {mdns_name}")
        print(f"Capabilities: {', '.join(capabilities)}")
        print("Press Ctrl+C to stop...")
        
        try:
            # Keep server running
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Stopping service...")
        finally:
            self.stop_service()
    
    def stop_service(self):
        """Stop the consumer service."""
        if self.server_socket:
            self.server_socket.close()
        
        self.network.shutdown()
        self.device_manager.destroy_all_devices()
        print("Service stopped")
def main():
    """Main entry point with refactored modular architecture."""
    parser = argparse.ArgumentParser(
        description="TransWacom: Share input devices over network (modular version)"
    )
    
    # Main mode selection
    parser.add_argument('--host', action='store_true', 
                       help='Host mode: capture and send device events')
    parser.add_argument('--consumer', action='store_true',
                       help='Consumer mode: receive events and create virtual devices')
    
    # Discovery and connection
    parser.add_argument('--discover', action='store_true',
                       help='Discover available consumers (host mode)')
    parser.add_argument('--connect', type=str, metavar='ADDRESS:PORT',
                       help='Connect directly to consumer (host mode)')
    
    # Device selection
    parser.add_argument('--device', type=str, metavar='PATH',
                       help='Specific device path (e.g., /dev/input/event11)')
    parser.add_argument('--list-devices', action='store_true',
                       help='List all detected input devices')
    
    # Consumer configuration
    parser.add_argument('--port', type=int, default=DEFAULT_PORT,
                       help=f'Network port (default: {DEFAULT_PORT})')
    
    # Device behavior
    parser.add_argument('--no-relative-mode', action='store_true',
                       help='Keep Wacom in absolute mode (host)')
    parser.add_argument('--no-disable-local', action='store_true',
                       help='Keep device active locally (host)')
    
    # Legacy compatibility
    parser.add_argument('--server', action='store_true',
                       help='Legacy: equivalent to --host')
    parser.add_argument('--client', action='store_true',
                       help='Legacy: equivalent to --consumer')
    
    args = parser.parse_args()
    
    # Handle legacy arguments
    if args.server:
        args.host = True
    if args.client:
        args.consumer = True
    
    # Validate arguments
    if args.host and args.consumer:
        print("Error: Cannot specify both --host and --consumer modes")
        sys.exit(1)
    
    if not args.host and not args.consumer:
        if args.list_devices:
            # Allow listing devices without mode selection
            detector = create_detector()
            devices = detector.detect_all_devices()
            print("Detected devices:")
            if not devices:
                print("  No devices found.")
            else:
                for device in devices:
                    print(f"  {device}")
                    if device.capabilities:
                        print(f"    Capabilities: {', '.join(device.capabilities)}")
            return
        else:
            print("Error: Must specify either --host or --consumer mode")
            parser.print_help()
            sys.exit(1)
    
    try:
        if args.host:
            # Host mode
            host = TransWacomHost()
            
            if args.list_devices:
                host.list_devices()
                return
            
            if args.discover:
                host.run_discovery()
            elif args.connect:
                # Parse address:port
                try:
                    if ':' in args.connect:
                        address, port = args.connect.split(':', 1)
                        port = int(port)
                    else:
                        address = args.connect
                        port = DEFAULT_PORT
                except ValueError:
                    print("Error: Invalid address format. Use ADDRESS:PORT")
                    sys.exit(1)
                
                # Select device
                if args.device:
                    device_path = args.device
                else:
                    devices = host.detector.detect_all_devices()
                    if not devices:
                        print("No devices detected. Use --device to specify manually.")
                        sys.exit(1)
                    device_path = devices[0].path
                    print(f"Auto-selected device: {devices[0].name} ({device_path})")
                
                # Connect
                success = host.connect_to_consumer(address, port, device_path)
                if success:
                    try:
                        print("Connected! Press Ctrl+C to disconnect...")
                        while host.active_connection:
                            time.sleep(1)
                    except KeyboardInterrupt:
                        host.disconnect()
                else:
                    print("Connection failed")
                    sys.exit(1)
            else:
                print("Host mode: use --discover for discovery or --connect ADDRESS:PORT")
                parser.print_help()
        
        elif args.consumer:
            # Consumer mode
            consumer = TransWacomConsumer()
            consumer.start_service(args.port)
    
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
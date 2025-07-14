"""
Network protocol and mDNS discovery for TransWacom.
"""
import json
import socket
import threading
import time
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass

# Configure logging
logger = logging.getLogger(__name__)

try:
    from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, ServiceListener
    ZEROCONF_AVAILABLE = True
except ImportError:
    ServiceInfo = None
    Zeroconf = None 
    ServiceBrowser = None
    ServiceListener = None
    ZEROCONF_AVAILABLE = False


@dataclass
class DiscoveredConsumer:
    """Information about a discovered consumer."""
    name: str
    address: str
    port: int
    capabilities: List[str]
    version: str

    @property
    def unique_id(self):
        # Use address:port as unique id (suficiente para la app)
        return f"{self.address}:{self.port}"


@dataclass
class ConnectionInfo:
    """Information about an active connection."""
    address: str
    port: int
    host_name: str
    consumer_name: str
    devices: List[Dict[str, Any]]
    connected_at: float


class NetworkProtocol:
    """Handles the JSON protocol over TCP."""
    
    def __init__(self):
        self.buffer = b''
    
    def pack_message(self, message: Dict[str, Any]) -> bytes:
        """Pack a message as JSON with newline delimiter."""
        json_str = json.dumps(message)
        return json_str.encode('utf-8') + b'\n'
    
    def unpack_messages(self, data: bytes) -> List[Dict[str, Any]]:
        """Unpack messages from received data."""
        self.buffer += data
        messages = []
        
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            if line:
                try:
                    message = json.loads(line.decode('utf-8'))
                    messages.append(message)
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    print(f"Protocol error: {e}")
        
        return messages
    
    def create_handshake(self, host_name: str, host_id: str, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create handshake message."""
        return {
            'type': 'handshake',
            'host_name': host_name,
            'host_id': host_id,
            'devices': devices,
            'version': '1.0'
        }
    
    def create_event_message(self, device_type: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create event message."""
        return {
            'type': 'event',
            'device_type': device_type,
            'events': events,
            'timestamp': time.time()
        }
    
    def create_auth_response(self, accepted: bool, consumer_name: str, consumer_id: str) -> Dict[str, Any]:
        """Create authorization response."""
        return {
            'type': 'auth_response',
            'accepted': accepted,
            'consumer_name': consumer_name,
            'consumer_id': consumer_id
        }
    
    def create_disconnect_message(self, reason: str = 'user_request') -> Dict[str, Any]:
        """Create disconnect message."""
        return {
            'type': 'disconnect',
            'reason': reason,
            'timestamp': time.time()
        }


class MDNSConsumerListener(ServiceListener):
    """Listener for mDNS consumer services."""
    
    def __init__(self, discovery_callback: Callable[[DiscoveredConsumer], None]):
        self.discovery_callback = discovery_callback
        self.discovered_services = {}
    
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is discovered."""
        try:
            info = zc.get_service_info(type_, name)
            if info:
                address = socket.inet_ntoa(info.addresses[0])
                port = info.port
                
                # Parse TXT records
                properties = {}
                if info.properties:
                    for key, value in info.properties.items():
                        properties[key.decode('utf-8')] = value.decode('utf-8')
                
                consumer = DiscoveredConsumer(
                    name=properties.get('name', name.split('.')[0]),
                    address=address,
                    port=port,
                    capabilities=properties.get('capabilities', '').split(','),
                    version=properties.get('version', '1.0')
                )
                
                self.discovered_services[name] = consumer
                self.discovery_callback(consumer)
                
        except Exception as e:
            print(f"Error processing discovered service: {e}")
    
    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Called when a service is removed."""
        if name in self.discovered_services:
            del self.discovered_services[name]


class TransNetwork:
    """Network management for TransWacom."""
    
    SERVICE_TYPE = "_input-consumer._tcp.local."
    
    def __init__(self):
        self.protocol = NetworkProtocol()
        self.zeroconf = None
        self.service_info = None
        self.service_browser = None
        self.listener = None
        self.active_connections = {}
        self.incoming_sockets = {}  # key: host_name, value: list of sockets
        
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
    
    def _get_local_ip(self) -> str:
        """Get the real local IP address (not loopback)."""
        try:
            # Try to connect to a remote address to determine local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # Connect to Google DNS (doesn't actually send data)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                if not local_ip.startswith('127.'):
                    return local_ip
        except Exception:
            pass
        
        try:
            # Fallback: get all network interfaces
            import netifaces
            for interface in netifaces.interfaces():
                addresses = netifaces.ifaddresses(interface)
                if netifaces.AF_INET in addresses:
                    for addr in addresses[netifaces.AF_INET]:
                        ip = addr['addr']
                        if not ip.startswith('127.') and not ip.startswith('169.254.'):
                            return ip
        except ImportError:
            pass
        
        try:
            # Another fallback: check common network interfaces
            import subprocess
            result = subprocess.run(['ip', 'route', 'get', '8.8.8.8'], 
                                  capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'src' in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == 'src' and i + 1 < len(parts):
                            return parts[i + 1]
        except Exception:
            pass
        
        # Final fallback to hostname resolution
        hostname = socket.gethostname()
        return socket.gethostbyname(hostname)

    # Consumer methods (server side)
    def publish_consumer_service(self, name: str, port: int, capabilities: List[str]) -> bool:
        """Publish consumer service via mDNS."""
        if not ZEROCONF_AVAILABLE:
            print("Warning: zeroconf not available, mDNS disabled")
            return False
        
        try:
            self.zeroconf = Zeroconf()
            
            # Get real local IP (not loopback)
            local_ip = self._get_local_ip()
            logger.debug(f"Publishing mDNS service on IP: {local_ip}")
            
            # Create service info
            service_name = f"{name}.{self.SERVICE_TYPE}"
            self.service_info = ServiceInfo(
                self.SERVICE_TYPE,
                service_name,
                addresses=[socket.inet_aton(local_ip)],
                port=port,
                properties={
                    b'version': b'1.0',
                    b'name': name.encode('utf-8'),
                    b'capabilities': ','.join(capabilities).encode('utf-8')
                }
            )
            
            self.zeroconf.register_service(self.service_info)
            logger.info(f"Published mDNS service: {service_name} on {local_ip}:{port}")
            return True
            
        except Exception as e:
            print(f"Failed to publish mDNS service: {e}")
            return False
    
    def unpublish_consumer_service(self):
        """Unpublish consumer service."""
        if self.zeroconf and self.service_info:
            try:
                self.zeroconf.unregister_service(self.service_info)
                logger.info("Unpublished mDNS service")
            except Exception as e:
                logger.error(f"Error unpublishing service: {e}")
    
    # Host methods (client side)
    def discover_consumers(self, discovery_callback: Callable[[DiscoveredConsumer], None]) -> bool:
        """Start discovering consumer services."""
        if not ZEROCONF_AVAILABLE:
            print("Warning: zeroconf not available, discovery disabled")
            return False
        
        try:
            self.zeroconf = Zeroconf()
            self.listener = MDNSConsumerListener(discovery_callback)
            self.service_browser = ServiceBrowser(self.zeroconf, self.SERVICE_TYPE, self.listener)
            print("Started mDNS discovery")
            return True
            
        except Exception as e:
            print(f"Failed to start discovery: {e}")
            return False
    
    def stop_discovery(self):
        """Stop discovering services."""
        if self.service_browser:
            self.service_browser.cancel()
            self.service_browser = None
        
        if self.listener:
            self.listener = None
    
    def connect_to_consumer(self, address: str, port: int, 
                          handshake_data: Dict[str, Any]) -> Optional[socket.socket]:
        """Connect to a consumer and perform handshake."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(60)  # 60 second timeout for user authorization
            sock.connect((address, port))
            
            print("Connected to consumer, sending handshake...")
            # Send handshake
            handshake_msg = self.protocol.pack_message(handshake_data)
            sock.sendall(handshake_msg)
            
            print("Waiting for authorization response...")
            # Wait for auth response with longer timeout
            response_data = sock.recv(1024)
            messages = self.protocol.unpack_messages(response_data)
            
            if messages and messages[0].get('type') == 'auth_response':
                auth_response = messages[0]
                if auth_response.get('accepted'):
                    # Connection accepted
                    connection_info = ConnectionInfo(
                        address=address,
                        port=port,
                        host_name=handshake_data['host_name'],
                        consumer_name=auth_response.get('consumer_name', 'Unknown'),
                        devices=handshake_data['devices'],
                        connected_at=time.time()
                    )
                    self.active_connections[f"{address}:{port}"] = connection_info
                    print(f"Connected to {auth_response.get('consumer_name')} at {address}:{port}")
                    return sock
                else:
                    print("Connection rejected by consumer")
                    sock.close()
                    return None
            else:
                print("Invalid handshake response")
                sock.close()
                return None
                
        except Exception as e:
            print(f"Connection failed: {e}")
            return None
    
    def disconnect_from_consumer(self, sock: socket.socket, reason: str = 'user_request'):
        """Disconnect from consumer with proper cleanup."""
        try:
            # Send disconnect message
            disconnect_msg = self.protocol.create_disconnect_message(reason)
            sock.sendall(self.protocol.pack_message(disconnect_msg))
            
            # Remove from active connections
            peer_addr = f"{sock.getpeername()[0]}:{sock.getpeername()[1]}"
            if peer_addr in self.active_connections:
                del self.active_connections[peer_addr]
            
        except Exception as e:
            print(f"Error during disconnect: {e}")
        finally:
            sock.close()
    
    def send_events(self, sock: socket.socket, device_type: str, events: List[Dict[str, Any]]) -> bool:
        """Send input events to consumer."""
        try:
            event_msg = self.protocol.create_event_message(device_type, events)
            data = self.protocol.pack_message(event_msg)
            sock.sendall(data)
            return True
        except socket.error as e:
            # Socket errors usually indicate connection issues
            import errno
            if e.errno in (errno.ENOTCONN, errno.ECONNRESET, errno.EPIPE, errno.ECONNABORTED):
                logger.error(f"Connection lost while sending events: {e}")
            else:
                logger.error(f"Socket error sending events: {e}")
            return False
        except Exception as e:
            logger.error(f"Error sending events: {e}")
            return False
    
    # Consumer server methods
    def create_consumer_server(self, port: int, 
                             auth_callback: Callable[[Dict[str, Any]], bool],
                             event_callback: Callable[[str, List[Dict[str, Any]]], None]) -> socket.socket:
        """Create consumer server socket."""
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(('0.0.0.0', port))
        server_sock.listen(5)

        def handle_client(client_sock, client_addr):
            """Handle individual client connection."""
            host_name = None
            try:
                client_protocol = NetworkProtocol()
                handshake_done = False
                while True:
                    data = client_sock.recv(1024)
                    if not data:
                        break
                    messages = client_protocol.unpack_messages(data)
                    for message in messages:
                        msg_type = message.get('type')
                        if msg_type == 'handshake':
                            # Handle authorization
                            host_name = message.get('host_name', str(client_addr))
                            accepted_host_name = auth_callback(message)
                            auth_response = self.protocol.create_auth_response(
                                bool(accepted_host_name), 
                                socket.gethostname(),
                                "consumer_id_placeholder"  # Should come from config
                            )
                            client_sock.sendall(self.protocol.pack_message(auth_response))
                            if accepted_host_name:
                                # Usar el host_name retornado por auth_callback para registrar la conexión
                                final_host_name = accepted_host_name
                                if final_host_name not in self.incoming_sockets:
                                    self.incoming_sockets[final_host_name] = []
                                self.incoming_sockets[final_host_name].append(client_sock)
                                host_name = final_host_name  # Actualizar para usar en cleanup
                                handshake_done = True
                            else:
                                client_sock.close()
                                return
                        elif msg_type == 'event':
                            device_type = message.get('device_type')
                            events = message.get('events', [])
                            event_callback(device_type, events)
                        elif msg_type == 'disconnect':
                            print(f"Host {client_addr} disconnected: {message.get('reason')}")
                            break
                
            except Exception as e:
                print(f"Error handling client {client_addr}: {e}")
            finally:
                # Limpiar socket de la lista si estaba registrado
                if host_name and host_name in self.incoming_sockets:
                    try:
                        self.incoming_sockets[host_name].remove(client_sock)
                        if not self.incoming_sockets[host_name]:
                            del self.incoming_sockets[host_name]
                    except ValueError:
                        pass
                client_sock.close()

        def accept_connections():
            """Accept and handle incoming connections."""
            while True:
                try:
                    client_sock, client_addr = server_sock.accept()
                    print(f"New connection from {client_addr}")
                    client_thread = threading.Thread(
                        target=handle_client,
                        args=(client_sock, client_addr),
                        daemon=True
                    )
                    client_thread.start()
                except Exception as e:
                    print(f"Error accepting connection: {e}")
                    break

        accept_thread = threading.Thread(target=accept_connections, daemon=True)
        accept_thread.start()
        return server_sock
    def disconnect_incoming_host(self, host_name: str, reason: str = 'revoked'):
        """Disconnect all incoming sockets for a given host_name."""
        sock_list = self.incoming_sockets.get(host_name, [])
        for sock in list(sock_list):
            try:
                try:
                    disconnect_msg = self.protocol.create_disconnect_message(reason)
                    sock.sendall(self.protocol.pack_message(disconnect_msg))
                except Exception:
                    pass
                sock.close()
            except Exception as e:
                print(f"Error disconnecting incoming host {host_name}: {e}")
            finally:
                try:
                    sock_list.remove(sock)
                except ValueError:
                    pass
        if host_name in self.incoming_sockets and not self.incoming_sockets[host_name]:
            del self.incoming_sockets[host_name]
    
    def get_active_connections(self) -> List[ConnectionInfo]:
        """Get list of active connections."""
        return list(self.active_connections.values())
    
    def shutdown(self):
        """Shutdown network services."""
        self.stop_discovery()
        self.unpublish_consumer_service()
        
        if self.zeroconf:
            self.zeroconf.close()
            self.zeroconf = None

    # Additional methods for GUI integration
    def start_discovery(self, on_consumer_discovered: Callable[[DiscoveredConsumer], None], 
                       on_consumer_lost: Callable[[str], None] = None):
        """Start discovery with callbacks for GUI."""
        self.on_consumer_lost = on_consumer_lost
        return self.discover_consumers(on_consumer_discovered)
    
    def start_advertising(self, port: int, capabilities: List[str], name: str = None):
        """Start advertising service for GUI."""
        if name is None:
            name = socket.gethostname()
        return self.publish_consumer_service(name, port, capabilities)
    
    def start_consumer_server(self, port: int, on_connection_request: Callable,
                            on_connection_established: Callable,
                            on_connection_lost: Callable,
                            on_events_received: Callable):
        """Start consumer server with GUI callbacks."""
        
        def auth_callback(handshake_data: Dict[str, Any]) -> bool:
            host_name = handshake_data.get('host_name', 'Unknown')
            address = handshake_data.get('address', 'Unknown')
            device_info = handshake_data.get('devices', [{}])[0] if handshake_data.get('devices') else {}
            return on_connection_request(host_name, address, device_info)
        
        def event_callback(device_type: str, events: List[Dict[str, Any]]):
            connection_id = f"connection_{int(time.time())}"  # Simple connection ID
            on_events_received(connection_id, events)
        
        server_socket = self.create_consumer_server(port, auth_callback, event_callback)
        
        # Start advertising
        capabilities = ['wacom', 'joystick']  # Default capabilities
        self.start_advertising(port, capabilities)
        
        return server_socket
    
    def connect_to_consumer(self, address: str, port: int, handshake_data: Dict[str, Any]) -> Optional[socket.socket]:
        """Connect to a consumer with proper handshake data."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(60)  # 60 second timeout for user authorization
            sock.connect((address, port))
            
            print("Connected to consumer, sending handshake...")
            # Send handshake
            handshake_msg = self.protocol.pack_message(handshake_data)
            sock.sendall(handshake_msg)
            
            print("Waiting for authorization response...")
            # Wait for auth response with longer timeout
            response_data = sock.recv(1024)
            messages = self.protocol.unpack_messages(response_data)
            
            if messages and messages[0].get('type') == 'auth_response':
                auth_response = messages[0]
                if auth_response.get('accepted'):
                    # Connection accepted
                    connection_info = ConnectionInfo(
                        address=address,
                        port=port,
                        host_name=handshake_data['host_name'],
                        consumer_name=auth_response.get('consumer_name', 'Unknown'),
                        devices=handshake_data['devices'],
                        connected_at=time.time()
                    )
                    self.active_connections[f"{address}:{port}"] = connection_info
                    print(f"Connected to {auth_response.get('consumer_name')} at {address}:{port}")
                    return sock
                else:
                    print("Connection rejected by consumer")
                    sock.close()
                    return None
            else:
                print("Invalid handshake response")
                sock.close()
                return None
                
        except Exception as e:
            print(f"Connection failed: {e}")
            return None
    
    def disconnect_host(self, connection_id: str):
        """Disconnect a specific host by connection ID."""
        # For now, just close all connections (simplified implementation)
        for conn_key in list(self.active_connections.keys()):
            if connection_id in conn_key:
                connection_info = self.active_connections[conn_key]
                # This would need the actual socket, simplified for demo
                print(f"Disconnecting {connection_id}")
                del self.active_connections[conn_key]
                break


def create_network() -> TransNetwork:
    """Factory function to create a TransNetwork instance."""
    return TransNetwork()

"""
Configuration and authorization management for TransWacom.
"""
import os
import hashlib
import socket
import yaml
from typing import Dict, List, Optional, Any
from pathlib import Path


class ConfigManager:
    """Manages configuration and authorization for TransWacom."""
    
    DEFAULT_CONFIG = {
        'host': {
            'trusted_consumers': {},
            'auto_connect': False,
            'relative_mode': True,
            'disable_local': True
        },
        'consumer': {
            'network': {
                'port': 3333,
                'mdns_name': None  # Will use hostname if None
            },
            'trusted_hosts': {},
            'auto_accept_trusted': True,
            'devices': {
                'wacom_enabled': True,
                'joystick_enabled': True
            }
        },
        'general': {
            'log_level': 'INFO',
            'startup_mode': None  # 'host', 'consumer', or None
        }
    }
    
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir) if config_dir else self._get_default_config_dir()
        self.config_file = self.config_dir / 'transwacom.yaml'
        self.config = self._load_config()
        self._machine_id = self._get_machine_fingerprint()
    
    def _get_default_config_dir(self) -> Path:
        """Get default configuration directory."""
        if os.name == 'posix':
            config_home = os.environ.get('XDG_CONFIG_HOME', 
                                       os.path.expanduser('~/.config'))
            return Path(config_home) / 'transwacom'
        else:
            return Path.home() / '.transwacom'
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from file."""
        if not self.config_file.exists():
            return self.DEFAULT_CONFIG.copy()
        
        try:
            with open(self.config_file, 'r') as f:
                config = yaml.safe_load(f)
                # Merge with defaults to ensure all keys exist
                return self._merge_configs(self.DEFAULT_CONFIG, config)
        except Exception as e:
            print(f"Error loading config: {e}")
            return self.DEFAULT_CONFIG.copy()
    
    def _merge_configs(self, default: Dict, loaded: Dict) -> Dict:
        """Recursively merge loaded config with defaults."""
        result = default.copy()
        for key, value in loaded.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result
    
    def save_config(self) -> bool:
        """Save current configuration to file."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                yaml.dump(self.config, f, default_flow_style=False, indent=2)
            return True
        except Exception as e:
            print(f"Error saving config: {e}")
            return False
    
    def _get_machine_fingerprint(self) -> str:
        """Generate unique machine fingerprint."""
        # Use hostname + MAC address of first network interface
        hostname = socket.gethostname()
        
        try:
            # Get MAC address
            import uuid
            mac = hex(uuid.getnode())
        except:
            mac = "unknown"
        
        # Create fingerprint
        fingerprint_data = f"{hostname}:{mac}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()[:16]
    
    @property
    def machine_id(self) -> str:
        """Get machine fingerprint."""
        return self._machine_id
    
    @property
    def machine_name(self) -> str:
        """Get machine name (hostname)."""
        return socket.gethostname()
    
    def get_trusted_consumers(self) -> Dict[str, Any]:
        """Get trusted consumers configuration."""
        return self.config.get('host', {}).get('trusted_consumers', {})
    
    def get_trusted_hosts(self) -> Dict[str, Any]:
        """Get trusted hosts configuration."""
        return self.config.get('consumer', {}).get('trusted_hosts', {})
    
    def get_consumer_port(self) -> int:
        """Get consumer port."""
        return self.config.get('consumer', {}).get('network', {}).get('port', 3333)
    
    # Host configuration methods
    def add_trusted_consumer(self, consumer_name: str, consumer_id: str, 
                           allowed_devices: List[str] = None, auto_accept: bool = True):
        """Add a trusted consumer."""
        if 'trusted_consumers' not in self.config['host']:
            self.config['host']['trusted_consumers'] = {}
        
        self.config['host']['trusted_consumers'][consumer_name] = {
            'consumer_id': consumer_id,
            'auto_accept': auto_accept,
            'allowed_devices': allowed_devices or ['wacom', 'joystick']
        }
        self.save_config()
    
    def remove_trusted_consumer(self, consumer_name: str):
        """Remove a trusted consumer."""
        trusted = self.config['host'].get('trusted_consumers', {})
        if consumer_name in trusted:
            del trusted[consumer_name]
            self.save_config()
    
    def is_consumer_trusted(self, consumer_name: str, consumer_id: str) -> bool:
        """Check if a consumer is trusted."""
        trusted = self.config['host'].get('trusted_consumers', {})
        consumer_config = trusted.get(consumer_name)
        
        if not consumer_config:
            return False
        
        return consumer_config.get('consumer_id') == consumer_id
    
    def should_auto_accept_consumer(self, consumer_name: str) -> bool:
        """Check if consumer should be auto-accepted."""
        trusted = self.config['host'].get('trusted_consumers', {})
        consumer_config = trusted.get(consumer_name)
        
        if not consumer_config:
            return False
        
        return consumer_config.get('auto_accept', False)
    
    def get_allowed_devices_for_consumer(self, consumer_name: str) -> List[str]:
        """Get allowed devices for a consumer."""
        trusted = self.config['host'].get('trusted_consumers', {})
        consumer_config = trusted.get(consumer_name)
        
        if not consumer_config:
            return []
        
        return consumer_config.get('allowed_devices', ['wacom', 'joystick'])
    
    # Consumer configuration methods
    def add_trusted_host(self, host_name: str, host_id: str, auto_accept: bool = True):
        """Add a trusted host."""
        if 'trusted_hosts' not in self.config['consumer']:
            self.config['consumer']['trusted_hosts'] = {}
        
        self.config['consumer']['trusted_hosts'][host_name] = {
            'host_id': host_id,
            'auto_accept': auto_accept
        }
        self.save_config()
    
    def remove_trusted_host(self, host_name: str):
        """Remove a trusted host."""
        trusted = self.config['consumer'].get('trusted_hosts', {})
        if host_name in trusted:
            del trusted[host_name]
            self.save_config()
    
    def is_host_trusted(self, host_name: str, host_id: str) -> bool:
        """Check if a host is trusted."""
        trusted = self.config['consumer'].get('trusted_hosts', {})
        host_config = trusted.get(host_name)
        
        if not host_config:
            return False
        
        return host_config.get('host_id') == host_id
    
    def should_auto_accept_host(self, host_name: str) -> bool:
        """Check if host should be auto-accepted."""
        trusted = self.config['consumer'].get('trusted_hosts', {})
        host_config = trusted.get(host_name)
        
        if not host_config:
            return self.config['consumer'].get('auto_accept_trusted', False)
        
        return host_config.get('auto_accept', False)
    
    # Network configuration
    def get_consumer_port(self) -> int:
        """Get consumer listening port."""
        return self.config['consumer']['network'].get('port', 3333)
    
    def set_consumer_port(self, port: int):
        """Set consumer listening port."""
        self.config['consumer']['network']['port'] = port
        self.save_config()
    
    def get_mdns_name(self) -> str:
        """Get mDNS service name."""
        name = self.config['consumer']['network'].get('mdns_name')
        return name if name else self.machine_name
    
    def set_mdns_name(self, name: str):
        """Set mDNS service name."""
        self.config['consumer']['network']['mdns_name'] = name
        self.save_config()
    
    # Device configuration
    def is_device_type_enabled(self, device_type: str) -> bool:
        """Check if device type is enabled."""
        devices_config = self.config['consumer'].get('devices', {})
        return devices_config.get(f'{device_type}_enabled', True)
    
    def set_device_type_enabled(self, device_type: str, enabled: bool):
        """Enable/disable device type."""
        if 'devices' not in self.config['consumer']:
            self.config['consumer']['devices'] = {}
        
        self.config['consumer']['devices'][f'{device_type}_enabled'] = enabled
        self.save_config()
    
    # Host behavior configuration
    def get_host_config(self) -> Dict[str, Any]:
        """Get host configuration."""
        return self.config.get('host', {})
    
    def set_host_relative_mode(self, enabled: bool):
        """Set whether to use relative mode for Wacom devices."""
        self.config['host']['relative_mode'] = enabled
        self.save_config()
    
    def set_host_disable_local(self, enabled: bool):
        """Set whether to disable local device when sharing."""
        self.config['host']['disable_local'] = enabled
        self.save_config()
    
    def should_use_relative_mode(self) -> bool:
        """Check if relative mode should be used."""
        return self.config['host'].get('relative_mode', True)
    
    def should_disable_local(self) -> bool:
        """Check if local device should be disabled."""
        return self.config['host'].get('disable_local', True)
    
    # General configuration
    def get_startup_mode(self) -> Optional[str]:
        """Get startup mode (host/consumer/None)."""
        return self.config['general'].get('startup_mode')
    
    def set_startup_mode(self, mode: Optional[str]):
        """Set startup mode."""
        self.config['general']['startup_mode'] = mode
        self.save_config()
    
    def get_log_level(self) -> str:
        """Get log level."""
        return self.config['general'].get('log_level', 'INFO')
    
    def set_log_level(self, level: str):
        """Set log level."""
        self.config['general']['log_level'] = level
        self.save_config()


def create_config_manager(config_dir: Optional[str] = None) -> ConfigManager:
    """Factory function to create a ConfigManager instance."""
    return ConfigManager(config_dir)

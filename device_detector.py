"""
Device detection and auto-discovery for input devices (Wacom tablets, joysticks).
"""
import os
import subprocess
from typing import List, Tuple, Optional, Dict, Any

try:
    import evdev
    from evdev import InputDevice, ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    evdev = None
    InputDevice = None
    ecodes = None
    EVDEV_AVAILABLE = False


class DeviceInfo:
    """Information about a detected input device."""
    
    def __init__(self, device_type: str, path: str, name: str, 
                 capabilities: List[str] = None, vendor_id: str = None, 
                 product_id: str = None):
        self.device_type = device_type
        self.path = path
        self.name = name
        self.capabilities = capabilities or []
        self.vendor_id = vendor_id
        self.product_id = product_id
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'type': self.device_type,
            'path': self.path,
            'name': self.name,
            'capabilities': self.capabilities,
            'vendor_id': self.vendor_id,
            'product_id': self.product_id
        }
    
    def __str__(self) -> str:
        return f"{self.device_type}: {self.path} - {self.name}"


class DeviceDetector:
    """Detects and manages input devices."""
    
    def __init__(self):
        self._devices = []
    
    def detect_all_devices(self) -> List[DeviceInfo]:
        """Detect all supported input devices."""
        devices = []
        devices.extend(self._detect_wacom_devices())
        devices.extend(self._detect_joystick_devices())
        self._devices = devices
        return devices
    
    def _detect_wacom_devices(self) -> List[DeviceInfo]:
        """Detect Wacom tablets using libwacom-list-local-devices."""
        devices = []
        
        try:
            result = subprocess.run(
                ["libwacom-list-local-devices"], 
                capture_output=True, text=True, check=True
            )
            
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith('- /dev/input/event'):
                    parts = line[1:].strip().split(':', 1)
                    if len(parts) >= 2:
                        dev_path = parts[0].strip()
                        device_name = parts[1].strip().strip("'")
                        
                        if os.path.exists(dev_path):
                            capabilities = self._get_wacom_capabilities(dev_path)
                            devices.append(DeviceInfo(
                                device_type='wacom',
                                path=dev_path,
                                name=device_name,
                                capabilities=capabilities
                            ))
                            
        except Exception as e:
            print(f"Wacom detection failed: {e}")
        
        return devices
    
    def _detect_joystick_devices(self) -> List[DeviceInfo]:
        """Detect joysticks and gamepads using evdev."""
        devices = []
        
        if not EVDEV_AVAILABLE:
            return devices
        
        try:
            for event_file in os.listdir('/dev/input'):
                if event_file.startswith('event'):
                    dev_path = f'/dev/input/{event_file}'
                    try:
                        device = InputDevice(dev_path)
                        capabilities = device.capabilities()
                        
                        # Check if it's a joystick (has abs axes and buttons)
                        if (ecodes.EV_ABS in capabilities and 
                            ecodes.EV_KEY in capabilities and
                            self._has_joystick_axes(capabilities)):
                            
                            joystick_caps = self._get_joystick_capabilities(capabilities)
                            devices.append(DeviceInfo(
                                device_type='joystick',
                                path=dev_path,
                                name=device.name,
                                capabilities=joystick_caps
                            ))
                        
                        device.close()
                    except Exception:
                        pass
                        
        except Exception as e:
            print(f"Joystick detection failed: {e}")
        
        return devices
    
    def _has_joystick_axes(self, capabilities: Dict) -> bool:
        """Check if device has joystick-like axes."""
        abs_axes = capabilities.get(ecodes.EV_ABS, [])
        return (ecodes.ABS_X in abs_axes or 
                ecodes.ABS_RX in abs_axes or
                ecodes.ABS_HAT0X in abs_axes)
    
    def _get_wacom_capabilities(self, device_path: str) -> List[str]:
        """Get Wacom-specific capabilities."""
        capabilities = []
        
        if EVDEV_AVAILABLE:
            try:
                device = InputDevice(device_path)
                caps = device.capabilities()
                
                abs_axes = caps.get(ecodes.EV_ABS, [])
                if ecodes.ABS_PRESSURE in abs_axes:
                    capabilities.append('pressure')
                if ecodes.ABS_TILT_X in abs_axes and ecodes.ABS_TILT_Y in abs_axes:
                    capabilities.append('tilt')
                if ecodes.ABS_DISTANCE in abs_axes:
                    capabilities.append('proximity')
                
                keys = caps.get(ecodes.EV_KEY, [])
                if ecodes.BTN_STYLUS in keys:
                    capabilities.append('stylus_buttons')
                if ecodes.BTN_TOOL_RUBBER in keys:
                    capabilities.append('eraser')
                
                device.close()
            except Exception:
                pass
        
        return capabilities
    
    def _get_joystick_capabilities(self, capabilities: Dict) -> List[str]:
        """Get joystick-specific capabilities."""
        caps = []
        
        abs_axes = capabilities.get(ecodes.EV_ABS, [])
        keys = capabilities.get(ecodes.EV_KEY, [])
        
        if ecodes.ABS_X in abs_axes and ecodes.ABS_Y in abs_axes:
            caps.append('left_stick')
        if ecodes.ABS_RX in abs_axes and ecodes.ABS_RY in abs_axes:
            caps.append('right_stick')
        if ecodes.ABS_Z in abs_axes or ecodes.ABS_RZ in abs_axes:
            caps.append('triggers')
        if ecodes.ABS_HAT0X in abs_axes and ecodes.ABS_HAT0Y in abs_axes:
            caps.append('dpad')
        
        # Count buttons
        button_count = sum(1 for key in keys if key >= ecodes.BTN_GAMEPAD and key <= ecodes.BTN_THUMBR)
        if button_count > 0:
            caps.append(f'buttons_{button_count}')
        
        return caps
    
    def get_device_by_path(self, path: str) -> Optional[DeviceInfo]:
        """Get device info by path."""
        for device in self._devices:
            if device.path == path:
                return device
        return None
    
    def get_devices_by_type(self, device_type: str) -> List[DeviceInfo]:
        """Get all devices of a specific type."""
        return [dev for dev in self._devices if dev.device_type == device_type]
    
    def get_wacom_device_id(self, device_path: str) -> Optional[str]:
        """Get Wacom device ID for xsetwacom/xinput commands."""
        try:
            # Try xsetwacom first
            result = subprocess.run(
                ["xsetwacom", "--list", "devices"], 
                capture_output=True, text=True, check=True
            )
            
            for line in result.stdout.splitlines():
                if device_path.split('/')[-1] in line or "event" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == "id:":
                            return parts[i + 1]
            
            # Fallback to xinput
            result = subprocess.run(
                ["xinput", "list", "--name-only"], 
                capture_output=True, text=True, check=True
            )
            for line in result.stdout.splitlines():
                if "wacom" in line.lower() or "pen" in line.lower():
                    return line.strip()
                    
        except Exception as e:
            print(f"Could not get Wacom device ID: {e}")
        
        return None


def create_detector() -> DeviceDetector:
    """Factory function to create a DeviceDetector instance."""
    return DeviceDetector()

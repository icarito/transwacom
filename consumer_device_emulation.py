"""
Consumer device emulation using uinput for TransWacom.
"""
import threading
import time
from typing import Dict, List, Optional, Any

try:
    import evdev
    from evdev import UInput, ecodes, AbsInfo
    EVDEV_AVAILABLE = True
except ImportError:
    evdev = None
    UInput = None
    ecodes = None
    AbsInfo = None
    EVDEV_AVAILABLE = False


class VirtualDevice:
    """Base class for virtual input devices."""
    
    def __init__(self, name: str, capabilities: Dict):
        if not EVDEV_AVAILABLE:
            raise RuntimeError("evdev is required for device emulation")
        
        self.name = name
        self.capabilities = capabilities
        self.uinput = None
        self.active = False
    
    def create(self) -> bool:
        """Create the virtual device."""
        try:
            self.uinput = UInput(self.capabilities, name=self.name)
            self.active = True
            print(f"Created virtual device: {self.name} at {self.uinput.device.path}")
            return True
        except Exception as e:
            print(f"Failed to create virtual device {self.name}: {e}")
            print("Make sure you have permissions for /dev/uinput (usually requires input group)")
            return False
    
    def destroy(self):
        """Destroy the virtual device."""
        if self.uinput:
            try:
                self.uinput.close()
                self.active = False
                print(f"Destroyed virtual device: {self.name}")
            except Exception as e:
                print(f"Error destroying virtual device: {e}")
    
    def write_event(self, event_type: int, event_code: int, value: int):
        """Write an event to the virtual device."""
        if self.uinput and self.active:
            try:
                self.uinput.write(event_type, event_code, value)
            except Exception as e:
                print(f"Error writing event: {e}")
    
    def sync(self):
        """Synchronize events (send EV_SYN)."""
        if self.uinput and self.active:
            try:
                self.uinput.syn()
            except Exception as e:
                print(f"Error syncing events: {e}")


class WacomVirtualDevice(VirtualDevice):
    """Virtual Wacom tablet device."""
    
    def __init__(self, name: str = "Virtual Wacom Tablet"):
        # Wacom tablet capabilities
        capabilities = {
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(value=0, min=0, max=15360, fuzz=0, flat=0, resolution=100)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=0, max=10240, fuzz=0, flat=0, resolution=100)),
                (ecodes.ABS_PRESSURE, AbsInfo(value=0, min=0, max=2047, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_TILT_X, AbsInfo(value=0, min=-64, max=63, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_TILT_Y, AbsInfo(value=0, min=-64, max=63, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_DISTANCE, AbsInfo(value=0, min=0, max=63, fuzz=0, flat=0, resolution=0)),
            ],
            ecodes.EV_KEY: [
                ecodes.BTN_TOOL_PEN,
                ecodes.BTN_TOOL_RUBBER,
                ecodes.BTN_TOUCH,
                ecodes.BTN_STYLUS,
                ecodes.BTN_STYLUS2
            ]
        }
        
        super().__init__(name, capabilities)
    
    def process_events(self, events: List[Dict[str, Any]]):
        """Process a batch of input events."""
        print(f"WacomVirtualDevice: Processing {len(events)} events")
        for event in events:
            code_str = event.get('code', '')
            value = event.get('value', 0)
            print(f"  Event: {code_str} = {value}")
            
            # Parse event code
            event_type, event_code = self._parse_event_code(code_str)
            if event_type is not None and event_code is not None:
                self.write_event(event_type, event_code, value)
            else:
                print(f"  ERROR: Could not parse {code_str}")
        
        # Sync after processing batch
        self.sync()
        print("  Events synced to uinput")
    
    def _parse_event_code(self, code_str: str) -> tuple:
        """Parse event code string to type and code integers."""
        try:
            if code_str.startswith('ABS_'):
                event_type = ecodes.EV_ABS
                event_code = getattr(ecodes, code_str, None)
            elif code_str.startswith('KEY_') or code_str.startswith('BTN_'):
                event_type = ecodes.EV_KEY
                event_code = getattr(ecodes, code_str, None)
            elif code_str.startswith('REL_'):
                event_type = ecodes.EV_REL
                event_code = getattr(ecodes, code_str, None)
            elif code_str.startswith('SYN_'):
                event_type = ecodes.EV_SYN
                event_code = getattr(ecodes, code_str, None)
            else:
                print(f"Unknown event code format: {code_str}")
                return None, None
            
            if event_code is None:
                print(f"Could not resolve event code: {code_str}")
                return None, None
                
            return event_type, event_code
            
        except AttributeError:
            print(f"Unknown event code: {code_str}")
            return None, None


class JoystickVirtualDevice(VirtualDevice):
    """Virtual joystick/gamepad device."""
    
    def __init__(self, name: str = "Virtual Gamepad"):
        # Gamepad capabilities
        capabilities = {
            ecodes.EV_ABS: [
                (ecodes.ABS_X, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Y, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RX, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RY, AbsInfo(value=0, min=-32768, max=32767, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_Z, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_RZ, AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_HAT0X, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
                (ecodes.ABS_HAT0Y, AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
            ],
            ecodes.EV_KEY: [
                ecodes.BTN_A, ecodes.BTN_B, ecodes.BTN_X, ecodes.BTN_Y,
                ecodes.BTN_TL, ecodes.BTN_TR, ecodes.BTN_TL2, ecodes.BTN_TR2,
                ecodes.BTN_SELECT, ecodes.BTN_START, ecodes.BTN_MODE,
                ecodes.BTN_THUMBL, ecodes.BTN_THUMBR
            ]
        }
        
        super().__init__(name, capabilities)
    
    def process_events(self, events: List[Dict[str, Any]]):
        """Process a batch of input events."""
        for event in events:
            code_str = event.get('code', '')
            value = event.get('value', 0)
            
            # Parse event code
            event_type, event_code = self._parse_event_code(code_str)
            if event_type is not None and event_code is not None:
                self.write_event(event_type, event_code, value)
        
        # Sync after processing batch
        self.sync()
    
    def _parse_event_code(self, code_str: str) -> tuple:
        """Parse event code string to type and code integers."""
        try:
            if code_str.startswith('ABS_'):
                event_type = ecodes.EV_ABS
                event_code = getattr(ecodes, code_str, None)
            elif code_str.startswith('KEY_') or code_str.startswith('BTN_'):
                event_type = ecodes.EV_KEY
                event_code = getattr(ecodes, code_str, None)
            elif code_str.startswith('REL_'):
                event_type = ecodes.EV_REL
                event_code = getattr(ecodes, code_str, None)
            elif code_str.startswith('SYN_'):
                event_type = ecodes.EV_SYN
                event_code = getattr(ecodes, code_str, None)
            else:
                print(f"Unknown event code format: {code_str}")
                return None, None
            
            if event_code is None:
                print(f"Could not resolve event code: {code_str}")
                return None, None
                
            return event_type, event_code
            
        except AttributeError:
            print(f"Unknown event code: {code_str}")
            return None, None


class DeviceEmulationManager:
    """Manages virtual device creation and event processing."""
    
    def __init__(self):
        self.virtual_devices = {}
        self.event_queue = {}
        self.processing = False
        self.process_thread = None
    
    def create_virtual_device(self, device_type: str, device_name: Optional[str] = None) -> bool:
        """Create a virtual device of the specified type."""
        if device_type in self.virtual_devices:
            print(f"Virtual device {device_type} already exists")
            return True
        
        try:
            if device_type == 'wacom':
                device = WacomVirtualDevice(device_name or "Virtual Wacom Tablet")
            elif device_type == 'joystick':
                device = JoystickVirtualDevice(device_name or "Virtual Gamepad")
            else:
                print(f"Unsupported device type: {device_type}")
                return False
            
            if device.create():
                self.virtual_devices[device_type] = device
                self.event_queue[device_type] = []
                return True
            else:
                return False
                
        except Exception as e:
            print(f"Failed to create virtual device {device_type}: {e}")
            return False
    
    def destroy_virtual_device(self, device_type: str):
        """Destroy a virtual device."""
        if device_type in self.virtual_devices:
            self.virtual_devices[device_type].destroy()
            del self.virtual_devices[device_type]
            
        if device_type in self.event_queue:
            del self.event_queue[device_type]
    
    def destroy_all_devices(self):
        """Destroy all virtual devices."""
        for device_type in list(self.virtual_devices.keys()):
            self.destroy_virtual_device(device_type)
    
    def process_events(self, device_type: str, events: List[Dict[str, Any]]):
        """Process events for a specific device type."""
        if device_type not in self.virtual_devices:
            # Auto-create device if it doesn't exist
            if not self.create_virtual_device(device_type):
                print(f"Failed to auto-create device {device_type}")
                return
        
        device = self.virtual_devices[device_type]
        device.process_events(events)
    
    def start_event_processing(self):
        """Start background event processing."""
        if self.processing:
            return
        
        self.processing = True
        self.process_thread = threading.Thread(target=self._event_processing_loop, daemon=True)
        self.process_thread.start()
    
    def stop_event_processing(self):
        """Stop background event processing."""
        self.processing = False
        if self.process_thread:
            self.process_thread.join(timeout=1)
    
    def _event_processing_loop(self):
        """Background event processing loop."""
        while self.processing:
            try:
                # Process queued events for each device
                for device_type, events in self.event_queue.items():
                    if events and device_type in self.virtual_devices:
                        device = self.virtual_devices[device_type]
                        batch = events[:10]  # Process in batches of 10
                        self.event_queue[device_type] = events[10:]
                        device.process_events(batch)
                
                time.sleep(0.001)  # 1ms sleep
                
            except Exception as e:
                print(f"Error in event processing loop: {e}")
    
    def queue_events(self, device_type: str, events: List[Dict[str, Any]]):
        """Queue events for processing."""
        if device_type in self.event_queue:
            self.event_queue[device_type].extend(events)
        else:
            # Auto-create queue and device
            self.event_queue[device_type] = events.copy()
            if device_type not in self.virtual_devices:
                self.create_virtual_device(device_type)
    
    def get_active_devices(self) -> List[str]:
        """Get list of active virtual device types."""
        return list(self.virtual_devices.keys())
    
    def get_device_info(self, device_type: str) -> Optional[Dict[str, Any]]:
        """Get information about a virtual device."""
        if device_type in self.virtual_devices:
            device = self.virtual_devices[device_type]
            return {
                'type': device_type,
                'name': device.name,
                'active': device.active,
                'path': device.uinput.device.path if device.uinput else None
            }
        return None
    
    def get_capabilities(self) -> List[str]:
        """Get list of supported device capabilities."""
        return ['wacom', 'joystick']


def create_device_emulation_manager() -> DeviceEmulationManager:
    """Factory function to create a DeviceEmulationManager instance."""
    return DeviceEmulationManager()

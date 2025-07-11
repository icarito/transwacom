"""
Host input capture and device management for TransWacom.
"""
import subprocess
import threading
import time
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass

try:
    import evdev
    from evdev import InputDevice, ecodes
    EVDEV_AVAILABLE = True
except ImportError:
    evdev = None
    InputDevice = None
    ecodes = None
    EVDEV_AVAILABLE = False


@dataclass
class InputEvent:
    """Represents an input event."""
    code: str
    value: int
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for network transmission."""
        return {
            'code': self.code,
            'value': self.value,
            'timestamp': self.timestamp
        }


class WacomController:
    """Controls Wacom tablet configuration via system tools."""
    
    def __init__(self, device_path: str):
        self.device_path = device_path
        self.device_id = None
        self.original_mode = None
        self.was_enabled = True
        
    def get_device_id(self) -> Optional[str]:
        """Get Wacom device ID for xsetwacom/xinput commands."""
        if self.device_id:
            return self.device_id
            
        try:
            # Try xsetwacom first
            result = subprocess.run(
                ["xsetwacom", "--list", "devices"],
                capture_output=True, text=True, check=True
            )
            
            for line in result.stdout.splitlines():
                if self.device_path.split('/')[-1] in line or "event" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if part == "id:":
                            self.device_id = parts[i + 1]
                            return self.device_id
            
            # Fallback to xinput
            result = subprocess.run(
                ["xinput", "list", "--name-only"],
                capture_output=True, text=True, check=True
            )
            for line in result.stdout.splitlines():
                if "wacom" in line.lower() or "pen" in line.lower():
                    self.device_id = line.strip()
                    return self.device_id
                    
        except Exception as e:
            print(f"Could not get Wacom device ID: {e}")
        
        return None
    
    def disable_local_input(self) -> bool:
        """Disable tablet input on local system."""
        device_id = self.get_device_id()
        if not device_id:
            return False
        
        try:
            # Try xinput first
            result = subprocess.run(
                ["xinput", "disable", device_id],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"Device {device_id} disabled locally via xinput")
                self.was_enabled = True
                return True
            
            # Try xsetwacom
            result = subprocess.run(
                ["xsetwacom", "--set", device_id, "Touch", "off"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"Device {device_id} disabled locally via xsetwacom")
                self.was_enabled = True
                return True
                
        except Exception as e:
            print(f"Error disabling device: {e}")
        
        return False
    
    def enable_local_input(self) -> bool:
        """Re-enable tablet input on local system."""
        device_id = self.get_device_id()
        if not device_id or not self.was_enabled:
            return False
        
        try:
            # Try xinput first
            result = subprocess.run(
                ["xinput", "enable", device_id],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"Device {device_id} re-enabled locally")
                return True
            
            # Try xsetwacom
            result = subprocess.run(
                ["xsetwacom", "--set", device_id, "Touch", "on"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"Device {device_id} re-enabled locally")
                return True
                
        except Exception as e:
            print(f"Error re-enabling device: {e}")
        
        return False
    
    def set_relative_mode(self) -> bool:
        """Set tablet to relative mode (mouse-like)."""
        device_id = self.get_device_id()
        if not device_id:
            return False
        
        try:
            result = subprocess.run(
                ["xsetwacom", "--set", device_id, "Mode", "Relative"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"Device {device_id} set to relative mode")
                self.original_mode = "Absolute"
                return True
        except Exception as e:
            print(f"Error setting relative mode: {e}")
        
        return False
    
    def restore_absolute_mode(self) -> bool:
        """Restore tablet to absolute mode."""
        device_id = self.get_device_id()
        if not device_id or not self.original_mode:
            return False
        
        try:
            result = subprocess.run(
                ["xsetwacom", "--set", device_id, "Mode", self.original_mode],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                print(f"Device {device_id} restored to {self.original_mode} mode")
                return True
        except Exception as e:
            print(f"Error restoring absolute mode: {e}")
        
        return False
    
    def cleanup(self):
        """Restore original device settings."""
        print(f"WacomController cleanup for device {self.device_path}")
        print(f"  was_enabled: {self.was_enabled}")
        print(f"  original_mode: {self.original_mode}")
        
        if self.was_enabled:
            print("  Restoring local input...")
            success = self.enable_local_input()
            print(f"  Local input restored: {success}")
            
        if self.original_mode:
            print("  Restoring original mode...")
            success = self.restore_absolute_mode()
            print(f"  Original mode restored: {success}")
            
        print("WacomController cleanup completed")


class InputCapture:
    """Captures input events from a device."""
    
    def __init__(self, device_path: str):
        self.device_path = device_path
        self.device = None
        self.running = False
        self.capture_thread = None
        self.event_callback = None
        self.wacom_controller = None
        
        if not EVDEV_AVAILABLE:
            raise RuntimeError("evdev is required for input capture")
    
    def start(self, event_callback: Callable[[str, List[InputEvent]], None],
              relative_mode: bool = True, disable_local: bool = True) -> bool:
        """Start capturing input events."""
        try:
            self.device = InputDevice(self.device_path)
            self.event_callback = event_callback
            
            print(f"Starting capture from: {self.device.name}")
            
            # Configure Wacom device if detected
            if self._is_wacom_device():
                self.wacom_controller = WacomController(self.device_path)
                
                if relative_mode:
                    self.wacom_controller.set_relative_mode()
                
                if disable_local:
                    self.wacom_controller.disable_local_input()
            
            # Start capture thread
            self.running = True
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()
            
            return True
            
        except Exception as e:
            print(f"Failed to start input capture: {e}")
            return False
    
    def stop(self):
        """Stop capturing input events."""
        print(f"Stopping input capture for {self.device_path}")
        self.running = False
        
        if self.capture_thread:
            print("  Waiting for capture thread to finish...")
            self.capture_thread.join(timeout=1)
        
        if self.wacom_controller:
            print("  Running Wacom controller cleanup...")
            self.wacom_controller.cleanup()
        
        if self.device:
            print("  Closing device...")
            self.device.close()
        
        print("Input capture stopped")
    
    def _is_wacom_device(self) -> bool:
        """Check if the device is a Wacom tablet."""
        if not self.device:
            return False
        
        device_name = self.device.name.lower()
        return "wacom" in device_name or "pen" in device_name
    
    def _capture_loop(self):
        """Main capture loop running in separate thread."""
        try:
            event_batch = []
            last_batch_time = time.time()
            
            for event in self.device.read_loop():
                if not self.running:
                    break
                
                # Convert evdev event to our format
                input_event = InputEvent(
                    code=self._event_code_to_string(event.type, event.code),
                    value=event.value,
                    timestamp=event.timestamp()
                )
                
                event_batch.append(input_event)
                
                # Send batch if we hit sync event or timeout
                current_time = time.time()
                if (event.type == ecodes.EV_SYN or 
                    current_time - last_batch_time > 0.01):  # 10ms batch timeout
                    
                    if event_batch and self.event_callback:
                        device_type = self._get_device_type()
                        print(f"Sending {len(event_batch)} events of type {device_type}")
                        self.event_callback(device_type, event_batch)
                    
                    event_batch = []
                    last_batch_time = current_time
                    
        except Exception as e:
            if self.running:  # Only log if not intentionally stopped
                print(f"Error in capture loop: {e}")
    
    def _event_code_to_string(self, event_type: int, event_code: int) -> str:
        """Convert event type/code to string representation."""
        try:
            if event_type == ecodes.EV_ABS:
                # Direct lookup using dir() for ABS codes
                for name in dir(ecodes):
                    if name.startswith('ABS_') and getattr(ecodes, name) == event_code:
                        return name
                return f"ABS_{event_code}"
                
            elif event_type == ecodes.EV_KEY:
                # Look for BTN_ first, then KEY_
                for name in dir(ecodes):
                    if name.startswith('BTN_') and getattr(ecodes, name) == event_code:
                        return name
                for name in dir(ecodes):
                    if name.startswith('KEY_') and getattr(ecodes, name) == event_code:
                        return name
                return f"KEY_{event_code}"
                
            elif event_type == ecodes.EV_REL:
                for name in dir(ecodes):
                    if name.startswith('REL_') and getattr(ecodes, name) == event_code:
                        return name
                return f"REL_{event_code}"
                
            elif event_type == ecodes.EV_SYN:
                for name in dir(ecodes):
                    if name.startswith('SYN_') and getattr(ecodes, name) == event_code:
                        return name
                return f"SYN_{event_code}"
            else:
                return f"TYPE_{event_type}_CODE_{event_code}"
        except (KeyError, AttributeError):
            return f"TYPE_{event_type}_CODE_{event_code}"
    
    def _get_device_type(self) -> str:
        """Determine device type based on capabilities."""
        if not self.device:
            return "unknown"
        
        if self._is_wacom_device():
            return "wacom"
        
        # Check for joystick/gamepad
        capabilities = self.device.capabilities()
        if (ecodes.EV_ABS in capabilities and 
            ecodes.EV_KEY in capabilities):
            abs_axes = capabilities.get(ecodes.EV_ABS, [])
            if (ecodes.ABS_X in abs_axes or 
                ecodes.ABS_RX in abs_axes or
                ecodes.ABS_HAT0X in abs_axes):
                return "joystick"
        
        return "generic"
    
    def get_device_info(self) -> Dict[str, Any]:
        """Get information about the captured device."""
        if not self.device:
            return {}
        
        capabilities = []
        device_caps = self.device.capabilities()
        
        if self._is_wacom_device():
            abs_axes = device_caps.get(ecodes.EV_ABS, [])
            if ecodes.ABS_PRESSURE in abs_axes:
                capabilities.append("pressure")
            if ecodes.ABS_TILT_X in abs_axes and ecodes.ABS_TILT_Y in abs_axes:
                capabilities.append("tilt")
            if ecodes.ABS_DISTANCE in abs_axes:
                capabilities.append("proximity")
            
            keys = device_caps.get(ecodes.EV_KEY, [])
            if ecodes.BTN_STYLUS in keys:
                capabilities.append("stylus_buttons")
            if ecodes.BTN_TOOL_RUBBER in keys:
                capabilities.append("eraser")
        
        return {
            'type': self._get_device_type(),
            'name': self.device.name,
            'path': self.device_path,
            'capabilities': capabilities
        }


class HostInputManager:
    """Manages input capture from multiple devices."""
    
    def __init__(self):
        self.active_captures = {}
    
    def start_capture(self, device_path: str, 
                     event_callback: Callable[[str, List[InputEvent]], None],
                     relative_mode: bool = True, disable_local: bool = True) -> bool:
        """Start capturing from a device."""
        if device_path in self.active_captures:
            print(f"Device {device_path} is already being captured")
            return False
        
        try:
            capture = InputCapture(device_path)
            if capture.start(event_callback, relative_mode, disable_local):
                self.active_captures[device_path] = capture
                return True
        except Exception as e:
            print(f"Failed to start capture for {device_path}: {e}")
        
        return False
    
    def stop_capture(self, device_path: str):
        """Stop capturing from a device."""
        if device_path in self.active_captures:
            self.active_captures[device_path].stop()
            del self.active_captures[device_path]
    
    def stop_all_captures(self):
        """Stop all active captures."""
        for device_path in list(self.active_captures.keys()):
            self.stop_capture(device_path)
    
    def get_active_devices(self) -> List[str]:
        """Get list of actively captured device paths."""
        return list(self.active_captures.keys())
    
    def get_device_info(self, device_path: str) -> Optional[Dict[str, Any]]:
        """Get information about a captured device."""
        if device_path in self.active_captures:
            return self.active_captures[device_path].get_device_info()
        return None
    
    def is_capturing(self, device_path: str) -> bool:
        """Check if device is being captured."""
        return device_path in self.active_captures


def create_host_input_manager() -> HostInputManager:
    """Factory function to create a HostInputManager instance."""
    return HostInputManager()

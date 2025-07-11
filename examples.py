#!/usr/bin/env python3
"""
Examples of using TransWacom modules independently.
"""

def example_device_detection():
    """Example: Device detection and information."""
    print("=== Device Detection Example ===")
    
    from device_detector import create_detector
    
    detector = create_detector()
    devices = detector.detect_all_devices()
    
    print(f"Found {len(devices)} devices:")
    for device in devices:
        print(f"  {device}")
        print(f"    Capabilities: {', '.join(device.capabilities)}")
        print(f"    Dictionary: {device.to_dict()}")
    
    # Get Wacom devices specifically
    wacom_devices = detector.get_devices_by_type('wacom')
    print(f"\nWacom devices: {len(wacom_devices)}")
    
    if wacom_devices:
        device = wacom_devices[0]
        wacom_id = detector.get_wacom_device_id(device.path)
        print(f"  Wacom ID for {device.path}: {wacom_id}")


def example_configuration():
    """Example: Configuration management."""
    print("\n=== Configuration Example ===")
    
    from config_manager import create_config_manager
    
    config = create_config_manager()
    
    print(f"Machine ID: {config.machine_id}")
    print(f"Machine Name: {config.machine_name}")
    print(f"Consumer Port: {config.get_consumer_port()}")
    print(f"mDNS Name: {config.get_mdns_name()}")
    
    # Add a trusted consumer
    config.add_trusted_consumer("TestConsumer", "test123", ["wacom"], auto_accept=True)
    print("Added trusted consumer")
    
    # Check trust
    is_trusted = config.is_consumer_trusted("TestConsumer", "test123")
    print(f"TestConsumer is trusted: {is_trusted}")
    
    # Host configuration
    print(f"Use relative mode: {config.should_use_relative_mode()}")
    print(f"Disable local: {config.should_disable_local()}")


def example_network_protocol():
    """Example: Network protocol usage."""
    print("\n=== Network Protocol Example ===")
    
    from transnetwork import NetworkProtocol
    
    protocol = NetworkProtocol()
    
    # Create messages
    handshake = protocol.create_handshake(
        host_name="ExampleHost",
        host_id="abc123",
        devices=[{
            'type': 'wacom',
            'name': 'Example Wacom',
            'capabilities': ['pressure', 'tilt']
        }]
    )
    
    events = protocol.create_event_message(
        device_type='wacom',
        events=[
            {'code': 'ABS_X', 'value': 1000},
            {'code': 'ABS_Y', 'value': 2000},
            {'code': 'ABS_PRESSURE', 'value': 500}
        ]
    )
    
    auth_response = protocol.create_auth_response(
        accepted=True,
        consumer_name="ExampleConsumer",
        consumer_id="def456"
    )
    
    print("Example messages:")
    print(f"Handshake: {handshake}")
    print(f"Events: {events}")
    print(f"Auth Response: {auth_response}")
    
    # Pack and unpack
    packed = protocol.pack_message(handshake)
    print(f"Packed size: {len(packed)} bytes")
    
    unpacked = protocol.unpack_messages(packed)
    print(f"Unpacked: {unpacked}")


def example_host_input():
    """Example: Host input capture (demonstration only)."""
    print("\n=== Host Input Example ===")
    
    from host_input import create_host_input_manager
    from device_detector import create_detector
    
    # Get available devices
    detector = create_detector()
    devices = detector.detect_all_devices()
    
    if not devices:
        print("No devices available for input capture example")
        return
    
    input_manager = create_host_input_manager()
    
    print(f"Would capture from: {devices[0]}")
    print("(Not actually starting capture in example)")
    
    # In real usage:
    # def event_callback(device_type, events):
    #     print(f"Received {len(events)} events from {device_type}")
    #     for event in events:
    #         print(f"  {event.code}: {event.value}")
    # 
    # success = input_manager.start_capture(
    #     devices[0].path, event_callback, 
    #     relative_mode=True, disable_local=True
    # )
    # 
    # if success:
    #     time.sleep(5)  # Capture for 5 seconds
    #     input_manager.stop_capture(devices[0].path)


def example_device_emulation():
    """Example: Device emulation (demonstration only)."""
    print("\n=== Device Emulation Example ===")
    
    from consumer_device_emulation import create_device_emulation_manager
    
    emulation_manager = create_device_emulation_manager()
    
    print("Available capabilities:", emulation_manager.get_capabilities())
    
    # Create virtual devices (commented out to avoid requiring permissions)
    print("Would create virtual Wacom device")
    print("(Not actually creating device in example)")
    
    # In real usage:
    # success = emulation_manager.create_virtual_device('wacom')
    # if success:
    #     # Process some events
    #     events = [
    #         {'code': 'ABS_X', 'value': 1000},
    #         {'code': 'ABS_Y', 'value': 2000},
    #         {'code': 'SYN_REPORT', 'value': 0}
    #     ]
    #     emulation_manager.process_events('wacom', events)
    #     
    #     time.sleep(1)
    #     emulation_manager.destroy_virtual_device('wacom')


def example_mdns_discovery():
    """Example: mDNS discovery (demonstration only)."""
    print("\n=== mDNS Discovery Example ===")
    
    from transnetwork import create_network
    
    network = create_network()
    
    print("Would start mDNS discovery")
    print("(Not actually starting discovery in example)")
    
    # In real usage:
    # def on_discovery(consumer):
    #     print(f"Found consumer: {consumer.name} at {consumer.address}:{consumer.port}")
    # 
    # network.discover_consumers(on_discovery)
    # time.sleep(5)  # Discover for 5 seconds
    # network.stop_discovery()


if __name__ == "__main__":
    """Run all examples."""
    print("TransWacom Module Examples")
    print("=" * 50)
    
    try:
        example_device_detection()
        example_configuration()
        example_network_protocol()
        example_host_input()
        example_device_emulation()
        example_mdns_discovery()
        
        print("\n=== Examples completed ===")
        print("Note: Some examples are demonstrations only to avoid")
        print("requiring special permissions or hardware.")
        
    except Exception as e:
        print(f"Example error: {e}")
        print("Some dependencies may not be installed.")

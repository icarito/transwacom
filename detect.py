import evdev
from evdev import InputDevice, ecodes

# Cambia este path por el de tu tableta (puedes ver los dispositivos con: python -m evdev.evtest)
DEVICE_PATH = '/dev/input/event19'  # <-- AJUSTA ESTO

def main():
    dev = InputDevice(DEVICE_PATH)
    print(f"Escuchando presión en: {dev.name} ({DEVICE_PATH})")
    for event in dev.read_loop():
        if event.type == ecodes.EV_ABS and event.code == ecodes.ABS_PRESSURE:
            print(f"Presión: {event.value}")

if __name__ == "__main__":
    main()
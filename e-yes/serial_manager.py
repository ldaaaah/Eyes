import serial

_ser = None

def get_serial(port="/dev/ttyUSB0", baud=9600):
    global _ser
    if _ser is None or not _ser.is_open:
        _ser = serial.Serial(port, baud, timeout=0.1)
    return _ser

def close_serial():
    global _ser
    if _ser and _ser.is_open:
        _ser.close()
        _ser = None
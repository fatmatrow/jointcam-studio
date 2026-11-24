INPUT_MODES = ("Device default", "640x360", "640x480", "960x540", "1280x720", "1920x1080")
INPUT_RATES = (0,15,24,30,60)  # Zero leaves frame rate selection to the driver.
OUTPUT_MODES = ("640x360", "960x540", "1280x720", "1920x1080")


def is_kiyo_pro(name):
    words=" ".join(name.casefold().split())
    return "kiyo pro" in words.split(" (")[0] and "ultra" not in words and "virtual" not in words


def kiyo_identity(name,vid=None,pid=None):
    if (vid,pid)==(0x1532,0x0e05) or is_kiyo_pro(name):
        return "confirmed"
    if " ".join(name.casefold().split())=="usb video device" and (vid is None or pid is None):
        return "generic"
    return ""


def dimensions(mode):
    if mode == "Device default":
        return None
    return tuple(map(int, mode.split("x")))


def display_mode(mode):
    return mode.replace("x", " × ")

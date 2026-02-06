def parse_timecode(value):
    text = value.strip()
    if not text:
        raise ValueError("Timecode cannot be empty.")

    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError("Timecode must be ss, mm:ss, or hh:mm:ss.")

    if len(parts) == 3:
        hours_str, minutes_str, seconds_str = parts
        hours = int(hours_str)
        minutes = int(minutes_str)
        seconds = float(seconds_str)
        if minutes >= 60 or seconds >= 60:
            raise ValueError("Minutes and seconds must be < 60 for hh:mm:ss.")
    elif len(parts) == 2:
        minutes_str, seconds_str = parts
        hours = 0
        minutes = int(minutes_str)
        seconds = float(seconds_str)
        if minutes >= 60 or seconds >= 60:
            raise ValueError("Minutes and seconds must be < 60 for mm:ss.")
    else:
        hours = 0
        minutes = 0
        seconds = float(parts[0])

    if hours < 0 or minutes < 0 or seconds < 0:
        raise ValueError("Timecode must be non-negative.")

    return hours * 3600 + minutes * 60 + seconds


def format_seconds(value):
    return f"{value:.6f}".rstrip("0").rstrip(".")

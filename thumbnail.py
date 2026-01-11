
# Written almost entirely by ChatGPT4


import os
import random
import sys
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(__file__)
FONT_PATH = os.path.join(SCRIPT_DIR, "assets", "cour_bold.ttf")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
TEST_THUMBNAIL_PREFIX = "test_thumbnail_"
BASE_WIDTH = 1920
BASE_HEIGHT = 1080
BASE_BORDER_SIZE = 50
BASE_TEXT_PADDING_X = 120
BASE_TEXT_PADDING_Y = 70
BASE_MAIN_FONT_SIZE = 300
BASE_SUB_FONT_SIZE = 100
BASE_GAP = 30
BASE_VERTICAL_OFFSET = 0
BASE_MAIN_OFFSET_Y = -40
BASE_SUB_OFFSET_Y = 20
LINE_SPACING_FACTOR = 0.0
MAX_SUB_LINES = 3
MIN_FONT_SIZE = 12
MAX_SCALE = 2.5
MAX_MAIN_FONT_SIZE = 320
MAX_SUB_FONT_SIZE = 120
TEST_THUMBNAIL_COUNT = 30
LOREM_WORDS = [
    "lorem",
    "ipsum",
    "dolor",
    "sit",
    "amet",
    "consectetur",
    "adipiscing",
    "elit",
    "sed",
    "do",
    "eiusmod",
    "tempor",
    "incididunt",
    "ut",
    "labore",
    "et",
    "dolore",
    "magna",
    "aliqua",
]
_FONT_CACHE = {}


def scale_value(value, scale):
    return int(round(value * scale))


def get_font(size):
    try:
        if size not in _FONT_CACHE:
            _FONT_CACHE[size] = ImageFont.truetype(FONT_PATH, size)
        return _FONT_CACHE[size]
    except IOError:
        raise FileNotFoundError("Font file not found.") from None


def text_dimensions(draw, text, font):
    left, top, right, bottom = draw.textbbox((0, 0), text=text, font=font)
    return right - left, bottom - top


def line_height(draw, font):
    return text_dimensions(draw, "Ag", font)[1]


def wrap_text(draw, text, font, max_width, max_lines):
    words = text.split()
    if not words:
        return [""]

    lines = []
    current = words[0]
    if draw.textlength(current, font=font) > max_width:
        return None

    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue

        lines.append(current)
        current = word
        if draw.textlength(current, font=font) > max_width:
            return None
        if len(lines) >= max_lines:
            return None

    lines.append(current)
    if len(lines) > max_lines:
        return None

    return lines


def compute_layout(draw, width, height, text1, text2):
    scale_x = width / BASE_WIDTH
    scale_y = height / BASE_HEIGHT
    border_size = scale_value(BASE_BORDER_SIZE, scale_y)
    padding_x = scale_value(BASE_TEXT_PADDING_X, scale_x)
    padding_y = scale_value(BASE_TEXT_PADDING_Y, scale_y)
    vertical_offset = scale_value(BASE_VERTICAL_OFFSET, scale_y)
    main_offset_y = scale_value(BASE_MAIN_OFFSET_Y, scale_y)
    sub_offset_y = scale_value(BASE_SUB_OFFSET_Y, scale_y)

    usable_left = border_size + padding_x
    usable_top = border_size + padding_y
    usable_width = width - 2 * usable_left
    usable_height = height - 2 * usable_top

    base_main_size = BASE_MAIN_FONT_SIZE * scale_y
    base_gap = BASE_GAP * scale_y

    sub_size = min(scale_value(BASE_SUB_FONT_SIZE, scale_y), MAX_SUB_FONT_SIZE)
    font_sub = get_font(sub_size)
    sub_lines = wrap_text(draw, text2, font_sub, usable_width, MAX_SUB_LINES)
    if not sub_lines:
        raise ValueError("Subtext is too large to fit inside the thumbnail.")

    sub_line_height = line_height(draw, font_sub)
    sub_line_spacing = int(round(sub_line_height * LINE_SPACING_FACTOR))
    sub_height = (
        sub_line_height * len(sub_lines)
        + sub_line_spacing * (len(sub_lines) - 1)
    )

    min_scale = MIN_FONT_SIZE / base_main_size
    low = min_scale
    max_scale_main = MAX_MAIN_FONT_SIZE / base_main_size
    max_scale = min(MAX_SCALE, max_scale_main)
    high = max(low, max_scale)
    best = None

    def try_layout(scale):
        main_size = max(1, int(round(base_main_size * scale)))
        font_main = get_font(main_size)

        main_width, main_height = text_dimensions(draw, text1, font_main)
        if main_width > usable_width:
            return None

        gap = int(round(base_gap))
        total_height = main_height + gap + sub_height
        shifted_main_y = main_offset_y
        shifted_sub_y = main_height + gap + sub_offset_y
        topmost = min(shifted_main_y, shifted_sub_y)
        bottommost = max(
            shifted_main_y + main_height,
            shifted_sub_y + sub_height,
        )
        span = bottommost - topmost
        if span > usable_height:
            return None

        return {
            "font_main": font_main,
            "font_sub": font_sub,
            "main_width": main_width,
            "main_height": main_height,
            "sub_lines": sub_lines,
            "sub_line_height": sub_line_height,
            "sub_line_spacing": sub_line_spacing,
            "sub_height": sub_height,
            "gap": gap,
            "total_height": total_height,
            "topmost": topmost,
            "span": span,
            "usable_top": usable_top,
            "usable_height": usable_height,
        }

    for _ in range(20):
        mid = (low + high) / 2
        candidate = try_layout(mid)
        if candidate:
            best = candidate
            low = mid
        else:
            high = mid

    if not best:
        raise ValueError("Text is too large to fit inside the thumbnail.")

    block_top = (
        best["usable_top"]
        + (best["usable_height"] - best["span"]) // 2
        - best["topmost"]
        + vertical_offset
    )
    min_top = best["usable_top"] - best["topmost"]
    max_top = best["usable_top"] + best["usable_height"] - best["span"] - best["topmost"]
    block_top = max(min_top, min(block_top, max_top))
    main_x = (width - best["main_width"]) // 2
    main_y = block_top + main_offset_y
    sub_y = block_top + best["main_height"] + best["gap"] + sub_offset_y

    return {
        "font_main": best["font_main"],
        "font_sub": best["font_sub"],
        "main_x": main_x,
        "main_y": main_y,
        "sub_lines": best["sub_lines"],
        "sub_y": sub_y,
        "sub_line_height": best["sub_line_height"],
        "sub_line_spacing": best["sub_line_spacing"],
    }


def generate_thumbnail(text1, text2, output_path):
    width, height = BASE_WIDTH, BASE_HEIGHT
    border_size = BASE_BORDER_SIZE

    img = Image.new("RGB", (width, height), color="#222222")
    draw = ImageDraw.Draw(img)

    try:
        layout = compute_layout(draw, width, height, text1, text2)
    except FileNotFoundError as exc:
        print(str(exc))
        sys.exit(1)
    except ValueError as exc:
        print(str(exc))
        sys.exit(1)

    draw.text((layout["main_x"], layout["main_y"]), text1, font=layout["font_main"], fill="white")

    for index, line in enumerate(layout["sub_lines"]):
        line_width, _ = text_dimensions(draw, line, layout["font_sub"])
        line_x = (width - line_width) // 2
        line_y = layout["sub_y"] + index * (
            layout["sub_line_height"] + layout["sub_line_spacing"]
        )
        draw.text((line_x, line_y), line, font=layout["font_sub"], fill="white")

    for i in range(border_size):
        draw.rectangle([i, i, width - 1 - i, height - 1 - i], outline="white")

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Save the image
    img.save(output_path)


def generate_empty_thumbnail(output_path):
    width, height = BASE_WIDTH, BASE_HEIGHT
    border_size = BASE_BORDER_SIZE

    img = Image.new("RGB", (width, height), color="#222222")
    draw = ImageDraw.Draw(img)

    for i in range(border_size):
        draw.rectangle([i, i, width - 1 - i, height - 1 - i], outline="white")

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    img.save(output_path)


def next_test_output_dir(base_output_dir):
    max_index = 0
    if os.path.isdir(base_output_dir):
        for name in os.listdir(base_output_dir):
            if not name.startswith(TEST_THUMBNAIL_PREFIX):
                continue
            suffix = name[len(TEST_THUMBNAIL_PREFIX):]
            if not suffix.isdigit():
                continue
            max_index = max(max_index, int(suffix))
    return os.path.join(base_output_dir, f"{TEST_THUMBNAIL_PREFIX}{max_index + 1}")


def random_phrase(min_words, max_words, title_case=False):
    count = random.randint(min_words, max_words)
    words = [random.choice(LOREM_WORDS) for _ in range(count)]
    if title_case:
        return " ".join(word.capitalize() for word in words)
    return " ".join(words).capitalize()


def generate_test_thumbnails(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    for index in range(1, TEST_THUMBNAIL_COUNT + 1):
        title = random_phrase(1, 5, title_case=True)
        subtitle = random_phrase(3, 10)
        filename = f"thumbnail_{index:02d}.png"
        output_path = os.path.join(output_dir, filename)
        generate_thumbnail(title, subtitle, output_path)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a thumbnail with two lines of text.")
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Generate a batch of test thumbnails in output/test_thumbnail_N/.",
    )
    parser.add_argument(
        "-e",
        "--empty",
        action="store_true",
        help="Generate an empty thumbnail (background + border only).",
    )
    parser.add_argument("text1", nargs="?", help="Primary text")
    parser.add_argument("text2", nargs="?", help="Secondary text")
    parser.add_argument("output_path", nargs="?", help="Output PNG path")

    args = parser.parse_args()

    if args.test and args.empty:
        parser.error("--test and --empty cannot be used together.")

    if args.test:
        extra_args = [args.text1, args.text2, args.output_path]
        if any(arg is not None for arg in extra_args):
            parser.error("Test mode does not accept text or output_path arguments.")
        output_dir = next_test_output_dir(OUTPUT_DIR)
        generate_test_thumbnails(output_dir)
        print(f"Generated {TEST_THUMBNAIL_COUNT} thumbnails in {output_dir}")
        raise SystemExit(0)

    if args.empty:
        extra_args = [args.text1, args.text2]
        if any(arg is not None for arg in extra_args):
            parser.error("Empty mode does not accept text arguments.")
        output_path = args.output_path or os.path.join(OUTPUT_DIR, "thumbnail.png")
        generate_empty_thumbnail(output_path)
        print(f"Thumbnail saved to {output_path}")
        raise SystemExit(0)

    if args.text1 is None or args.text2 is None:
        parser.error("text1 and text2 are required unless --test is set.")

    output_path = args.output_path or os.path.join(OUTPUT_DIR, "thumbnail.png")
    generate_thumbnail(args.text1, args.text2, output_path)
    print(f"Thumbnail saved to {output_path}")

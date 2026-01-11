# Written almost entirely by ChatGPT4

import os
from PIL import Image, ImageDraw, ImageFont

SCRIPT_DIR = os.path.dirname(__file__)
FONT_PATH = os.path.join(SCRIPT_DIR, "assets", "cour_bold.ttf")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
TEST_OUTPUT_PREFIX = "test_output_"
TEST_SIZES = [
    (1920, 1080),
    (1280, 720),
    (2560, 1440),
    (3840, 2160),
    (1080, 1920),
    (720, 1280),
    (1440, 2560),
    (2160, 1080),
    (2560, 1080),
    (3440, 1440),
    (720, 720),
    (1080, 1080),
    (1440, 1440),
    (2160, 2160),
    (1024, 1024),
    (1280, 1024),
    (640, 480),
    (720, 480),
    (720, 576),
    (1024, 768),
]
BASE_WIDTH = 1920
BASE_HEIGHT = 1080
BASE_FONT_SIZE = 24
BASE_LEFT_MARGIN = 7
BASE_RIGHT_MARGIN = 6
BASE_BOTTOM_MARGIN = 3
BASE_TEXT_OFFSET_Y = -1
BASE_PADDING_X = 4
BASE_PADDING_Y = 2
BASE_RECT_LEFT_LEFT = 10
BASE_RECT_LEFT_RIGHT = 4
BASE_RECT_RIGHT_LEFT = 8
BASE_RECT_RIGHT_RIGHT = 11
BASE_RECT_TOP = 3
BASE_RECT_BOTTOM = 5
BASE_EXTRA_TOP_PADDING = 0


def scale_value(value, scale):
    return int(round(value * scale))


def textsize(text, font):
    img = Image.new(mode="P", size=(1, 1))
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = draw.textbbox((0, 0), text=text, font=font)
    return right - left, bottom - top


def create_text_overlay(width, height, text, bottom_right_text, output_path):
    # Create a transparent image of the same dimensions
    img = Image.new("RGBA", (width, height), (255, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    scale_x = width / BASE_WIDTH
    scale_y = height / BASE_HEIGHT
    padding_x = scale_value(BASE_PADDING_X, scale_x)
    padding_y = scale_value(BASE_PADDING_Y, scale_y)
    text_offset_y = scale_value(BASE_TEXT_OFFSET_Y, scale_y)
    extra_top_padding = scale_value(BASE_EXTRA_TOP_PADDING, scale_y)
    left_margin = scale_value(BASE_LEFT_MARGIN, scale_x)
    right_margin = scale_value(BASE_RIGHT_MARGIN, scale_x)
    bottom_margin = scale_value(BASE_BOTTOM_MARGIN, scale_y)
    rect_left_left = scale_value(BASE_RECT_LEFT_LEFT, scale_x)
    rect_left_right = scale_value(BASE_RECT_LEFT_RIGHT, scale_x)
    rect_right_left = scale_value(BASE_RECT_RIGHT_LEFT, scale_x)
    rect_right_right = scale_value(BASE_RECT_RIGHT_RIGHT, scale_x)
    rect_top = scale_value(BASE_RECT_TOP, scale_y)
    rect_bottom = scale_value(BASE_RECT_BOTTOM, scale_y)

    # Define font, size and text
    font_size = max(1, scale_value(BASE_FONT_SIZE, scale_y))
    font = ImageFont.truetype(FONT_PATH, font_size)

    # Calculate text width and height
    text_width, text_height = textsize(text, font=font)

    # Position text at the bottom left
    x, y = left_margin, height - text_height - bottom_margin + text_offset_y

    # Define the position and size of the background rectangle for the text
    rect_x0 = x - rect_left_left - padding_x
    rect_y0 = y - rect_top - padding_y - extra_top_padding
    rect_x1 = x + text_width + rect_left_right + padding_x
    rect_y1 = y + text_height + rect_bottom + padding_y

    # Draw the black rectangle behind the text
    draw.rounded_rectangle([rect_x0, rect_y0, rect_x1, rect_y1], fill="#202020", radius=2)

    # Add text over the rectangle
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))

    if bottom_right_text:
        # Calculate text width and height
        text_width, text_height = textsize(bottom_right_text, font=font)

        # Position text at the bottom right
        x, y = width - text_width - right_margin, height - text_height - bottom_margin + text_offset_y

        # Define the position and size of the background rectangle for the text
        rect_x0 = x - rect_right_left - padding_x
        rect_y0 = y - rect_top - padding_y - extra_top_padding
        rect_x1 = x + text_width + rect_right_right + padding_x
        rect_y1 = y + text_height + rect_bottom + padding_y

        # Draw the black rectangle behind the text
        draw.rounded_rectangle([rect_x0, rect_y0, rect_x1, rect_y1], fill="#202020", radius=2)

        # Add text over the rectangle
        draw.text((x, y), bottom_right_text, font=font, fill=(255, 255, 255, 255))

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # Save the image
    img.save(output_path)

    return output_path


def next_test_output_dir(base_output_dir):
    max_index = 0
    if os.path.isdir(base_output_dir):
        for name in os.listdir(base_output_dir):
            if not name.startswith(TEST_OUTPUT_PREFIX):
                continue
            suffix = name[len(TEST_OUTPUT_PREFIX):]
            if not suffix.isdigit():
                continue
            max_index = max(max_index, int(suffix))
    return os.path.join(base_output_dir, f"{TEST_OUTPUT_PREFIX}{max_index + 1}")


def generate_test_overlays(output_dir):
    os.makedirs(output_dir, exist_ok=True)
    for width, height in TEST_SIZES:
        filename = f"overlay_{width}x{height}.png"
        output_path = os.path.join(output_dir, filename)
        create_text_overlay(
            width,
            height,
            "Test Overlay",
            f"{width}x{height}",
            output_path,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a PNG overlay from dimensions and text.")
    parser.add_argument(
        "-t",
        "--test",
        action="store_true",
        help="Generate test overlays in output/test_output_N.",
    )
    parser.add_argument("width", type=int, nargs="?", help="Overlay width in pixels")
    parser.add_argument("height", type=int, nargs="?", help="Overlay height in pixels")
    parser.add_argument("text", nargs="?", help="Bottom-left overlay text")
    parser.add_argument("output_path", nargs="?", help="Output PNG path")
    parser.add_argument(
        "bottom_right_text",
        nargs="?",
        default=None,
        help="Optional bottom-right overlay text",
    )

    args = parser.parse_args()
    if args.test:
        extra_args = [args.width, args.height, args.text, args.output_path, args.bottom_right_text]
        if any(arg is not None for arg in extra_args):
            parser.error("Test mode does not accept width/height/text/output_path arguments.")
        test_output_dir = next_test_output_dir(OUTPUT_DIR)
        generate_test_overlays(test_output_dir)
        print(f"Generated {len(TEST_SIZES)} overlays in {test_output_dir}")
        raise SystemExit(0)

    if args.width is None or args.height is None or args.text is None or args.output_path is None:
        parser.error("width, height, text, and output_path are required unless --test is set.")

    create_text_overlay(
        args.width,
        args.height,
        args.text,
        args.bottom_right_text,
        args.output_path,
    )


# Written almost entirely by ChatGPT4


from PIL import Image, ImageDraw, ImageFont
import sys
import os

def generate_thumbnail(text1, text2, output_path):
    # Image dimensions
    width, height = 1920, 1080
    border_size = 20

    # Create a new image with a black background
    img = Image.new('RGB', (width, height), color='black')
    draw = ImageDraw.Draw(img)

    # Fonts
    try:
        font_path = "/home/matt/Projects/video_tools/assets/cour_bold.ttf"
        font1 = ImageFont.truetype(font_path, 120)
        font2 = ImageFont.truetype(font_path, 60)
    except IOError:
        print("Font file not found.")
        sys.exit(1)

    # Calculate text size and position for text1
    text1_size = draw.textsize(text1, font=font1)
    text1_x = (width - text1_size[0]) // 2
    text1_y = (height - text1_size[1]) // 2 - 30  # Adjust y to leave space for text2

    # Calculate text size and position for text2
    text2_size = draw.textsize(text2, font=font2)
    text2_x = (width - text2_size[0]) // 2
    text2_y = text1_y + text1_size[1] + 10  # Position below text1

    # Draw text on the image
    draw.text((text1_x, text1_y), text1, font=font1, fill="white")
    draw.text((text2_x, text2_y), text2, font=font2, fill="white")

    # Draw white border
    for i in range(border_size):
        draw.rectangle([i, i, width-1-i, height-1-i], outline="white")

    # Save the image
    img.save(output_path)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python generate_thumbnail.py <text1> <text2> <output_path>")
        sys.exit(1)

    text1 = sys.argv[1]
    text2 = sys.argv[2]
    output_path = sys.argv[3]

    generate_thumbnail(text1, text2, output_path)
    print(f"Thumbnail saved to {output_path}")
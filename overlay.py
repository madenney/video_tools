
# Written almost entirely by ChatGPT

import sys
import os
import subprocess
import json
from PIL import Image, ImageDraw, ImageFont

def get_video_dimensions(video_path):
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-select_streams', 'v:0', 
        '-show_entries', 'stream=width,height', 
        '-of', 'json', 
        video_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    video_info = json.loads(result.stdout)
    width = video_info['streams'][0]['width']
    height = video_info['streams'][0]['height']
    return width, height


def create_text_overlay(video_path, text, bottom_right_text):
    # Get video dimensions
    width, height = get_video_dimensions(video_path)

    # Create a transparent image of the same dimensions
    img = Image.new('RGBA', (width, height), (255, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Define font, size and text
    font_size = int(height / 45)  # Dynamic size based on video height
    font = ImageFont.truetype("./assets/cour_bold.ttf", font_size)

    # Calculate text width and height
    text_width, text_height = textsize(text, font=font)

    # Position text at the bottom left
    x, y = 7, height - text_height - 3

    # Define the position and size of the background rectangle for the text
    # Rectangle coordinates (x0, y0, x1, y1)
    rect_x0 = x - 10  
    rect_y0 = y - 3 
    rect_x1 = x + text_width + 4  
    rect_y1 = y + text_height + 5  

    # Draw the black rectangle behind the text
    #d.rounded_rectangle([(rect_x0, rect_y0), (rect_x1, rect_y1 )], fill="#202020", radius=5)
    d.rounded_rectangle([rect_x0, rect_y0, rect_x1, rect_y1], fill="#202020", radius = 2)

    # Add text over the rectangle
    d.text((x, y), text, font=font, fill=(255,255,255,255))

    
    if bottom_right_text:
        # Calculate text width and height
        text_width, text_height = textsize(bottom_right_text, font=font)

        # Position text at the bottom right
        x, y = width - text_width - 6, height - text_height - 3

        # Define the position and size of the background rectangle for the text
        # Rectangle coordinates (x0, y0, x1, y1)
        rect_x0 = x - 8  
        rect_y0 = y - 3 
        rect_x1 = x + text_width + 11  
        rect_y1 = y + text_height + 5  

        # Draw the black rectangle behind the text
        #d.rounded_rectangle([(rect_x0, rect_y0), (rect_x1, rect_y1 )], fill="#202020", radius=5)
        d.rounded_rectangle([rect_x0, rect_y0, rect_x1, rect_y1], fill="#202020", radius = 2)

        # Add text over the rectangle
        d.text((x, y), bottom_right_text, font=font, fill=(255,255,255,255))

    # Save the image
    text_overlay_path = 'overlay.png'
    img.save(text_overlay_path)

    return text_overlay_path

def overlay_text_on_video(video_path, overlay_image_path, output_video_path):
    # Construct FFmpeg command to overlay the png onto the video
    # cmd = f"ffmpeg -i {video_path} -i {overlay_image_path} -filter_complex " \
    #       f"\"[0:v][1:v] overlay=0:0\" -codec:a copy {output_video_path}"

    cmd = (
        f"ffmpeg -i {video_path} -i {overlay_image_path} "
        f"-filter_complex "
        f"\"[0:v][1:v]scale2ref[vid][ovr];[vid][ovr]overlay=format=auto:0:0\" "
        f"-codec:a copy {output_video_path}"
    )

    print("Executing command:", cmd)
    os.system(cmd)


def textsize(text, font):
    im = Image.new(mode="P", size=(0, 0))
    draw = ImageDraw.Draw(im)
    _, _, width, height = draw.textbbox((0, 0), text=text, font=font)
    return width, height

if __name__ == "__main__":
    if len(sys.argv) != 4 and len(sys.argv) != 5:
        print("Usage: python overlay.py <video_file_path> <video_output_path> <overlay_text> <overlay_text_bottom_right> (optional)")
        sys.exit(1)

    video_file_path = sys.argv[1]
    video_output_path = sys.argv[2]
    overlay_text = sys.argv[3]
    overlay_text_2 = sys.argv[4]

    # Generate overlay
    overlay_image_path = create_text_overlay(video_file_path, overlay_text, overlay_text_2)

    # Overlay text onto the video
    overlay_text_on_video(video_file_path, overlay_image_path, video_output_path)
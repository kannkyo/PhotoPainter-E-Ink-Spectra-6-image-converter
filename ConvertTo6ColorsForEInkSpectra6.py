# encoding: utf-8

import sys
import os
import os.path
import concurrent.futures
import numpy as np
from PIL import Image, ImagePalette, ImageOps, ImageEnhance, ImageFilter
import argparse
import pillow_heif
from tqdm import tqdm

pillow_heif.register_heif_opener()

# Define the 6-color palette (black, white, yellow, red, blue, green)
# Extracted from the putpalette call: (0,0,0, 255,255,255, 255,255,0, 255,0,0, 0,0,255, 0,255,0)
# Using Compensated Colors R, Y, G, B
PALETTE_COLORS = [
    (0, 0, 0),      # Black
    (255, 255, 255),  # White
    (255, 255, 0),   # Yellow
    (255, 0, 0),     # Red
    (0, 0, 255),     # Blue
    (0, 255, 0)      # Green
]

# Tried custom palette colors for better closer actual colors on the e-ink display, but adjusted closest_palette_color function instead
#                   Black          White         Yellow        Red           Blue          Green
# PALETTE_COLORS = [(0, 0, 0), (255, 255, 255), (240, 224, 80), (160, 32, 32), (80, 128, 184), (96, 128, 80)]

# Precompute palette as NumPy arrays for faster access
PALETTE_ARRAY = np.array(PALETTE_COLORS, dtype=np.float32)
# blue and green prints darker, lower its luma value so the distance metric favors it over white, also at luma1
PALETTE_LUMA_ARRAY = np.array(
    [r*250 + g*350 + b*400 for (r, g, b) in PALETTE_COLORS], dtype=np.float32) / (255.0 * 1000)

# Find the closest palette color using floating-point arithmetic (exact RGBL method)


def closest_palette_color(rgb):
    r1, g1, b1 = rgb
    # Calculate luma for the input pixel
    luma1 = (r1 * 250 + g1 * 350 + b1 * 400) / (255.0 * 1000)

    # Calculate differences using precomputed arrays
    diffR = r1 - PALETTE_ARRAY[:, 0]
    diffG = g1 - PALETTE_ARRAY[:, 1]
    diffB = b1 - PALETTE_ARRAY[:, 2]

    # Calculate RGB component of distance
    # boost blue, reduce green a bit and red a little more to compensate for human eye sensitivity and e-ink display characteristics (trial and error)
    rgb_dist = (diffR*diffR*0.250 + diffG*diffG*0.350 +
                diffB*diffB*0.400) * 0.75 / (255.0*255.0)

    # Calculate luma differences
    luma_diff = luma1 - PALETTE_LUMA_ARRAY
    luma_dist = luma_diff * luma_diff

    # Total distance
    # hue errors are more important, increased the rgb_dist factor.
    total_dist = 1.5*rgb_dist + 0.60*luma_dist

    # Find minimum distance index
    return np.argmin(total_dist)

# Atkinson dithering implementation with floating-point error diffusion for accuracy


def quantize_atkinson(image):
    img_array = np.array(image.convert('RGB'))
    height, width, _ = img_array.shape
    # Use float array for error diffusion to avoid integer truncation issues
    working_img = img_array.astype(np.float32)

    for y in range(height):
        for x in range(width):
            old_pixel = working_img[y, x].copy()
            # Use exact color comparison instead of lookup table for better accuracy
            idx = closest_palette_color(
                tuple(np.clip(old_pixel, 0, 255).astype(int)))
            new_pixel = np.array(PALETTE_COLORS[idx], dtype=np.float32)
            working_img[y, x] = new_pixel

            # Calculate error
            error = old_pixel - new_pixel

            # Atkinson error distribution - only to not-yet-processed pixels (right and down)
            # Weights: Right: 1/8, Bottom-left: 1/8, Bottom: 1/4, Bottom-right: 1/8
            # Total distributed: 5/8, which is standard for Atkinson
            if x + 1 < width:
                working_img[y, x + 1] += error * (1/8)
            if y + 1 < height:
                if x - 1 >= 0:
                    working_img[y + 1, x - 1] += error * (1/8)
                working_img[y + 1, x] += error * (1/4)
                if x + 1 < width:
                    working_img[y + 1, x + 1] += error * (1/8)

    # Clip to valid RGB range and convert back to uint8
    quantized_array = np.clip(working_img, 0, 255).astype(np.uint8)
    return Image.fromarray(quantized_array)


# Create an ArgumentParser object
parser = argparse.ArgumentParser(description='Process some images.')

# Add orientation parameter
parser.add_argument('input_paths', nargs='+', type=str,
                    help='Input image file(s) or directory')
parser.add_argument('--dir', choices=['landscape', 'portrait'],
                    help='Image direction (landscape or portrait)')
parser.add_argument('--width', type=int, default=None,
                    help='Target image width in pixels. Cannot be used with --scale')
parser.add_argument('--height', type=int, default=None,
                    help='Target image height in pixels. Cannot be used with --scale')
parser.add_argument('--scale', type=float, default=1.0,
                    help='Scale factor for output image size relative to the original (e.g., 1.0 = same size as original). Cannot be used with --width or --height (default: 1.0)')
parser.add_argument('--mode', choices=['scale', 'cut'],
                    default='scale', help='Image conversion mode (scale or cut)')
parser.add_argument('--dither', type=int, choices=[0, 1, 3], default=1,
                    help='Image dithering algorithm (0 for NONE, 1 for ATKINSON (slow), 3 for FLOYDSTEINBERG)')
# Add enhancement arguments
parser.add_argument('--brightness', type=float, default=1.1,
                    help='Brightness factor (1.0 = no change)')
parser.add_argument('--contrast', type=float, default=1.2,
                    help='Contrast factor (1.0 = no change)')
parser.add_argument('--saturation', type=float, default=1.2,
                    help='Color saturation factor (1.0 = no change)')
parser.add_argument('--switchbot-133', action='store_true',
                    help='Preset for SwitchBot AI Canvas 13.3 inch (width=1200, height=1600; swapped when --dir is also specified)')
parser.add_argument('--workers', type=int, default=os.cpu_count(),
                    help='Number of parallel worker threads (default: number of CPU cores)')


# Parse command line arguments
args = parser.parse_args()

# Detect whether --scale was explicitly provided on the command line
_scale_explicit = any(arg == '--scale' or arg.startswith('--scale=')
                      for arg in sys.argv)

# Validate --scale value is positive
if args.scale <= 0:
    parser.error('--scale must be a positive number')

# Validate --scale is not combined with --width, --height, or --switchbot-133
if _scale_explicit:
    if args.width is not None or args.height is not None:
        parser.error(
            '--scale cannot be used together with --width or --height')
    if args.switchbot_133:
        parser.error('--scale cannot be used together with --switchbot-133')

# Apply --switchbot-133 preset (width=1200, height=1600; swap if --dir is specified)
if args.switchbot_133:
    args.width = 1200
    args.height = 1600
    if args.dir == 'landscape':
        args.width, args.height = args.height, args.width

# Fill in any missing fixed dimension when at least one of --width/--height is given
if args.width is not None and args.width <= 0:
    parser.error('--width must be a positive integer')

if args.height is not None and args.height <= 0:
    parser.error('--height must be a positive integer')

# Add comments about dithering options
if args.dither == 3:  # Floyd-Steinberg
    print("Using Floyd-Steinberg dithering. Note: dither option 1 (Atkinson) can be used for better visual results")
elif args.dither == 1:  # Atkinson
    print("Using Atkinson dithering. Note: dither option 3 (Floyd-Steinberg) is 80x faster but gives less visual quality")

# Get input parameters
input_paths = args.input_paths
display_direction = args.dir
display_mode = args.mode
display_dither = Image.Dither(args.dither)

# Define function to process a single image file


def process_image(image_file):
    try:
        # Determine output filename and check if it can be skipped.
        # BMP file size for a 24-bit RGB image: 54-byte header + row-aligned pixel data.
        dither_label = 'ATK' if args.dither == 1 else 'FS' if args.dither == 3 else ''
        output_filename = os.path.splitext(image_file)[
            0] + '_' + display_mode + ('_' + dither_label if dither_label else '') + '_output.bmp'

        # Read input image
        input_image = Image.open(image_file)

        # Get the original image size
        width, height = input_image.size

        # Specified target size
        if args.width is not None and args.height is not None:
            target_width, target_height = args.width, args.height
        else:
            target_width = max(1, int(width * args.scale))
            target_height = max(1, int(height * args.scale))

        row_stride = ((target_width * 3 + 3) // 4) * 4
        expected_size = 54 + row_stride * target_height
        try:
            if os.stat(output_filename).st_size == expected_size:
                print(
                    f'Skipping {output_filename} (already exists with same size)')
                return
        except OSError:
            pass

        if display_mode == 'scale':
            # Computed scaling
            scale_ratio = max(target_width / width, target_height / height)

            # Calculate the size after scaling
            resized_width = int(width * scale_ratio)
            resized_height = int(height * scale_ratio)

            # Resize image
            output_image = input_image.resize((resized_width, resized_height))

            # Create the target image and center the resized image
            resized_image = Image.new(
                'RGB', (target_width, target_height), (255, 255, 255))
            left = (target_width - resized_width) // 2
            top = (target_height - resized_height) // 2
            resized_image.paste(output_image, (left, top))
        elif display_mode == 'cut':
            # Calculate the fill size to add or the area to crop
            if width / height >= target_width / target_height:
                # The image aspect ratio is larger than the target aspect ratio, and padding needs to be added on the left and right
                delta_width = int(height * target_width /
                                  target_height - width)
                padding = (delta_width // 2, 0,
                           delta_width - delta_width // 2, 0)
                box = (0, 0, width, height)
            else:
                # The image aspect ratio is smaller than the target aspect ratio and needs to be filled up and down
                delta_height = int(width * target_height /
                                   target_width - height)
                padding = (0, delta_height // 2, 0,
                           delta_height - delta_height // 2)
                box = (0, 0, width, height)

            resized_image = ImageOps.pad(input_image.crop(box), size=(
                target_width, target_height), color=(255, 255, 255), centering=(0.5, 0.5))

        # Apply enhancements (contrast and saturation)
        enhancer = ImageEnhance.Brightness(resized_image)
        enhanced_image = enhancer.enhance(args.brightness)

        enhancer = ImageEnhance.Contrast(enhanced_image)
        enhanced_image = enhancer.enhance(args.contrast)

        enhancer = ImageEnhance.Color(enhanced_image)
        enhanced_image = enhancer.enhance(args.saturation)

        # Add edge enhancement
        enhanced_image = enhanced_image.filter(ImageFilter.EDGE_ENHANCE)

        # Add noise reduction
        enhanced_image = enhanced_image.filter(ImageFilter.SMOOTH)

        # Add sharpening for better detail visibility
        enhanced_image = enhanced_image.filter(ImageFilter.SHARPEN)

        # Create a palette object
        pal_image = Image.new("P", (1, 1))
        pal_image.putpalette((0, 0, 0,  255, 255, 255,  255, 255, 0,
                             255, 0, 0,  0, 0, 0,  0, 0, 255,  0, 255, 0) + (0, 0, 0)*249)

        # The color quantization and dithering algorithms are performed, and the results are converted to RGB mode
        if args.dither == 1:  # Atkinson dithering
            quantized_image = quantize_atkinson(enhanced_image).convert('RGB')
        else:
            quantized_image = enhanced_image.quantize(
                dither=display_dither, palette=pal_image).convert('RGB')

        # Save output image
        quantized_image.save(output_filename)
        print(f'Successfully converted {image_file} to {output_filename}')
    except Exception as e:
        print(f'Error processing {image_file}: {e}')


# Collect all image files from input paths
image_extensions = ['.jpg', '.jpeg', '.png',
                    '.tiff', '.tif', '.webp', '.gif', '.heic']
all_image_files = []

for input_path in input_paths:
    # Check if input path exists
    if not os.path.exists(input_path):
        print(f'Error: path {input_path} does not exist')
        continue

    # Determine if input is a file or directory
    if os.path.isfile(input_path):
        # Add single file
        all_image_files.append(input_path)
    elif os.path.isdir(input_path):
        # Add all image files from directory
        for file in os.listdir(input_path):
            file_path = os.path.join(input_path, file)
            if (os.path.isfile(file_path) and
                    any(file.lower().endswith(ext) for ext in image_extensions)):
                all_image_files.append(file_path)

        # Check if directory has any image files
        has_images = False
        for file in os.listdir(input_path):
            if any(file.lower().endswith(ext) for ext in image_extensions):
                has_images = True
                break
        if not has_images:
            print(f'Warning: no image files found in directory {input_path}')
    else:
        print(f'Error: {input_path} is not a valid file or directory')

# Process all collected image files with progress bar
if not all_image_files:
    print('Error: no valid image files to process')
    sys.exit(1)

print(f'Found {len(all_image_files)} image files to process')
with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
    futures = {executor.submit(process_image, f): f for f in all_image_files}
    for _ in tqdm(concurrent.futures.as_completed(futures), total=len(all_image_files), desc="Processing images", unit="file"):
        pass

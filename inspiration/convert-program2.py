# encoding: utf-8

import sys
import os
import os.path
import argparse
import glob
import datetime

# Try to import tqdm for progress bar
try:
    from tqdm import tqdm

    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("For a better experience with progress bars, install tqdm: pip install tqdm")

from PIL import Image, ImageOps, ImageEnhance, ImageFilter, ImageDraw, ImageFont

# Try to import pillow-heif for HEIC support
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIC_SUPPORT = True
except ImportError:
    HEIC_SUPPORT = False
    print("Warning: pillow-heif not installed. HEIC files will not be processed.")
    print("To enable HEIC support, install with: pip install pillow-heif")

# Create an ArgumentParser object for minimal required arguments
parser = argparse.ArgumentParser(description="Process some images.")
args = parser.parse_args()


# Function to ask user questions with default values
def ask_with_default(question, default, choices=None):
    # Format the prompt to look nicer
    if choices:
        # Create a more readable choice format
        if isinstance(choices[0], str):
            # For orientation, create a special formatted prompt
            if "portrait" in choices or "landscape" in choices:
                prompt = f"{question}\n  (p) Portrait\n  (l) Landscape\n  (b) Both\n[default: {default}]: "
            else:
                # Format other choice prompts nicely
                options = []
                for choice in choices:
                    if choice == default:
                        options.append(f"{choice} (default)")
                    else:
                        options.append(choice)
                prompt = f"{question}\n  Options: {', '.join(options)}\n> "
        else:
            # For numeric options, show them nicely
            options = []
            for choice in choices:
                if str(choice) == str(default):
                    options.append(f"{choice} (default)")
                else:
                    options.append(str(choice))
            prompt = f"{question}\n  Options: {', '.join(options)}\n> "
    else:
        # For free-form input
        prompt = f"{question} [default: {default}]\n> "

    answer = input(prompt)
    # If user just pressed Enter, use default
    if not answer.strip():
        return default

    # For choices, validate input
    if choices and answer.lower() not in [str(c).lower() for c in choices]:
        print(f"Invalid choice. Using default: {default}")
        return default

    return answer


# Ask for user preferences interactively
print("\n===== Image Processing Configuration =====\n")

# Ask for orientation - special case with simplified prompt
orientation_choice = None
while True:
    orientation_choice = ask_with_default(
        "Process which orientation?",
        "b",
        ["p", "l", "b", "portrait", "landscape", "both"],
    ).lower()
    if orientation_choice in ["p", "l", "b", "portrait", "landscape", "both"]:
        break
    print("Invalid choice. Please enter 'p', 'l', or 'b'.")

# Convert short codes to full names for clearer code
if orientation_choice == "p":
    orientation_choice = "portrait"
elif orientation_choice == "l":
    orientation_choice = "landscape"
elif orientation_choice == "b":
    orientation_choice = "both"

# Ask for conversion mode
display_mode = ask_with_default(
    "Image conversion mode?", "scale", ["scale", "cut"]
).lower()

# Ask for dithering
dither_input = ask_with_default("Dithering algorithm?", "3", ["0", "3"])
display_dither = int(dither_input)

# Ask for enhancement factors with descriptions
print("\n----- Image Enhancement Settings -----")
brightness = float(ask_with_default("Brightness factor? (higher = brighter)", "1.2"))
contrast = float(ask_with_default("Contrast factor? (higher = more contrast)", "1.4"))
saturation = float(ask_with_default("Color saturation? (higher = more vivid)", "1.3"))

# Ask for date display preferences
print("\n----- Date Display Settings -----")
original_show_date = (
    ask_with_default("Print date on images?", "yes", ["yes", "no"]).lower() == "yes"
)
show_date = original_show_date

# Only ask for date display details if the user wants dates
if show_date:
    date_color = ask_with_default(
        "Date background color?", "blue", ["black", "blue", "green", "red"]
    ).lower()
    date_size = int(ask_with_default("Date font size?", "10"))
else:
    # Set default values that won't be used
    date_color = "blue"
    date_size = 10

# Create pic/ subfolder if it doesn't exist
OUTPUT_DIR = "pic"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)


# Function to print only when progress bar is not available
def conditional_print(message):
    if not TQDM_AVAILABLE:
        print(message)


# Get all image files in current directory
supported_formats = ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.gif", "*.tiff"]
if HEIC_SUPPORT:
    supported_formats.append("*.heic")
    supported_formats.append("*.HEIC")
image_files = []
for format in supported_formats:
    image_files.extend(glob.glob(format))

if not image_files:
    print("No image files found in the current directory")
    sys.exit(1)

conditional_print(f"Found {len(image_files)} image(s) to process")

# Filter images by orientation if needed
if orientation_choice != "both":
    filtered_files = []
    skipped_files = []

    print(f"\nFiltering images for {orientation_choice} orientation...")

    # Don't use progress bar for filtering, just process files silently
    for filename in image_files:
        try:
            img = Image.open(filename)
            width, height = img.size

            # Default to dimension-based orientation
            is_landscape = width > height
            exif_orientation = None

            # Try to check EXIF data for more accurate orientation
            try:
                exif = img._getexif()
                if exif and 274 in exif:  # 274 is the orientation tag
                    exif_orientation = exif[274]
                    # Orientations 5-8 indicate the image should be rotated to portrait
                    if exif_orientation in [5, 6, 7, 8]:
                        is_landscape = False
                    # Orientations 1-4 maintain landscape/portrait based on dimensions
            except (AttributeError, KeyError, TypeError):
                # If EXIF check fails, stick with dimension-based orientation
                pass

            # Print detailed info about each image for debugging
            orientation_str = "landscape" if is_landscape else "portrait"
            exif_str = (
                f" (EXIF orientation: {exif_orientation})" if exif_orientation else ""
            )

            # Add to the appropriate list
            if (orientation_choice == "landscape" and is_landscape) or (
                orientation_choice == "portrait" and not is_landscape
            ):
                filtered_files.append(filename)
            else:
                skipped_files.append(filename)

        except Exception as e:
            print(f"Error checking orientation of {filename}: {e}")

    # Update image_files to only include the filtered ones
    image_files = filtered_files

    print(
        f"\nKept {len(filtered_files)} {orientation_choice} images, skipped {len(skipped_files)} images"
    )

    if not image_files:
        print(f"No {orientation_choice} images found")
        sys.exit(1)

# Process each image
converted_files = []
counter = 1

# Create a progress bar to show conversion progress
if TQDM_AVAILABLE:
    pbar = tqdm(total=len(image_files), desc="Converting images", unit="image")

for input_filename in image_files:
    try:
        # Reset date_str and show_date for each new image
        date_str = None
        # Reset to the user's original preference for each image
        show_date = original_show_date

        # Read input image
        input_image = Image.open(input_filename)

        # Apply EXIF rotation correction
        try:
            exif = input_image._getexif()
            if exif and 274 in exif:  # 274 is the orientation tag
                orientation = exif[274]
                # Apply rotation based on EXIF orientation
                if orientation == 2:
                    input_image = input_image.transpose(Image.FLIP_LEFT_RIGHT)
                elif orientation == 3:
                    input_image = input_image.transpose(Image.ROTATE_180)
                elif orientation == 4:
                    input_image = input_image.transpose(Image.FLIP_TOP_BOTTOM)
                elif orientation == 5:
                    input_image = input_image.transpose(
                        Image.FLIP_LEFT_RIGHT
                    ).transpose(Image.ROTATE_90)
                elif orientation == 6:
                    input_image = input_image.transpose(Image.ROTATE_270)
                elif orientation == 7:
                    input_image = input_image.transpose(
                        Image.FLIP_LEFT_RIGHT
                    ).transpose(Image.ROTATE_270)
                elif orientation == 8:
                    input_image = input_image.transpose(Image.ROTATE_90)
        except (AttributeError, KeyError, TypeError, ValueError):
            # If EXIF rotation fails, continue with the original image
            pass

        # Get the original image size
        width, height = input_image.size

        # Specified target size
        # Set dimensions based on the actual image orientation
        if width > height:
            # This is a landscape image
            target_width, target_height = 800, 480
        else:
            # This is a portrait image
            target_width, target_height = 480, 800

        if display_mode == "scale":
            # Computed scaling
            scale_ratio = max(target_width / width, target_height / height)

            # Calculate the size after scaling
            resized_width = int(width * scale_ratio)
            resized_height = int(height * scale_ratio)

            # Resize image
            output_image = input_image.resize((resized_width, resized_height))

            # Create the target image and center the resized image
            resized_image = Image.new(
                "RGB", (target_width, target_height), (255, 255, 255)
            )
            left = (target_width - resized_width) // 2
            top = (target_height - resized_height) // 2
            resized_image.paste(output_image, (left, top))
        elif display_mode == "cut":
            # Calculate the fill size to add or the area to crop
            if width / height >= target_width / target_height:
                # The image aspect ratio is larger than the target aspect ratio, and padding needs to be added on the left and right
                delta_width = int(height * target_width / target_height - width)
                padding = (delta_width // 2, 0, delta_width - delta_width // 2, 0)
                box = (0, 0, width, height)
            else:
                # The image aspect ratio is smaller than the target aspect ratio and needs to be filled up and down
                delta_height = int(width * target_height / target_width - height)
                padding = (0, delta_height // 2, 0, delta_height - delta_height // 2)
                box = (0, 0, width, height)

            resized_image = ImageOps.pad(
                input_image.crop(box),
                size=(target_width, target_height),
                color=(255, 255, 255),
                centering=(0.5, 0.5),
            )

        # Apply enhancements (contrast and saturation)
        enhancer = ImageEnhance.Brightness(resized_image)
        enhanced_image = enhancer.enhance(brightness)

        enhancer = ImageEnhance.Contrast(enhanced_image)
        enhanced_image = enhancer.enhance(contrast)

        enhancer = ImageEnhance.Color(enhanced_image)
        enhanced_image = enhancer.enhance(saturation)

        # Add edge enhancement
        enhanced_image = enhanced_image.filter(ImageFilter.EDGE_ENHANCE)

        # Add noise reduction
        enhanced_image = enhanced_image.filter(ImageFilter.SMOOTH)

        # Add sharpening for better detail visibility
        enhanced_image = enhanced_image.filter(ImageFilter.SHARPEN)

        # Try to extract date from EXIF data - only if user wants date display
        if show_date:
            try:
                # Regular EXIF processing for non-HEIC files
                try:
                    # Try to get EXIF data - focusing only on the most reliable fields for Date Taken
                    # Tag 36867 (0x9003) = DateTimeOriginal - Standard "Date Taken" field
                    # Tag 306 (0x132) = DateTime - Standard create date field
                    # Tag 36868 (0x9004) = DateTimeDigitized - When image was scanned/digitized
                    # Tag 40091 = XPDateTaken - Microsoft's Windows-specific tag

                    date_str = None

                    # Get EXIF data - first try _getexif() (works in most cases)
                    if hasattr(input_image, "_getexif"):
                        exif = input_image._getexif()
                        if exif:
                            # Simple priority list for date fields (most to least reliable)
                            date_fields = [
                                (36867, "DateTimeOriginal"),  # Standard date taken
                                (40091, "XPDateTaken"),  # Windows-specific date taken
                                (306, "DateTime"),  # File creation date
                                (36868, "DateTimeDigitized"),  # When digitized
                            ]

                            # Try each field in order of reliability
                            for tag_id, tag_name in date_fields:
                                if date_str:
                                    break  # Exit once we have a date

                                if tag_id in exif and exif[tag_id]:
                                    raw_date = str(exif[tag_id])
                                    conditional_print(f"Found {tag_name}: {raw_date}")

                                    # Handle date format based on separator
                                    if ":" in raw_date and len(raw_date) >= 10:
                                        date_str = raw_date[:10].replace(":", "-")
                                    elif "-" in raw_date and len(raw_date) >= 10:
                                        date_str = raw_date[:10]

                    # If the above method failed, try newer getexif() method (Pillow 6.0+)
                    if not date_str and hasattr(input_image, "getexif"):
                        try:
                            exif = input_image.getexif()
                            if exif:
                                # Try the same tags with the newer API
                                if 36867 in exif and exif[36867]:  # DateTimeOriginal
                                    raw_date = str(exif[36867])
                                    if ":" in raw_date and len(raw_date) >= 10:
                                        date_str = raw_date[:10].replace(":", "-")
                                elif 306 in exif and exif[306]:  # DateTime
                                    raw_date = str(exif[306])
                                    if ":" in raw_date and len(raw_date) >= 10:
                                        date_str = raw_date[:10].replace(":", "-")
                        except Exception:
                            pass  # Silently continue if this method fails

                    # If no date was found in EXIF, don't show date
                    if not date_str:
                        conditional_print(f"No Date Taken found for {input_filename}")
                        show_date = False
                except Exception as e:
                    conditional_print(f"Error extracting date: {e}")
                    show_date = False

                # If date was found and user wants to show it, add it to the image BEFORE quantization
                if date_str and show_date:
                    # Create a drawing context
                    draw = ImageDraw.Draw(enhanced_image)
                    # Try to use a default font, fallback to default if not available
                    try:
                        # Use smaller font size as requested
                        font_size = date_size
                        try:
                            font = ImageFont.truetype("arial.ttf", font_size)
                        except:
                            try:
                                font = ImageFont.truetype("DejaVuSans.ttf", font_size)
                            except:
                                font = ImageFont.load_default()
                    except IOError:
                        # If no TrueType fonts available, use default
                        font = ImageFont.load_default()

                    # Calculate position (bottom right with padding)
                    text_width = draw.textlength(date_str, font=font)

                    # Use different padding for horizontal and vertical to make box shorter
                    h_padding = 8  # Horizontal padding (left/right)
                    v_padding_top = 2  # Reduced top padding by 1px
                    v_padding_bottom = 3  # Keep bottom padding unchanged

                    # Calculate height with asymmetric padding
                    rect_width = text_width + h_padding * 2
                    rect_height = font_size + v_padding_top + v_padding_bottom

                    # Position the rectangle in the bottom right corner
                    # Move rect_y down by 1px to reduce the box from the top
                    rect_x = enhanced_image.width - rect_width - 10
                    rect_y = enhanced_image.height - rect_height - 10

                    # Set background color based on user preference - define BEFORE using it
                    bg_color = (0, 0, 128)  # Default to dark blue
                    if date_color == "black":
                        bg_color = (0, 0, 0)
                    elif date_color == "blue":
                        bg_color = (0, 0, 128)  # Dark blue
                    elif date_color == "green":
                        bg_color = (0, 80, 0)  # Dark green
                    elif date_color == "red":
                        bg_color = (128, 0, 0)  # Dark red

                    # Create rounded rectangle for background
                    # Use smaller corner radius for smaller height
                    corner_radius = min(
                        6, int(rect_height // 2.5)
                    )  # Adjusted ratio, max 6px

                    # Create a transparent image and draw a rounded rectangle
                    rounded_rect = Image.new(
                        "RGBA", (int(rect_width), int(rect_height)), (0, 0, 0, 0)
                    )
                    rect_draw = ImageDraw.Draw(rounded_rect)

                    # Draw the rectangle with rounded corners
                    # Use try/except for compatibility with older Pillow versions
                    try:
                        # For newer Pillow versions that support rounded_rectangle
                        rect_draw.rounded_rectangle(
                            [(0, 0), (rect_width - 1, rect_height - 1)],
                            fill=bg_color + (200,),  # Add alpha for semi-transparency
                            radius=corner_radius,
                        )
                    except AttributeError:
                        # Fallback for older Pillow versions - draw rectangle and circles for corners
                        # Draw main rectangle
                        rect_draw.rectangle(
                            [
                                (corner_radius, 0),
                                (rect_width - corner_radius - 1, rect_height - 1),
                            ],
                            fill=bg_color + (200,),
                        )
                        rect_draw.rectangle(
                            [
                                (0, corner_radius),
                                (rect_width - 1, rect_height - corner_radius - 1),
                            ],
                            fill=bg_color + (200,),
                        )

                        # Draw four corner circles
                        rect_draw.ellipse(
                            [(0, 0), (corner_radius * 2, corner_radius * 2)],
                            fill=bg_color + (200,),
                        )
                        rect_draw.ellipse(
                            [
                                (rect_width - corner_radius * 2 - 1, 0),
                                (rect_width - 1, corner_radius * 2),
                            ],
                            fill=bg_color + (200,),
                        )
                        rect_draw.ellipse(
                            [
                                (0, rect_height - corner_radius * 2 - 1),
                                (corner_radius * 2, rect_height - 1),
                            ],
                            fill=bg_color + (200,),
                        )
                        rect_draw.ellipse(
                            [
                                (
                                    rect_width - corner_radius * 2 - 1,
                                    rect_height - corner_radius * 2 - 1,
                                ),
                                (rect_width - 1, rect_height - 1),
                            ],
                            fill=bg_color + (200,),
                        )

                    # Paste the rounded rectangle onto the main image
                    enhanced_image.paste(
                        rounded_rect, (int(rect_x), int(rect_y)), rounded_rect
                    )

                    # Calculate text position to center it in the box
                    text_x = rect_x + h_padding
                    # Keep text at the same position as before, equivalent to the old centering formula
                    text_y = rect_y + (rect_height - font_size) // 2 - 1

                    # Draw text in white
                    draw.text(
                        (text_x, text_y), date_str, fill=(255, 255, 255), font=font
                    )
            except (AttributeError, KeyError, TypeError, ValueError) as e:
                conditional_print(f"Error extracting date from {input_filename}: {e}")
                # Use file modification time as fallback
                try:
                    file_time = os.path.getmtime(input_filename)
                    file_date = datetime.datetime.fromtimestamp(file_time)
                    date_str = file_date.strftime("%Y-%m-%d")
                    conditional_print(
                        f"Using file modification time as fallback: {date_str}"
                    )
                except Exception:
                    pass

        # Create a palette object with exact display colors
        # (Black, White, Green, Blue, Red, Yellow)
        pal_image = Image.new("P", (1, 1))
        pal_image.putpalette(
            (
                0,
                0,
                0,  # Black
                255,
                255,
                255,  # White
                0,
                255,
                0,  # Green
                0,
                0,
                255,  # Blue
                255,
                0,
                0,  # Red
                255,
                255,
                0,
            )  # Yellow
            + (0, 0, 0) * 246
        )

        # Perform quantization on the enhanced image (including the date text)
        quantized_image = enhanced_image.quantize(
            dither=display_dither, palette=pal_image
        ).convert("RGB")

        # Save output image to pic/ subfolder with sequentially numbered filename
        sequential_name = f"{counter:06d}.bmp"  # Format as 000001.bmp
        output_filename = os.path.join(OUTPUT_DIR, sequential_name)
        quantized_image.save(output_filename)

        # Add to list of converted files
        converted_files.append(output_filename)

        # Update progress instead of printing
        if TQDM_AVAILABLE:
            pbar.update(1)
            pbar.set_postfix(file=os.path.basename(input_filename), status="Success")
        else:
            conditional_print(
                f"Successfully converted {input_filename} to {output_filename}"
            )

        # Increment counter for next file
        counter += 1
    except Exception as e:
        # Show errors even with progress bar, but use pbar.write for cleaner output
        if TQDM_AVAILABLE:
            pbar.update(1)
            pbar.set_postfix(file=os.path.basename(input_filename), status="Error")
            pbar.write(f"Error processing {input_filename}: {e}")
        else:
            conditional_print(f"Error processing {input_filename}: {e}")

# Close the progress bar
if TQDM_AVAILABLE:
    pbar.close()

# Write the list of converted files to fileList.txt
if converted_files:
    with open("fileList.txt", "w") as f:
        for file in converted_files:
            f.write(f"{file}\n")
    if TQDM_AVAILABLE:
        pbar.write(f"Created fileList.txt with {len(converted_files)} entries")
    else:
        conditional_print(f"Created fileList.txt with {len(converted_files)} entries")

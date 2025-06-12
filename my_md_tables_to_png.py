import io

import matplotlib
matplotlib.use('Agg')

import matplotlib.pyplot as plt
import pandas as pd
import re
from typing import List


def markdown_table_to_image_bytes(markdown_table_string: str) -> bytes:
    """
    Converts a Markdown table string into a beautifully styled PNG image and returns its bytes.

    This function parses a simple Markdown table string, converts it into a
    pandas DataFrame, and then renders the DataFrame as a table image using
    Matplotlib with enhanced styling for better aesthetics. The image is saved
    into an in-memory buffer and returned as bytes.

    Args:
        markdown_table_string (str): A string containing the Markdown table.
                                     Example format:
                                     "| Header1 | Header2 |\n|---|---|\n| Cell1 | Cell2 |"

    Returns:
        bytes: The byte representation of the PNG image.

    Raises:
        ValueError: If the input markdown_table_string is not a valid table format.
    """
    # Split the input string into individual lines
    lines = markdown_table_string.strip().split('\n')

    if len(lines) < 2:
        raise ValueError("Markdown table must have at least a header and a separator line.")

    # Parse headers from the first line.
    headers = [h.strip() for h in lines[0].strip('|').split('|') if h.strip()]
    if not headers:
        raise ValueError("No headers found in the Markdown table.")

    # Parse data rows starting from the third line (after header and separator line).
    data = []
    for line in lines[2:]:
        row = [cell.strip() for cell in line.strip('|').split('|') if cell.strip() or len(row) < len(headers)]
        if len(row) < len(headers):
            row.extend([''] * (len(headers) - len(row)))
        elif len(row) > len(headers):
            row = row[:len(headers)]

        data.append(row)

    # Create a pandas DataFrame from the parsed data and headers
    df = pd.DataFrame(data, columns=headers)

    # --- Matplotlib setup for rendering the table with enhanced styling ---
    # Adjust figsize based on content for better layout
    fig_width = max(len(headers) * 2.5, 8) # Minimum width for better appearance
    fig_height = max(len(df) * 0.4 + 1, 3) # Minimum height
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    ax.axis('off') # Turn off the axes to display only the table content

    # Create the table using Matplotlib's table function
    table = ax.table(cellText=df.values,
                     colLabels=df.columns,
                     loc='center',
                     cellLoc='center',
                     bbox=[0, 0, 1, 1])

    # --- Apply styling to the table cells ---
    table.auto_set_font_size(False) # Disable auto font size to set manually
    table.set_fontsize(12) # Set a comfortable font size
    table.scale(1, 1.5) # Adjust cell height for better spacing

    # Style header cells
    for (i, j), cell in table.get_celld().items():
        if i == 0: # Header row
            cell.set_facecolor("#4CAF50") # Green background for headers
            cell.set_text_props(color='white', weight='bold') # White, bold text
            cell.set_edgecolor('black') # Black border for headers
            cell.set_linewidth(1.5) # Thicker border for headers
        else: # Data rows
            if i % 2 == 1: # Odd rows (after header, so 1, 3, 5...)
                cell.set_facecolor("#f2f2f2") # Light grey for odd rows
            else: # Even rows
                cell.set_facecolor("#ffffff") # White for even rows
            cell.set_edgecolor('lightgray') # Lighter border for data cells
            cell.set_linewidth(0.5) # Thinner border for data cells

        cell.set_alpha(1.0) # Ensure full opacity
        cell.set_text_props(color='black') # Default text color for data cells

    # Set the title for the table
    # plt.title("Styled Table Data", fontsize=18, pad=20, weight='bold') # Larger, bold title with padding

    # Automatically adjust subplot parameters for a tight layout
    plt.tight_layout(pad=3.0) # Add more padding around the figure

    # --- Save the plot to an in-memory buffer ---
    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight', dpi=75)
    plt.close(fig)

    image_bytes = buffer.getvalue()
    buffer.close()

    return image_bytes


def find_markdown_tables(markdown_text: str) -> List[str]:
    """
    Finds and extracts Markdown tables from a given text.

    This function iterates through the lines of the input text,
    identifying potential Markdown tables based on a header line
    immediately followed by a delimiter line. It then collects
    subsequent data lines that conform to table structure.

    Args:
        markdown_text (str): The input string containing Markdown text.

    Returns:
        List[str]: A list of strings, where each string is a detected
                   Markdown table. Returns an empty list if no tables are found.
    """
    tables = []
    lines = markdown_text.strip().split('\n')
    num_lines = len(lines)

    # Improved Regex for a standard Markdown table delimiter line.
    # It correctly handles optional leading/trailing pipes and whitespace,
    # and requires at least one segment of hyphens with optional colons and a pipe.
    # Pattern explanation for segment: `(?:[:-]?\-+[:]?)`
    #   `[:-]?` : Optional colon at the beginning of the segment (for left alignment).
    #   `\-+`   : One or more hyphens.
    #   `[:]?`  : Optional colon at the end of the segment (for right alignment).
    delimiter_pattern = re.compile(r'^\s*\|?(?:\s*(?:[:-]?\-+[:]?)\s*\|)+\s*$', re.IGNORECASE)

    i = 0
    while i < num_lines:
        line = lines[i].strip()

        # Look for a potential header line (must contain '|')
        if '|' in line and i + 1 < num_lines:
            next_line = lines[i+1].strip()

            # Check if the next line is a valid Markdown table delimiter
            if delimiter_pattern.match(next_line):
                # Found a table: header line + delimiter line
                current_table_lines = [line, next_line]
                i += 2 # Move past the header and delimiter lines

                # Now, collect all subsequent data lines belonging to this table
                while i < num_lines:
                    data_line = lines[i].strip()
                    # A valid data line must contain '|' and NOT be a delimiter line itself.
                    if '|' in data_line and not delimiter_pattern.match(data_line):
                        current_table_lines.append(data_line)
                        i += 1
                    else:
                        # Current line is not a data line (e.g., empty line, plain text, or another delimiter)
                        # So, the current table has ended.
                        break
                
                # Add the complete table to the list of found tables
                tables.append("\n".join(current_table_lines))
                # The outer while loop will handle advancing 'i' from its current position.
            else:
                # The next line is not a delimiter, so this is not a table. Move to the next line.
                i += 1
        else:
            # Current line doesn't contain '|' or is the last line, so it cannot be a table header.
            # Move to the next line.
            i += 1

    return tables


if __name__ == "__main__":

    # --- Example Usage ---
    markdown_text_with_tables = """
This is some introductory text.

Here is the first table:
| Header 1 | Header 2 | Header 3 |
| :------- | :------: | --------: |
| Row 1 Col 1 | Row 1 Col 2 | Row 1 Col 3 |
| Row 2 Col 1 | Row 2 Col 2 | Row 2 Col 3 |
Some text in between tables.

And here is a second table:
| Item      | Quantity | Price  |
|-----------|:--------:|-------:|
| Apples    | 10       | 1.50   |
| Oranges   | 5        | 0.75   |
| Bananas   | 12       | 0.25   |

Final paragraph after tables.
"""

    found_tables = find_markdown_tables(markdown_text_with_tables)
    n = 1
    for table in found_tables:
        print(table)

        try:
            # Call the function to get the styled image bytes
            image_data_bytes = markdown_table_to_image_bytes(table)

            # Save it directly to a file (for demonstration/testing):
            output_filename = f"c:/Users/user/Downloads/{n}.png"
            n += 1
            with open(output_filename, "wb") as f:
                f.write(image_data_bytes)
            print(f"Styled image successfully created and saved to '{output_filename}' from bytes.")

        except ValueError as e:
            print(f"Error processing Markdown table: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")


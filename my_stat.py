#!/usr/bin/env python3


import datetime
import io
import matplotlib
import time
from typing import List, Tuple, Dict, Optional

matplotlib.use('Agg') #  Отключаем вывод графиков на экран
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.font_manager import FontProperties

import my_db
import my_log
import utils


def draw_user_activity(days: int = 90) -> bytes:
    """
    Generates a chart of user activity with English labels and comments.

    Args:
        days: The number of days for which to generate the chart. Defaults to 90.

    Returns:
        Bytes of the chart image in PNG format.
    """

    data = my_db.get_users_for_last_days(days)
    new_users_data = my_db.get_new_users_for_last_days(days)

    dates = list(data.keys())
    x_dates = [datetime.datetime.strptime(d, "%Y-%m-%d").date() for d in dates]
    active_users = list(data.values())
    new_users = list(new_users_data.values())

    fig, ax1 = plt.subplots(figsize=(10, 6), facecolor='white')

    # Plot active users on the primary y-axis
    ax1.plot(x_dates, active_users, marker='o', color='#4C72B0', label='Active Users', alpha=0.7)
    ax1.set_xlabel("Date", fontsize=12)
    ax1.set_ylabel("Active Users", fontsize=12, color='#4C72B0')
    ax1.tick_params(axis='y', labelcolor='#4C72B0')

    # Create a secondary y-axis for new users
    ax2 = ax1.twinx()
    ax2.plot(x_dates, new_users, marker='x', linestyle='--', color='#C44E52', label='New Users', alpha=0.7)
    ax2.set_ylabel("New Users", fontsize=12, color='#C44E52')
    ax2.tick_params(axis='y', labelcolor='#C44E52')

    # Set chart title and grid
    ax1.set_title(f"User Activity for the Last {days} Days", fontsize=14)
    ax1.grid(axis='y', linestyle='--', alpha=0.3)  # Lighter grid lines
    ax2.grid(False) # Turn off grid for the secondary axis


    # Format x-axis dates
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    fig.autofmt_xdate()

    # Combine legends for both axes
    handles1, labels1 = ax1.get_legend_handles_labels()
    handles2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(handles1 + handles2, labels1 + labels2, loc="upper left")

    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches='tight') # Increased DPI for better quality
    buf.seek(0)
    image_bytes = buf.read()
    buf.close()

    return utils.compress_png_bytes(image_bytes)


def get_model_usage_for_days(num_days: int) -> List[Tuple[str, Dict[str, int]]]:
    """
    Retrieves model usage data for the past num_days, excluding the current day.
    Includes image generation counts.
    Data is sorted from oldest to newest.

    Args:
        num_days: The number of past days to retrieve data for.

    Returns:
        A list of tuples, where each tuple contains:
        - The date (YYYY-MM-DD)
        - A dictionary of model usage counts for that date, including image generation.
        Returns an empty list if there is an error or no data.
    """

    end_date = datetime.date.today() - datetime.timedelta(days=1)
    usage_data: List[Tuple[str, Dict[str, int]]] = []

    for i in range(num_days - 1, -1, -1):
        current_date = end_date - datetime.timedelta(days=i)
        date_str = current_date.strftime("%Y-%m-%d")
        start_timestamp = time.mktime(current_date.timetuple())
        end_timestamp = start_timestamp + 24 * 60 * 60

        model_usage: Dict[str, int] = {} # Initialize model_usage here

        with my_db.LOCK:
            try:
                # Existing model usage query (msg_counter table)
                my_db.CUR.execute('''
                    SELECT model_used, COUNT(*) FROM msg_counter
                    WHERE access_time >= ? AND access_time < ?
                    GROUP BY model_used
                ''', (start_timestamp, end_timestamp))
                results = my_db.CUR.fetchall()
                
                for row in results:
                    model = row[0]
                    usage_count = row[1]
                    model_usage[model] = usage_count

                usage_data.append((date_str, model_usage))

            except Exception as error:
                my_log.log2(f'my_db:get_model_usage_for_days {error}')
                return []

    return usage_data


def visualize_usage(usage_data: List[Tuple[str, Dict[str, int]]], mode: str = 'llm') -> Optional[bytes]:
    """
    Visualizes model usage data over time.

    Args:
        usage_data: A list of tuples, where each tuple contains:
            - The date (YYYY-MM-DD) as a string.
            - A dictionary of model usage counts for that date,
              where keys are model names (str) and values are counts (int).
        mode: The visualization mode ('llm' or 'img'). If 'llm', only non-image models are plotted. If 'img', only image models are plotted.

    Returns:
        A byte string containing the PNG image data of the generated plot,
        or None if the input data is empty.
    """

    if not usage_data:  # Check for empty input data
        my_log.log2('my_db:visualize_usage: No data to visualize.')
        return None

    dates: List[str] = [data[0] for data in usage_data]  # Extract dates
    models: List[str] = sorted(set(
        model for date, usage in usage_data for model in usage
    ))  # Extract unique model names
    model_counts: Dict[str, List[int]] = {model: [] for model in models}  # Initialize count lists for each model

    # Populate data lists
    for date, usage in usage_data:
        for model in models:
            model_counts[model].append(usage.get(model, 0))  # Get count or default to 0

    fig, ax = plt.subplots(figsize=(10, 6))  # Create figure and axis

    # Create a list of tuples (handle, label, value) for the legend
    handles_labels_values = []

    # Plot model usage
    for model in models:
        if mode == 'llm':
            if model.startswith('img '):
                continue
        elif mode == 'img':
            if not model.startswith('img '):
                continue

        label = model[4:] if model.startswith('img ') else model
        line, = ax.plot(dates, model_counts[model], label=label, marker='o')
        value = model_counts[model][-1]
        handles_labels_values.append((line, label, value))

    # Sort by values in descending order
    handles_labels_values.sort(key=lambda x: x[2], reverse=True)

    # Unpack tuples into separate lists
    handles, labels, values = zip(*handles_labels_values)


    ax.set_xlabel("Date")  # Set x-axis label
    ax.set_ylabel("Usage Count")  # Set y-axis label
    ax.set_title("Model Usage Over Time")  # Set plot title
    ax.grid(axis='y', linestyle='--')  # Add horizontal grid lines
    ax.tick_params(axis='x', rotation=45, labelsize=8)  # Rotate x-axis labels for better readability

    # Adjust x-axis ticks if too many dates
    if len(dates) > 10:
        step: int = len(dates) // 10  # Calculate step size for ticks
        try:
            ax.set_xticks(dates[::step])    # Set x-axis ticks
        except:
            return None

    fontP = FontProperties(size='x-small')
    ax.legend(handles, [f"{label} ({value})" for label, value in zip(labels, values)], loc='upper left', prop=fontP)


    plt.tight_layout()  # Adjust layout for better spacing

    # Save plot to byte buffer
    buf = io.BytesIO()   # Create in-memory byte buffer
    plt.savefig(buf, format="png", dpi=150, bbox_inches='tight') # Save plot to buffer as PNG
    buf.seek(0)            # Reset buffer position
    image_bytes: bytes = buf.read() # Read image bytes from buffer
    buf.close()           # Close buffer
    return utils.compress_png_bytes(image_bytes) # Return compressed PNG image bytes


if __name__ == '__main__':
    pass
    my_db.init(backup=False)

    usage_data = get_model_usage_for_days(90)  # Get data for the past 90 days
    with open('d:/downloads/1.png', 'wb') as f:
        f.write(visualize_usage(usage_data, mode='llm'))

    with open('d:/downloads/2.png', 'wb') as f:
        f.write(visualize_usage(usage_data, mode='img'))

    with open('d:/downloads/3.png', 'wb') as f:
        f.write(draw_user_activity(90))

    my_db.close()

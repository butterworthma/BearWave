import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import time, timedelta
import matplotlib.patches as mpatches

# Load the Excel file into a pandas DataFrame
data_belpha_new = pd.read_excel('data/field_trial_data.xlsx')

# Rename columns for easier access
data_belpha_new.columns = ['Date', 'Time', 'SNR_DB', 'Value2', 'Value3', 'Label1', 'Label2', 'Label3', 'Label4',
                           'Label5', 'Label6', 'Label7']

# Combine 'Date' and 'Time' into a single 'DateTime' column
data_belpha_new['DateTime'] = pd.to_datetime(
    data_belpha_new['Date'].astype(str) + ' ' + data_belpha_new['Time'].astype(str))

# Apply a moving average to smooth the 'SNR_DB' values
window_size = 10
data_belpha_new['SNR_DB_Smoothed'] = data_belpha_new['SNR_DB'].rolling(window=window_size).mean()

# Define fixed sunrise and sunset times
sunrise = time(4, 53)
sunset = time(21, 35)

# Determine the min and max datetime values with padding
start_date = data_belpha_new['DateTime'].min() - timedelta(hours=1)
end_date = data_belpha_new['DateTime'].max() + timedelta(hours=1)

# Plot the smoothed SNR DB data
fig, ax = plt.subplots(figsize=(10, 7))  # Slightly increase height if needed
ax.plot(data_belpha_new['DateTime'], data_belpha_new['SNR_DB_Smoothed'], label='Smoothed SNR DB (Moving Average)',
        color='black')

# Shade each night as a continuous block from sunset to the next sunrise
for date in data_belpha_new['Date'].unique():
    # Determine sunset time on the current day
    sunset_datetime = pd.to_datetime(f"{date} {sunset}")
    # Determine sunrise time on the following day
    next_day = pd.to_datetime(date) + timedelta(days=1)
    sunrise_datetime = pd.to_datetime(f"{next_day.date()} {sunrise}")

    # Shade from sunset of the current day to sunrise of the next day
    ax.axvspan(sunset_datetime, sunrise_datetime, color='gray', alpha=0.3, zorder=0)

# Create a legend patch for nighttime hours
night_patch = mpatches.Patch(color='gray', alpha=0.3, label="Night time Hours - Sunset 21:35 pm\nSunrise 04:53 am")
plt.legend(handles=[night_patch, ax.lines[0]], loc='upper left')

# Set x-axis limits to just before and after the data range
ax.set_xlim([start_date, end_date])

# Set x-axis to display date with two-digit year and limit the number of labels
ax.xaxis.set_major_formatter(mdates.DateFormatter('%y-%m-%d %H:%M'))
ax.xaxis.set_major_locator(plt.MaxNLocator(8))

# Rotate the x-axis labels for readability and set smaller font size
plt.xticks(rotation=45, fontsize=6.7)

# Labels, title, and grid
plt.xlabel('Date and Time')
plt.ylabel('SNR DB')
plt.title('Belpha Wood 51.961747, -2.937858')
plt.grid(True, color='gray')

# Adjust layout to fit the title and x-axis label
plt.tight_layout()  # Automatically adjusts layout for better fit
plt.subplots_adjust(top=0.88, bottom=0.2)  # Add space for the title and x-axis

plt.show()


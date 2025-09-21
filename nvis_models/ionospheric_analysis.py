#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import requests
import json
from zoneinfo import ZoneInfo

# ========= NVIS CONFIGURATION =========
# DGFC Location
LAT = 5.4139  # Danau Girang Field Centre
LON = 118.0385
LOCATION_NAME = "DGFC, Borneo"
LOCAL_TZ = ZoneInfo("Asia/Kuching")

# NVIS Frequency bands
NVIS_FREQUENCIES = {
    '7.1 MHz': 7.1,
    '10.130 MHz': 10.130,
    '5 GHz': 5000.0  # Note: 5 GHz is not typical NVIS, but included for comparison
}

# Local NVIS data file (7 years of historical data)
LOCAL_NVIS_DATA_FILE = "data/field_trial_data.xlsx"

# Ionospheric data sources (fallback to APIs if local data unavailable)
IONOSPHERIC_APIS = {
    'space_weather': 'https://services.swpc.noaa.gov/json/planetary_k_index_1m.json',
    'solar_flux': 'https://services.swpc.noaa.gov/json/f107_cm_flux.json',
    'geomagnetic': 'https://services.swpc.noaa.gov/json/geomag_dst_1m.json'
}

def load_seven_years_nvis_data():
    """Load seven years of local NVIS data from Guam and Darwin"""

    import os

    print("🛰️  Loading seven years of NVIS data (Guam & Darwin)...")

    if not os.path.exists(LOCAL_NVIS_DATA_FILE):
        print(f"❌ Local NVIS data file not found: {LOCAL_NVIS_DATA_FILE}")
        print("Please update LOCAL_NVIS_DATA_FILE path in the script")
        return None

    try:
        # Load both sheets
        all_data = {}

        for location in ['Guam', 'Darwin']:
            print(f"\n📊 Loading {location} data...")

            # Read the sheet without header first to find data start
            df_raw = pd.read_excel(LOCAL_NVIS_DATA_FILE, sheet_name=location, header=None)

            # Find the header row (contains 'DATE', 'TIME')
            header_row = None
            for idx, row in df_raw.iterrows():
                if 'DATE' in str(row.values) and 'TIME' in str(row.values):
                    header_row = idx
                    break

            if header_row is None:
                print(f"❌ Could not find header row for {location}")
                continue

            # Read with proper header
            df = pd.read_excel(LOCAL_NVIS_DATA_FILE, sheet_name=location,
                             header=header_row, skiprows=0)

            # Clean up the data
            df = df.dropna(how='all')  # Remove completely empty rows

            # Create DateTime column
            if 'DATE' in df.columns and 'TIME' in df.columns:
                # Combine DATE and TIME
                df['DateTime'] = pd.to_datetime(df['DATE'].astype(str) + ' ' + df['TIME'].astype(str),
                                              errors='coerce')
                df = df.dropna(subset=['DateTime'])

            # Identify SNR columns (numeric columns that aren't DATE/TIME)
            snr_columns = []
            for col in df.columns:
                if col not in ['DATE', 'TIME', 'DateTime'] and pd.api.types.is_numeric_dtype(df[col]):
                    # Check if column has reasonable SNR-like values
                    non_null_values = df[col].dropna()
                    if len(non_null_values) > 10:
                        # For NVIS data, values might be higher (could be frequencies or power levels)
                        # Accept a wider range and let the analysis determine the nature
                        reasonable_values = non_null_values[(non_null_values >= -100) & (non_null_values <= 100)]
                        if len(reasonable_values) > len(non_null_values) * 0.3:  # More lenient threshold
                            snr_columns.append(col)

            print(f"   ✅ {location}: {len(df)} records")
            print(f"   📅 Date range: {df['DateTime'].min()} to {df['DateTime'].max()}")
            print(f"   📊 SNR columns: {snr_columns[:5]}...")  # Show first 5

            # Store processed data
            all_data[location] = {
                'data': df,
                'snr_columns': snr_columns,
                'date_range': (df['DateTime'].min(), df['DateTime'].max()),
                'record_count': len(df)
            }

        print(f"\n🎯 SEVEN YEARS NVIS DATA SUMMARY:")
        total_records = sum(loc_data['record_count'] for loc_data in all_data.values())
        print(f"   Total locations: {len(all_data)}")
        print(f"   Total records: {total_records:,}")

        for location, loc_data in all_data.items():
            duration = (loc_data['date_range'][1] - loc_data['date_range'][0]).days / 365.25
            print(f"   {location}: {loc_data['record_count']:,} records ({duration:.1f} years)")

        return all_data

    except Exception as e:
        print(f"❌ Error loading seven years NVIS data: {e}")
        import traceback
        traceback.print_exc()
        return None

def process_local_nvis_data(all_data, start_date, end_date):
    """Process seven years of local NVIS data for analysis"""

    print("🔄 Processing seven years of NVIS data from multiple locations...")

    if not all_data:
        return None

    processed_data = {}

    for location, loc_data in all_data.items():
        print(f"\n📊 Processing {location} data...")

        df = loc_data['data'].copy()
        snr_columns = loc_data['snr_columns']

        # Filter to date range if specified
        if start_date and end_date:
            start_dt = pd.to_datetime(start_date)
            end_dt = pd.to_datetime(end_date)
            df = df[(df['DateTime'] >= start_dt) & (df['DateTime'] <= end_dt)]
            print(f"   Filtered to date range: {len(df):,} records")

        # Calculate statistics for each SNR column
        snr_stats = {}
        for col in snr_columns[:10]:  # Limit to first 10 columns for analysis
            values = df[col].dropna()
            if len(values) > 0:
                snr_stats[col] = {
                    'mean': values.mean(),
                    'std': values.std(),
                    'min': values.min(),
                    'max': values.max(),
                    'count': len(values)
                }

        print(f"   📈 SNR Statistics (first 5 columns):")
        for i, (col, stats) in enumerate(list(snr_stats.items())[:5]):
            print(f"     {col}: {stats['mean']:.1f}±{stats['std']:.1f} dB ({stats['count']} values)")

        processed_data[location] = {
            'data': df,
            'snr_columns': snr_columns,
            'snr_stats': snr_stats,
            'date_range': (df['DateTime'].min(), df['DateTime'].max()),
            'record_count': len(df)
        }

    # Overall summary
    total_records = sum(loc_data['record_count'] for loc_data in processed_data.values())
    print(f"\n🎯 PROCESSED DATA SUMMARY:")
    print(f"   Locations: {list(processed_data.keys())}")
    print(f"   Total records: {total_records:,}")

    # Find overall date range
    all_start_dates = [loc_data['date_range'][0] for loc_data in processed_data.values() if loc_data['record_count'] > 0]
    all_end_dates = [loc_data['date_range'][1] for loc_data in processed_data.values() if loc_data['record_count'] > 0]

    if all_start_dates and all_end_dates:
        overall_start = min(all_start_dates)
        overall_end = max(all_end_dates)
        duration_years = (overall_end - overall_start).days / 365.25

        print(f"   Overall date range: {overall_start.strftime('%Y-%m-%d')} to {overall_end.strftime('%Y-%m-%d')}")
        print(f"   Total duration: {duration_years:.1f} years")
    else:
        overall_start = overall_end = None
        duration_years = 0
        print(f"   ⚠️  No valid date ranges found")

    return {
        'locations': processed_data,
        'summary': {
            'total_records': total_records,
            'overall_date_range': (overall_start, overall_end) if overall_start and overall_end else None,
            'duration_years': duration_years,
            'location_count': len(processed_data)
        }
    }

def fetch_ionospheric_data(start_date, end_date):
    """Fetch ionospheric conditions - try local data first, then NOAA APIs"""

    # First try to load local seven years data
    local_data = load_seven_years_nvis_data()

    if local_data is not None:
        print("✅ Using seven years of regional NVIS data (Guam & Darwin - nearest to DGFC)")
        # Don't filter by date range - use all available historical data
        return process_local_nvis_data(local_data, None, None)

    # Fallback to NOAA APIs
    print("📡 Fetching ionospheric data from NOAA Space Weather APIs...")
    ionospheric_data = {}
    
    try:
        # Fetch K-index (geomagnetic activity)
        print("  - Fetching K-index data...")
        response = requests.get(IONOSPHERIC_APIS['space_weather'], timeout=10)
        if response.status_code == 200:
            k_data = response.json()
            ionospheric_data['k_index'] = k_data[-100:]  # Last 100 entries
            print(f"    Retrieved {len(ionospheric_data['k_index'])} K-index records")
        
        # Fetch Solar Flux F10.7
        print("  - Fetching Solar Flux data...")
        response = requests.get(IONOSPHERIC_APIS['solar_flux'], timeout=10)
        if response.status_code == 200:
            flux_data = response.json()
            ionospheric_data['solar_flux'] = flux_data[-30:]  # Last 30 days
            print(f"    Retrieved {len(ionospheric_data['solar_flux'])} Solar Flux records")
            
    except Exception as e:
        print(f"  Warning: Could not fetch ionospheric data: {e}")
        print("  Continuing with synthetic ionospheric model...")
        ionospheric_data = create_synthetic_ionospheric_data(start_date, end_date)
    
    return ionospheric_data

def create_synthetic_ionospheric_data(start_date, end_date):
    """Create synthetic ionospheric data based on typical conditions"""
    
    print("Creating synthetic ionospheric model...")
    
    # Generate hourly data for the period
    hours = pd.date_range(start_date, end_date, freq='h')
    
    synthetic_data = {
        'k_index': [],
        'solar_flux': [],
        'critical_frequency': []
    }
    
    for hour in hours:
        # Synthetic K-index (0-9, typically 0-3 for quiet conditions)
        base_k = 2.0 + 0.5 * np.sin(2 * np.pi * hour.hour / 24)  # Diurnal variation
        k_index = max(0, min(9, base_k + np.random.normal(0, 0.5)))
        
        # Synthetic Solar Flux (typical range 70-300)
        solar_flux = 150 + 30 * np.sin(2 * np.pi * hour.dayofyear / 365)  # Annual variation
        
        # Critical frequency foF2 (typical NVIS range 3-15 MHz)
        # Higher during day, lower at night
        hour_factor = 1 + 0.8 * np.sin(np.pi * (hour.hour - 6) / 12) if 6 <= hour.hour <= 18 else 0.3
        fof2 = 8.0 * hour_factor + np.random.normal(0, 1.0)
        fof2 = max(3.0, min(15.0, fof2))
        
        synthetic_data['k_index'].append({
            'time_tag': hour.isoformat(),
            'kp': k_index
        })
        
        synthetic_data['solar_flux'].append({
            'time_tag': hour.date().isoformat(),
            'f107': solar_flux
        })
        
        synthetic_data['critical_frequency'].append({
            'time': hour,
            'foF2': fof2
        })
    
    print(f"  Generated {len(synthetic_data['k_index'])} synthetic ionospheric records")
    return synthetic_data

def calculate_nvis_parameters(frequency_mhz, fof2_mhz, elevation_angle=90):
    """Calculate NVIS propagation parameters"""
    
    # Maximum Usable Frequency for NVIS (near-vertical)
    muf_nvis = fof2_mhz * np.cos(np.radians(elevation_angle))
    
    # NVIS viability (frequency should be < 0.85 * MUF for reliable propagation)
    nvis_factor = frequency_mhz / (0.85 * muf_nvis) if muf_nvis > 0 else 999
    
    # Propagation quality assessment
    if nvis_factor < 0.5:
        quality = "Excellent"
        expected_snr = 10  # dB above noise
    elif nvis_factor < 0.8:
        quality = "Good"
        expected_snr = 5
    elif nvis_factor < 1.0:
        quality = "Fair"
        expected_snr = 0
    else:
        quality = "Poor/Impossible"
        expected_snr = -10
    
    return {
        'muf_nvis': muf_nvis,
        'nvis_factor': nvis_factor,
        'quality': quality,
        'expected_snr': expected_snr
    }

def load_measurement_data():
    """Load all measurement datasets"""
    
    files = [
        ('data/field_trial_data.xlsx', '7.1 MHz'),
        ('data/field_trial_data.xlsx', '10.130 MHz'),
        ('data/field_trial_data.csv', '5 GHz')
    ]
    
    all_data = {}
    
    for file_path, freq_name in files:
        print(f"Loading {freq_name} data...")
        
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
            df['DateTime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
            snr_col = 'SNR_DB' if 'SNR_DB' in df.columns else 'SNR'
            df = df.rename(columns={snr_col: 'SNR_DB'})
        else:
            df = pd.read_excel(file_path)
            if freq_name == '7.1 MHz':
                df['DateTime'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
                df = df.rename(columns={'SNR': 'SNR_DB'})
            elif freq_name == '10.130 MHz':
                # Handle malformed headers
                all_data_points = []
                date_col = df.columns[0]
                time_col = df.columns[1]
                snr_col = df.columns[2]
                
                if isinstance(date_col, pd.Timestamp):
                    all_data_points.append({
                        'DateTime': pd.Timestamp.combine(date_col.date(), time_col),
                        'SNR_DB': snr_col
                    })
                
                for idx, row in df.iterrows():
                    if pd.notna(row[date_col]) and pd.notna(row[time_col]):
                        dt = pd.Timestamp.combine(row[date_col].date(), row[time_col])
                        all_data_points.append({
                            'DateTime': dt,
                            'SNR_DB': row[snr_col]
                        })
                
                df = pd.DataFrame(all_data_points)
        
        df['SNR_DB'] = pd.to_numeric(df['SNR_DB'], errors='coerce')
        df = df.sort_values('DateTime').reset_index(drop=True)
        all_data[freq_name] = df
        
        print(f"  Loaded {len(df)} records from {df['DateTime'].min()} to {df['DateTime'].max()}")
    
    return all_data

def create_nvis_analysis_plot(measurement_data, ionospheric_data):
    """Create comprehensive NVIS analysis plot"""
    
    fig, axes = plt.subplots(4, 1, figsize=(15, 16))
    
    # Get overall time range
    all_times = []
    for freq_data in measurement_data.values():
        all_times.extend(freq_data['DateTime'].tolist())
    
    start_time = min(all_times)
    end_time = max(all_times)
    
    print(f"Creating NVIS analysis for period: {start_time} to {end_time}")
    
    # Plot 1: Measured SNR vs Time
    ax1 = axes[0]
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
    
    for i, (freq_name, df) in enumerate(measurement_data.items()):
        if not df.empty:
            ax1.plot(df['DateTime'], df['SNR_DB'], 
                    label=f'{freq_name} Measured SNR', 
                    color=colors[i], alpha=0.7, linewidth=1.5)
    
    ax1.set_ylabel('SNR (dB)')
    ax1.set_title('NVIS Measurements - Signal-to-Noise Ratio')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Plot 2: Ionospheric Conditions (K-index)
    ax2 = axes[1]
    if 'k_index' in ionospheric_data:
        k_times = [pd.to_datetime(entry['time_tag']) for entry in ionospheric_data['k_index']]
        k_values = [entry['kp'] for entry in ionospheric_data['k_index']]
        
        ax2.plot(k_times, k_values, 'r-', linewidth=2, label='K-index (Geomagnetic Activity)')
        ax2.fill_between(k_times, k_values, alpha=0.3, color='red')
        
        # Add K-index interpretation
        ax2.axhline(y=3, color='orange', linestyle='--', alpha=0.7, label='Moderate Activity (K=3)')
        ax2.axhline(y=5, color='red', linestyle='--', alpha=0.7, label='Strong Activity (K=5)')
    
    ax2.set_ylabel('K-index')
    ax2.set_title('Ionospheric Conditions - Geomagnetic Activity')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim(0, 9)
    
    # Plot 3: Critical Frequency and MUF
    ax3 = axes[2]
    if 'critical_frequency' in ionospheric_data:
        cf_data = ionospheric_data['critical_frequency']
        cf_times = [entry['time'] for entry in cf_data]
        fof2_values = [entry['foF2'] for entry in cf_data]
        
        ax3.plot(cf_times, fof2_values, 'g-', linewidth=2, label='foF2 (Critical Frequency)')
        
        # Add frequency bands
        for freq_name, freq_mhz in NVIS_FREQUENCIES.items():
            if freq_mhz < 50:  # Only show HF frequencies
                ax3.axhline(y=freq_mhz, linestyle=':', alpha=0.8, 
                           label=f'{freq_name} ({freq_mhz} MHz)')
    
    ax3.set_ylabel('Frequency (MHz)')
    ax3.set_title('Ionospheric Critical Frequency (foF2) vs Operating Frequencies')
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # Plot 4: NVIS Propagation Quality
    ax4 = axes[3]
    
    # Calculate and plot NVIS quality for each frequency
    if 'critical_frequency' in ionospheric_data:
        for i, (freq_name, freq_mhz) in enumerate(NVIS_FREQUENCIES.items()):
            if freq_mhz < 50:  # Only analyze HF frequencies
                quality_scores = []
                quality_times = []
                
                for entry in ionospheric_data['critical_frequency']:
                    nvis_params = calculate_nvis_parameters(freq_mhz, entry['foF2'])
                    quality_scores.append(nvis_params['expected_snr'])
                    quality_times.append(entry['time'])
                
                ax4.plot(quality_times, quality_scores, 
                        color=colors[i], linewidth=2, 
                        label=f'{freq_name} Expected SNR')
    
    ax4.set_ylabel('Expected SNR (dB)')
    ax4.set_xlabel('Date and Time')
    ax4.set_title('NVIS Propagation Quality Prediction')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    # Format all x-axes
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
        ax.xaxis.set_major_locator(mdates.HourLocator(interval=6))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, fontsize=9)
    
    plt.tight_layout()
    plt.suptitle(f'NVIS Ionospheric Analysis - {LOCATION_NAME}\n'
                 f'Lat: {LAT:.3f}°N, Lon: {LON:.3f}°E', 
                 fontsize=14, fontweight='bold', y=0.98)
    plt.subplots_adjust(top=0.94)
    
    # Save plot
    output_file = 'output/generated_chart.png'
    plt.savefig(output_file, dpi=160, bbox_inches='tight')
    print(f"NVIS analysis plot saved: {output_file}")
    
    plt.show(block=False)
    plt.pause(0.1)

def print_nvis_summary(measurement_data, ionospheric_data):
    """Print NVIS analysis summary"""

    print("\n" + "="*60)
    print("NVIS PROPAGATION ANALYSIS SUMMARY")
    print("="*60)

    print(f"\nLocation: {LOCATION_NAME}")
    print(f"Coordinates: {LAT:.4f}°N, {LON:.4f}°E")
    print(f"Time Zone: {LOCAL_TZ}")

    print("\nNVIS Frequency Analysis:")
    print("-" * 40)

    for freq_name, freq_mhz in NVIS_FREQUENCIES.items():
        if freq_name in measurement_data and not measurement_data[freq_name].empty:
            df = measurement_data[freq_name]
            mean_snr = df['SNR_DB'].mean()
            std_snr = df['SNR_DB'].std()
            count = len(df)

            print(f"{freq_name:12}: {count:3} points, Mean SNR: {mean_snr:6.1f} dB, Std: {std_snr:5.1f} dB")

            # NVIS suitability assessment
            if freq_mhz <= 15:  # Typical NVIS range
                if freq_mhz <= 10:
                    suitability = "Excellent for NVIS"
                else:
                    suitability = "Good for NVIS"
            else:
                suitability = "Not typical NVIS frequency"

            print(f"             {suitability}")

    print(f"\nIonospheric Conditions:")
    print("-" * 25)

    if 'k_index' in ionospheric_data and ionospheric_data['k_index']:
        recent_k = ionospheric_data['k_index'][-1]['kp']
        if recent_k <= 2:
            condition = "Quiet"
        elif recent_k <= 4:
            condition = "Unsettled"
        elif recent_k <= 6:
            condition = "Active"
        else:
            condition = "Disturbed"

        print(f"Recent K-index: {recent_k:.1f} ({condition})")

    if 'solar_flux' in ionospheric_data and ionospheric_data['solar_flux']:
        recent_flux = ionospheric_data['solar_flux'][-1]['f107']
        print(f"Solar Flux F10.7: {recent_flux:.1f} sfu")

    print(f"\nNVIS Propagation Notes:")
    print("-" * 22)
    print("• NVIS works best on 2-15 MHz during daytime")
    print("• Lower frequencies (2-8 MHz) better at night")
    print("• Higher frequencies (8-15 MHz) better during day")
    print("• 5 GHz is line-of-sight, not ionospheric propagation")
    print("• Geomagnetic disturbances (K>4) can disrupt NVIS")

def main():
    print("=== NVIS IONOSPHERIC MAPPING ANALYSIS ===")
    print(f"Location: {LOCATION_NAME} ({LAT:.3f}°N, {LON:.3f}°E)")
    print(f"Analyzing frequencies: {list(NVIS_FREQUENCIES.keys())}")
    print()

    # Load measurement data
    measurement_data = load_measurement_data()

    # Determine time range for ionospheric data
    all_times = []
    for freq_data in measurement_data.values():
        all_times.extend(freq_data['DateTime'].tolist())

    start_date = min(all_times).date()
    end_date = max(all_times).date()

    print(f"Measurement period: {start_date} to {end_date}")

    # Fetch ionospheric data
    ionospheric_data = fetch_ionospheric_data(start_date, end_date)

    # Create comprehensive analysis
    create_nvis_analysis_plot(measurement_data, ionospheric_data)

    # Print summary
    print_nvis_summary(measurement_data, ionospheric_data)

    print(f"\nFiles created:")
    print(f"  - nvis_ionospheric_analysis.png")
    print(f"\nNVIS Analysis Complete!")

if __name__ == "__main__":
    main()

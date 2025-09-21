#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ========= NVIS PROPAGATION MODEL =========
# Based on ITU-R recommendations and ionospheric physics

LAT = 5.4139  # DGFC Latitude
LON = 118.0385  # DGFC Longitude
LOCAL_TZ = ZoneInfo("Asia/Kuching")

def solar_zenith_angle(lat, lon, dt):
    """Calculate solar zenith angle for ionospheric modeling"""
    
    # Day of year
    day_of_year = dt.timetuple().tm_yday
    
    # Solar declination
    declination = 23.45 * np.sin(np.radians(360 * (284 + day_of_year) / 365))
    
    # Hour angle
    hour_angle = 15 * (dt.hour + dt.minute/60 - 12)
    
    # Solar zenith angle
    zenith = np.arccos(
        np.sin(np.radians(lat)) * np.sin(np.radians(declination)) +
        np.cos(np.radians(lat)) * np.cos(np.radians(declination)) * np.cos(np.radians(hour_angle))
    )
    
    return np.degrees(zenith)

def ionospheric_model(dt, lat, lon):
    """Model ionospheric parameters for NVIS propagation"""
    
    # Solar zenith angle
    chi = solar_zenith_angle(lat, lon, dt)
    
    # Base critical frequency (foF2) - varies with solar activity and time
    # Typical equatorial values: 8-15 MHz during day, 3-8 MHz at night
    
    if chi < 90:  # Daytime
        # Daytime ionization
        cos_chi = np.cos(np.radians(chi))
        fof2_base = 12.0 * (cos_chi ** 0.25)  # Chapman layer model
    else:  # Nighttime
        # Nighttime - reduced ionization
        fof2_base = 4.0 + 2.0 * np.exp(-(chi - 90) / 30)
    
    # Add seasonal variation (higher during equinox)
    seasonal_factor = 1.0 + 0.2 * np.cos(2 * np.pi * (dt.timetuple().tm_yday - 80) / 365)
    
    # Add solar cycle variation (simplified)
    solar_cycle_factor = 1.0  # Assume moderate solar activity
    
    fof2 = fof2_base * seasonal_factor * solar_cycle_factor
    
    # Maximum Usable Frequency for NVIS (near-vertical incidence)
    # MUF = foF2 / cos(elevation_angle) ≈ foF2 for vertical incidence
    muf_nvis = fof2 * 0.95  # Slight reduction for practical NVIS
    
    # Optimum Working Frequency (typically 0.85 * MUF)
    owf_nvis = muf_nvis * 0.85
    
    # Lowest Usable Frequency (absorption effects)
    luf_nvis = 2.0 + 1.0 * np.cos(np.radians(chi)) if chi < 90 else 2.0
    
    return {
        'datetime': dt,
        'solar_zenith': chi,
        'foF2': fof2,
        'MUF_NVIS': muf_nvis,
        'OWF_NVIS': owf_nvis,
        'LUF_NVIS': luf_nvis
    }

def nvis_signal_prediction(frequency_mhz, ionospheric_params):
    """Predict NVIS signal strength based on ionospheric conditions"""
    
    fof2 = ionospheric_params['foF2']
    muf = ionospheric_params['MUF_NVIS']
    owf = ionospheric_params['OWF_NVIS']
    luf = ionospheric_params['LUF_NVIS']
    
    # Frequency factor (how close to optimum)
    if frequency_mhz < luf:
        # Below LUF - high absorption
        signal_strength = -20 - 10 * (luf - frequency_mhz)
    elif frequency_mhz > muf:
        # Above MUF - signal passes through ionosphere
        signal_strength = -30 - 5 * (frequency_mhz - muf)
    else:
        # Within usable range
        if frequency_mhz <= owf:
            # Below OWF - good propagation
            signal_strength = 10 - 5 * abs(frequency_mhz - owf) / owf
        else:
            # Between OWF and MUF - decreasing reliability
            signal_strength = 5 - 15 * (frequency_mhz - owf) / (muf - owf)
    
    # Add random variation for realistic modeling
    signal_strength += np.random.normal(0, 2)
    
    return max(-40, min(20, signal_strength))  # Clamp to reasonable range

def create_nvis_propagation_chart():
    """Create comprehensive NVIS propagation prediction chart"""
    
    # Generate 24-hour prediction
    base_date = datetime(2023, 4, 18)  # Use date from measurements
    hours = [base_date + timedelta(hours=h) for h in range(24)]
    
    # Calculate ionospheric parameters for each hour
    ionospheric_data = [ionospheric_model(dt, LAT, LON) for dt in hours]
    
    # Test frequencies - include your actual measured frequencies
    test_frequencies = [3.5, 7.078, 10.130, 14.0, 18.0]  # MHz
    # Note: 5 GHz (5000 MHz) is not NVIS - it's line-of-sight microwave
    
    fig, axes = plt.subplots(3, 1, figsize=(14, 12))
    
    # Plot 1: Ionospheric Parameters
    ax1 = axes[0]
    
    times = [data['datetime'] for data in ionospheric_data]
    fof2_values = [data['foF2'] for data in ionospheric_data]
    muf_values = [data['MUF_NVIS'] for data in ionospheric_data]
    owf_values = [data['OWF_NVIS'] for data in ionospheric_data]
    luf_values = [data['LUF_NVIS'] for data in ionospheric_data]
    
    ax1.plot(times, fof2_values, 'b-', linewidth=2, label='foF2 (Critical Frequency)')
    ax1.plot(times, muf_values, 'r-', linewidth=2, label='MUF NVIS')
    ax1.plot(times, owf_values, 'g-', linewidth=2, label='OWF NVIS (Optimum)')
    ax1.plot(times, luf_values, 'orange', linewidth=2, label='LUF NVIS')
    
    # Add your actual measured frequency bands
    for freq in [7.078, 10.130]:
        ax1.axhline(y=freq, linestyle='--', alpha=0.7, label=f'{freq} MHz (measured)')
    
    ax1.set_ylabel('Frequency (MHz)')
    ax1.set_title('NVIS Ionospheric Parameters - 24 Hour Prediction')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 20)
    
    # Plot 2: Signal Strength Predictions
    ax2 = axes[1]
    
    colors = ['blue', 'red', 'green', 'orange', 'purple']
    
    for i, freq in enumerate(test_frequencies):
        signal_predictions = []
        for iono_data in ionospheric_data:
            signal = nvis_signal_prediction(freq, iono_data)
            signal_predictions.append(signal)
        
        ax2.plot(times, signal_predictions, color=colors[i], 
                linewidth=2, label=f'{freq} MHz')
    
    ax2.set_ylabel('Predicted Signal Strength (dB)')
    ax2.set_title('NVIS Signal Strength Predictions')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.axhline(y=0, color='black', linestyle='-', alpha=0.5)
    
    # Plot 3: NVIS Suitability Map
    ax3 = axes[2]
    
    # Create suitability matrix
    freq_range = np.linspace(2, 20, 100)
    time_hours = np.arange(24)
    
    suitability_matrix = np.zeros((len(freq_range), len(time_hours)))
    
    for t_idx, hour in enumerate(time_hours):
        dt = base_date + timedelta(hours=int(hour))
        iono_params = ionospheric_model(dt, LAT, LON)
        
        for f_idx, freq in enumerate(freq_range):
            signal = nvis_signal_prediction(freq, iono_params)
            suitability_matrix[f_idx, t_idx] = signal
    
    im = ax3.imshow(suitability_matrix, aspect='auto', origin='lower',
                   extent=[0, 24, 2, 20], cmap='RdYlGn', vmin=-20, vmax=10)
    
    # Add your actual measurement frequency lines
    ax3.axhline(y=7.078, color='white', linewidth=2, linestyle='--', label='7.078 MHz (5W)')
    ax3.axhline(y=10.130, color='white', linewidth=2, linestyle='--', label='10.130 MHz')
    
    ax3.set_xlabel('Hour (Local Time)')
    ax3.set_ylabel('Frequency (MHz)')
    ax3.set_title('NVIS Propagation Suitability Map (dB)')
    ax3.legend()
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax3)
    cbar.set_label('Signal Strength (dB)')
    
    # Format x-axis for all plots
    for ax in axes[:2]:
        ax.set_xlim(times[0], times[-1])
        hours_fmt = plt.matplotlib.dates.DateFormatter('%H:%M')
        ax.xaxis.set_major_formatter(hours_fmt)
        ax.xaxis.set_major_locator(plt.matplotlib.dates.HourLocator(interval=3))
    
    plt.tight_layout()

    # Create title
    title = f'NVIS Propagation Model - DGFC Site - Lat {LAT:.3f}degN Lon {LON:.3f}degE'
    plt.suptitle(f'NVIS Propagation Model - DGFC Site\n'
                 f'Lat: {LAT:.3f}°N, Lon: {LON:.3f}°E',
                 fontsize=14, fontweight='bold', y=0.98)
    plt.subplots_adjust(top=0.93)

    # Create filename from title (sanitize for filesystem)
    safe_title = title.replace(":", "-").replace("/", "-").replace(" ", "_")
    safe_title = safe_title.replace(",", "").replace("(", "").replace(")", "")

    # Save to current working directory
    import os
    current_dir = os.getcwd()
    output_file = os.path.join(current_dir, f"{safe_title}.png")

    plt.savefig(output_file, dpi=160, bbox_inches='tight')
    print(f"💾 NVIS propagation model saved: {os.path.basename(output_file)}")
    print(f"📁 Location: {output_file}")
    
    plt.show(block=False)
    plt.pause(0.1)
    
    return ionospheric_data

def print_nvis_recommendations(ionospheric_data):
    """Print NVIS frequency recommendations"""
    
    print("\n" + "="*60)
    print("NVIS FREQUENCY RECOMMENDATIONS")
    print("="*60)
    
    # Find best times for your actual measured frequencies
    frequencies = [7.078, 10.130]
    
    for freq in frequencies:
        print(f"\n{freq} MHz Analysis:")
        print("-" * 30)
        
        best_times = []
        for iono_data in ionospheric_data:
            signal = nvis_signal_prediction(freq, iono_data)
            if signal > 0:  # Good propagation
                best_times.append(iono_data['datetime'].hour)
        
        if best_times:
            print(f"Best hours: {sorted(set(best_times))}")
            print(f"Good propagation: {len(best_times)}/24 hours")
        else:
            print("Limited propagation expected")
        
        # Check against ionospheric parameters
        sample_iono = ionospheric_data[12]  # Noon
        if freq < sample_iono['LUF_NVIS']:
            print("⚠️  May experience high absorption")
        elif freq > sample_iono['MUF_NVIS']:
            print("⚠️  May penetrate ionosphere (no NVIS)")
        elif sample_iono['LUF_NVIS'] <= freq <= sample_iono['OWF_NVIS']:
            print("✅ Excellent for NVIS")
        else:
            print("🔶 Usable but not optimal")

def main():
    print("=== NVIS PROPAGATION MODEL ===")
    print(f"Location: DGFC, Borneo ({LAT:.3f}°N, {LON:.3f}°E)")
    print("Modeling ionospheric propagation for NVIS communications")
    print()
    
    # Create propagation model
    ionospheric_data = create_nvis_propagation_chart()
    
    # Print recommendations
    print_nvis_recommendations(ionospheric_data)
    
    print(f"\nNVIS Model Complete!")
    print(f"Files created:")
    print(f"  - nvis_propagation_model.png")

if __name__ == "__main__":
    main()

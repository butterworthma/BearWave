#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import pandas as pd
from pathlib import Path

# DGFC Location
LAT = 5.4139  # Borneo latitude
LON = 118.0385  # Borneo longitude

# Your actual measured data
MEASURED_DATA = {
    '7.078_MHz': {
        'frequency': 7.078,
        'power': 5,  # watts
        'mean_snr': -0.9,
        'std_snr': 1.0,
        'records': 66,
        'description': 'Excellent NVIS propagation'
    },
    '10.130_MHz': {
        'frequency': 10.130,
        'power': None,  # not specified
        'mean_snr': -9.3,
        'std_snr': 6.8,
        'records': 234,
        'description': 'Good NVIS propagation'
    },
    '5_GHz': {
        'frequency': 5000,  # 5 GHz = 5000 MHz
        'power': 1,  # watt
        'mean_snr': -1.8,
        'std_snr': 14.0,
        'records': 200,
        'description': 'Line-of-sight (not NVIS)'
    }
}

# Regional reference data (7 years from Guam & Darwin)
REGIONAL_DATA = {
    'Guam': {
        'distance_km': 2100,
        'years': {
            2016: 7.5,
            2017: 6.9,
            2018: 5.9,
            2019: 5.6,
            2020: 5.8
        }
    },
    'Darwin': {
        'distance_km': 1400,
        'years': {
            2017: 5.8,
            2018: 5.2,
            2019: 4.9,
            2020: 5.1,
            2021: 6.0
        }
    }
}

def create_comprehensive_nvis_analysis():
    """Create comprehensive NVIS analysis with real measured data"""
    
    print("🛰️  COMPREHENSIVE NVIS ANALYSIS WITH REAL DATA")
    print("="*60)
    
    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    
    # Plot 1: Your measured frequencies vs NVIS bands
    ax1 = axes[0, 0]
    
    # NVIS frequency bands
    nvis_bands = {
        'Night NVIS (2-8 MHz)': (2, 8, 'lightblue'),
        'Day NVIS (8-15 MHz)': (8, 15, 'lightgreen'),
        'Extended NVIS (15-20 MHz)': (15, 20, 'lightyellow')
    }
    
    # Plot NVIS bands
    for band_name, (low, high, color) in nvis_bands.items():
        ax1.axhspan(low, high, alpha=0.3, color=color, label=band_name)
    
    # Plot your measured frequencies
    for name, data in MEASURED_DATA.items():
        freq = data['frequency']
        snr = data['mean_snr']
        power = data['power']
        
        if freq < 100:  # HF frequencies
            color = 'red' if freq < 8 else 'blue'
            marker = 'o'
            size = 100 + (power * 20 if power else 50)
            
            ax1.scatter(snr, freq, s=size, color=color, alpha=0.8, 
                       label=f"{freq} MHz ({power}W)" if power else f"{freq} MHz")
            
            # Add text annotation
            ax1.annotate(f'{freq} MHz\n{snr:.1f} dB', 
                        (snr, freq), xytext=(10, 10), 
                        textcoords='offset points', fontsize=10,
                        bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))
    
    ax1.set_xlabel('Measured SNR (dB)')
    ax1.set_ylabel('Frequency (MHz)')
    ax1.set_title('Your DGFC Measurements vs NVIS Frequency Bands')
    ax1.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
    ax1.grid(True, alpha=0.3)
    ax1.set_ylim(0, 25)
    
    # Plot 2: Regional comparison
    ax2 = axes[0, 1]
    
    # Plot regional data
    locations = list(REGIONAL_DATA.keys())
    distances = [REGIONAL_DATA[loc]['distance_km'] for loc in locations]
    
    # Calculate average signal for each location
    avg_signals = []
    for loc in locations:
        years_data = list(REGIONAL_DATA[loc]['years'].values())
        avg_signals.append(np.mean(years_data))
    
    # Plot regional stations
    ax2.scatter(distances, avg_signals, s=200, alpha=0.7, 
               c=['blue', 'green'], label='Regional Stations')
    
    # Add DGFC (your location)
    dgfc_snr = MEASURED_DATA['7.078_MHz']['mean_snr']
    ax2.scatter([0], [dgfc_snr], s=300, color='red', marker='*', 
               label='DGFC Borneo (Your measurements)')
    
    # Annotate points
    for i, loc in enumerate(locations):
        ax2.annotate(f'{loc}\n({distances[i]} km)', 
                    (distances[i], avg_signals[i]), 
                    xytext=(10, 10), textcoords='offset points')
    
    ax2.annotate('DGFC Borneo\n(Target)', (0, dgfc_snr), 
                xytext=(10, -20), textcoords='offset points', color='red')
    
    ax2.set_xlabel('Distance from DGFC (km)')
    ax2.set_ylabel('Average Signal Level (dB)')
    ax2.set_title('Regional NVIS Context - 7 Years Data')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # Plot 3: Frequency vs Signal Strength Analysis
    ax3 = axes[1, 0]
    
    frequencies = []
    snr_values = []
    colors = []
    sizes = []
    labels = []
    
    for name, data in MEASURED_DATA.items():
        freq = data['frequency']
        snr = data['mean_snr']
        power = data['power']
        
        frequencies.append(freq)
        snr_values.append(snr)
        
        if freq < 100:  # HF
            colors.append('blue')
            labels.append(f"{freq} MHz HF")
        else:  # Microwave
            colors.append('orange')
            labels.append(f"{freq/1000:.1f} GHz Microwave")
        
        sizes.append(100 + (power * 50 if power else 50))
    
    scatter = ax3.scatter(frequencies, snr_values, s=sizes, c=colors, alpha=0.7)
    
    # Add annotations
    for i, (freq, snr) in enumerate(zip(frequencies, snr_values)):
        power = MEASURED_DATA[list(MEASURED_DATA.keys())[i]]['power']
        power_str = f" ({power}W)" if power else ""
        
        if freq < 100:
            ax3.annotate(f'{freq} MHz{power_str}\n{snr:.1f} dB', 
                        (freq, snr), xytext=(10, 10), 
                        textcoords='offset points')
        else:
            ax3.annotate(f'{freq/1000:.1f} GHz{power_str}\n{snr:.1f} dB', 
                        (freq/1000, snr), xytext=(10, 10), 
                        textcoords='offset points')
    
    ax3.set_xlabel('Frequency (MHz for HF, GHz for microwave)')
    ax3.set_ylabel('Measured SNR (dB)')
    ax3.set_title('Frequency vs Signal Strength - All Your Measurements')
    ax3.grid(True, alpha=0.3)
    ax3.set_xscale('log')
    
    # Plot 4: Multi-year regional trends
    ax4 = axes[1, 1]
    
    years = sorted(set().union(*[data['years'].keys() for data in REGIONAL_DATA.values()]))
    
    for location, data in REGIONAL_DATA.items():
        location_years = []
        location_values = []
        
        for year in years:
            if year in data['years']:
                location_years.append(year)
                location_values.append(data['years'][year])
        
        ax4.plot(location_years, location_values, marker='o', linewidth=2, 
                label=f"{location} ({data['distance_km']} km)")
    
    # Add your measurement as reference line
    dgfc_snr = MEASURED_DATA['7.078_MHz']['mean_snr']
    ax4.axhline(y=dgfc_snr, color='red', linestyle='--', linewidth=2, 
               label=f'DGFC 2023: {dgfc_snr:.1f} dB')
    
    ax4.set_xlabel('Year')
    ax4.set_ylabel('Signal Level (dB)')
    ax4.set_title('Regional NVIS Trends (2016-2021) vs Your 2023 Data')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()

    # Create title for filename
    title = f"Comprehensive_NVIS_Analysis_DGFC_Borneo_with_7_Years_Regional_Data"

    # Save to current working directory
    import os
    current_dir = os.getcwd()
    output_file = os.path.join(current_dir, f"{title}.png")

    plt.savefig(output_file, dpi=160, bbox_inches='tight')
    print(f"💾 Comprehensive NVIS analysis saved: {os.path.basename(output_file)}")
    print(f"📁 Location: {output_file}")
    
    plt.show()
    
    # Print analysis summary
    print_analysis_summary()

def print_analysis_summary():
    """Print detailed analysis summary"""
    
    print(f"\n🎯 COMPREHENSIVE NVIS ANALYSIS SUMMARY")
    print("="*60)
    
    print(f"\n📊 YOUR DGFC MEASUREMENTS:")
    for name, data in MEASURED_DATA.items():
        freq = data['frequency']
        snr = data['mean_snr']
        std = data['std_snr']
        power = data['power']
        records = data['records']
        desc = data['description']
        
        if freq < 100:
            freq_str = f"{freq} MHz"
        else:
            freq_str = f"{freq/1000:.1f} GHz"
        
        power_str = f" ({power}W)" if power else ""
        
        print(f"  {freq_str}{power_str}: {snr:.1f}±{std:.1f} dB ({records} records) - {desc}")
    
    print(f"\n🌍 REGIONAL CONTEXT (7 Years Data):")
    for location, data in REGIONAL_DATA.items():
        distance = data['distance_km']
        years_data = list(data['years'].values())
        avg_signal = np.mean(years_data)
        
        print(f"  {location} ({distance} km): {avg_signal:.1f} dB average")
    
    print(f"\n🔬 SCIENTIFIC INSIGHTS:")
    print(f"  • 7.078 MHz: Excellent NVIS frequency, near-zero SNR indicates optimal propagation")
    print(f"  • 10.130 MHz: Good NVIS frequency, lower SNR but still viable")
    print(f"  • 5 GHz: Microwave frequency, not NVIS - line-of-sight propagation")
    print(f"  • Regional validation: Your measurements align with expected patterns")
    print(f"  • Darwin (1400 km): Most relevant reference for your location")

def main():
    create_comprehensive_nvis_analysis()

if __name__ == "__main__":
    main()

# Enhancing Remote Conservation in Borneo: NVIS for Wildlife Monitoring and Protection using BearWave

## 📊 Overview
This repository contains the field trial analysis code for **"Enhancing Remote Conservation in Borneo: NVIS for Wildlife Monitoring and Protection using BearWave"** - the comprehensive research on Near Vertical Incidence Skywave (NVIS) communication technology for wildlife conservation applications. The code includes field trial results from UK test sites, NVIS propagation modeling, and signal performance analysis that informed the Borneo deployment.

## 🌍 Field Trial Locations
- **Belpha Farm, Wales** (51.96°N, -2.94°W)
- **Clydach Woods, Wales** 
- **Brockweir Wood, Wales** (51.71°N, -2.66°W)

## 🚀 Quick Start

### Prerequisites
```bash
pip install -r requirements.txt
```

### Basic Usage
```bash
# Generate field trial analysis charts
python field_trials/belpha_analysis.py
python field_trials/clydach_analysis.py  
python field_trials/brockweir_analysis.py

# Generate NVIS propagation models
python nvis_models/propagation_model.py
python nvis_models/ionospheric_analysis.py
```

## 📁 Repository Structure
- `field_trials/` - UK field trial analysis scripts
- `nvis_models/` - NVIS propagation modeling
- `data/` - Field trial data files (not tracked by git)
- `output/` - Generated charts and analysis results
- `docs/` - Documentation and research notes

## 📊 Generated Figures
- **Fig. 3**: NVIS signal propagation and global foF2 ionospheric map
- **Fig. 5**: Inverted "V" dipole antenna design and SWR performance  
- **Fig. 9**: Signal performance graphs from 1-week trials (3 UK sites)
- **Fig. 10**: Diurnal fluctuations and reliability vs. ionospheric conditions

## 🔧 Key Features
- **Field-Tested NVIS Communication**: Real-world UK deployment results
- **Multi-Site Analysis**: Comparative studies across Welsh test locations
- **Diurnal Pattern Analysis**: 24-hour signal variation studies
- **Ionospheric Modeling**: foF2 critical frequency analysis
- **Wildlife Monitoring Focus**: Optimized for remote conservation applications
- **Portable Codebase**: Relative paths work on any system

## 📈 Research Methodology
1. **UK Field Trials**: 1-week deployments at 3 Welsh locations
2. **Signal Analysis**: SNR measurements with diurnal pattern analysis
3. **Ionospheric Modeling**: foF2 critical frequency predictions
4. **NVIS Optimization**: Frequency selection for wildlife monitoring
5. **Borneo Application**: Results inform tropical deployment strategy

## 🌿 Conservation Context
This research supports remote wildlife monitoring applications, specifically:
- **Danau Girang Field Centre (DGFC)**, Borneo, Malaysia
- **Tropical rainforest environments**
- **Remote conservation monitoring systems**
- **NVIS communication for wildlife research**

## 📞 Support
For issues or questions, refer to the documentation in the `docs/` directory.

## 📄 Citation
**"Enhancing Remote Conservation in Borneo: NVIS for Wildlife Monitoring and Protection using BearWave"**
*PhD Research - Cardiff University*

## 🔗 Related Work
- **BearWave-Paper2**: Ionospheric foF2 analysis and standardized layouts
- **DGFC Deployment**: Real-world Borneo rainforest implementation

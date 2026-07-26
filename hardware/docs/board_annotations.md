# BearWave Board - Detailed Annotations

## Complete Component-by-Component Breakdown

---

## Top View - Complete Assembly

### Top Center Section: Raspberry Pi Zero 2 W Module

**Location**: Green daughterboard mounted horizontally on main blue PCB

**Components Visible:**
- **Main SoC**: Large dark grey rectangular component (CPU/GPU)
- **WiFi/Bluetooth Module**: White rectangular component to the left of SoC
- **SD Card Slot**: White rectangular slot on the right side
- **USB Ports**: Two white micro-USB ports along top edge
  - Power input
  - Data/OTG port
- **Mini-HDMI Port**: White port for display output
- **GPIO Header**: 40-pin header along bottom edge connecting to main board
- **Mounting Holes**: Two circular holes (left and right) for standoffs

**Connections to Main Board:**
- GPIO pins (GPIO2-GPIO27)
- SPI interface (SCLK, MISO, MOSI, CS)
- I2C interface (SDA, SCLK)
- UART (TX, RX)
- USB data lines (DP, DM)
- Power (3.3V, 5V, GND)

---

### Top Left Section: RTC and GPIO Headers

**RTC Module:**
- **Component**: DS3231M+ Real-Time Clock IC (U3, SOIC-16 package)
- **Battery Holder**: White rectangular component labeled "RTC Cell CR1225"
  - Holds CR1225 coin cell for backup power
  - Ensures timekeeping during power loss
- **Supporting Components**:
  - **R3, R4, R6, R7**: 4.7KΩ pull-up resistors (I2C bus)
  - **C1**: 1µF capacitor
  - **C2**: 100nF capacitor
  - **CR1**: 32.768kHz crystal (MY-1225-01-J)

**GPIO Headers:**
- **Pin Labels** (from left to right):
  - GPIO_26
  - GPIO_13
  - GPIO_6
  - GPIO_5
  - SPI_SCLK (SPI Clock)
  - SPI_MISO (SPI Master In Slave Out)
  - SPI_MOSI (SPI Master Out Slave In)
  - SPI_CS (SPI Chip Select)
  - I2C_SCLK (I2C Clock)
  - I2C_SDA (I2C Data)

**Power Connections:**
- **Screw Terminal**: "+" symbol at very top left
- **Pi3V3**: 3.3V power rail
- **GND**: Ground connections

---

### Top Right Section: BearWave Branding and Power/USB Headers

**BearWave Logo:**
- **Design**: White logo featuring:
  - Bear sitting on small island
  - Two palm trees
  - Three white arcs above bear's head (radio waves)
- **Text**: "BearWave" in bold white sans-serif font
- **Location**: Prominently displayed in upper right quadrant

**Power/USB Headers:**
- **Header Set 1** (above logo):
  - Pi3V3 (3.3V power)
  - USB_DP (USB Data Positive)
  - USB_DM (USB Data Minus)
  - GND (Ground)
  
- **Header Set 2** (to the right):
  - Pi3V3 (3.3V power)
  - GND (Ground)

**Screw Terminal:**
- **Location**: Very top right
- **Label**: "+" symbol
- **Function**: Additional power connection point

---

### Middle Section: Power Regulation and Fuses

**Boost Converters:**
- **Inductors**: Four large dark blue circular inductors
  - Each labeled "330" (330µH)
  - Part of boost converter circuits
  - Energy storage for voltage conversion
  
- **ICs**: Four black integrated circuits
  - Two labeled "XL6019E1" (boost converter controllers)
  - **U6**: 5V boost converter
  - **U7**: 12V boost converter
  - High-efficiency switching regulators

**Capacitors:**
- **Electrolytic Capacitors**: White cylinders with black tops
  - Labeled "220 35V VT" (220µF, 35V rating)
  - Power filtering and energy storage
  - Smooth output voltage

**Fuses:**
- **Input Fuse** (F2, left side):
  - Black rectangular component with metal clips
  - Protects against overcurrent on battery input
  - 5A rating (3557-2 type)
  
- **Output Fuse** (F1, right side):
  - Black rectangular component with metal clips
  - Protects 12V output circuit
  - Prevents damage from short circuits

**Indicators and Controls:**
- **LED1**: "5V On" indicator
  - Green LED (HL-PC-2012U97GC-L)
  - Shows 5V power status
  - Current limiting resistor R5 (910Ω)
  
- **LED2**: "12V On" indicator
  - Green LED
  - Shows 12V power status
  - Current limiting resistor R14 (3.6KΩ)
  
- **Jumpers**:
  - "LED En": Enable/disable LED indicators
  - Power control jumpers

**Screw Terminals:**
- **IN+**: Positive input terminal
- **IN-**: Negative input terminal (ground)
- **OUT+**: Positive output terminal
- **OUT-**: Negative output terminal (ground)

**Supporting Components:**
- **D1**: Protection diode (MMBD1205)
- **C3**: 100nF capacitor (filtering)
- **R5, R8**: Current limiting resistors
- **R13**: 100KΩ pull-down resistor for power enable

---

### Bottom Left Section: Display and Battery Connection

**Display Module:**
- **Type**: Large white rectangular module
- **Screen**: Black display area (likely OLED or LCD)
- **Interface**: USB-C port on left side
- **Function**: System status display and data visualization
- **Mounting**: Secured to main board

**Screw Terminal Blocks:**
- **TRAP2/TRAP1**: Blue terminal blocks
  - Connections for external trap sensors
  - Two independent trap monitoring channels
  - Pull-up resistors R9, R10 (47KΩ) for switch inputs

- **Battery Connection**: Blue terminal block
  - Labeled "Battery Connection" (text may be truncated)
  - **+** terminal: Positive battery connection
  - **-** terminal: Negative battery connection (ground)
  - Main power input for entire system

---

### Bottom Right Section: Radio/ATU Connections

**Screw Terminal Block:**
- **RADIO**: Radio module connections
  - **+** terminal: Positive power (12V)
  - **-** terminal: Ground
  
- **ATU**: Antenna Tuning Unit connections
  - **+** terminal: Positive power (12V)
  - **-** terminal: Ground
  - Enables automatic antenna matching for NVIS operation

**Indicators:**
- **LED**: "12V On" indicator
  - Shows 12V power status for radio systems
  
- **Jumper**: "LED En"
  - Enable/disable LED indicator

---

## Power Flow and Distribution

### Input Path:
1. **Battery Connection** (bottom left) → Main battery input
2. **Input Fuse** (F2) → Overcurrent protection
3. **Reverse Polarity Protection** (U4, LTC4358CFE) → Prevents damage from reversed battery
4. **M_BAT_OUT** → Protected battery voltage

### Power Rails:
1. **3.3V Rail**:
   - Powers: RTC, GPS, ESP32, low-power components
   - Derived from main battery via regulator

2. **5V Rail** (Boost Converter U6):
   - Powers: Raspberry Pi Zero 2 W
   - Powers: USB peripherals
   - Inductor: 330µH
   - Output capacitor: 220µF 35V
   - LED indicator: LED1

3. **12V Rail** (Boost Converter U7):
   - Powers: Radio module
   - Powers: ATU (Antenna Tuning Unit)
   - Inductor: 330µH
   - Output capacitor: 220µF 35V
   - Output fuse: F1
   - LED indicator: LED2

---

## Communication Interfaces

### I2C Bus:
- **Devices**: RTC (U3), ESP32, other I2C peripherals
- **Lines**: SDA (data), SCLK (clock)
- **Pull-ups**: R3, R4, R6, R7 (4.7KΩ)
- **Voltage**: 3.3V logic

### SPI Bus:
- **Devices**: High-speed peripherals, displays
- **Lines**: SCLK, MISO, MOSI, CS
- **Voltage**: 3.3V logic

### UART:
- **GPS UART**: GPS_TX, GPS_RX
- **Pi UART**: PIUARTTX, PIUARTRX
- **Function**: Serial communication for GPS and debugging

### USB:
- **Data Lines**: USB_DP, USB_DM
- **Function**: Data transfer, device communication
- **Power**: 5V from boost converter

---

## Safety and Protection Features

1. **Input Fuse** (F2): Protects against overcurrent on battery input
2. **Output Fuse** (F1): Protects 12V output circuit
3. **Reverse Polarity Protection** (U4): Ideal diode controller prevents damage
4. **Voltage Monitoring**: Battery voltage divider (R11, R12) for ADC monitoring
5. **Current Limiting**: Resistors on LED circuits and power paths

---

## Environmental Considerations

- **Operating Temperature**: Designed for tropical environments
- **Humidity**: Conformal coating compatible
- **Durability**: Professional PCB manufacturing
- **Mounting**: Standoffs for proper airflow and isolation

---

## Design Notes

- **PCB Color**: Blue (standard FR4 substrate)
- **Silkscreen**: White text and component labels
- **Finish**: Professional HASL or ENIG (gold) finish
- **Shape**: Rectangular with rounded corners
- **Mounting Holes**: For secure installation in field equipment

---

## Revision Information

- **Design Date**: 2025-11-21
- **Last Update**: 2026-01-03
- **Version**: V1.0
- **Schematic**: Schematic1
- **Board**: Board1

# BearWave Schematic Documentation

## Schematic Overview

**Title**: BearWave  
**Software**: EasyEDA  
**Creation Date**: 2025-11-21  
**Last Update**: 2026-01-03  
**Version**: V1.0  
**Schematic**: Schematic1  
**Board**: Board1  
**Page Size**: A4

---

## Functional Blocks

### 1. Heltec V3.2 ESP32 Module (Top-Left, A1-B1)

**Component**: U5.1 - WIFI_KIT_32_V3_

**Power Connections:**
- **+5V**: 5V power input
- **3V3**: 3.3V power rail
- **GND**: Ground connections

**GPIO Pins:**
- GPIO2 through GPIO27 (extensive I/O capability)

**Communication Interfaces:**
- **PIUARTTX/PIUARTRX**: UART communication with Raspberry Pi
- **RTC_SDA/RTC_SCL**: I2C connection to RTC module
- **GPS_TX/GPS_RX**: UART communication with GPS module
- **USB_DP/USB_DM**: USB data lines
- **ID_SD/ID_SC**: I2C identification lines

**Control Signals:**
- **/ENPSU**: Power supply enable (active low)
- **RTC_INT**: RTC interrupt signal
- **TRAPSWITCH2/TRAPSWITCH1**: Trap sensor inputs
- **MAINBATLVL**: Main battery voltage level (ADC input)

**Design Note**: "Ensure JTAG is disabled" - Security consideration for production deployment

---

### 2. Raspberry Pi Zero 2 W (Top-Right, A3-B6)

**Component**: U1 - RASPBERRY_PI_ZERO_2_W

**Power Connections:**
- **PI3V3**: 3.3V power rail
- **+5V**: 5V power input (from boost converter)
- **GND**: Ground connections

**GPIO Pins:**
- **GPIO2/SDA1** through **GPIO27/GPIO_GEN2**
- Extensive GPIO capability for peripherals

**Communication Interfaces:**
- **USB_DP/USB_DM**: USB data lines
- **I2C_SDA/I2C_SCLK**: I2C bus
- **SPI_MISO/SPI_MOSI/SPI_SCLK/SPI_CS**: SPI bus
- **PIUARTTX/PIUARTRX**: UART communication

**Headers (H1-H9):**
- **H1-H4**: GPIO connections
- **H5-H6**: I2C bus (SDA, SCLK)
- **H7-H9**: SPI bus (MISO, MOSI, SCLK, CS)
- **Power**: Pi3V3 and GND connections

**Pull-up Resistors:**
- **R1, R2**: 4.7KΩ pull-up resistors
  - Connected to PI3V3
  - On I2C lines (SDA, SCLK)
  - Standard I2C bus termination

---

### 3. Fused Main Battery Input and Reverse Polarity Protection (Middle-Left, B1-C2)

**Input Protection Circuit:**

**Fuse (F2):**
- **Type**: 3557-2 fuse holder
- **Location**: Between M_BAT_IN and protection circuit
- **Function**: Overcurrent protection (5A rating)

**Ideal Diode Controller (U4):**
- **Part**: LTC4358CFE#PBF (ADI)
- **Package**: HTSSOP-16
- **Function**: Reverse polarity protection
- **Input**: M_BAT_IN (after fuse)
- **Output**: M_BAT_OUT (protected battery voltage)
- **Max Current**: 5A continuous

**Supporting Components:**
- **D1**: MMBD1205 diode (protection)
- **R8**: 100Ω resistor (current limiting)
- **C3**: 100nF capacitor (filtering)

**Design Note**: "Fused main battery input and reverse polarity protection Max continuous current 5amp"

---

### 4. GPS Module + Battery Backup (Middle-Middle, B3-C4)

**Component**: U2 - GPSModule

**Power Connections:**
- **SWITCHED3V3**: Switched 3.3V power (for power management)
- **GND**: Ground
- **3V3**: Continuous 3.3V power
- **RESET**: Reset signal

**Communication:**
- **Tx**: GPS transmit (connected to GPS_TX)
- **Rx**: GPS receive (connected to GPS_RX)
- **WakeUp**: Wake-up signal for power management

**Battery Backup:**
- **Bat1**: MS621FE_FL11E_1 battery
- **Connection**: Via CN1 connector
- **Function**: Maintains GPS memory for hot-start capability
- **Benefit**: Faster GPS lock times after power cycles

---

### 5. RTC (Real-Time Clock) (Middle-Right, B4-C6)

**Component**: U3 - DS3231M+ (ADI/MAXIM)

**Power Connections:**
- **3V3**: 3.3V power rail
- **VCC**: Primary power supply
- **VBAT**: Battery backup (connected to RTCBAT)

**Timing:**
- **CR1**: 32.768kHz crystal (MY-1225-01-J)
- **Function**: Precise timekeeping reference
- **Accuracy**: ±2ppm from -40°C to +85°C

**Communication:**
- **SCL**: I2C clock (connected to RTC_SCL)
- **SDA**: I2C data (connected to RTC_SDA)
- **Interface**: Standard I2C protocol

**Interrupt:**
- **INT#/SQW**: Interrupt/square wave output
- **Connected to**: RTC_INT
- **Function**: Wake-up signal, periodic interrupts

**Supporting Components:**
- **C1**: 1µF capacitor (power filtering)
- **C2**: 100nF capacitor (decoupling)
- **R3, R4, R6, R7**: 4.7KΩ pull-up resistors (I2C bus)
- **TP1**: Test point for debugging

**Battery Backup:**
- **RTCBAT**: CR1225 coin cell connection
- **Function**: Maintains time during power loss

---

### 6. Trap Switch Inputs (Bottom-Left, D1-E1)

**Input Channels:**
- **TRAPSWITCH2**: Second trap sensor input
- **TRAPSWITCH1**: First trap sensor input

**Pull-up Resistors:**
- **R9**: 4.7KΩ pull-up to 3V3 (TRAPSWITCH2)
- **R10**: 4.7KΩ pull-up to 3V3 (TRAPSWITCH1)

**Connectors:**
- Two 2-pin connectors for external trap sensors
- Active-high logic (pulled high, goes low when triggered)

**Function**: Monitor wildlife trap status remotely

---

### 7. 5V and 12V Buck-Boost Modules (Bottom-Middle-Left, D2-E3)

**5V Boost Converter (U6):**
- **Module**: XL6019 Module
- **Input**: M_BAT_OUT (protected battery voltage)
- **Output**: +5V
- **Function**: Powers Raspberry Pi Zero 2 W and USB peripherals
- **Inductor**: 330µH (external, not in schematic detail)
- **Output Capacitor**: 220µF 35V (filtering)

**Supporting Components:**
- **R5**: 910Ω current limiting resistor
- **LK1**: LED enable jumper
- **LED1**: Power status indicator (5V On)

**12V Boost Converter (U7):**
- **Module**: XL6019 Module
- **Input**: M_BAT_OUT (protected battery voltage)
- **Output**: +12V
- **Function**: Powers radio module and ATU
- **Inductor**: 330µH (external)
- **Output Capacitor**: 220µF 35V (filtering)

**Output Protection:**
- **F1**: 3557-2 fuse on +12V output
- **Function**: Protects radio/ATU circuits from overcurrent

**Supporting Components:**
- **R14**: 3.6KΩ current limiting resistor
- **LK2**: LED enable jumper
- **LED2**: Power status indicator (12V On)

**Power Enable:**
- **/ENPSU**: Power supply enable signal (active low)
- **R13**: 100KΩ pull-down resistor
- **Function**: Allows software control of power supplies

---

### 8. Battery Voltage ADC Divider (Bottom-Middle-Right, D3-E4)

**Voltage Divider Circuit:**
- **R12**: 1MΩ resistor (upper leg)
- **R11**: 250KΩ resistor (lower leg)
- **Input**: M_BAT_OUT (battery voltage)
- **Output**: MAINBATLVL (ADC input to ESP32)

**Calculation:**
- **Divider Ratio**: R11/(R11+R12) = 250K/(250K+1M) = 0.2
- **ADC Range**: 0-3.3V (typical ESP32 ADC)
- **Battery Range**: 0-16.5V (theoretical, practical range depends on battery)

**Supporting Component:**
- **C4**: 100nF capacitor (filtering, reduces noise)

**Function**: Monitor battery voltage for power management and low-battery warnings

---

## Power Distribution Summary

### Input:
- **M_BAT_IN** → Fuse (F2) → Reverse Protection (U4) → **M_BAT_OUT**

### Output Rails:
1. **3.3V**: Direct regulation from M_BAT_OUT
   - Powers: RTC, GPS, ESP32, low-power components

2. **5V**: Boost converter (U6) from M_BAT_OUT
   - Powers: Raspberry Pi Zero 2 W, USB peripherals
   - Indicator: LED1

3. **12V**: Boost converter (U7) from M_BAT_OUT
   - Powers: Radio module, ATU
   - Protected by: Fuse (F1)
   - Indicator: LED2

---

## Communication Bus Summary

### I2C Bus:
- **Devices**: RTC (U3), ESP32, Raspberry Pi
- **Lines**: SDA, SCLK
- **Pull-ups**: R1, R2, R3, R4, R6, R7 (4.7KΩ)
- **Voltage**: 3.3V

### SPI Bus:
- **Devices**: High-speed peripherals
- **Lines**: SCLK, MISO, MOSI, CS
- **Voltage**: 3.3V

### UART:
- **GPS UART**: GPS_TX, GPS_RX (ESP32 ↔ GPS)
- **Pi UART**: PIUARTTX, PIUARTRX (ESP32 ↔ Raspberry Pi)

---

## Design Considerations

1. **Power Efficiency**: Boost converters for optimal battery usage
2. **Protection**: Fuses and reverse polarity protection
3. **Reliability**: Battery backup for RTC and GPS
4. **Monitoring**: Battery voltage and trap status
5. **Flexibility**: Multiple communication interfaces
6. **Field Deployment**: Designed for harsh tropical environments

---

## Revision History

- **2026-01-03**: Updated schematic (V1.0)
- **2025-11-21**: Initial schematic creation

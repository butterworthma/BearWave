# BearWave Board Assembly Guide

## Overview

This guide provides step-by-step instructions for assembling the BearWave hardware platform. Follow these instructions carefully to ensure proper functionality and reliability.

---

## Prerequisites

### Tools Required:
- Soldering iron (temperature controlled, 350-400°C)
- Solder (lead-free recommended, 0.5-0.8mm diameter)
- Flux (rosin-based)
- Desoldering braid/wick
- Tweezers (ESD-safe)
- Multimeter
- Oscilloscope (optional, for testing)
- Hot air rework station (optional, for SMD components)

### Components:
- All components from BOM (see [BOM Documentation](BOM_Board1_Schematic1_2026-01-05.md))
- Raspberry Pi Zero 2 W
- Heltec V3.2 ESP32 Module
- GPS Module with battery
- Display Module
- XL6019E1 Boost Converter Modules (x2)
- Inductors (330µH, x4)
- Electrolytic capacitors (220µF 35V, x4)

---

## Assembly Order

### Step 1: Prepare the PCB

1. **Inspect PCB**:
   - Check for any manufacturing defects
   - Verify all pads and vias are properly plated
   - Check silkscreen alignment

2. **Clean PCB**:
   - Use isopropyl alcohol (99%+) to clean
   - Remove any flux residue or contamination
   - Allow to dry completely

---

### Step 2: Solder Passive Components (Bottom Side First)

**Resistors (R3-R14):**
1. Start with smallest components (0805 package)
2. Apply flux to pad
3. Place resistor with tweezers
4. Solder one pad, then the other
5. Verify resistance with multimeter

**Capacitors (C1-C4):**
1. Solder ceramic capacitors (0805 package)
2. Note: C1 is 1µF, C2-C4 are 100nF
3. Verify orientation (ceramic caps are non-polarized)

**Order**: Solder all 0805 components first, then move to larger components.

---

### Step 3: Solder Integrated Circuits

**RTC Module (U3 - DS3231M+):**
1. **Package**: SOIC-16
2. **Orientation**: Check pin 1 marking (usually dot or notch)
3. **Method**: 
   - Apply flux
   - Align IC carefully
   - Solder one corner pin first
   - Check alignment
   - Solder remaining pins
   - Use desoldering braid to remove bridges if needed
4. **Test**: Verify I2C communication after soldering

**Ideal Diode Controller (U4 - LTC4358CFE#PBF):**
1. **Package**: HTSSOP-16 (fine pitch)
2. **Orientation**: Critical - verify pin 1 location
3. **Method**: 
   - Use fine tip soldering iron or hot air
   - Apply flux generously
   - Carefully align IC
   - Solder with care (fine pitch requires precision)
4. **Test**: Verify continuity after soldering

---

### Step 4: Solder Power Components

**Fuses (F1, F2):**
1. **Type**: 3557-2 fuse holders
2. **Installation**: 
   - Insert fuse holders
   - Solder from top side
   - Ensure secure mechanical connection
3. **Note**: Do not insert fuses until final testing

**Inductors:**
1. **Value**: 330µH (x4)
2. **Installation**: 
   - Solder to boost converter areas
   - Ensure good thermal connection
   - Verify no shorts to adjacent pads

**Electrolytic Capacitors:**
1. **Value**: 220µF 35V (x4)
2. **Orientation**: **CRITICAL** - negative terminal marked
3. **Installation**:
   - Verify polarity before soldering
   - Solder positive terminal first
   - Ensure proper clearance from other components

---

### Step 5: Install Connectors and Headers

**Screw Terminals (ST1-ST5):**
1. **Type**: KF301-5.0-2P (5mm pitch)
2. **Installation**:
   - Insert from top side
   - Solder from bottom
   - Ensure terminals are straight and secure
3. **Labels**: Verify correct placement per schematic

**GPIO Headers:**
1. **Installation**: 
   - Insert male pin headers
   - Solder from bottom
   - Ensure pins are straight and perpendicular
2. **Verification**: Check pin spacing matches Raspberry Pi header

**Test Points (Pogo1, Pogo2):**
1. **Type**: SMD test points
2. **Installation**: Solder with hot air or fine tip iron
3. **Function**: For debugging and testing

---

### Step 6: Install LEDs and Diodes

**LEDs (LED1, LED2):**
1. **Type**: HL-PC-2012U97GC-L (0805 package)
2. **Orientation**: **CRITICAL** - anode/cathode must be correct
3. **Installation**:
   - Verify polarity (usually marked on package)
   - Solder with correct orientation
   - Test with multimeter (diode mode)

**Diode (D1):**
1. **Type**: MMBD1205 (SOT-23-3)
2. **Orientation**: Check marking on package
3. **Installation**: Solder with correct orientation

---

### Step 7: Install Crystal and Battery Holder

**Crystal (CR1):**
1. **Type**: 32.768kHz (MY-1225-01-J)
2. **Installation**: 
   - Solder carefully (crystals are fragile)
   - Ensure good connection
   - Avoid excessive heat

**RTC Battery Holder:**
1. **Type**: CR1225 coin cell holder
2. **Installation**: 
   - Solder from bottom
   - Ensure secure mechanical connection
3. **Note**: Do not insert battery until RTC is tested

---

### Step 8: Install Modules

**Raspberry Pi Zero 2 W:**
1. **Mounting**: Use standoffs (supplied separately)
2. **Installation**:
   - Align GPIO header with board connector
   - Secure with standoffs
   - Ensure proper alignment
   - Connect GPIO header (40-pin)
3. **Verification**: Check all pins make contact

**Heltec V3.2 ESP32 Module:**
1. **Connection**: Via headers or direct connection
2. **Installation**: 
   - Align pins carefully
   - Secure connection
   - Verify UART and I2C connections

**GPS Module:**
1. **Installation**: 
   - Connect to designated headers
   - Verify UART connections (GPS_TX, GPS_RX)
   - Install backup battery if required

**Boost Converter Modules (U6, U7):**
1. **Installation**: 
   - Mount XL6019E1 modules
   - Connect to inductor pads
   - Verify input/output connections
2. **Testing**: Test output voltages before full assembly

**Display Module:**
1. **Installation**: 
   - Connect USB-C interface
   - Secure mounting
   - Verify connections

---

### Step 9: Final Assembly

1. **Insert Fuses**:
   - F2: Input fuse (5A)
   - F1: Output fuse (12V circuit)
   - Verify fuse ratings

2. **Insert Batteries**:
   - RTC: CR1225 coin cell
   - GPS: Backup battery (if required)

3. **Final Inspection**:
   - Check all solder joints
   - Verify component orientation
   - Check for shorts (use multimeter)
   - Verify no loose components

---

## Testing Procedure

### Pre-Power Tests:

1. **Continuity Check**:
   - Verify no shorts between power rails
   - Check ground connections
   - Verify signal paths

2. **Resistance Check**:
   - Measure power rail resistance (should not be near zero)
   - Verify pull-up resistors (4.7KΩ, etc.)

### Power-On Tests:

1. **Power Rails** (with multimeter):
   - 3.3V rail: Should read 3.3V ±5%
   - 5V rail: Should read 5.0V ±5%
   - 12V rail: Should read 12.0V ±5%

2. **Current Draw**:
   - Measure input current (should be reasonable)
   - Check for excessive current (indicates problem)

3. **LED Indicators**:
   - LED1: Should indicate 5V power
   - LED2: Should indicate 12V power

4. **Communication Tests**:
   - I2C: Verify RTC communication
   - UART: Test GPS communication
   - SPI: Test if applicable

5. **Module Tests**:
   - Raspberry Pi: Boot and verify operation
   - ESP32: Verify WiFi/Bluetooth
   - GPS: Verify lock and data
   - RTC: Verify timekeeping

---

## Troubleshooting

### Common Issues:

1. **No Power**:
   - Check fuse (F2)
   - Verify battery connection
   - Check reverse polarity protection

2. **Incorrect Voltages**:
   - Verify boost converter connections
   - Check inductor connections
   - Verify feedback resistors

3. **Communication Failures**:
   - Check I2C pull-up resistors
   - Verify UART connections
   - Check power to modules

4. **RTC Not Working**:
   - Verify battery installed
   - Check I2C connections
   - Verify crystal connection

5. **LEDs Not Working**:
   - Check LED orientation
   - Verify current limiting resistors
   - Check enable jumpers

---

## Safety Considerations

1. **ESD Protection**: Use ESD-safe workspace
2. **Temperature**: Avoid excessive soldering iron heat
3. **Ventilation**: Ensure good ventilation when soldering
4. **Power**: Never apply power during assembly
5. **Testing**: Test with current-limited power supply first

---

## Post-Assembly

1. **Conformal Coating** (optional):
   - Apply for field deployment
   - Protects against humidity
   - Follow manufacturer instructions

2. **Documentation**:
   - Record serial numbers
   - Note any modifications
   - Document test results

3. **Calibration** (if required):
   - RTC time accuracy
   - GPS performance
   - Power consumption

---

## Revision History

- **2026-01-05**: Initial assembly guide (V1.0)

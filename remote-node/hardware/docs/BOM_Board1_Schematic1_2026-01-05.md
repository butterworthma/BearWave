# Bill of Materials (BOM)
## Board1 - Schematic1
**Date:** 2026-01-05  
**Version:** V1.0  
**Schematic:** Schematic1  
**Board:** Board1

---

## Complete Component List

| No. | Qty | Comment | Designator | Footprint | Value | Manufacturer Part | Manufacturer | Supplier Part | Supplier |
|-----|-----|---------|------------|-----------|-------|-------------------|--------------|---------------|----------|
| 1 | 1 | 1uF | C1 | C0805 | 1uF | - | YAGEO | - | LCSC |
| 2 | 3 | 100nF | C2, C3, C4 | C0805 | 100nF | - | YAGEO | - | LCSC |
| 3 | 1 | Crystal | CR1 | BAT-SMD_MY-1225-01-J | - | MY-1225-01-J | MYOUNG | - | LCSC |
| 4 | 1 | Diode | D1 | SOT-23-3_L3.0-W1.7-P0.95-LS2.9-BR | - | MMBD1205 | onsemi | - | LCSC |
| 5 | 2 | Fuse | F1, F2 | FUSE-TH_4P-L19.8-W6.7_3557-2 | - | 3557-2 | Keystone | - | LCSC |
| 6 | 2 | LED | LED1, LED2 | LED0805-RD_GREEN | - | HL-PC-2012U97GC-L | HONGLITRONIC | - | LCSC |
| 7 | 2 | Test Point | Pogo1, Pogo2 | TESTPOINT-SMD_KH-PG203505-DZ | - | KH-PG203505-DZ | kinghelm | - | LCSC |
| 8 | 4 | 4.7KΩ Resistor | R3, R4, R6, R7 | R0805 | 4.7KΩ | - | YAGEO | - | LCSC |
| 9 | 1 | 910Ω Resistor | R5 | R0805 | 910Ω | - | YAGEO | - | LCSC |
| 10 | 1 | 100Ω Resistor | R8 | R0805 | 100Ω | - | YAGEO | - | LCSC |
| 11 | 2 | 47KΩ Resistor | R9, R10 | R0805 | 47KΩ | - | YAGEO | - | LCSC |
| 12 | 1 | 250KΩ Resistor | R11 | R0805 | 250KΩ | - | Viking | - | LCSC |
| 13 | 1 | 1MΩ Resistor | R12 | R0805 | 1MΩ | - | YAGEO | - | LCSC |
| 14 | 1 | 100KΩ Resistor | R13 | R0805_NEW | 100KΩ | - | YAGEO | - | LCSC |
| 15 | 1 | 3.6KΩ Resistor | R14 | R0805 | 3.6KΩ | - | YAGEO | - | LCSC |
| 16 | 5 | Connector | ST1-ST5 | CONN-TH_P5.00_KF301-5.0-2P | - | KF301-5.0-2P | KEFA | - | LCSC |
| 17 | 1 | RTC IC | U3 | SOIC-16_L10.3-W7.5-P1.27-LS10.3-BL | - | DS3231M+ | ADI/MAXIM | - | LCSC |
| 18 | 1 | Ideal Diode Controller | U4 | HTSSOP-16_L5.0-W4.4-P0.65-LS6.4-BL-EP-A | - | LTC4358CFE#PBF | ADI | - | LCSC |

**Total Components:** 18 unique part numbers  
**Total Quantity:** 28 components

---

## Component Categories

### Capacitors
- **C1**: 1µF, C0805 package (YAGEO)
- **C2, C3, C4**: 100nF, C0805 package (YAGEO)

### Resistors
- **R3, R4, R6, R7**: 4.7KΩ pull-up resistors (I2C bus)
- **R5**: 910Ω current limiting resistor (5V LED)
- **R8**: 100Ω current limiting resistor
- **R9, R10**: 47KΩ pull-up resistors (trap switch inputs)
- **R11**: 250KΩ voltage divider resistor (battery monitoring)
- **R12**: 1MΩ voltage divider resistor (battery monitoring)
- **R13**: 100KΩ pull-down resistor (power enable)
- **R14**: 3.6KΩ current limiting resistor (12V LED)

### Integrated Circuits
- **U3**: DS3231M+ Real-Time Clock (ADI/MAXIM)
  - SOIC-16 package
  - High accuracy RTC with battery backup
  - I2C interface
  
- **U4**: LTC4358CFE#PBF Ideal Diode Controller (ADI)
  - HTSSOP-16 package
  - Reverse polarity protection
  - Max 5A continuous current

### Power Components
- **F1, F2**: 3557-2 Fuses (Keystone)
  - Input and output protection
  - 5A rating
  
- **LED1, LED2**: HL-PC-2012U97GC-L Green LEDs (HONGLITRONIC)
  - 0805 package
  - Power status indicators

### Connectors
- **ST1-ST5**: KF301-5.0-2P Screw Terminals (KEFA)
  - 5.00mm pitch
  - 2-pin connectors
  - Used for: Battery, Radio, ATU, Trap connections

### Other Components
- **CR1**: 32.768kHz Crystal (MY-1225-01-J)
  - RTC timing reference
  
- **D1**: MMBD1205 Diode (onsemi)
  - SOT-23-3 package
  - Protection diode
  
- **Pogo1, Pogo2**: Test Points (KH-PG203505-DZ)
  - SMD test points for debugging

---

## Additional Modules (Not in BOM)

These components are separate modules/assemblies:

1. **Raspberry Pi Zero 2 W** - Main computing module
2. **Heltec V3.2 ESP32 Module** - WiFi/Bluetooth connectivity
3. **GPS Module** - Location and time synchronization
4. **Display Module** - Status display with USB-C interface
5. **XL6019E1 Boost Converters** (x2) - 5V and 12V power regulation
6. **Inductors** - 330µH for boost converters (x4)
7. **Electrolytic Capacitors** - 220µF 35V (power filtering)

---

## Notes

- All components sourced from LCSC
- Standard surface-mount packages (0805, SOIC, SOT-23)
- Professional-grade components for field deployment
- Designed for tropical environment operation
- Conformal coating compatible

---

## Revision History

- **2026-01-05**: Initial BOM release (V1.0)
- **2025-11-21**: Initial schematic creation

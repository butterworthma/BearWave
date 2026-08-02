# BearWave ESP32 Remote-Node Supervisor

This repository contains the ESP32/Heltec supervisor firmware for the BearWave remote node. The ESP32 acts as the hardware authority for the node: it controls the Raspberry Pi and radio power rails, maintains GPS/RTC time, exposes node state to the Pi over UART, monitors alarm inputs, accepts shutdown signalling from the Pi, and enters deep sleep between wake cycles.

## Current version

File:

```text
BearWave_ESP32_Remote_Node_Supervisor.ino
```

This version targets BearWave PCB V2, where the 5 V Raspberry Pi rail and 12 V radio/ATU rail are controlled separately through external flip-flop latch circuits.

## Hardware model

BearWave PCB V2 separates the high-power rails:

- 5 V rail for the Raspberry Pi Zero 2 W
- 12 V rail for the QDX/radio/ATU path

Each rail has:

- an active-low pulse input driven briefly by the ESP32
- a rail-present status input read by the ESP32

On the current PCB V2 bench unit, `5VOK` is active-high and `12VOK` is active-low. The firmware therefore uses `INPUT_PULLDOWN` for `5VOK`, `INPUT_PULLUP` for `12VOK`, and per-rail active-level constants rather than assuming both feedback lines use the same polarity.

The ESP32 itself must remain powered from an always-on supply, for example the Heltec external battery path or an independent always-on regulator. The latched 5 V and 12 V rails should only control the higher-power Pi and radio/ATU subsystems.

## Why GPIO hold is no longer used

The previous prototype held GPIO 33 during ESP32 deep sleep because it directly controlled a single active-low rail enable. PCB V2 moves this responsibility into external latch hardware. The ESP32 now sends a momentary pulse, reads back the rail state, and then leaves the pulse pin high-impedance. The latch, not the ESP32 GPIO drive state, preserves power state during deep sleep.

## Normal operating sequence

1. ESP32 wakes.
2. ESP32 configures latch pulse pins as high-impedance idle inputs.
3. ESP32 shows reset/wake diagnostics on the OLED.
4. ESP32 turns on the 5 V rail, then the 12 V rail, using the latch pulse inputs and status feedback.
5. ESP32 starts the RTC, GPS, OLED and Pi UART services.
6. ESP32 attempts to refresh RTC time from GPS.
7. Raspberry Pi boots and asks the ESP32 for time and state over UART.
8. Raspberry Pi runs JS8Call and the BearWave remote-node Python application.
9. Raspberry Pi sends the BearWave heartbeat or alarm message.
10. Raspberry Pi waits for the control-node acknowledgement.
11. Raspberry Pi sends `EVENT_ACKED,<type>` if a critical event was delivered.
12. Raspberry Pi sends `SHUTDOWN` to the ESP32.
13. ESP32 replies `OK,SHUTDOWN_RECEIVED`.
14. ESP32 waits 50 seconds to allow Linux shutdown.
15. ESP32 turns off the 12 V rail, then the 5 V rail, using the latch pulse inputs and status feedback.
16. ESP32 isolates the Pi UART pins.
17. ESP32 returns latch pulse pins to high impedance and enters deep sleep.
18. ESP32 wakes by timer and repeats.

## UART command interface

The Raspberry Pi communicates with the ESP32 over a line-based UART protocol.

### `PING`

Response:

```text
PONG
```

### `STATUS?`

Response:

```text
OK,BEARWAVE_RTC_GPS_EVENTS
```

### `TIME?`

Responses:

```text
TIME,YYYY-MM-DDTHH:MM:SSZ
ERR,RTC_READ
ERR,RTC_INVALID
```

### `BAT?`

Response:

```text
BAT,<voltage>,<percent>
```

### `COORD?`

Responses:

```text
COORD,<lat>,<lon>
COORD,INVALID
```

### `EVENT?`

Responses:

```text
EVENT,NONE
EVENT,TRAP
EVENT,LOW_BAT
EVENT,TRAP+LOW_BAT
```

### `EVENT_RAW?`

Response:

```text
RAW,<trap1>,<trap2>,<trapLatched>,<trapReported>,<lowBatActive>,<lowBatReported>
```

### `EVENT_ACKED,TRAP`

Response:

```text
OK,EVENT_ACKED,TRAP
```

### `EVENT_ACKED,LOW_BAT`

Response:

```text
OK,EVENT_ACKED,LOW_BAT
```

### `EVENT_ACKED,ALL`

Response:

```text
OK,EVENT_ACKED,ALL
```

### `SHUTDOWN`

Response:

```text
OK,SHUTDOWN_RECEIVED
```

After this command, the ESP32 starts the delayed power-cut and deep-sleep sequence.

## OLED diagnostics

USB serial should not be connected during full power testing because USB 5 V can back-feed the Raspberry Pi. The OLED is therefore used as the primary diagnostic console.

At boot, the OLED shows:

```text
Last stage:<stage>
Boot:<count>
Reset:<reason>
Wake:<reason>
Rail:<5ON/5OFF>/<12ON/12OFF>
```

Healthy sleep/wake behaviour should show:

```text
Reset:DEEPSLEEP
Wake:TIMER
```

If the ESP32 is losing power, the display is more likely to show:

```text
Reset:POWERON
Wake:UNDEFINED
```

If the ESP32 is browning out, it may show:

```text
Reset:BROWNOUT
Wake:UNDEFINED
```

## Shutdown stage values

The sketch stores the last shutdown stage in RTC memory.

```text
0 = Pi sent SHUTDOWN and ESP32 accepted it
1 = ESP32 started rail cut sequence
2 = 12 V and 5 V rails switched off
3 = preparing for sleep
4 = Pi UART pins isolated
5 = deep sleep setup started
6 = latch pulse pins returned to high-impedance idle before sleep
99 = code continued after esp_deep_sleep_start(), which should not happen
```

A successful diagnostic run should usually show:

```text
Last stage:6
Reset:DEEPSLEEP
Wake:TIMER
Rail:5OFF/12OFF
```

## Timing settings

The shutdown delay is currently:

```cpp
const unsigned long PI_POWER_CUT_DELAY_MS = 50000UL;
```

This gives the Raspberry Pi 50 seconds to halt cleanly before power is removed.

The current diagnostic wake interval is:

```cpp
const uint64_t WAKE_INTERVAL_US = 60ULL * 1000000ULL;
```

For a 15-minute test cycle, change it to:

```cpp
const uint64_t WAKE_INTERVAL_US = 15ULL * 60ULL * 1000000ULL;
```

## Pin summary

| Function | GPIO |
|---|---:|
| 5 V latch pulse, active low | 17 |
| 12 V latch pulse, active low | 45 |
| 5 V rail-present status, active high | 7 |
| 12 V rail-present status, active low | 6 |
| Pi UART RX from Pi TX | 34 |
| Pi UART TX to Pi RX | 33 |
| RTC SDA | 2 |
| RTC SCL | 3 |
| RTC interrupt | 47 |
| GPS RX | 4 |
| GPS TX | 5 |
| GPS/VEXT control | 36 |
| Battery ADC | 20 |
| Trap input 1 | 48 |
| Trap input 2 | 26 |

## Integration with BearWave Pi software

The Raspberry Pi should:

1. Boot when the ESP32 confirms the 5 V latch is on.
2. Read ESP32 time using `TIME?`.
3. Set Linux UTC time.
4. Start JS8Call.
5. Set JS8Call to 7.078 MHz.
6. Run the BearWave remote-node Python application.
7. Send `EVENT_ACKED,<type>` after successful critical alarm delivery.
8. Send `SHUTDOWN` before halting.

The ESP32 then turns off the 12 V and 5 V latches and sleeps.

## Notes for deployment

- Keep the ESP32 on an always-on supply.
- The 5 V and 12 V rails should be switched through the PCB V2 latch pulse inputs only.
- Avoid USB serial during full power testing because USB can back-feed the Pi.
- Use the OLED diagnostic values to confirm reset/wake cause.
- Once the behaviour is proven, set the wake interval to the required field-test interval.

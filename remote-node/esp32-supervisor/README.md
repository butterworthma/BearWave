# BearWave ESP32 Remote-Node Supervisor

This repository contains the ESP32/Heltec supervisor firmware for the BearWave remote node. The ESP32 acts as the hardware authority for the node: it controls the Raspberry Pi and radio power rail, maintains GPS/RTC time, exposes node state to the Pi over UART, monitors alarm inputs, accepts shutdown signalling from the Pi, and enters deep sleep between wake cycles.

## Current version

File:

```text
BearWave_ESP32_Remote_Node_Supervisor.ino
```

This version includes the active-low GPIO 33 power-control fix and the deep-sleep GPIO hold fix.

## Hardware model

GPIO 33 controls the combined switched rail for:

- Raspberry Pi
- radio

The enable line is active-low:

```text
GPIO 33 LOW  = Pi/radio rail ON
GPIO 33 HIGH = Pi/radio rail OFF
```

The ESP32 itself must remain powered from an always-on supply, for example the Heltec external battery path or an independent always-on regulator. The GPIO 33 switched rail should only control the Raspberry Pi and radio.

## Why GPIO hold is required

The Pi/radio enable line is active-low. Before deep sleep, the ESP32 drives GPIO 33 HIGH to turn the rail off. During ESP32 deep sleep, normal GPIO output drive may relax unless hold is enabled. If GPIO 33 floats or falls low during sleep, the Pi/radio rail can turn back on even though the ESP32 is asleep.

The sketch therefore does this before deep sleep:

```cpp
pinMode(PI_RADIO_POWER_EN_PIN, OUTPUT);
digitalWrite(PI_RADIO_POWER_EN_PIN, HIGH);
gpio_hold_en((gpio_num_t)PI_RADIO_POWER_EN_PIN);
gpio_deep_sleep_hold_en();
```

At the next boot, the sketch releases the hold before controlling GPIO 33 again:

```cpp
gpio_deep_sleep_hold_dis();
gpio_hold_dis((gpio_num_t)PI_RADIO_POWER_EN_PIN);
```

## Normal operating sequence

1. ESP32 wakes.
2. ESP32 releases any previous GPIO hold.
3. ESP32 shows reset/wake diagnostics on the OLED.
4. ESP32 powers the Pi/radio rail by driving GPIO 33 LOW.
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
15. ESP32 turns GPIO 33 HIGH, disabling the Pi/radio rail.
16. ESP32 isolates the Pi UART pins.
17. ESP32 holds GPIO 33 HIGH and enters deep sleep.
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
Rail:<ON/OFF>
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
2 = Pi/radio rail switched off
3 = preparing for sleep
4 = Pi UART pins isolated
5 = deep sleep setup started
6 = GPIO 33 set HIGH and held for sleep
99 = code continued after esp_deep_sleep_start(), which should not happen
```

A successful diagnostic run should usually show:

```text
Last stage:6
Reset:DEEPSLEEP
Wake:TIMER
Rail:OFF
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
| Pi/radio active-low enable | 33 |
| Pi UART RX | 42 |
| Pi UART TX | 41 |
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

1. Boot when GPIO 33 is driven LOW.
2. Read ESP32 time using `TIME?`.
3. Set Linux UTC time.
4. Start JS8Call.
5. Set JS8Call to 7.078 MHz.
6. Run the BearWave remote-node Python application.
7. Send `EVENT_ACKED,<type>` after successful critical alarm delivery.
8. Send `SHUTDOWN` before halting.

The ESP32 then cuts power and sleeps.

## Notes for deployment

- Keep the ESP32 on an always-on supply.
- The Pi/radio rail should be switched by GPIO 33 only.
- Avoid USB serial during full power testing because USB can back-feed the Pi.
- Use the OLED diagnostic values to confirm reset/wake cause.
- Once the behaviour is proven, set the wake interval to the required field-test interval.

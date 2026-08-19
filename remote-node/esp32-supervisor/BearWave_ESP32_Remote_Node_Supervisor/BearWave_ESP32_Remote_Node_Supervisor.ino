/*
  BearWave Heltec RTC / GPS / OLED / Pi-UART bridge
  -------------------------------------------------

  REMOTE-NODE SUPERVISOR VERSION FOR BEARWAVE PCB V2
  --------------------------------------------------

  Purpose:
    This ESP32/Heltec sketch supervises the BearWave remote node hardware.
    It powers the Raspberry Pi and radio, provides GPS/RTC/time/event state
    to the Pi over UART, accepts shutdown signalling from the Pi, cuts the
    switched power rails, and then enters deep sleep until the next wake cycle.

  Key hardware behaviour:
    BearWave PCB V2 uses flip-flop latch circuits for the high-power rails:
      - 5 V rail for the Raspberry Pi Zero 2 W
      - 12 V rail for the QDX/radio/ATU path

    The ESP32 does not hold a rail-enable level during deep sleep. Instead, it
    briefly drives the relevant ENABLE*PULSE line HIGH to emulate the latch
    push-button pulse proven on the PCB V2 bench unit, then returns the output
    LOW while idle. The external latch preserves the rail state while the ESP32
    sleeps.

    Rail status is read back using 5VOK and 12VOK so the firmware only pulses a
    latch when the measured rail state does not match the requested state.

  Diagnostic method:
    USB serial must not be connected during the full power test because USB 5 V
    can back-feed the Raspberry Pi. Therefore, the OLED is used as the primary
    diagnostic console.

  OLED diagnostics show:
    - boot count
    - reset reason
    - wake reason
    - 5 V and 12 V rail state
    - last shutdown stage

  Expected healthy wake after sleep:
    Reset: DEEPSLEEP
    Wake:  TIMER

  UART command summary for the Pi:

    PING
      -> PONG

    STATUS?
      -> OK,BEARWAVE_RTC_GPS_EVENTS

    TIME?
      -> TIME,YYYY-MM-DDTHH:MM:SSZ
      -> ERR,RTC_READ
      -> ERR,RTC_INVALID

    BAT?
      -> BAT,<voltage>,<percent>

    COORD?
      -> COORD,<lat>,<lon>
      -> COORD,INVALID

    EVENT?
      -> EVENT,NONE
      -> EVENT,TRAP
      -> EVENT,LOW_BAT
      -> EVENT,TRAP+LOW_BAT

    EVENT_RAW?
      -> RAW,<trap1>,<trap2>,<trapLatched>,<trapReported>,<lowBatActive>,<lowBatReported>

    EVENT_ACKED,TRAP
      -> OK,EVENT_ACKED,TRAP

    EVENT_ACKED,LOW_BAT
      -> OK,EVENT_ACKED,LOW_BAT

    EVENT_ACKED,ALL
      -> OK,EVENT_ACKED,ALL

    SHUTDOWN
      -> OK,SHUTDOWN_RECEIVED
      The ESP32 then waits PI_POWER_CUT_DELAY_MS, turns off the 12 V rail,
      turns off the 5 V rail, isolates the Pi UART pins, and enters deep sleep.

  Test/deployment note:
    WAKE_INTERVAL_US is currently set to 5 minutes for test. Change it back
    to 15 minutes once the behaviour is proven.
*/

#include <Wire.h>
#include <TinyGPSPlus.h>
#include "SSD1306Wire.h"
#include "pins_arduino.h"
#include "esp_sleep.h"
#include "driver/gpio.h"
#include "driver/rtc_io.h"

// ============================================================
// RTC DS3231 configuration
// ============================================================

#define RTC_SDA_PIN    40
#define RTC_SCL_PIN    39
#define RTC_INT_PIN    6
#define DS3231_ADDR    0x68

// ============================================================
// GPS configuration
// ============================================================

#define VEXT_CTRL_PIN  36
#define GPS_RX_PIN     41
#define GPS_TX_PIN     42
#define GPS_BAUD       9600

// ============================================================
// Battery measurement configuration
// ============================================================

#define BATTERY_ADC_PIN 2

#define ADC_MAX_COUNTS        4095.0f
#define ADC_REF_VOLTAGE       3.3f
#define BATTERY_DIVIDER_RATIO 5.0f

#define BATTERY_FLAT_VOLTAGE  11.0f
#define BATTERY_FULL_VOLTAGE  12.6f

#define LOW_BATTERY_ASSERT_VOLTAGE 11.30f
#define LOW_BATTERY_CLEAR_VOLTAGE  11.60f

// ============================================================
// Raspberry Pi UART configuration
// ============================================================

#define PI_UART_RX_PIN 33
#define PI_UART_TX_PIN 34
#define PI_UART_BAUD   115200

// ============================================================
// BearWave PCB V2 latch-based power control
// ============================================================

#define PSU_5V_PULSE_PIN   7
#define PSU_12V_PULSE_PIN  38
#define PSU_5V_OK_PIN      47
#define PSU_12V_OK_PIN     48
#define PSU_5V_OK_ACTIVE_LEVEL   LOW
#define PSU_12V_OK_ACTIVE_LEVEL  LOW

/*
  V2 power latch convention:
    ENABLE5VPULSE / ENABLE12VPULSE are momentary latch inputs that were
    bench-proven to toggle from a driven HIGH pulse.
    5VOK / 12VOK are rail-present status inputs. The current PCB V2 bench unit
    presents both 5VOK and 12VOK as active-low open-drain/open-collector style
    signals. The ESP32 enables internal pull-ups so OFF reads HIGH and ON reads
    LOW.

  Confirmed PCB V2 ESP32 GPIO assignments:
    PI UART RX    -> GPIO33  (ESP32 receives from Raspberry Pi TX)
    PI UART TX    -> GPIO34  (ESP32 transmits to Raspberry Pi RX)
    GPS UART RX   -> GPIO41  (ESP32 receives from GPS TX)
    GPS UART TX   -> GPIO42  (ESP32 transmits to GPS RX)
    RTC SDA       -> GPIO40
    RTC SCL       -> GPIO39
    RTC INT       -> GPIO6
    5VOK          -> GPIO47
    12VOK         -> GPIO48
    ENABLE5VPULSE -> GPIO7
    ENABLE12VPULSE-> GPIO38
    Battery ADC   -> GPIO2
    Trap switch 1 -> GPIO5
    Trap switch 2 -> GPIO4
*/
const unsigned long PSU_LATCH_PULSE_MS = 250UL;
const unsigned long PSU_LATCH_SETTLE_MS = 1000UL;
const unsigned long PI_POWER_CUT_DELAY_MS = 50000UL;
const unsigned long PI_MAX_ON_TIME_MS = 20UL * 60UL * 1000UL;

/*
  TEST SLEEP INTERVAL
  -------------------
  Current value is 5 minutes for diagnostics.

  For the 15-minute test cycle, use:
    const uint64_t WAKE_INTERVAL_US = 15ULL * 60ULL * 1000000ULL;
*/
const uint64_t WAKE_INTERVAL_US = 5ULL * 60ULL * 1000000ULL;

// ============================================================
// Trap/alarm input configuration
// ============================================================

#define TRAP_PIN_1 5
#define TRAP_PIN_2 4

const uint64_t TRAP_WAKE_MASK =
  (1ULL << TRAP_PIN_1) |
  (1ULL << TRAP_PIN_2);

// ============================================================
// General timing configuration
// ============================================================

const unsigned long DISPLAY_UPDATE_MS       = 1000UL;
const unsigned long RTC_CHECK_INTERVAL_MS   = 15000UL;
const unsigned long GPS_POWERUP_DELAY_MS    = 3000UL;
const unsigned long GPS_SYNC_TIMEOUT_MS     = 180000UL;
const unsigned long GPS_FRESH_AGE_MS        = 2000UL;
const long MAX_ALLOWED_DRIFT_SECONDS        = 1;
const unsigned long EVENT_POLL_INTERVAL_MS  = 200UL;

// ============================================================
// OLED display object
// ============================================================

SSD1306Wire display(0x3c, SDA_OLED, SCL_OLED);

// ============================================================
// Separate I2C bus for the RTC
// ============================================================

TwoWire RTCWire = TwoWire(1);

// ============================================================
// Global objects
// ============================================================

TinyGPSPlus gps;
HardwareSerial GPSSerial(1);
HardwareSerial PiSerial(2);

// ============================================================
// Runtime timing state
// ============================================================

unsigned long lastDisplayUpdate = 0;
unsigned long lastRtcCheck = 0;
unsigned long lastEventPoll = 0;
unsigned long highPowerRailsOnAt = 0;
bool highPowerRailsRequestedOn = false;

// ============================================================
// Pi UART receive buffer
// ============================================================

String piRxLine;

// ============================================================
// Event / alarm state model
// ============================================================

bool trapLatched = false;
bool trapReported = false;

bool lowBatteryActive = false;
bool lowBatteryReported = false;

bool shutdownRequested = false;
unsigned long shutdownRequestTime = 0;

// ============================================================
// Deep-sleep retained diagnostic state
// ============================================================

RTC_DATA_ATTR int bootCount = 0;
RTC_DATA_ATTR int lastShutdownStage = 0;

// ============================================================
// Forward declarations
// ============================================================

void servicePiUart();
void updateEventState();
void updateDisplay();
void serviceShutdownSequence();
void serviceHighPowerFailsafe();

// ============================================================
// Text helpers for reset/wake diagnostics
// ============================================================

String resetReasonText() {
  esp_reset_reason_t reason = esp_reset_reason();

  switch (reason) {
    case ESP_RST_POWERON:
      return "POWERON";
    case ESP_RST_EXT:
      return "EXT";
    case ESP_RST_SW:
      return "SW";
    case ESP_RST_PANIC:
      return "PANIC";
    case ESP_RST_INT_WDT:
      return "INT_WDT";
    case ESP_RST_TASK_WDT:
      return "TASK_WDT";
    case ESP_RST_WDT:
      return "WDT";
    case ESP_RST_DEEPSLEEP:
      return "DEEPSLEEP";
    case ESP_RST_BROWNOUT:
      return "BROWNOUT";
    default:
      return "UNKNOWN";
  }
}

String wakeReasonText() {
  esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();

  switch (cause) {
    case ESP_SLEEP_WAKEUP_UNDEFINED:
      return "UNDEFINED";
    case ESP_SLEEP_WAKEUP_TIMER:
      return "TIMER";
    case ESP_SLEEP_WAKEUP_EXT0:
      return "EXT0";
    case ESP_SLEEP_WAKEUP_EXT1:
      return "EXT1";
    case ESP_SLEEP_WAKEUP_GPIO:
      return "GPIO";
    case ESP_SLEEP_WAKEUP_UART:
      return "UART";
    default:
      return "OTHER";
  }
}

String railStateText() {
  String five = digitalRead(PSU_5V_OK_PIN) == PSU_5V_OK_ACTIVE_LEVEL ? "5ON" : "5OFF";
  String twelve = digitalRead(PSU_12V_OK_PIN) == PSU_12V_OK_ACTIVE_LEVEL ? "12ON" : "12OFF";
  return five + "/" + twelve;
}

// ============================================================
// OLED diagnostic display helpers
// ============================================================

void showDiagScreen(const String &stage) {
  display.clear();
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);

  display.drawString(0, 0,  "BearWave diag");
  display.drawString(0, 10, "Boot:" + String(bootCount));
  display.drawString(0, 20, "R:" + resetReasonText());
  display.drawString(0, 30, "W:" + wakeReasonText());
  display.drawString(0, 40, "Rail:" + railStateText());
  display.drawString(0, 50, stage);

  display.display();
}

void showStage(const String &stage, unsigned long holdMs = 1000) {
  showDiagScreen(stage);
  delay(holdMs);
}

void showLastBootDetails(unsigned long holdMs = 5000) {
  display.clear();
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);

  display.drawString(0, 0,  "Last stage:" + String(lastShutdownStage));
  display.drawString(0, 12, "Boot:" + String(bootCount));
  display.drawString(0, 24, "Reset:" + resetReasonText());
  display.drawString(0, 36, "Wake:" + wakeReasonText());
  display.drawString(0, 48, "Rail:" + railStateText());

  display.display();

  delay(holdMs);
}

// ============================================================
// Heltec OLED power and reset helpers
// ============================================================

void VextON(void) {
  pinMode(Vext, OUTPUT);
  digitalWrite(Vext, LOW);
}

void VextOFF(void) {
  pinMode(Vext, OUTPUT);
  digitalWrite(Vext, HIGH);
}

void displayReset(void) {
  pinMode(RST_OLED, OUTPUT);

  digitalWrite(RST_OLED, HIGH);
  delay(1);

  digitalWrite(RST_OLED, LOW);
  delay(1);

  digitalWrite(RST_OLED, HIGH);
  delay(1);
}

// ============================================================
// BearWave PCB V2 latch-based power helpers
// ============================================================

bool rail5VOn() {
  return digitalRead(PSU_5V_OK_PIN) == PSU_5V_OK_ACTIVE_LEVEL;
}

bool rail12VOn() {
  return digitalRead(PSU_12V_OK_PIN) == PSU_12V_OK_ACTIVE_LEVEL;
}

void configurePowerLatchPinsIdle() {
  /*
    The BearWave PCB V2 latch inputs have been bench-proven to respond to a
    driven HIGH pulse from the Heltec GPIO. Keep the pulse outputs LOW when
    idle, then briefly drive HIGH to emulate the latch push.
  */
  pinMode(PSU_5V_PULSE_PIN, OUTPUT);
  pinMode(PSU_12V_PULSE_PIN, OUTPUT);
  digitalWrite(PSU_5V_PULSE_PIN, LOW);
  digitalWrite(PSU_12V_PULSE_PIN, LOW);

  pinMode(PSU_5V_OK_PIN, INPUT_PULLUP);
  pinMode(PSU_12V_OK_PIN, INPUT_PULLUP);
}

void pulseLatchHigh(uint8_t pin, const char *label) {
  Serial.print("Pulsing ");
  Serial.print(label);
  Serial.println(" latch");

  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
  delay(20);
  digitalWrite(pin, HIGH);
  delay(PSU_LATCH_PULSE_MS);
  digitalWrite(pin, LOW);
  delay(20);
}

bool ensureRailState(const char *label, uint8_t pulsePin, uint8_t okPin, bool shouldBeOn) {
  bool activeLevel = okPin == PSU_12V_OK_PIN ? PSU_12V_OK_ACTIVE_LEVEL : PSU_5V_OK_ACTIVE_LEVEL;
  bool isOn = digitalRead(okPin) == activeLevel;

  Serial.print(label);
  Serial.print(" rail currently ");
  Serial.println(isOn ? "ON" : "OFF");

  showStage(String(label) + (isOn ? " is ON" : " is OFF"), 800);

  if (isOn == shouldBeOn) {
    Serial.print(label);
    Serial.println(" rail already in requested state");
    showStage(String(label) + " already OK", 800);
    return true;
  }

  showStage(String("Pulse ") + label, 800);
  pulseLatchHigh(pulsePin, label);
  delay(PSU_LATCH_SETTLE_MS);

  bool nowOn = digitalRead(okPin) == activeLevel;

  Serial.print(label);
  Serial.print(" rail after pulse ");
  Serial.println(nowOn ? "ON" : "OFF");

  showStage(String(label) + (nowOn == shouldBeOn ? " OK" : " FAIL"), 1500);

  return nowOn == shouldBeOn;
}

void powerPiAndRadioOn() {
  /*
    Bring the Pi rail up first, then the radio rail. The Pi boot script waits
    for JS8Call/radio readiness, so a short delay between rails is sufficient
    for deterministic bench testing.
  */
  bool fiveOk = ensureRailState("5V", PSU_5V_PULSE_PIN, PSU_5V_OK_PIN, true);

  if (!fiveOk) {
    Serial.println("ERROR: 5V rail did not confirm ON; leaving 12V rail off");
    showStage("5V ON FAIL", 2500);
    return;
  }

  delay(1000);
  bool twelveOk = ensureRailState("12V", PSU_12V_PULSE_PIN, PSU_12V_OK_PIN, true);

  if (fiveOk || twelveOk) {
    highPowerRailsRequestedOn = true;
    highPowerRailsOnAt = millis();
  }

  if (!fiveOk || !twelveOk) {
    Serial.println("WARNING: requested rail ON state was not confirmed");
  }
}

bool powerPiAndRadioOff() {
  /*
    Remove radio/ATU power first, then remove the Pi rail after Linux has had
    PI_POWER_CUT_DELAY_MS to halt.
  */
  bool twelveOk = ensureRailState("12V", PSU_12V_PULSE_PIN, PSU_12V_OK_PIN, false);
  delay(1000);
  bool fiveOk = ensureRailState("5V", PSU_5V_PULSE_PIN, PSU_5V_OK_PIN, false);

  bool offOk = fiveOk && twelveOk;

  if (!offOk) {
    Serial.println("WARNING: requested rail OFF state was not confirmed");
  } else {
    highPowerRailsRequestedOn = false;
    highPowerRailsOnAt = 0;
  }

  return offOk;
}

bool normaliseRailsOffAtBoot() {
  /*
    Flip-flop latches preserve their state across ESP32 resets and sleep. During
    bench testing that can leave the 5 V or 12 V rail on before the supervisor
    starts a fresh cycle. Force both high-power rails off first so the later
    boot sequence always starts from a known state.
  */
  showStage("Check rails", 1000);

  bool twelveOffOk = ensureRailState("12V", PSU_12V_PULSE_PIN, PSU_12V_OK_PIN, false);
  delay(1000);
  bool fiveOffOk = ensureRailState("5V", PSU_5V_PULSE_PIN, PSU_5V_OK_PIN, false);

  if (twelveOffOk && fiveOffOk) {
    showStage("Rails are OFF", 1500);
    return true;
  }

  showStage("Rail off FAIL", 2500);
  Serial.println("WARNING: one or more rails failed to confirm OFF at boot");
  return false;
}

void bootRailControlTest() {
  /*
    Bench-test the latch control path on every ESP32 boot:
      1. read rail state
      2. force 12 V and 5 V off
      3. hold off for 5 seconds so the operator can confirm the rails dropped

    The rails remain OFF after this test. They are turned back ON later only
    when the supervisor is ready to wake the Pi/radio for a heartbeat or alarm
    cycle.
  */
  showStage("Rail boot test", 1500);

  normaliseRailsOffAtBoot();

  showStage("Rails OFF hold", 5000);
}

// ============================================================
// Pi UART isolation helper
// ============================================================

void isolatePiUartBeforeSleep() {
  /*
    Prevent the ESP32 UART pins from back-powering the Raspberry Pi through
    GPIO protection paths after the 5 V Pi rail is switched off.
  */
  PiSerial.end();

  pinMode(PI_UART_TX_PIN, INPUT);
  pinMode(PI_UART_RX_PIN, INPUT);
}

// ============================================================
// BCD conversion helpers
// ============================================================

uint8_t bcdToDec(uint8_t val) {
  return ((val >> 4) * 10) + (val & 0x0F);
}

uint8_t decToBcd(uint8_t val) {
  return ((val / 10) << 4) | (val % 10);
}

// ============================================================
// RTC helpers
// ============================================================

bool readDS3231Raw(uint8_t &sec, uint8_t &minu, uint8_t &hour,
                   uint8_t &dayOfWeek, uint8_t &dayOfMonth,
                   uint8_t &month, uint16_t &year) {
  RTCWire.beginTransmission(DS3231_ADDR);
  RTCWire.write(0x00);

  if (RTCWire.endTransmission(false) != 0) {
    return false;
  }

  uint8_t bytesReceived = RTCWire.requestFrom(DS3231_ADDR, (uint8_t)7);

  if (bytesReceived != 7) {
    return false;
  }

  uint8_t rawSec   = RTCWire.read();
  uint8_t rawMin   = RTCWire.read();
  uint8_t rawHour  = RTCWire.read();
  uint8_t rawDOW   = RTCWire.read();
  uint8_t rawDOM   = RTCWire.read();
  uint8_t rawMonth = RTCWire.read();
  uint8_t rawYear  = RTCWire.read();

  sec  = bcdToDec(rawSec & 0x7F);
  minu = bcdToDec(rawMin & 0x7F);

  if (rawHour & 0x40) {
    uint8_t hr = bcdToDec(rawHour & 0x1F);
    bool pm = rawHour & 0x20;

    if (pm && hr < 12) {
      hr += 12;
    }

    if (!pm && hr == 12) {
      hr = 0;
    }

    hour = hr;
  } else {
    hour = bcdToDec(rawHour & 0x3F);
  }

  dayOfWeek  = bcdToDec(rawDOW & 0x07);
  dayOfMonth = bcdToDec(rawDOM & 0x3F);
  month      = bcdToDec(rawMonth & 0x1F);
  year       = 2000 + bcdToDec(rawYear);

  return true;
}

bool writeDS3231(uint8_t sec, uint8_t minu, uint8_t hour,
                 uint8_t dayOfWeek, uint8_t dayOfMonth,
                 uint8_t month, uint16_t year) {
  RTCWire.beginTransmission(DS3231_ADDR);

  RTCWire.write(0x00);
  RTCWire.write(decToBcd(sec));
  RTCWire.write(decToBcd(minu));
  RTCWire.write(decToBcd(hour));
  RTCWire.write(decToBcd(dayOfWeek));
  RTCWire.write(decToBcd(dayOfMonth));
  RTCWire.write(decToBcd(month));
  RTCWire.write(decToBcd((uint8_t)(year - 2000)));

  return (RTCWire.endTransmission() == 0);
}

bool rtcLooksSane(uint16_t year, uint8_t month, uint8_t day,
                  uint8_t hour, uint8_t minute, uint8_t second) {
  if (year < 2024 || year > 2099) return false;
  if (month < 1 || month > 12) return false;
  if (day < 1 || day > 31) return false;
  if (hour > 23) return false;
  if (minute > 59) return false;
  if (second > 59) return false;

  return true;
}

// ============================================================
// Time conversion helpers
// ============================================================

long long daysFromCivil(int y, unsigned m, unsigned d) {
  y -= m <= 2;

  const int era = (y >= 0 ? y : y - 399) / 400;
  const unsigned yoe = (unsigned)(y - era * 400);
  const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;

  return era * 146097LL + (long long)doe - 719468LL;
}

time_t utcToEpoch(uint16_t year, uint8_t month, uint8_t day,
                  uint8_t hour, uint8_t minute, uint8_t second) {
  long long days = daysFromCivil(year, month, day);
  long long secs = days * 86400LL + hour * 3600LL + minute * 60LL + second;

  return (time_t)secs;
}

uint8_t calculateDayOfWeek(uint16_t year, uint8_t month, uint8_t day) {
  static const uint8_t t[] = {0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4};

  uint16_t y = year;

  if (month < 3) {
    y -= 1;
  }

  uint8_t dow0 = (y + y / 4 - y / 100 + y / 400 + t[month - 1] + day) % 7;

  return dow0 + 1;
}

bool rtcToEpoch(time_t &epochOut) {
  uint8_t sec, minu, hour, dow, dom, month;
  uint16_t year;

  if (!readDS3231Raw(sec, minu, hour, dow, dom, month, year)) {
    return false;
  }

  if (!rtcLooksSane(year, month, dom, hour, minu, sec)) {
    return false;
  }

  epochOut = utcToEpoch(year, month, dom, hour, minu, sec);
  return true;
}

// ============================================================
// GPS validity helpers
// ============================================================

bool gpsTimeValid() {
  if (!gps.date.isValid()) return false;
  if (!gps.time.isValid()) return false;

  if (gps.date.age() > GPS_FRESH_AGE_MS) return false;
  if (gps.time.age() > GPS_FRESH_AGE_MS) return false;

  if (gps.date.year() < 2024) return false;
  if (gps.date.month() < 1 || gps.date.month() > 12) return false;
  if (gps.date.day() < 1 || gps.date.day() > 31) return false;

  if (gps.time.hour() > 23) return false;
  if (gps.time.minute() > 59) return false;
  if (gps.time.second() > 59) return false;

  return true;
}

bool gpsToEpoch(time_t &epochOut) {
  if (!gpsTimeValid()) {
    return false;
  }

  epochOut = utcToEpoch(
    gps.date.year(),
    gps.date.month(),
    gps.date.day(),
    gps.time.hour(),
    gps.time.minute(),
    gps.time.second()
  );

  return true;
}

String rtcIsoString() {
  uint8_t sec, minu, hour, dow, dom, month;
  uint16_t year;

  if (!readDS3231Raw(sec, minu, hour, dow, dom, month, year)) {
    return "ERR,RTC_READ";
  }

  if (!rtcLooksSane(year, month, dom, hour, minu, sec)) {
    return "ERR,RTC_INVALID";
  }

  char buf[32];

  snprintf(
    buf,
    sizeof(buf),
    "%04u-%02u-%02uT%02u:%02u:%02uZ",
    year,
    month,
    dom,
    hour,
    minu,
    sec
  );

  return String(buf);
}

// ============================================================
// Battery helpers
// ============================================================

float readBatteryVoltage() {
  uint32_t total = 0;
  const int samples = 32;

  for (int i = 0; i < samples; i++) {
    total += analogRead(BATTERY_ADC_PIN);
    delay(2);
  }

  float raw = (float)total / samples;
  float pinVoltage = (raw / ADC_MAX_COUNTS) * ADC_REF_VOLTAGE;
  float batteryVoltage = pinVoltage * BATTERY_DIVIDER_RATIO;

  return batteryVoltage;
}

int batteryPercentFromVoltage(float vbat) {
  if (vbat >= BATTERY_FULL_VOLTAGE) return 100;
  if (vbat <= BATTERY_FLAT_VOLTAGE) return 0;

  float pct = (
    (vbat - BATTERY_FLAT_VOLTAGE) /
    (BATTERY_FULL_VOLTAGE - BATTERY_FLAT_VOLTAGE)
  ) * 100.0f;

  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;

  return (int)(pct + 0.5f);
}

// ============================================================
// GPS helpers
// ============================================================

void powerGPSOn() {
  pinMode(VEXT_CTRL_PIN, OUTPUT);
  digitalWrite(VEXT_CTRL_PIN, LOW);
}

void readGpsStream(bool echoRaw = false) {
  while (GPSSerial.available()) {
    char c = (char)GPSSerial.read();

    if (echoRaw) {
      Serial.write(c);
    }

    gps.encode(c);
  }
}

bool waitForInitialGpsTime(unsigned long timeoutMs) {
  unsigned long start = millis();
  unsigned long lastScreen = 0;

  showStage("GPS wait", 500);

  while (millis() - start < timeoutMs) {
    readGpsStream(false);
    servicePiUart();
    updateEventState();

    if (gpsTimeValid()) {
      showStage("GPS time OK", 1000);
      return true;
    }

    if (millis() - lastScreen >= 2000) {
      lastScreen = millis();

      display.clear();
      display.setTextAlignment(TEXT_ALIGN_LEFT);
      display.setFont(ArialMT_Plain_10);

      display.drawString(0, 0,  "GPS wait");
      display.drawString(0, 12, "Chars:" + String(gps.charsProcessed()));
      display.drawString(0, 24, "Date:" + String(gps.date.isValid() ? "Y" : "N"));
      display.drawString(0, 36, "Time:" + String(gps.time.isValid() ? "Y" : "N"));

      if (gps.satellites.isValid()) {
        display.drawString(0, 48, "Sats:" + String(gps.satellites.value()));
      } else {
        display.drawString(0, 48, "Sats:INVALID");
      }

      display.display();
    }

    delay(10);
  }

  showStage("GPS timeout", 1000);
  return false;
}

// ============================================================
// RTC sync logic
// ============================================================

bool setRtcFromGps() {
  if (!gpsTimeValid()) {
    showStage("GPS invalid", 1000);
    return false;
  }

  uint16_t year  = gps.date.year();
  uint8_t month  = gps.date.month();
  uint8_t day    = gps.date.day();
  uint8_t hour   = gps.time.hour();
  uint8_t minute = gps.time.minute();
  uint8_t second = gps.time.second();
  uint8_t dow    = calculateDayOfWeek(year, month, day);

  bool ok = writeDS3231(
    second,
    minute,
    hour,
    dow,
    day,
    month,
    year
  );

  if (ok) {
    showStage("RTC set GPS", 1000);
  } else {
    showStage("RTC write fail", 1000);
  }

  return ok;
}

void compareRtcWithGpsAndCorrect() {
  time_t rtcEpoch;
  time_t gpsEpoch;

  if (!gpsToEpoch(gpsEpoch)) {
    return;
  }

  if (!rtcToEpoch(rtcEpoch)) {
    setRtcFromGps();
    return;
  }

  long diff = labs((long)(rtcEpoch - gpsEpoch));

  if (diff > MAX_ALLOWED_DRIFT_SECONDS) {
    setRtcFromGps();
  }
}

// ============================================================
// Event / trap / low-battery helpers
// ============================================================

bool trapPinActive(uint8_t pin) {
  return digitalRead(pin) == LOW;
}

bool trap1Active() {
  return trapPinActive(TRAP_PIN_1);
}

bool trap2Active() {
  return trapPinActive(TRAP_PIN_2);
}

bool anyTrapInputActive() {
  return trap1Active() || trap2Active();
}

void configureTrapInputPins() {
  /*
    Both trap inputs are wired active-low on PCB V2. The internal pull-ups keep
    the inputs idle-high, and a closed trap switch pulls the corresponding GPIO
    low. These are also the pins used by the EXT1 deep-sleep wake mask below.
  */
  pinMode(TRAP_PIN_1, INPUT_PULLUP);
  pinMode(TRAP_PIN_2, INPUT_PULLUP);
}

void enableTrapDeepSleepWake() {
  /*
    While the ESP32-S3 is in deep sleep the normal digital GPIO block is off.
    EXT1 wake is handled by the RTC controller and can monitor more than one
    RTC-capable pin. ESP_EXT1_WAKEUP_ANY_LOW matches the active-low trap
    wiring, so either Trap 1 on GPIO5 or Trap 2 on GPIO4 can wake the supervisor.
  */
  configureTrapInputPins();

  rtc_gpio_pullup_en((gpio_num_t)TRAP_PIN_1);
  rtc_gpio_pullup_en((gpio_num_t)TRAP_PIN_2);
  rtc_gpio_pulldown_dis((gpio_num_t)TRAP_PIN_1);
  rtc_gpio_pulldown_dis((gpio_num_t)TRAP_PIN_2);

  esp_sleep_enable_ext1_wakeup(TRAP_WAKE_MASK, ESP_EXT1_WAKEUP_ANY_LOW);
}

String currentEventSummary() {
  bool trapOffer = trapLatched && !trapReported;
  bool lowBatOffer = lowBatteryActive && !lowBatteryReported;

  if (trapOffer && lowBatOffer) return "TRAP+LOW_BAT";
  if (trapOffer) return "TRAP";
  if (lowBatOffer) return "LOW_BAT";

  return "NONE";
}

String rawEventStateReply() {
  char buf[96];

  snprintf(
    buf,
    sizeof(buf),
    "RAW,%d,%d,%d,%d,%d,%d",
    trap1Active() ? 1 : 0,
    trap2Active() ? 1 : 0,
    trapLatched ? 1 : 0,
    trapReported ? 1 : 0,
    lowBatteryActive ? 1 : 0,
    lowBatteryReported ? 1 : 0
  );

  return String(buf);
}

void updateEventState() {
  unsigned long now = millis();

  if (now - lastEventPoll < EVENT_POLL_INTERVAL_MS) {
    return;
  }

  lastEventPoll = now;

  bool trapNow = anyTrapInputActive();

  if (trapNow) {
    if (!trapLatched) {
      trapLatched = true;
    }
  } else {
    trapLatched = false;
    trapReported = false;
  }

  float vbat = readBatteryVoltage();

  if (!lowBatteryActive && vbat <= LOW_BATTERY_ASSERT_VOLTAGE) {
    lowBatteryActive = true;
  } else if (lowBatteryActive && vbat >= LOW_BATTERY_CLEAR_VOLTAGE) {
    lowBatteryActive = false;
    lowBatteryReported = false;
  }
}

void acknowledgeEventType(String eventType) {
  eventType.trim();
  eventType.toUpperCase();

  if (eventType == "TRAP") {
    trapReported = true;
  } else if (eventType == "LOW_BAT") {
    lowBatteryReported = true;
  } else if (eventType == "ALL") {
    trapReported = true;
    lowBatteryReported = true;
  }
}

// ============================================================
// UART reply builders
// ============================================================

String batteryReply() {
  float vbat = readBatteryVoltage();
  int pct = batteryPercentFromVoltage(vbat);

  char buf[32];

  snprintf(
    buf,
    sizeof(buf),
    "BAT,%.2f,%d",
    vbat,
    pct
  );

  return String(buf);
}

String coordReply() {
  if (!gps.location.isValid()) {
    return "COORD,INVALID";
  }

  char buf[48];

  snprintf(
    buf,
    sizeof(buf),
    "COORD,%.6f,%.6f",
    gps.location.lat(),
    gps.location.lng()
  );

  return String(buf);
}

// ============================================================
// Pi UART command handling
// ============================================================

void handlePiCommand(String cmd) {
  cmd.trim();

  String upperCmd = cmd;
  upperCmd.toUpperCase();

  if (upperCmd == "PING") {
    PiSerial.println("PONG");
  }

  else if (upperCmd == "STATUS?") {
    PiSerial.println("OK,BEARWAVE_RTC_GPS_EVENTS");
  }

  else if (upperCmd == "TIME?") {
    String t = rtcIsoString();

    if (t.startsWith("ERR,")) {
      PiSerial.println(t);
    } else {
      PiSerial.println("TIME," + t);
    }
  }

  else if (upperCmd == "BAT?") {
    PiSerial.println(batteryReply());
  }

  else if (upperCmd == "COORD?") {
    PiSerial.println(coordReply());
  }

  else if (upperCmd == "EVENT?") {
    updateEventState();
    PiSerial.println("EVENT," + currentEventSummary());
  }

  else if (upperCmd == "EVENT_RAW?") {
    updateEventState();
    PiSerial.println(rawEventStateReply());
  }

  else if (upperCmd.startsWith("EVENT_ACKED,")) {
    String eventType = cmd.substring(String("EVENT_ACKED,").length());

    eventType.trim();
    eventType.toUpperCase();

    if (
      eventType == "TRAP" ||
      eventType == "LOW_BAT" ||
      eventType == "ALL"
    ) {
      acknowledgeEventType(eventType);

      PiSerial.print("OK,EVENT_ACKED,");
      PiSerial.println(eventType);
    } else {
      PiSerial.print("ERR,BAD_EVENT_TYPE,");
      PiSerial.println(eventType);
    }
  }

  else if (upperCmd == "SHUTDOWN") {
    shutdownRequested = true;
    shutdownRequestTime = millis();

    lastShutdownStage = 0;

    PiSerial.println("OK,SHUTDOWN_RECEIVED");

    showStage("Pi shutdown req", 1500);
  }

  else {
    PiSerial.print("ERR,UNKNOWN_CMD,");
    PiSerial.println(cmd);
  }
}

void servicePiUart() {
  while (PiSerial.available()) {
    char c = (char)PiSerial.read();

    if (c == '\n') {
      handlePiCommand(piRxLine);
      piRxLine = "";
      continue;
    }

    if (c == '\r') {
      continue;
    }

    if ((uint8_t)c < 32 || (uint8_t)c > 126) {
      continue;
    }

    piRxLine += c;

    if (piRxLine.length() > 100) {
      piRxLine = "";
    }
  }
}

// ============================================================
// OLED normal status display
// ============================================================

void updateDisplay() {
  unsigned long now = millis();

  if (now - lastDisplayUpdate < DISPLAY_UPDATE_MS) {
    return;
  }

  lastDisplayUpdate = now;

  uint8_t sec, minu, hour, dow, dom, month;
  uint16_t year;

  bool rtcOk = readDS3231Raw(sec, minu, hour, dow, dom, month, year);
  bool rtcValid = rtcOk && rtcLooksSane(year, month, dom, hour, minu, sec);

  float vbat = readBatteryVoltage();
  int battPct = batteryPercentFromVoltage(vbat);

  String line1;
  String line2;
  String line3;
  String line4;
  String line5;

  if (rtcValid) {
    char buf1[24];
    char buf2[24];

    snprintf(buf1, sizeof(buf1), "%04u-%02u-%02u", year, month, dom);
    snprintf(buf2, sizeof(buf2), "%02u:%02u:%02u UTC", hour, minu, sec);

    line1 = buf1;
    line2 = buf2;
  } else {
    line1 = "RTC invalid";
    line2 = gpsTimeValid() ? "GPS valid" : "Waiting GPS";
  }

  char batBuf[24];

  snprintf(
    batBuf,
    sizeof(batBuf),
    "Bat %.2fV %d%%",
    vbat,
    battPct
  );

  line3 = batBuf;

  if (gps.location.isValid()) {
    char latBuf[24];

    snprintf(
      latBuf,
      sizeof(latBuf),
      "Lat %.4f",
      gps.location.lat()
    );

    line4 = latBuf;
  } else {
    line4 = "GPS no fix";
  }

  line5 = "E:" + currentEventSummary();

  display.clear();
  display.setTextAlignment(TEXT_ALIGN_LEFT);
  display.setFont(ArialMT_Plain_10);

  display.drawString(0, 0,  line1);
  display.drawString(0, 12, line2);
  display.drawString(0, 24, line3);
  display.drawString(0, 36, line4);
  display.drawString(0, 48, line5);

  display.display();
}

// ============================================================
// Deep sleep helper
// ============================================================

void enterDeepSleepForNextCycle() {
  lastShutdownStage = 5;
  showStage("S5 sleep set", 1500);

  /*
    PCB V2 uses external flip-flop latches for the 5 V and 12 V rails. Once the
    rails have been toggled off by powerPiAndRadioOff(), no ESP32 GPIO needs to
    be held during deep sleep.
  */
  configurePowerLatchPinsIdle();

  lastShutdownStage = 6;
  showStage("S6 latch idle", 1500);

  enableTrapDeepSleepWake();
  esp_sleep_enable_timer_wakeup(WAKE_INTERVAL_US);

  showStage("Entering sleep", 2500);

  display.clear();
  display.display();
  VextOFF();
  delay(50);

  esp_deep_sleep_start();

  /*
    This should never run. If it ever does, preserve the fact.
  */
  lastShutdownStage = 99;
}

// ============================================================
// Shutdown sequence service
// ============================================================

void serviceShutdownSequence() {
  if (!shutdownRequested) {
    return;
  }

  unsigned long now = millis();

  if (now - shutdownRequestTime >= PI_POWER_CUT_DELAY_MS) {
    lastShutdownStage = 1;
    showStage("S1 cut rails", 1500);

    bool railsOff = powerPiAndRadioOff();

    lastShutdownStage = 2;
    showStage("S2 rails off", 1500);

    if (!railsOff) {
      /*
        The high-power rails are controlled by flip-flop latches. If the status
        feedback does not confirm OFF, do not blindly retry: a second pulse can
        toggle the latch back ON and reboot the Pi. Continue toward sleep after
        one off attempt and leave the diagnostic visible briefly.
      */
      showStage("Rail off unsure", 3000);
    }

    /*
      Give the 12 V and 5 V rails time to collapse.
    */
    delay(3000);

    lastShutdownStage = 3;
    showStage("S3 prep sleep", 1500);

    /*
      Isolate Pi UART pins to reduce the chance of back-powering the Pi through
      UART protection paths.
    */
    isolatePiUartBeforeSleep();

    lastShutdownStage = 4;
    showStage("S4 UART iso", 1500);

    shutdownRequested = false;

    enterDeepSleepForNextCycle();
  }
}

void serviceHighPowerFailsafe() {
  if (!highPowerRailsRequestedOn || shutdownRequested) {
    return;
  }

  if (!rail5VOn() && !rail12VOn()) {
    highPowerRailsRequestedOn = false;
    highPowerRailsOnAt = 0;
    return;
  }

  unsigned long now = millis();

  if (now - highPowerRailsOnAt < PI_MAX_ON_TIME_MS) {
    return;
  }

  Serial.println("ERROR: high-power rail failsafe elapsed; cutting rails");
  showStage("Failsafe cut", 2500);

  shutdownRequested = true;
  shutdownRequestTime = millis() - PI_POWER_CUT_DELAY_MS;
  lastShutdownStage = 0;
}

// ============================================================
// setup()
// ============================================================

void setup() {
  bootCount++;

  Serial.begin(115200);
  delay(500);

  /*
    Configure V2 latch pulse outputs to their LOW idle state and status pins as
    pulled-up inputs before any display or rail-state diagnostics run.
  */
  configurePowerLatchPinsIdle();

  /*
    Initialise OLED before doing anything else so it can show reset/wake cause.
  */
  VextON();
  displayReset();
  display.init();
  display.flipScreenVertically();
  display.setFont(ArialMT_Plain_10);
  display.setTextAlignment(TEXT_ALIGN_LEFT);

  showStage("Boot diag", 1500);
  showLastBootDetails(5000);

  bootRailControlTest();

  pinMode(RTC_INT_PIN, INPUT_PULLUP);

  analogReadResolution(12);

  configureTrapInputPins();

  /*
    Start DS3231 RTC bus.
  */
  RTCWire.begin(RTC_SDA_PIN, RTC_SCL_PIN, 100000);

  RTCWire.beginTransmission(DS3231_ADDR);
  uint8_t err = RTCWire.endTransmission();

  if (err == 0) {
    showStage("RTC found", 1000);
  } else {
    showStage("RTC missing", 1000);
  }

  /*
    Start GPS.
  */
  powerGPSOn();
  delay(GPS_POWERUP_DELAY_MS);

  GPSSerial.begin(GPS_BAUD, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);

  /*
    Start Pi UART.
  */
  PiSerial.begin(PI_UART_BAUD, SERIAL_8N1, PI_UART_RX_PIN, PI_UART_TX_PIN);

  showStage("UART/GPS start", 1000);

  updateEventState();

  bool gpsInitialTimeOk = waitForInitialGpsTime(GPS_SYNC_TIMEOUT_MS);

  if (gpsInitialTimeOk) {
    setRtcFromGps();
  } else {
    showStage("RTC unchanged", 1000);
  }

  /*
    The high-power rails have deliberately been kept OFF until this point.
    Once GPS/RTC startup is complete, wake the Pi and radio path so the Pi can
    send the scheduled heartbeat or handle a latched alarm.
  */
  showStage("Wake Pi/radio", 1000);
  powerPiAndRadioOn();
  showStage("Rails ON", 1000);

  lastDisplayUpdate = 0;
  lastRtcCheck = millis();
  lastEventPoll = 0;

  updateEventState();
  updateDisplay();

  showStage("Setup complete", 1000);
}

// ============================================================
// loop()
// ============================================================

void loop() {
  readGpsStream(false);

  servicePiUart();

  updateEventState();

  updateDisplay();

  serviceShutdownSequence();
  serviceHighPowerFailsafe();

  unsigned long now = millis();

  if (now - lastRtcCheck >= RTC_CHECK_INTERVAL_MS) {
    lastRtcCheck = now;
    compareRtcWithGpsAndCorrect();
  }
}

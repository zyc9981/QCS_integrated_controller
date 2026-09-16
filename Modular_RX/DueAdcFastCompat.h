#ifndef _DUEADCFAST_COMPAT_H
#define _DUEADCFAST_COMPAT_H

#include <Arduino.h>

#if defined(__has_include)
#if __has_include(<DueAdcFast.h>)
#include <DueAdcFast.h>
#define BASIC_CONTROLS_HAS_DUEADCFAST 1
#endif
#endif

#ifndef BASIC_CONTROLS_HAS_DUEADCFAST
// Lightweight compatibility wrapper for environments where the external
// DueAdcFast library is not installed. It preserves the API this project uses
// and falls back to the standard Arduino ADC calls.
class DueAdcFast {
  public:
    explicit DueAdcFast(uint16_t sample_buffer_size = 1024)
      : sample_buffer_size_(sample_buffer_size) {}

    void EnablePin(uint8_t pin) const {
      pinMode(pin, INPUT);
    }

    void Start1Mhz() const {
#if defined(ARDUINO_ARCH_SAM)
      analogReadResolution(12);
#endif
    }

    uint16_t ReadAnalogPin(uint8_t pin) const {
      (void)sample_buffer_size_;
      return static_cast<uint16_t>(analogRead(pin));
    }

    void adcHandler() const {}

  private:
    uint16_t sample_buffer_size_;
};
#endif

#endif

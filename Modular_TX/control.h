#ifndef _CONTROL_H
#define _CONTROL_H

#include <Arduino.h>
#include "DueAdcFastCompat.h"
#include "dacx1416.h"

const float Iteration_threshold = 0.000;

// template <typename T> int sgn(T val);
template <typename T> int sgn(T val) {
    return (T(0) < val) - (val < T(0));
}

void Sweep_Measure_1D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD_PIN, uint16_t Sweep_Delay_us, int N_sweep, float* V_sweep, float* Rx_Signal, float* V_extreme, float* Signal_extreme, int OUT_MAX = 65535);
void Sweep_Measure_1D_2PD(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD1_PIN, uint8_t PD2_PIN, uint16_t Sweep_Delay_us, int N_sweep, float* V_sweep, float* Rx1_Signal, float* Rx2_Signal, int OUT_MAX = 65535);
void Sweep_Measure_1D_2PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD2_PIN, float PD2_CALIB, uint16_t Sweep_Delay_us, int N_sweep, float* V_sweep, float* Diff_Signal, int OUT_MAX = 65535);
void Sweep_Measure_1D_3PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD3_PIN, float PD3_CALIB, uint8_t PD4_PIN, float PD4_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, float* dS12, float* dS34, int OUT_MAX = 65535);
void Sweep_Measure_2D_2PD(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, uint8_t PD2_PIN, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Rx1_Signal, float* Rx2_Signal, int OUT_MAX = 65535);
void Sweep_Measure_2D_2PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD2_PIN, float PD2_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Diff_Signal, int OUT_MAX = 65535);
void Sweep_Measure_2D_3PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD3_PIN, float PD3_CALIB, uint8_t PD4_PIN, float PD4_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* dS12, float* dS34, int OUT_MAX = 65535);
void Sweep_Measure_2D_3PDdiffAVG(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD3_PIN, float PD3_CALIB, uint8_t PD4_PIN, float PD4_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* dS12, float* dS34, int PD_repeat, int OUT_MAX = 65535);
void Sweep_Serial_Output_1D(int N_sweep, float* V_sweep, float* Rx_Signal, int Output_Delay = 1);
void Sweep_Serial_Output_1D_query(int N_sweep, float* V_extreme, float* V_sweep, float* Rx_Signal, int Output_Delay = 1);
void Sweep_Serial_Output_1D_queryNEW(int N_sweep, float* V_sweep, float* Rx_Signal, int Output_Delay = 1);
void Sweep_Serial_Output_2D_query(int N_sweep1, int N_sweep2, float* V_sweep1, float* V_sweep2, float* Rx_Signal, int Output_Delay = 1);
void TimeTrace_Serial_Output_1D_query(int N_sweep, float Time_Period, float V_optimized, float* Rx_Signal, int Output_Delay = 1);
// void Sweep_Measure_2D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_RANGE1, uint8_t DAC_PIN2, uint8_t DAC_RANGE2, uint8_t PD_PIN, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Rx_Signal, float* V_extreme1, float* V_extreme2, float* Signal_extreme, int OUT_MAX = 65535);
// void Sweep_Serial_Output_2D(int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Rx_Signal, int Output_Delay = 1);

float Stabilizer_1D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD_PIN, uint16_t Sweep_Delay_us, float V_init, float Slope_step, float step, int Mode = 0, int Iter_max = 10, int Iter_period_ms = 10, float Iter_thred = 0.05, int OUT_MAX = 65535);
float* Optimizer_Multi(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t N_DOFs, uint8_t* DAC_PIN, uint8_t* DAC_RANGE, uint8_t PD_PIN, uint16_t Sweep_Delay_us, float* V_init, float* Slope_step, float* step, int* Direction, float* S_monitor, int Iter_max = 25, int Iter_period_us = 200, float Iter_thred = Iteration_threshold, int OUT_MAX = 65535);
float* Optimizer_Multi2(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t N_DOFs, uint8_t* DAC_PIN, uint8_t* DAC_RANGE, uint8_t* PD_PIN, uint16_t Sweep_Delay_us, float* V_init, float* Slope_step, float* step, int* Direction, float* S_monitor, int Iter_max = 25, int Iter_period_us = 200, float Iter_thred = Iteration_threshold, int OUT_MAX = 65535);
void Optimizer_Multi_Sweep_1D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t N_DOFs, uint8_t* DAC_PIN, uint8_t DAC_PINs, uint8_t* DAC_RANGE, uint8_t DAC_RANGEs, uint8_t PD_PIN, uint16_t Sweep_Delay_us, float* V_init, int N_sweep, float* V_sweep, float* Rx_Signal, float* V_extreme, float* Slope_step, float* step, int* Direction, int OUT_MAX = 65535);

#endif

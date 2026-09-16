#include "control.h"

// template <typename T> int sgn(T val) {
//     return (T(0) < val) - (val < T(0));
// }

void Sweep_Measure_1D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD_PIN, uint16_t Sweep_Delay_us, int N_sweep, float* V_sweep, float* Rx_Signal, float* V_extreme, float* Signal_extreme, int OUT_MAX){
  int DAC_OUT = 0;

  for(int idx = 0; idx < N_sweep; idx++){
    DAC_OUT = int(V_sweep[idx] / DAC_RANGE * OUT_MAX);
    dac -> set_out(DAC_PIN, DAC_OUT);
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);
    Rx_Signal[idx] = DueAdcF -> ReadAnalogPin(PD_PIN);

    if(idx == 0){
      V_extreme[0] = V_sweep[idx];
      V_extreme[1] = V_sweep[idx];
      Signal_extreme[0] = Rx_Signal[idx];
      Signal_extreme[1] = Rx_Signal[idx];
    }
    else if(Rx_Signal[idx] > Signal_extreme[0]){
      V_extreme[0] = V_sweep[idx];
      Signal_extreme[0] = Rx_Signal[idx];
    }
    else if(Rx_Signal[idx] < Signal_extreme[1]){
      V_extreme[1] = V_sweep[idx];
      Signal_extreme[1] = Rx_Signal[idx];
    }
  }

  // Look for the medium value
  int ref_med = (Signal_extreme[0] + Signal_extreme[1]) / 2;
  int dev_med = 0;
  for(int idx = 0; idx < N_sweep; idx++){
    if((V_sweep[idx] > V_extreme[0]) && (V_sweep[idx] > V_extreme[1])) break;
    if((idx == 0) || (abs(Rx_Signal[idx] - ref_med) < dev_med)){
      V_extreme[2] = V_sweep[idx];
      Signal_extreme[2] = Rx_Signal[idx];
      dev_med = abs(Rx_Signal[idx] - ref_med);
    }
  }

  DAC_OUT = int(0.0 / DAC_RANGE * OUT_MAX);
  dac -> set_out(DAC_PIN, DAC_OUT);
  dac -> sync(1);
}

void Sweep_Measure_1D_2PD(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD1_PIN, uint8_t PD2_PIN, uint16_t Sweep_Delay_us, int N_sweep, float* V_sweep, float* Rx1_Signal, float* Rx2_Signal, int OUT_MAX){
  int DAC_OUT = 0;

  for(int idx = 0; idx < N_sweep; idx++){
    DAC_OUT = int(V_sweep[idx] / DAC_RANGE * OUT_MAX);
    dac -> set_out(DAC_PIN, DAC_OUT);
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);
    Rx1_Signal[idx] = DueAdcF -> ReadAnalogPin(PD1_PIN);
    Rx2_Signal[idx] = DueAdcF -> ReadAnalogPin(PD2_PIN);
  }
}

void Sweep_Measure_1D_2PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD2_PIN, float PD2_CALIB, uint16_t Sweep_Delay_us, int N_sweep, float* V_sweep, float* Diff_Signal, int OUT_MAX){
  int DAC_OUT = 0;
  int S1 = 0;
  int S2 = 0;

  for(int idx = 0; idx < N_sweep; idx++){
    DAC_OUT = int(V_sweep[idx] / DAC_RANGE * OUT_MAX);
    dac -> set_out(DAC_PIN, DAC_OUT);
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);
    S1 = DueAdcF -> ReadAnalogPin(PD1_PIN);
    S2 = DueAdcF -> ReadAnalogPin(PD2_PIN);
    Diff_Signal[idx] = (S1 * PD1_CALIB - S2 * PD2_CALIB) / float(S1 * PD1_CALIB + S2 * PD2_CALIB);
  }
}

void Sweep_Measure_1D_3PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD3_PIN, float PD3_CALIB, uint8_t PD4_PIN, float PD4_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, float* dS12, float* dS34, int OUT_MAX){
  int DAC_OUT1 = 0;
  int S1 = 0;
  int S2 = 0;
  int S3 = 0;
  int S4 = 0;

  for(int idx1 = 0; idx1 < N_sweep1; idx1++){
    DAC_OUT1 = int(V_sweep1[idx1] / DAC_RANGE * OUT_MAX);
    dac -> set_out(DAC_PIN1, DAC_OUT1);
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);
    S1 = DueAdcF -> ReadAnalogPin(PD1_PIN) * PD1_CALIB;
    S3 = DueAdcF -> ReadAnalogPin(PD3_PIN) * PD3_CALIB;
    S4 = DueAdcF -> ReadAnalogPin(PD4_PIN) * PD4_CALIB;
    S2 = (S3 + S4 < S1) ? 0 : S3 + S4 - S1;
    dS12[idx1] = (S1 - S2) / float(S1 + S2);
    dS34[idx1] = (S3 - S4) / float(S3 + S4);
  }
}

void Sweep_Measure_2D_2PD(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, uint8_t PD2_PIN, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Rx1_Signal, float* Rx2_Signal, int OUT_MAX){
  int DAC_OUT1 = 0;
  int DAC_OUT2 = 0;

  for(int idx1 = 0; idx1 < N_sweep1; idx1++){
    for(int idx2 = 0; idx2 < N_sweep2; idx2++){
      DAC_OUT1 = int(V_sweep1[idx1] / DAC_RANGE * OUT_MAX);
      DAC_OUT2 = int(V_sweep2[idx2] / DAC_RANGE * OUT_MAX);
      dac -> set_out(DAC_PIN1, DAC_OUT1);
      dac -> set_out(DAC_PIN2, DAC_OUT2);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);
      Rx1_Signal[idx1 * N_sweep1 + idx2] = DueAdcF -> ReadAnalogPin(PD1_PIN);
      Rx2_Signal[idx1 * N_sweep1 + idx2] = DueAdcF -> ReadAnalogPin(PD2_PIN);
    }
  }
}

void Sweep_Measure_2D_2PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD2_PIN, float PD2_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Diff_Signal, int OUT_MAX){
  int DAC_OUT1 = 0;
  int DAC_OUT2 = 0;
  int S1 = 0;
  int S2 = 0;

  for(int idx1 = 0; idx1 < N_sweep1; idx1++){
    for(int idx2 = 0; idx2 < N_sweep2; idx2++){
      DAC_OUT1 = int(V_sweep1[idx1] / DAC_RANGE * OUT_MAX);
      DAC_OUT2 = int(V_sweep2[idx2] / DAC_RANGE * OUT_MAX);
      dac -> set_out(DAC_PIN1, DAC_OUT1);
      dac -> set_out(DAC_PIN2, DAC_OUT2);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);
      S1 = DueAdcF -> ReadAnalogPin(PD1_PIN);
      S2 = DueAdcF -> ReadAnalogPin(PD2_PIN);
      Diff_Signal[idx1 * N_sweep1 + idx2] = (S1 * PD1_CALIB - S2 * PD2_CALIB) / float(S1 * PD1_CALIB + S2 * PD2_CALIB);
    }
  }
}

void Sweep_Measure_2D_3PDdiff(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD3_PIN, float PD3_CALIB, uint8_t PD4_PIN, float PD4_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* dS12, float* dS34, int OUT_MAX){
  int DAC_OUT1 = 0;
  int DAC_OUT2 = 0;
  int S1 = 0;
  int S2 = 0;
  int S3 = 0;
  int S4 = 0;

  for(int idx1 = 0; idx1 < N_sweep1; idx1++){
    for(int idx2 = 0; idx2 < N_sweep2; idx2++){
      DAC_OUT1 = int(V_sweep1[idx1] / DAC_RANGE * OUT_MAX);
      DAC_OUT2 = int(V_sweep2[idx2] / DAC_RANGE * OUT_MAX);
      dac -> set_out(DAC_PIN1, DAC_OUT1);
      dac -> set_out(DAC_PIN2, DAC_OUT2);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);
      S1 = DueAdcF -> ReadAnalogPin(PD1_PIN) * PD1_CALIB;
      S3 = DueAdcF -> ReadAnalogPin(PD3_PIN) * PD3_CALIB;
      S4 = DueAdcF -> ReadAnalogPin(PD4_PIN) * PD4_CALIB;
      S2 = S3 + S4 - S1;
      dS12[idx1 * N_sweep1 + idx2] = (S1 - S2) / float(S1 + S2);
      dS34[idx1 * N_sweep1 + idx2] = (S3 - S4) / float(S3 + S4);
    }
  }
}

void Sweep_Measure_2D_3PDdiffAVG(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_PIN2, uint8_t DAC_RANGE, uint8_t PD1_PIN, float PD1_CALIB, uint8_t PD3_PIN, float PD3_CALIB, uint8_t PD4_PIN, float PD4_CALIB, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* dS12, float* dS34, int PD_repeat, int OUT_MAX){
  int DAC_OUT1 = 0;
  int DAC_OUT2 = 0;
  int S1 = 0;
  int S2 = 0;
  int S3 = 0;
  int S4 = 0;

  for(int idx1 = 0; idx1 < N_sweep1; idx1++){
    for(int idx2 = 0; idx2 < N_sweep2; idx2++){
      DAC_OUT1 = int(V_sweep1[idx1] / DAC_RANGE * OUT_MAX);
      DAC_OUT2 = int(V_sweep2[idx2] / DAC_RANGE * OUT_MAX);
      dac -> set_out(DAC_PIN1, DAC_OUT1);
      dac -> set_out(DAC_PIN2, DAC_OUT2);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);
      // S1 = DueAdcF -> ReadAnalogPin(PD1_PIN) * PD1_CALIB;
      // S3 = DueAdcF -> ReadAnalogPin(PD3_PIN) * PD3_CALIB;
      // S4 = DueAdcF -> ReadAnalogPin(PD4_PIN) * PD4_CALIB;
      // S2 = S3 + S4 - S1;
      S1 = 0;
      S3 = 0;
      S4 = 0;
      S2 = 0;
      for(int idx=0; idx<PD_repeat; idx++){
        S1 += int(DueAdcF -> ReadAnalogPin(PD1_PIN) * PD1_CALIB);
        S3 += int(DueAdcF -> ReadAnalogPin(PD3_PIN) * PD3_CALIB);
        S4 += int(DueAdcF -> ReadAnalogPin(PD4_PIN) * PD4_CALIB);
      }
      S1 = int(S1/PD_repeat);
      S3 = int(S3/PD_repeat);
      S4 = int(S4/PD_repeat);
      S2 = (S3 + S4 < S1) ? 0 : S3 + S4 - S1;
      dS12[idx1 * N_sweep1 + idx2] = (S1 - S2) / float(S1 + S2);
      dS34[idx1 * N_sweep1 + idx2] = (S3 - S4) / float(S3 + S4);
    }
  }
}

void Sweep_Serial_Output_1D(int N_sweep, float* V_sweep, float* Rx_Signal, int Output_Delay){
  Serial.println(N_sweep);
  delay(Output_Delay);

  for(int idx = 0; idx < N_sweep; idx++){
    Serial.println(sq(V_sweep[idx]));
    delay(Output_Delay);
    Serial.println(Rx_Signal[idx]);
    delay(Output_Delay);
  }
}

void Sweep_Serial_Output_1D_query(int N_sweep, float* V_extreme, float* V_sweep, float* Rx_Signal, int Output_Delay){
  while (Serial.available() == 0) {}
  Serial.parseInt();
  
  Serial.println(N_sweep);
  // delay(Output_Delay);
  Serial.println(V_extreme[0]);
  Serial.println(V_extreme[1]);
  Serial.println(V_extreme[2]);

  for(int idx = 0; idx < N_sweep; idx++){
    Serial.println(sq(V_sweep[idx]));
    // delay(Output_Delay);
    Serial.println(Rx_Signal[idx]);
    // delay(Output_Delay);
  }
}

void Sweep_Serial_Output_1D_queryNEW(int N_sweep, float* V_sweep, float* Rx_Signal, int Output_Delay){
  while (Serial.available() == 0) {}
  Serial.parseInt();
  
  Serial.println(N_sweep);

  for(int idx = 0; idx < N_sweep; idx++){
    Serial.println(sq(V_sweep[idx]));
    Serial.println(Rx_Signal[idx]);
  }
}

void Sweep_Serial_Output_2D_query(int N_sweep1, int N_sweep2, float* V_sweep1, float* V_sweep2, float* Rx_Signal, int Output_Delay){
  while (Serial.available() == 0) {}
  Serial.parseInt();

  Serial.println(N_sweep1);
  Serial.println(N_sweep2);

  for(int idx1 = 0; idx1 < N_sweep1; idx1++){
    for(int idx2 = 0; idx2 < N_sweep2; idx2++){
      Serial.println(sq(V_sweep1[idx1]));
      // delay(Output_Delay);
      Serial.println(sq(V_sweep2[idx2]));
      // delay(Output_Delay);
      // Serial.println(Rx_Signal[idx1][idx2]);
      Serial.println(Rx_Signal[idx1 * N_sweep2 + idx2]);
      // delay(Output_Delay);
    }
  }
}

void TimeTrace_Serial_Output_1D_query(int N_sweep, float Time_Period, float V_optimized, float* Rx_Signal, int Output_Delay){
  while (Serial.available() == 0) {}
  Serial.parseInt();
  
  Serial.println(N_sweep);
  Serial.println(V_optimized);
  Serial.println(V_optimized);
  Serial.println(V_optimized);

  for(int idx = 0; idx < N_sweep; idx++){
    Serial.println(idx * Time_Period);
    Serial.println(Rx_Signal[idx]);
  }
}

// void Sweep_Measure_2D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN1, uint8_t DAC_RANGE1, uint8_t DAC_PIN2, uint8_t DAC_RANGE2, uint8_t PD_PIN, uint16_t Sweep_Delay_us, int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Rx_Signal, float* V_extreme1, float* V_extreme2, float* Signal_extreme, int OUT_MAX){
//   int DAC_OUT1 = 0;
//   int DAC_OUT2 = 0;

//   for(int idx1 = 0; idx1 < N_sweep1; idx1++){
//     for(int idx2 = 0; idx2 < N_sweep2; idx2++){
//       DAC_OUT1 = int(V_sweep1[idx1] / DAC_RANGE1 * OUT_MAX);
//       DAC_OUT2 = int(V_sweep1[idx2] / DAC_RANGE2 * OUT_MAX);
//       dac -> set_out(DAC_PIN1, DAC_OUT1);
//       dac -> set_out(DAC_PIN2, DAC_OUT2);
//       dac -> sync(1);
//       delayMicroseconds(Sweep_Delay_us);
//       Rx_Signal[idx1 * N_sweep1 + idx2] = DueAdcF -> ReadAnalogPin(PD_PIN);

//       if(idx1 == 0 && idx2 == 0){
//         V_extreme1[0] = V_sweep1[idx1];
//         V_extreme1[1] = V_sweep1[idx1];
//         V_extreme2[0] = V_sweep2[idx2];
//         V_extreme2[1] = V_sweep2[idx2];
//         Signal_extreme[0] = Rx_Signal[idx1 * N_sweep1 + idx2];
//         Signal_extreme[1] = Rx_Signal[idx1 * N_sweep1 + idx2];
//       }
//       else if(Rx_Signal[idx1 * N_sweep1 + idx2] > Signal_extreme[0]){
//         V_extreme1[0] = V_sweep1[idx1];
//         V_extreme2[0] = V_sweep2[idx2];
//         Signal_extreme[0] = Rx_Signal[idx1 * N_sweep1 + idx2];
//       }
//       else if(Rx_Signal[idx1 * N_sweep1 + idx2] < Signal_extreme[1]){
//         V_extreme1[1] = V_sweep1[idx1];
//         V_extreme2[1] = V_sweep2[idx2];
//         Signal_extreme[1] = Rx_Signal[idx1 * N_sweep1 + idx2];
//       }
//     }
//   }

//   dac -> set_out(DAC_PIN1, 0);
//   dac -> set_out(DAC_PIN2, 0);
//   dac -> sync(1);
// }

// void Sweep_Serial_Output_2D(int N_sweep1, float* V_sweep1, int N_sweep2, float* V_sweep2, float* Rx_Signal, int Output_Delay){
//   Serial.println(N_sweep1);
//   delay(Output_Delay);
//   Serial.println(N_sweep2);
//   delay(Output_Delay);

//   for(int idx1 = 0; idx1 < N_sweep1; idx1++){
//     for(int idx2 = 0; idx2 < N_sweep2; idx2++){
//       Serial.println(V_sweep1[idx1]);
//       delay(Output_Delay);
//       Serial.println(V_sweep2[idx2]);
//       delay(Output_Delay);
//       Serial.println(Rx_Signal[idx1 * N_sweep1 + idx2]);
//       delay(Output_Delay);
//     }
//   }
// }

float Stabilizer_1D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t DAC_PIN, uint8_t DAC_RANGE, uint8_t PD_PIN, uint16_t Sweep_Delay_us, float V_init, float Slope_step, float step, int Mode, int Iter_max, int Iter_period_ms, float Iter_thred, int OUT_MAX){
  int flow_trigger = 0;
  float V = V_init;
  int S = 0;
  int S_new = 0;
  int DAC_OUT = 0;

  float V_0 = 0.0;
  float V_1 = 0.0;
  int S_0 = 0;
  int S_1 = 0;
  int direction = (Mode == 0) ? 1 : -1;
  float Slope = 0.0;
  
  while(flow_trigger < Iter_max){
    S_new = DueAdcF -> ReadAnalogPin(PD_PIN);
    if(float(abs(S_new - S))/float(S) < Iter_thred) break;
    S = S_new;

    V_0 = V;
    S_0 = S;
    // DAC_OUT = int(V_0 / DAC_RANGE * OUT_MAX);
    // dac -> set_out(DAC_PIN, DAC_OUT);
    // dac -> sync(1);
    // delayMicroseconds(Sweep_Delay_us);
    // S_0 = DueAdcF -> ReadAnalogPin(PD_PIN);

    V_1 = sqrt(sq(V) + Slope_step);
    DAC_OUT = int(V_1 / DAC_RANGE * OUT_MAX);
    dac -> set_out(DAC_PIN, DAC_OUT);
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);
    S_1 = DueAdcF -> ReadAnalogPin(PD_PIN);

    Slope = float(S_1 - S_0) / (sq(V_1) - sq(V_0));
    V = sqrt(abs(sq(V) + direction * Slope * step));

    if(V < 0.0) V == 0.0;
    if(V > 25.0) V == 25.0;

    DAC_OUT = int(V / DAC_RANGE * OUT_MAX);
    dac -> set_out(DAC_PIN, DAC_OUT);
    dac -> sync(1);
    S = S_1;

    delay(Iter_period_ms);
  }

  return V;
}

float* Optimizer_Multi(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t N_DOFs, uint8_t* DAC_PIN, uint8_t* DAC_RANGE, uint8_t PD_PIN, uint16_t Sweep_Delay_us, float* V_init, float* Slope_step, float* step, int* Direction, float* S_monitor, int Iter_max, int Iter_period_us, float Iter_thred, int OUT_MAX){
  int flow_trigger = 0;
  int num_of_optimizers = N_DOFs;
  float* V = new float[N_DOFs];
  uint8_t idx = 0;
  
  int DAC_OUT = 0;
  float V_0 = 0.0;
  float V_1 = 0.0;
  int S_0 = 0;
  int S_1 = 0;
  int S = 0;
  int S_new = 0;
  int direction_tmp = 1;
  float* Slope = new float[N_DOFs];
  float* V_MIN = new float[N_DOFs];
  float* V_MAX = new float[N_DOFs];

  #pragma region Initilization
  for(idx = 0; idx < N_DOFs; idx++) {
    V[idx] = V_init[idx];
    Slope[idx] = -1.0;
    V_MIN[idx] = V_init[idx] * 0.5;
    V_MAX[idx] = V_init[idx] * 1.5;
  }
  #pragma endregion

  #pragma region Optimization
  while(flow_trigger < Iter_max){
    S_new = DueAdcF -> ReadAnalogPin(PD_PIN);
    S_monitor[flow_trigger] = S_new;
    // Serial.println(S_new);
    // Serial.print(S_new);
    // Serial.print(" ");
    if(float(abs(S_new - S))/float(S) < Iter_thred) break;
    S = S_new;

    // Estimate gradient
    for(idx = 0; idx < N_DOFs; idx++){
      V_0 = V[idx];
      S_0 = DueAdcF -> ReadAnalogPin(PD_PIN);

      // direction_tmp = (Slope[idx] >= 0) ? 1 : -1;
      direction_tmp = 1;
      V_1 = sqrt(sq(V_0) + direction_tmp * Slope_step[idx]);
      DAC_OUT = int(V_1 / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);
      S_1 = DueAdcF -> ReadAnalogPin(PD_PIN);
      delayMicroseconds(10);

      DAC_OUT = int(V_0 / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);

      Slope[idx] = float(S_1 - S_0) / (sq(V_1) - sq(V_0));
      // V[idx] = sqrt(abs(sq(V[idx]) + Direction[idx] * Slope[idx] * step[idx]));
      V[idx] = sq(V[idx]) + Direction[idx] * Slope[idx] * step[idx];
      if(V[idx] < sq(V_MIN[idx])) V[idx] = sq(V_MIN[idx]);
      if(V[idx] > sq(V_MAX[idx])) V[idx] = sq(V_MAX[idx]);
      V[idx] = sqrt(V[idx]);

      // Serial.print(V[idx]);
      // Serial.print(" ");
    }
    // Serial.print("\n");

    // Update V
    for(idx = 0; idx < N_DOFs; idx++){
      DAC_OUT = int(V[idx] / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
    }
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);

    delay(Iter_period_us);
    flow_trigger++;
  }
  #pragma endregion

  return V;
}

float* Optimizer_Multi2(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t N_DOFs, uint8_t* DAC_PIN, uint8_t* DAC_RANGE, uint8_t* PD_PIN, uint16_t Sweep_Delay_us, float* V_init, float* Slope_step, float* step, int* Direction, float* S_monitor, int Iter_max, int Iter_period_us, float Iter_thred, int OUT_MAX){
  int flow_trigger = 0;
  int num_of_optimizers = N_DOFs;
  float* V = new float[N_DOFs];
  uint8_t idx = 0;
  
  int DAC_OUT = 0;
  float V_0 = 0.0;
  float V_1 = 0.0;
  int S_0 = 0;
  int S_1 = 0;
  int direction_tmp = 1;
  int* S = new int[N_DOFs];
  int* S_new = new int[N_DOFs];
  float* Slope = new float[N_DOFs];
  float* V_MIN = new float[N_DOFs];
  float* V_MAX = new float[N_DOFs];

  #pragma region Initilization
  for(idx = 0; idx < N_DOFs; idx++) {
    V[idx] = V_init[idx];
    Slope[idx] = -1.0;
    V_MIN[idx] = V_init[idx] * 0.5;
    V_MAX[idx] = V_init[idx] * 1.5;
  }
  #pragma endregion

  #pragma region Optimization
  while(flow_trigger < Iter_max){
    for(idx = 0; idx < N_DOFs; idx++){
      S_new[idx] = DueAdcF -> ReadAnalogPin(PD_PIN[idx]);
      S_monitor[flow_trigger] = S_new[0];
      // Serial.println(S_new);
      // Serial.print(S_new);
      // Serial.print(" ");
      // if(float(abs(S_new[idx] - S[idx]))/float(S[idx]) < Iter_thred) break;
      S[idx] = S_new[idx];

      // Estimate gradient
      V_0 = V[idx];
      S_0 = DueAdcF -> ReadAnalogPin(PD_PIN[idx]);

      // direction_tmp = (Slope[idx] >= 0) ? 1 : -1;
      direction_tmp = 1;
      V_1 = sqrt(sq(V_0) + direction_tmp * Slope_step[idx]);
      DAC_OUT = int(V_1 / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);
      S_1 = DueAdcF -> ReadAnalogPin(PD_PIN[idx]);
      delayMicroseconds(10);

      DAC_OUT = int(V_0 / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);

      Slope[idx] = float(S_1 - S_0) / (sq(V_1) - sq(V_0));
      // V[idx] = sqrt(abs(sq(V[idx]) + Direction[idx] * Slope[idx] * step[idx]));
      V[idx] = sq(V[idx]) + Direction[idx] * Slope[idx] * step[idx];
      if(V[idx] < sq(V_MIN[idx])) V[idx] = sq(V_MIN[idx]);
      if(V[idx] > sq(V_MAX[idx])) V[idx] = sq(V_MAX[idx]);
      V[idx] = sqrt(V[idx]);

      // Serial.print(V[idx]);
      // Serial.print(" ");
    }
    // Serial.print("\n");

    // Update V
    for(idx = 0; idx < N_DOFs; idx++){
      DAC_OUT = int(V[idx] / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
    }
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);

    delay(Iter_period_us);
    flow_trigger++;
  }
  #pragma endregion

  return V;
}

void Optimizer_Multi_Sweep_1D(DACX1416* dac, DueAdcFast* DueAdcF, uint8_t N_DOFs, uint8_t* DAC_PIN, uint8_t DAC_PINs, uint8_t* DAC_RANGE, uint8_t DAC_RANGEs, uint8_t PD_PIN, uint16_t Sweep_Delay_us, float* V_init, int N_sweep, float* V_sweep, float* Rx_Signal, float* V_extreme, float* Slope_step, float* step, int* Direction, int OUT_MAX){
  float* V = new float[N_DOFs];
  uint8_t idx = 0;
  
  int DAC_OUT = 0;
  float V_0 = 0.0;
  float V_1 = 0.0;
  int S_0 = 0;
  int S_1 = 0;
  int S = 0;
  int S_new = 0;
  int direction_tmp = 1;
  float* Slope = new float[N_DOFs];
  float* V_MIN = new float[N_DOFs];
  float* V_MAX = new float[N_DOFs];
  int Signal_extreme[3];

  #pragma region Initilization
  for(idx = 0; idx < N_DOFs; idx++) {
    V[idx] = V_init[idx];
    Slope[idx] = -1.0;
    V_MIN[idx] = V_init[idx] * 0.5;
    V_MAX[idx] = V_init[idx] * 1.5;
  }
  #pragma endregion

  #pragma region Sweep
  for(int idx_s = 0; idx_s < N_sweep; idx_s++){
    // Update sweep voltage
    DAC_OUT = int(V_sweep[idx_s] / DAC_RANGEs * OUT_MAX);
    dac -> set_out(DAC_PINs, DAC_OUT);
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);
    Rx_Signal[idx_s] = DueAdcF -> ReadAnalogPin(PD_PIN);
    if(idx_s == 0){
      V_extreme[0] = V_sweep[idx_s];
      V_extreme[1] = V_sweep[idx_s];
      Signal_extreme[0] = Rx_Signal[idx_s];
      Signal_extreme[1] = Rx_Signal[idx_s];
    }
    else if(Rx_Signal[idx_s] > Signal_extreme[0]){
      V_extreme[0] = V_sweep[idx_s];
      Signal_extreme[0] = Rx_Signal[idx_s];
    }
    else if(Rx_Signal[idx_s] < Signal_extreme[1]){
      V_extreme[1] = V_sweep[idx_s];
      Signal_extreme[1] = Rx_Signal[idx_s];
    }

    S_new = DueAdcF -> ReadAnalogPin(PD_PIN);
    // Serial.println(S_new);
    // Serial.print(S_new);
    // Serial.print(" ");
    S = S_new;

    // Estimate gradient
    for(idx = 0; idx < N_DOFs; idx++){
      V_0 = V[idx];
      S_0 = DueAdcF -> ReadAnalogPin(PD_PIN);

      // direction_tmp = (Slope[idx] >= 0) ? 1 : -1;
      direction_tmp = 1;
      V_1 = sqrt(sq(V_0) + direction_tmp * Slope_step[idx]);
      DAC_OUT = int(V_1 / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);
      S_1 = DueAdcF -> ReadAnalogPin(PD_PIN);
      delayMicroseconds(10);

      DAC_OUT = int(V_0 / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
      dac -> sync(1);
      delayMicroseconds(Sweep_Delay_us);

      Slope[idx] = float(S_1 - S_0) / (sq(V_1) - sq(V_0));
      // V[idx] = sqrt(abs(sq(V[idx]) + Direction[idx] * Slope[idx] * step[idx]));
      V[idx] = sq(V[idx]) + Direction[idx] * Slope[idx] * step[idx];
      if(V[idx] < sq(V_MIN[idx])) V[idx] = sq(V_MIN[idx]);
      if(V[idx] > sq(V_MAX[idx])) V[idx] = sq(V_MAX[idx]);
      V[idx] = sqrt(V[idx]);

      // Serial.print(V[idx]);
      // Serial.print(" ");
    }
    // Serial.print("\n");

    // Update V
    for(idx = 0; idx < N_DOFs; idx++){
      DAC_OUT = int(V[idx] / DAC_RANGE[idx] * OUT_MAX);
      dac -> set_out(DAC_PIN[idx], DAC_OUT);
    }
    dac -> sync(1);
    delayMicroseconds(Sweep_Delay_us);
  }

  // Look for the medium value
  int ref_med = (Signal_extreme[0] + Signal_extreme[1]) / 2;
  int dev_med = 0;
  for(int idx_s = 0; idx_s < N_sweep; idx_s++){
    if((V_sweep[idx_s] > V_extreme[0]) && (V_sweep[idx_s] > V_extreme[1])) break;
    if((idx_s == 0) || (abs(Rx_Signal[idx_s] - ref_med) < dev_med)){
      V_extreme[2] = V_sweep[idx_s];
      Signal_extreme[2] = Rx_Signal[idx_s];
      dev_med = abs(Rx_Signal[idx_s] - ref_med);
    }
  }
  #pragma endregion

  dac -> set_out(DAC_PINs, 0);
  for(idx = 0; idx < N_DOFs; idx++) dac -> set_out(DAC_PIN[idx], int(V_init[idx] / DAC_RANGE[idx] * OUT_MAX));
  dac -> sync(1);
}

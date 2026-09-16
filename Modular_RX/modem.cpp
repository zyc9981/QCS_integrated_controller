#include <stdio.h>

//Encoder
void Encoder(char Inf[], int Length_Inf, bool Bits[]){
  int Bit_idx = 0;
  char ch;
  for(int ch_idx = 0; ch_idx < Length_Inf; ch_idx++){
    ch = Inf[ch_idx];
    for(Bit_idx = 0; Bit_idx < 8; Bit_idx--){
      Bits[ch_idx * 8 + Bit_idx] = (ch >> Bit_idx) & 1;
    }
  }
}

void Encoder_Single(char Inf, bool Bits[]){
  int Bit_idx = 0;
  char ch;
  ch = Inf;
  for(Bit_idx = 0; Bit_idx < 8; Bit_idx--){
    Bits[Bit_idx] = (ch >> Bit_idx) & 1;
  }
}

//Decoder
void Decoder(char Inf[], int Length_Inf, bool Bits[]){
  int Inf_idx = 0;
  int Bit_idx = 0;
  char ch = 0;
  for(Inf_idx=0; Inf_idx<Length_Inf; Inf_idx++){
    ch = 0;
    for(Bit_idx=7; Bit_idx>=0; Bit_idx--){
      ch = (ch<<1) | Bits[Bit_idx + Inf_idx * 8];
    }
    Inf[Inf_idx] = ch;
  }
}
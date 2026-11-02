// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#pragma once
#include <algorithm>
#include <cmath>
#include <stdexcept>

inline double rc_advance(double voltage,double source,double seconds,double resistance,double capacitance){
    if(!std::isfinite(voltage) || !std::isfinite(source) || !std::isfinite(seconds) || seconds<0 || !std::isfinite(resistance) || !std::isfinite(capacitance) || !(resistance>0) || !(capacitance>0))throw std::invalid_argument("SPICE_MODEL_INPUT");
    return voltage+(source-voltage)*(-std::expm1(-seconds/(resistance*capacitance)));
}
inline unsigned reference_adc(double voltage,unsigned bits){
    if(!std::isfinite(voltage) || bits<2 || bits>16)throw std::invalid_argument("SPICE_MODEL_INPUT");
    return unsigned(std::lround(std::clamp(voltage/3.3,0.0,1.0)*double((1u<<bits)-1)));
}
inline bool next_drive(bool previous,bool resetn,bool enable,unsigned adc,unsigned low,unsigned high){
    if(low>=high)throw std::invalid_argument("SPICE_MODEL_INPUT");
    if(!resetn || !enable)return false;
    if(adc<=low)return true;
    if(adc>=high)return false;
    return previous;
}

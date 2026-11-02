// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
#include "reference.hpp"
#include <algorithm>

FirResult FirReference::accept(int sample){
    const int limit=1<<(width_-1);
    if(sample < -limit || sample>=limit)throw std::invalid_argument("sample outside signed width");
    const std::array<int,3> samples={sample,past_[0],past_[1]};
    const std::array<int,3> coefficients={3,faulty_?2:-2,1};
    std::int64_t sum=0;
    for(unsigned i=0;i<samples.size();i++)sum+=std::int64_t(samples[i])*coefficients[i];
    // Divide/remainder specification, independent of the RTL's widened shifts.
    std::int64_t q=sum/4;
    const std::int64_t remainder=sum%4;
    if(remainder>=2)q++;
    if(remainder<=-2)q--;
    FirResult result{int(std::clamp(q,std::int64_t(-limit),std::int64_t(limit-1))),sum,q>=limit,q < -limit,past_[0]!=0 || past_[1]!=0};
    past_[1]=past_[0];past_[0]=sample;
    return result;
}

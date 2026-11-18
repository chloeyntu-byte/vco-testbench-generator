; Preserve explicit family coordinates (not inferred signal-name sidebands).
procedure(tbgenEmitWave(out analysisName signalName wave coordinates)
 let((xx yy vv xv)
  cond(
   (numberp(wave)
    fprintf(out "RAW\t%L\t%s\t0\t%.17g\t%.17g\n" analysisName signalName real(wave)*1.0 imag(wave)*1.0))
   (drIsWaveform(wave)
    xx=drGetWaveformXVec(wave) yy=drGetWaveformYVec(wave)
    for(index 0 min(2 drVectorLength(xx)-1)
     vv=drGetElem(yy index) xv=drGetElem(xx index)
     when(numberp(vv) && numberp(xv)
      fprintf(out "FAMILY_RAW\t%L\t%s\t%L\t%.17g\t%.17g\t%.17g\n"
       analysisName signalName coordinates xv real(vv) imag(vv)))))
   (famIsFamily(wave)
    foreach(coordinate famGetSweepValues(wave)
     tbgenEmitWave(out analysisName signalName famValue(wave coordinate)
      append(coordinates list(list(famGetSweepName(wave) coordinate))))))
 ))
)

; Required expression waves export all actual samples, units and family coordinates.
procedure(tbgenEmitOutput(out outputName wave coordinates)
 let((xx yy vv xv)
  cond(
   (numberp(wave)
    fprintf(out "SCALAR_SAMPLE\t%s\t%.17g\t%.17g\n" outputName real(wave)*1.0 imag(wave)*1.0))
   (drIsWaveform(wave)
    xx=drGetWaveformXVec(wave) yy=drGetWaveformYVec(wave)
    fprintf(out "WAVE_META\t%s\t%L\t%L\t%L\n" outputName coordinates xx->units yy->units)
    for(index 0 drVectorLength(xx)-1
     vv=drGetElem(yy index) xv=drGetElem(xx index)
     fprintf(out "WAVE_SAMPLE\t%s\t%.17g\t%.17g\t%.17g\n" outputName xv real(vv) imag(vv))))
   (famIsFamily(wave)
    foreach(coordinate famGetSweepValues(wave)
     tbgenEmitOutput(out outputName famValue(wave coordinate)
      append(coordinates list(list(famGetSweepName(wave) coordinate)))))))))

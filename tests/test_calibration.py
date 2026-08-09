from scalp.calibration import score_calibration

def test_calibration_marks_small_sample_uncalibrated():
    r=score_calibration([{"setup_quality":88,"net_pnl":1,"r_multiple":1.2}])
    assert next(iter(r.values()))["calibrated"] is False

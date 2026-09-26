import numpy as np



from odin_pi.tag_lines import format_pilot_line, pilot_line_from_detection, quadrilateral_area_px





def test_square_corners_area_100():

    corners = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], dtype=float)

    assert quadrilateral_area_px(corners) == 100





def test_miss_formats_pilot_follow_zeros():

    assert format_pilot_line("FOLLOW", False, 999, 888, 1234) == "PILOT FOLLOW 0 0 0"

    assert pilot_line_from_detection("FOLLOW", False, 0, 0, None) == "PILOT FOLLOW 0 0 0"



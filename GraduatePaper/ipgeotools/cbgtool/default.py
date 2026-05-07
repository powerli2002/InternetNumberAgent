"""All the reference paths to storing files settings and constants"""

import os
from pathlib import Path

# Default path
DEFAULT_DIR: Path = Path(__file__).resolve().parent

##################################################################################################
# CONSTANTS                                                                                      #
##################################################################################################
THRESHOLD_DISTANCES = [0, 40, 100, 500, 1000]
SPEED_OF_LIGHT = 300000
SPEED_OF_INTERNET = SPEED_OF_LIGHT * 2 / 3


##################################################################################################
# USER DATASET FILES (generated)                                                                 #
##################################################################################################
USER_PATH: Path = DEFAULT_DIR / "data/"
USER_FORMAT_PATH: Path = USER_PATH / "format/"
USER_GENERATED_PATH: Path = USER_PATH / "generated/"

USER_ANCHORS_FILE: Path = USER_FORMAT_PATH / "user_anchors.json"
USER_PROBES_FILE: Path = USER_FORMAT_PATH / "user_probes.json"
USER_PROBES_AND_ANCHORS_FILE: Path = USER_FORMAT_PATH / "user_probes_and_anchors.json"

USER_PAIRWISE_DISTANCE_FILE: Path = (
    USER_GENERATED_PATH / "user_pairwise_distance_ripe_probes.json"
)
USER_REMOVED_PROBES_FILE: Path = USER_GENERATED_PATH / "user_removed_probes.json"
USER_FILTERED_PROBES_FILE: Path = USER_GENERATED_PATH / "user_filtered_probes.json"
USER_GREEDY_PROBES_FILE: Path = USER_GENERATED_PATH / "user_greedy_probes.json"
USER_HITLIST_FILE: Path = USER_GENERATED_PATH / "user_parsed_hitlist.json"

PROBES_TO_ANCHORS_PING_TABLE : Path = USER_FORMAT_PATH / "ping_to_anchors.csv"


##################################################################################################
# ANALYSIS RESULTS FILES                                                                         #
##################################################################################################

# FROM USER MEASUREMENTS
USER_ANALYSIS_PATH: Path = DEFAULT_DIR / "analysis/results/user/"

USER_PROBES_TO_ANCHORS_RESULT_FILE: Path = (
    USER_ANALYSIS_PATH / "cbg_thresholds_probes_to_anchors.json"
)
USER_VP_SELECTION_ALGORITHM_PROBES_1_FILE: Path = (
    USER_ANALYSIS_PATH / "vp_selection_algorithm_probes_1.json"
)
USER_VP_SELECTION_ALGORITHM_PROBES_3_FILE: Path = (
    USER_ANALYSIS_PATH / "vp_selection_algorithm_probes_3.json"
)
USER_VP_SELECTION_ALGORITHM_PROBES_10_FILE: Path = (
    USER_ANALYSIS_PATH / "vp_selection_algoxrithm_probes_10.json"
)
USER_ACCURACY_VS_N_VPS_PROBES_FILE: Path = (
    USER_ANALYSIS_PATH / "accuracy_vs_n_vps_probes.json"
)
USER_ROUND_BASED_ALGORITHM_FILE: Path = (
    USER_ANALYSIS_PATH / "round_based_algorithm_error_cdf.json"
)


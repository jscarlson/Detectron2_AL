from detectron2.config.defaults import _C
from detectron2.config.config import CfgNode as CN

# ---------------------------------------------------------------------------- #
# Additional Configuration for Active Learning
# ---------------------------------------------------------------------------- #

_C.AL = CN()
_C.AL.MODE = 'object' # {'image', 'object'}
# Perform active learning on whether image-level or object-level 
_C.AL.OBJECT_SCORING = '1vs2' # {'1vs2, 'least_confidence', 'jitter'}
# The method to compute the individual object scores  
_C.AL.IMAGE_SCORE_AGGREGATION = 'avg' # {'avg', 'max', 'sum'}
# The method to aggregate the individual object scores to the whole image score 

_C.AL.DATASET = CN()
# Specifies the configs for creating new datasets 
# It will also combines configs from DATASETS and DATALOADER 
# when creating the DynamicDataset for training.
_C.AL.DATASET.NAME = ''
_C.AL.DATASET.IMG_ROOT = ''
_C.AL.DATASET.ANNO_PATH = ''
# Extra meta information for the dataset, only supports COCO Dataset
# This is somehow ugly, and shall be updated in the future.
_C.AL.DATASET.CACHE_DIR = 'al_datasets'
# The created dataset will be saved in during the active learning 
# training process 
_C.AL.DATASET.NAME_PREFIX = 'r'
# The created dataset will be named as '{NAME}-{NAME_PREFIX}{idx}' in the 
# Detectron2 system
_C.AL.DATASET.BUDGET_STYLE = 'object' # {'image', 'object'}
# Depericated. Now the budget style is the same as AL.MODE
_C.AL.DATASET.IMAGE_BUDGET = 20
_C.AL.DATASET.OBJECT_BUDGET = 2000
# Specifies the way to calculate the budget 
# If specify the BUDGET_STYLE as image, while using the object-level
# Active Learning, we will convert the image_budget to object budget 
# by OBJECT_BUDGET = IMAGE_BUDGET * AVG_OBJ_IN_TRAINING. 
# Similarly, we have 
# IMAGE_BUDGET = OBJECT_BUDGET // AVG_OBJ_IN_TRAINING.
_C.AL.DATASET.BUDGET_ALLOCATION = 'linear'
_C.AL.DATASET.SAMPLE_METHOD = 'top' # {'top', 'kmeans'}
# The method to sample images when labeling 

_C.AL.OBJECT_FUSION = CN()
# Specifies the configs to fuse model prediction and ground-truth (gt)
_C.AL.OBJECT_FUSION.OVERLAPPING_METRIC = 'iou' # {'iou', 'dice_coefficient', 'overlap_coefficient'}
# The function to calculate the overlapping between model pred and gt
_C.AL.OBJECT_FUSION.OVERLAPPING_TH = 0.25 # Optional
# The threshold for selecting the boxes 
_C.AL.OBJECT_FUSION.SELECTION_METHOD = 'top' # {'top', 'above', 'nonzero'}
# For gt boxes with non-zero overlapping with the pred box, specify the 
# way to choose the gt boxes. 
# top: choose the one with the highest overlapping
# above: choose the ones has the overlapping above the threshold specified above
# nonzero: choose the gt boxes with non-zero overlapping
_C.AL.OBJECT_FUSION.REMOVE_DUPLICATES = True
_C.AL.OBJECT_FUSION.REMOVE_DUPLICATES_TH = 0.15
# For the fused dataset, remove duplicated boxes with overlapping more than 
# the given threshold
_C.AL.OBJECT_FUSION.RECOVER_MISSING_OBJECTS = True
# If true, we recover the mis-identified objects during the process
_C.AL.OBJECT_FUSION.INITIAL_RATIO = 0.85
_C.AL.OBJECT_FUSION.LAST_RATIO = 0.25
_C.AL.OBJECT_FUSION.DECAY = 'linear'

_C.AL.TRAINING = CN()
_C.AL.TRAINING.ROUNDS = 5 
# The number of rounds for performing AL dataset update
_C.AL.TRAINING.EPOCHS_PER_ROUND_INITIAL = 500
# The numbers of epochs for training during each round. 
# As Detectron2 does not support epochs natively, we will use the 
# following formula to convert the epochs to iterations after creating 
# the new dataset:
# iterations = total_imgs / batch_size * epochs_per_round
_C.AL.TRAINING.EPOCHS_PER_ROUND_DECAY = 'linear'
_C.AL.TRAINING.EPOCHS_PER_ROUND_LAST = 50
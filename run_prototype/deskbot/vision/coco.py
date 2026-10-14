"""The 80 COCO class names in model order (YOLO26 / Ultralytics), and the subset that matters on a desk.

Used to send detections between processes as small numbers (class index) instead of strings, and by the
benchmark to map COCO's own category ids (1..90, with gaps) to model indices.
"""

NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]
INDEX = {n: i for i, n in enumerate(NAMES)}

# COCO annotation category_id (1..90 with gaps) -> model index 0..79
COCO91_TO_80 = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 27, 28,
                31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55,
                56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 67, 70, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 84,
                85, 86, 87, 88, 89, 90]
CATEGORY_TO_INDEX = {cat: i for i, cat in enumerate(COCO91_TO_80)}

# Things the robot meets on a desk (the benchmark scores these classes)
DESK_CLASSES = ["person", "bottle", "wine glass", "cup", "bowl", "chair", "potted plant", "tv", "laptop",
                "mouse", "remote", "keyboard", "cell phone", "book", "clock", "vase", "scissors", "teddy bear"]


def index(label):
    return INDEX.get(label, -1)


def name(i):
    i = int(i)
    return NAMES[i] if 0 <= i < len(NAMES) else "object"

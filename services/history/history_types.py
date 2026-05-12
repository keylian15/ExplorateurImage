from enum import Enum, auto


class HistoryActionType(Enum):
    SELECT = auto()

    FOLDER_CHANGED = auto()

    RENAME_WORKSPACE = auto()

    MODIFY_METADATA = auto()

    PIN_IMAGE = auto()

    SEARCH = auto()

    MODIFY_MAP_PARAMS = auto()

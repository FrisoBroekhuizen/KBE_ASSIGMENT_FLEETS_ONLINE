# from _future_ import annotations

import os
from typing import List, Tuple, Optional

from parapy.core import Base, Input, Attribute, Part, child, action
from parapy.exchange import STEPWriter

from machine import *

maindir = os.path.dirname(__file__)

Location_A= ...
Location_B= ...

"""Module that sets up logging capabilities.

Sets up logging to communicate with user without having to resort to warnings.
"""

import logging
import sys

logger = logging.getLogger('morpy')

if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("[MOrPy] %(message)s"))
    logger.addHandler(_handler)
logger.propagate = False

logger.addHandler(logging.NullHandler())  # do not resort to warnings if logging is not set up

def print_info_msgs(verbose=True):
    """Function that allows user to enable or disable info messages from MOrPy."""
    logger.setLevel(logging.INFO if verbose else logging.WARNING)

print_info_msgs(True) # default is true, can be disabled manually by user.


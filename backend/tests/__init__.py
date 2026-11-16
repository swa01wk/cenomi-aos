"""Test package setup.

Tests publish packs themselves through the Console API. The app's default start-up sync auto-publishes the demo pack,
which leaves no publish request for those tests to approve, so it is off here unless a run sets it explicitly.
"""

import os

os.environ.setdefault("AOS_SYNC_PACK_ON_START", "0")

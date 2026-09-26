"""What the person observed, as opposed to what the watch measured.

Every other layer in this app is device data. This one is the only place the user
says anything, and it exists because the physiology alone cannot explain itself: the
watch can tell you your HRV fell eleven points and has no idea you were on a plane.
"""

from vitals.context.canonical import TAGS, Tag, tag_for
from vitals.context.store import day, set_note, set_tags, span

__all__ = ["TAGS", "Tag", "day", "set_note", "set_tags", "span", "tag_for"]

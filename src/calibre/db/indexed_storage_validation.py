#!/usr/bin/env python3
# License: GPLv3
"""Conservative filesystem validation for an Indexed metadata database.

Only Linux mountinfo is implemented. Unknown filesystems and other platforms
fail closed until platform-specific implementations and tests are available.
This does not access any configured ebook source roots.
"""
import os
import sys
from pathlib import Path

class UnverifiedIndexedStorage(RuntimeError):
    pass

NETWORK_TYPES = frozenset({
    'nfs', 'nfs4', 'cifs', 'smb3', 'smbfs', 'sshfs', 'fuse.sshfs',
    '9p', 'ceph', 'glusterfs', 'fuse.rclone', 'davfs', 'fuse.davfs',
})
LOCAL_TYPES = frozenset({
    'ext2', 'ext3', 'ext4', 'btrfs', 'xfs', 'zfs', 'f2fs', 'vfat',
    'exfat', 'ntfs', 'ntfs3', 'apfs', 'tmpfs',
})


def _unescape_mount(value):
    # mountinfo escapes whitespace and backslashes using octal sequences.
    import re
    return re.sub(r'\\([0-7]{3})', lambda m: chr(int(m.group(1), 8)), value)


def linux_filesystem_type(path, mountinfo_text):
    """Return the type of the deepest matching Linux mountpoint."""
    target = str(Path(path).resolve(strict=True))
    matches = []
    for line in mountinfo_text.splitlines():
        before, sep, after = line.partition(' - ')
        if not sep:
            continue
        fields, details = before.split(), after.split()
        if len(fields) < 5 or len(details) < 1:
            continue
        mountpoint = _unescape_mount(fields[4])
        try:
            if os.path.commonpath((target, mountpoint)) == mountpoint:
                matches.append((len(mountpoint), details[0]))
        except ValueError:
            continue
    if not matches:
        raise UnverifiedIndexedStorage('Cannot identify filesystem mount')
    return max(matches, key=lambda item: item[0])[1].lower()


def require_local_indexed_storage(library_directory, *, platform=None, mountinfo_text=None):
    """Refuse network or unverified database storage.

    Linux checks the directory's actual mount; macOS/Windows remain blocked
    pending native filesystem checks. This is intentionally fail-closed.
    """
    directory = Path(library_directory)
    if not directory.is_dir():
        raise FileNotFoundError(directory)
    platform = sys.platform if platform is None else platform
    if platform != 'linux':
        raise UnverifiedIndexedStorage('Local filesystem verification is not implemented for this platform')
    if mountinfo_text is None:
        try:
            mountinfo_text = Path('/proc/self/mountinfo').read_text(encoding='utf-8')
        except OSError as err:
            raise UnverifiedIndexedStorage('Cannot inspect Linux mount information') from err
    fs_type = linux_filesystem_type(directory, mountinfo_text)
    if fs_type in NETWORK_TYPES or fs_type.startswith(('fuse.', 'nfs', 'cifs', 'smb')):
        raise UnverifiedIndexedStorage(f'Network filesystem is not allowed for Indexed database: {fs_type}')
    if fs_type not in LOCAL_TYPES:
        raise UnverifiedIndexedStorage(f'Filesystem locality is not verified: {fs_type}')
    return fs_type

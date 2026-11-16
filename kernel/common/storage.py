"""Copy persistent disks without sharing future writes or expanding sparse holes."""
import subprocess
import sys


def clone_disk(source, target):
    """Use APFS cloning when possible, otherwise preserve zero regions as holes."""
    if sys.platform == 'darwin':
        result = subprocess.run(['/bin/cp', '-c', str(source), str(target)], capture_output=True)
        if result.returncode == 0:
            return
    with source.open('rb') as reader, target.open('wb') as writer:
        while chunk := reader.read(1024 * 1024):
            if chunk.strip(b'\0'):
                writer.write(chunk)
            else:
                writer.seek(len(chunk), 1)
        writer.truncate(reader.tell())

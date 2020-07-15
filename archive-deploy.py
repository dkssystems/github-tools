#!/usr/bin/env python3
import sys, os, io
import zipfile, posixpath, shutil
import argparse
import pathspec
import zlib

parser = argparse.ArgumentParser()

parser.add_argument('--archive', action='store', dest='archive', required=True, help='Archive file')
parser.add_argument('--remote', action='store', dest='remote_root', required=True, help='Remote root folder')
parser.add_argument('--artifacts', action='store', dest='artifacts_root', required=False, help='Artifacts (backup) root folder')
parser.add_argument('--dry-run', action='store_true', dest='dry_run', default=False, help='Output only (no changes)')

args = parser.parse_args()

def crc32(filename):
    if not os.path.exists(filename):
        return -1

    fh = open(filename, 'rb')
    hash = 0
    while True:
        s = fh.read(65536)
        if not s:
            break
        hash = zlib.crc32(s, hash)
    fh.close()
    return (hash & 0xFFFFFFFF)

def file_ignored(file):
    if ignore is None:
        return False

    return ignore.match_file(file)

def read_list(zip, filename, default = []):
    try:
        with zip.open(filename, 'r') as file:
            return [line.decode('utf-8').rstrip('\n') for line in file.readlines()]
    except KeyError:
        return default

def walk_error(err):
    print (err)
    exit(1)

def copy_zip_file(zip, archive_info, archive_path, remote_path):
    print ('DEPLOYING ' + archive_path)
    print (" --> " + remote_path)

    if not args.dry_run:
        remote_dir = os.path.dirname(remote_path)
        if not os.path.exists(remote_dir):
            os.makedirs(remote_dir)

        # We can't use ZipFile.extract because it preserves the archive path
        source = zip.open(posixpath.join('copies', archive_path))
        target = open(remote_path, "wb")
        with source, target:
            shutil.copyfileobj(source, target)

        # It also doesn't set file permissions - handle execute bit on Unix
        if os.name == 'posix':
            if info.create_system == 3 and os.path.isfile(remote_path): # 3 is Unix
                unix_attributes = archive_info.external_attr >> 16
                if unix_attributes & S_IXUSR:
                    os.chmod(remote_path, os.stat(remote_path).st_mode | S_IXUSR)

def artifact_file(from_path, to_path):
    print ('ARTIFACT ' + from_path)
    print (" --> " + to_path)

    if not args.dry_run:
        to_dir = os.path.dirname(to_path)
        if not os.path.exists(to_dir):
            os.makedirs(to_dir)

        shutil.move(from_path, to_path)

print ("READING ARCHIVE")

with zipfile.ZipFile(args.archive) as zip:
    if zip.testzip() is not None:
        print ('ERROR: archive failed CRC test')
        exit()

    # Read ignores
    ignore = None
    ignores = read_list(zip, '.pushignore', None)
    if ignores is not None:
        ignore = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, ignores)
            
    # Read through remote files and check for differences
    print ("WALKING DIRECTORY")

    # Create hash of files in archive. Files will be removed which match a remote file.
    archive_hash = {}
    for archive_path in read_list(zip, 'copies.txt'):
        archive_hash[archive_path] = None

    remotes = []

    remote_root = args.remote_root.replace('\\', '/').strip().rstrip('/').replace(posixpath.sep, os.sep)
    artifacts_root = (args.artifacts_root or '/deployment-artifacts').replace('\\', '/').strip().rstrip('/').replace(posixpath.sep, os.sep)

    if not os.path.exists(remote_root):
        os.makedirs(remote_root)

    for remote_parent, child_dirs, child_files in os.walk(remote_root, onerror=walk_error):
        rel_parent = str(remote_parent[(len(remote_root)+1)::])
        archive_parent = rel_parent.replace(os.sep, posixpath.sep) # Turn remote to archive parent
        artifacts_parent = os.path.join(artifacts_root, rel_parent)
        
        # Directories
        for child_dir in child_dirs:
            archive_child_path = posixpath.join(archive_parent, child_dir)
            
            # Check if directory should be ignored
            if file_ignored(archive_child_path + posixpath.sep):
                child_dirs.remove(child_dir)

        # Files
        for child_file in child_files:
            archive_child_path = posixpath.join(archive_parent, child_file)
            remote_child_path = os.path.join(remote_parent, child_file)
            artifacts_child_path = os.path.join(artifacts_parent, child_file)

            # Check if file should be ignored
            if file_ignored(archive_child_path):
                continue

            if archive_child_path in archive_hash:
                # File should exist
                archive_info = zip.getinfo(posixpath.join('copies', archive_child_path))
                remote_info = None
                if os.path.exists(remote_child_path):
                    remote_info = os.stat(remote_child_path)

                changed = False

                # First check for file size difference
                if remote_info is None or remote_info.st_size != archive_info.file_size:
                    changed = True
                
                # Then check for hash difference
                if not changed:
                    remote_crc = crc32(remote_child_path)
                    if archive_info.CRC != remote_crc:
                        changed = True

                if changed:
                    # File should be deployed
                    artifact_file(remote_child_path, artifacts_child_path)
                    copy_zip_file(zip, archive_info, archive_child_path, remote_child_path)

                del archive_hash[archive_child_path]
            else:
                # File should not exist
                artifact_file(remote_child_path, artifacts_child_path)
    
    print ('NEW FILES')
    # Files remaining in hash are new
    for archive_path in archive_hash.keys():
        archive_info = zip.getinfo(posixpath.join('copies', archive_path))
        remote_path = os.path.join(remote_root, archive_path.replace(posixpath.sep, os.sep)) # Turn archive to remote parent
        copy_zip_file(zip, archive_info, archive_path, remote_path)

print ("DONE")
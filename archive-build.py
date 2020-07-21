import sys, os
import zipfile, posixpath
import argparse
import pathspec

parser = argparse.ArgumentParser()

parser.add_argument('--archive', action='store', dest='archive', required=True, help='Filename of archive created')
parser.add_argument('--local', action='store', dest='local_root', required=True, help='Local root folder')
parser.add_argument('--dry-run', action='store_true', dest='dry_run', default=False, help='Output only (no changes)')
parser.add_argument('--quiet', action='store_true', dest='quiet', default=False, help='Do not list individual files')

args = parser.parse_args()

if not os.path.exists(args.local_root):
    os.makedirs(args.local_root)

ignore = None
ignore_filename = os.path.join(args.local_root, '.pushignore')
if os.path.exists(ignore_filename):
    with open(ignore_filename) as ignore_file:
        ignore = pathspec.PathSpec.from_lines(pathspec.patterns.GitWildMatchPattern, ignore_file.readlines())

def apply_ignores(list):
    if ignore is None:
        return list
    
    for item in list:
        file = item['archive_path']
        if ignore.match_file(file):
            print(file)
        else:
            yield item

def walk_error(err):
    print (err)
    exit(1)

# Check every item and build copy list
print ("WALKING DIRECTORY")
copies = []

local_root = args.local_root.replace('\\', '/').strip().rstrip('/')

for local_parent, child_dirs, child_files in os.walk(local_root, onerror=walk_error):
    if '.git' in child_dirs:
        child_dirs.remove('.git') # ignore .git directories
    if '.github' in child_dirs:
        child_dirs.remove('.github') # ignore .github directories
        
    archive_parent = str(local_parent[(len(local_root)+1)::].replace(os.sep, posixpath.sep)) # Turn local to archive parent
    for child_file in child_files:
        local_child_path = os.path.join(local_parent, child_file)
        archive_child_path = posixpath.join(archive_parent, child_file)
        copies.append({'local_path': local_child_path, 'archive_path': archive_child_path})

# Apply .pushignore
if not ignore is None:
    print ("APPLYING .PUSHIGNORE RULES")
    copies = list(apply_ignores(copies))

if not args.dry_run:
    with zipfile.ZipFile(args.archive, 'w') as zip:
        # Push ignore
        if not ignore is None:
            zip.write(ignore_filename, '.pushignore')

        # Perform copies
        print ("COPY LIST")

        copies_meta = []
        for copy in copies:
            if not args.quiet:
                print (copy['local_path'])
                print (" --> " + copy['archive_path'])
            copies_meta.append(copy['archive_path'])
            zip.write(copy['local_path'], posixpath.join('copies', copy['archive_path']))
        
        zip.writestr('copies.txt', '\n'.join(copies_meta))

print ("DONE")
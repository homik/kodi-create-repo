from lxml import etree
import click
import datetime
import git
import json
import shutil
import os
import hashlib
import urllib
import collections
import io

plugins_dir = 'plugins'
build_dir = 'build'
build_plugins_dir = os.path.join(build_dir, 'Plugins')
build_repo_dir = os.path.join(build_dir, 'Repository')

config = json.load(open('config.json'))
host_url = config['host_url']
plugins_info = config['plugins']
repo_info = config['repository']

repo_name_with_version = '%s-%s' % (repo_info['id'], repo_info['version'])
build_repo_final_dir = os.path.join(build_repo_dir, repo_name_with_version)

def generate_checksum(archive_path):
    checksum_path = '{}.md5'.format(archive_path) 
    checksum_dirname = os.path.dirname(checksum_path)
    archive_relpath = os.path.relpath(archive_path, checksum_dirname)

    checksum = hashlib.md5()
    with open(archive_path, 'rb') as archive_contents:
        for chunk in iter(lambda: archive_contents.read(2 ** 12), b''):
            checksum.update(chunk)
    digest = checksum.hexdigest()

    binary_marker = '*'
    # Force a UNIX line ending, like the md5sum utility.
    with io.open(checksum_path, 'w', newline='\n') as sig:
        sig.write(u'{} {}{}\n'.format(digest, binary_marker, archive_relpath))
    return checksum_path

def init():
    if not os.path.isdir(plugins_dir):
        os.mkdir(plugins_dir)

    if not os.path.isdir(build_dir):
        os.mkdir(build_dir)

    if not os.path.isdir(build_plugins_dir):
        os.mkdir(build_plugins_dir)

    if not os.path.isdir(build_repo_dir):
        os.mkdir(build_repo_dir)

    if not os.path.isdir(build_repo_final_dir):
        os.mkdir(build_repo_final_dir)


def build_plugins():
    addons_xml_file = os.path.join(build_plugins_dir, 'addons.xml')
    existing_addons = {}

    if os.path.isfile(addons_xml_file):
        addons_xml_root = etree.parse(addons_xml_file).getroot()

        existing_addons = {a.attrib['id']: a.attrib['version'] for a in addons_xml_root.findall('addon')}
    else:
        addons_xml_root = etree.Element('addons')

    for plugin_info in plugins_info:
        name = plugin_info['name']
        github_url = plugin_info['github_url']
        version = plugin_info.get('version', None)

        repo_dir = os.path.join(plugins_dir, name)
        if not os.path.isdir(repo_dir):
            repo = git.Repo.clone_from(github_url, repo_dir)
        else:
            repo = git.Repo(repo_dir)

        repo.remote().fetch()
        repo.head.reset(index=True, working_tree=True)

        if not version:
            version = repo.tags[-1].name

        repo.git.checkout('tags/%s' % version)

        if version.startswith('v'):
            version = version[1:]

        name_with_version = '%s-%s' % (name, version)
        print name_with_version

        include_addon = True

        existing_addon_info = addons_xml_root.find("addon[@id='%s']" % name)
        if existing_addon_info is not None:
            v = dict(existing_addon_info.items())['version']
            _name_with_version = '%s-%s' % (name, v)

            if name_with_version == _name_with_version:
                include_addon = False
            else:
                addons_xml_root.remove(existing_addon_info)
                _build_repo_path = os.path.join(build_plugins_dir, _name_with_version)
                if os.path.isdir(_build_repo_path):
                    shutil.rmtree(_build_repo_path)

        if include_addon:
            build_repo_path = os.path.join(build_plugins_dir, name_with_version)

            shutil.copytree(repo_dir, build_repo_path, ignore=shutil.ignore_patterns('.git*'))

            zip_file = shutil.make_archive(build_repo_path, 'zip', build_plugins_dir, name_with_version)
            md5_file = generate_checksum(zip_file)
            shutil.move(zip_file, build_repo_path)
            shutil.move(md5_file, build_repo_path)

            plugin_addon_xml = etree.parse(open(os.path.join(build_repo_path, 'addon.xml')))
            addons_xml_root.append(plugin_addon_xml.getroot())

            for f in os.listdir(build_repo_path):
                if f.startswith('changelog.') or f.startswith('fanart.') or f.startswith('icon.') or f.endswith('.zip') or f.endswith('.md5'):
                    pass
                else:
                    _f = os.path.join(build_repo_path, f)
                    if os.path.isdir(_f):
                        shutil.rmtree(_f)
                    else:
                        os.remove(_f)

            shutil.move(os.path.join(build_repo_path, 'changelog.txt'), os.path.join(build_repo_path, 'changelog-%s.txt' % version))

            dst = os.path.join(build_plugins_dir, name)
            if os.path.isdir(dst):
                for f in os.listdir(build_repo_path):
                    s = os.path.join(build_repo_path, f)
                    d = os.path.join(dst, f)
                    if os.path.isfile(d):
                        os.remove(d)
                    shutil.move(s, d)
                shutil.rmtree(build_repo_path)
            else:
                shutil.move(build_repo_path, os.path.join(build_plugins_dir, name))

    xml_str = etree.tostring(addons_xml_root, pretty_print=True)

    f = open(os.path.join(build_plugins_dir, 'addons.xml'), 'w')
    f.write(xml_str)
    f.close()

    m = hashlib.md5()
    m.update(xml_str)

    f = open(os.path.join(build_plugins_dir, 'addons.xml.md5'), 'w')
    f.write(m.hexdigest())
    f.close()


def build_repo():
    icon_file = repo_info['icon']
    if os.path.isfile(icon_file):
        shutil.copyfile(icon_file, os.path.join(build_repo_final_dir, 'icon.png'))
    elif icon_file.startswith('http://') or icon_file.startswith('https://'):
        urllib.urlretrieve(icon_file, os.path.join(build_repo_final_dir, 'icon.png'))

    attrib = collections.OrderedDict()
    for k in ('id', 'name', 'version', 'provider-name'):
        attrib.update([(k, repo_info[k])])

    addon_xml_root = etree.Element('addon', attrib=attrib)

    requires_node = etree.Element('requires')
    addon_xml_root.append(requires_node)

    etree.SubElement(requires_node, 'import', attrib=collections.OrderedDict([('addon', 'xbmc.addon'), ('version', '12.0.0')]))

    extension_node = etree.SubElement(
        addon_xml_root,
        'extension',
        attrib=collections.OrderedDict([('point', 'xbmc.addon.repository'), ('name', repo_info['name'])])
    )

    etree.SubElement(extension_node, 'info', attrib={'compressed': 'true'}).text = '%s/Plugins/addons.xml' % host_url
    etree.SubElement(extension_node, 'checksum').text = '%s/Plugins/addons.xml.md5' % host_url
    etree.SubElement(extension_node, 'datadir', attrib={'zip': 'true'}).text = '%s/Plugins' % host_url
    etree.SubElement(extension_node, 'hashes').text = 'true'

    extension_node = etree.SubElement(addon_xml_root, 'extension', attrib={'point': 'xbmc.addon.metadata'})

    etree.SubElement(extension_node, 'summary').text = repo_info['summary']
    etree.SubElement(extension_node, 'description').text = repo_info['description']
    etree.SubElement(extension_node, 'platform').text = 'all'

    xml_str = etree.tostring(addon_xml_root, pretty_print=True, encoding='UTF-8', standalone=True)

    f = open(os.path.join(build_repo_final_dir, 'addon.xml'), 'w')
    f.write(xml_str)
    f.close()

    changelog = "[B]Version %s[/B]\n- Initial version" % repo_info['version']
    f = open(os.path.join(build_repo_final_dir, 'changelog.txt'), 'w')
    f.write(changelog)
    f.close()

    zip_file = os.path.join(build_repo_final_dir, '%s.zip' % repo_name_with_version)
    if os.path.isfile(zip_file):
        os.remove(zip_file)
    shutil.make_archive(build_repo_final_dir, 'zip', build_repo_dir, repo_name_with_version)
    shutil.move('%s.zip' % build_repo_final_dir, build_repo_final_dir)


def build_gh_pages(root, current_dir):
    cur_dir = os.path.join(root, current_dir)

    html_root = etree.Element('html')
    etree.SubElement(html_root, 'head')
    body = etree.SubElement(html_root, 'body')

    pth = os.path.relpath(cur_dir, root)
    if pth == '.':
        pth = ''

    index_path = os.path.join('/', pth)

    etree.SubElement(body, 'h1').text = 'Index of %s' % index_path
    etree.SubElement(body, 'hr')

    table = etree.SubElement(body, 'table', style='width: 50%; min-width: 800px;')

    tr = etree.SubElement(table, 'tr')
    td = etree.SubElement(tr, 'td')
    item = '.' if index_path == '/' else '../'
    etree.SubElement(td, 'a', href=item, style='width: 70%;').text = '../'
    etree.SubElement(tr, 'td')
    etree.SubElement(tr, 'td')

    dir_items = os.listdir(cur_dir)
    for item in dir_items:
        item_path = os.path.join(cur_dir, item)
        if os.path.isdir(item_path):
            tr = etree.SubElement(table, 'tr')
            td = etree.SubElement(tr, 'td')
            etree.SubElement(td, 'a', href=item).text = '%s/' % item
            etree.SubElement(tr, 'td').text = datetime.datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%d-%b-%Y %H:%M')
            etree.SubElement(tr, 'td').text = '-'

            build_gh_pages(root, os.path.join(current_dir, item))
        else:
            if item != 'index.html':
                tr = etree.SubElement(table, 'tr')
                td = etree.SubElement(tr, 'td')
                etree.SubElement(td, 'a', href=item).text = item
                etree.SubElement(tr, 'td').text = datetime.datetime.fromtimestamp(os.path.getmtime(item_path)).strftime('%d-%b-%Y %H:%M')
                etree.SubElement(tr, 'td').text = str(os.path.getsize(item_path))

    etree.SubElement(body, 'hr')

    html_str = etree.tostring(html_root, pretty_print=True)
    f = open(os.path.join(cur_dir, 'index.html'), 'w')
    f.write(html_str)
    f.close()


@click.command()
@click.option('--gh-pages', is_flag=True)
def run(gh_pages):
    init()
    build_plugins()
    build_repo()
    if gh_pages:
        build_gh_pages(os.path.abspath(build_dir), '')

if __name__ == "__main__":
    run()

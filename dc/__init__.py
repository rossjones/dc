"""
Package
"""
"""
Utility functions for  data harvesting

Commandline usage can fire API calls with an ID e.g. 

dc.py organization_purge hscic
"""
import ConfigParser
import hashlib
import json
import logging
import mimetypes
import time
import sys
import urllib

import ffs
from ffs.contrib import http
import ckanapi
from ckanapi.errors import ValidationError

inifile = ffs.Path('~/.dc.ini').abspath

CONF = ConfigParser.ConfigParser()
CONF.read(inifile)

ckan = ckanapi.RemoteCKAN(CONF.get('ckan', 'url'),  apikey=CONF.get('ckan', 'api_key'))

class Error(Exception): 
    def __init__(self, msg):
        Exception.__init__(self, '\n\n\n{0}\n\n\n'.format(msg))

class NHSEnglandNotFoundException(Error): pass

def tags(*tags):
    """
    Given a list of tags as positional arguments TAGS, return
    a list of dictionaries in the format that the CKAN API 
    wants!
    """
    return [{'name': t.replace("'", "") } for t in tags]

def fh_for_url(url):
    """
    Return a file-like-object for URL!
    """
    return http.HTTPPath(url).open()

def disk_fh_for_url(url):
    tmpfile = ffs.Path.newfile(url.split('/')[-1])
    print url, tmpfile
    tmpfile << urllib.urlopen(url).read()
    return open(tmpfile, 'r')

def filetype(url):
    tp, enc = mimetypes.guess_type(url)
    if not tp: return ''
    return tp.split('/')[-1]

def _org_existsp(name):
    orglist = ckan.action.organization_list()
    return name in orglist

def _group_existsp(name):
    grouplist = ckan.action.group_list()
    return name in grouplist
    
def ensure_publisher(name):
    """
    Ensure that the publisher NAME exists. 
    if not, attempt to create it from our settings file or COMPLAIN LOUDLY!
    """
    if _org_existsp(name):
        return # YAY
    if not CONF.has_section('publisher:'+name):
        what = 'Publisher "{0}" does not exist in the catalogue or inifile'.format(name)
        raise NHSEnglandNotFoundException(what)

    ckan.action.organization_create(
        name=CONF.get('publisher:'+name, 'name'),
        title=CONF.get('publisher:'+name, 'title'),
        description=CONF.get('publisher:'+name, 'description'),
        image_url= CONF.get('publisher:'+name, 'image_url')
    )
    return

def ensure_group(name):
    """
    Ensure that the group NAME exists. 
    if not, attempt to create it from our settings file or COMPLAIN LOUDLY!
    """
    name = name.lower()
    if _group_existsp(name):
        return # YAY
    if not CONF.has_section('group:'+name):
        what = 'Group "{0}" does not exist in the catalogue or inifile'.format(name)
        raise NHSEnglandNotFoundException(what)

    grp = dict(
        name=CONF.get('group:'+name, 'name'),
        title=CONF.get('group:'+name, 'title'),
        description=CONF.get('group:'+name, 'description'),
    )
    ckan.action.group_create(**grp)
    return


class Dataset(object):
    """
    Not really a class. 

    Namespaces are one honking...
    """
    @staticmethod
    def _no_srsly_create_or_update(**deets):        
        resources = deets.pop('resources')
        try:
            pkg =  ckan.action.package_show(id=deets['name'])
            pkg.update(deets)
            ckan.action.package_update(**pkg)
        except ckanapi.errors.NotFound:
            pkg = ckan.action.package_create(**deets)    
        
        logging.info(json.dumps(pkg, indent=2))
        for resource in resources:
            print resource['name']
            fh = resource['upload']
            contents = fh.read()
            size = fh.tell()
            
            # Reset the file pointer so ckanapi can read the whole file.
            fh.seek(0)
            checksum = hashlib.md5(contents).hexdigest()
            resource['hash'] = checksum
            resource['size'] = size

            resource['package_id'] = pkg['id']
            name = resource['name']
            existing = [r for r in pkg['resources'] if r['name'] == name]
            if not existing:
                print 'Creating resource'
                ckan.action.resource_create(**resource)
            else:
                existing = existing[0]
                if existing['hash'] == checksum:
                    print 'Unchanged'
                    continue # It's not updated
                print 'Updating resource'
                existing.update(resource)
                ckan.action.resource_update(**existing)
        return

    @staticmethod
    def create_or_update(**deets):
        try:
            Dataset._no_srsly_create_or_update(**deets)
        except ValidationError as verr:
            print "We got a validation error. Your data is dodgy."
            print verr
            raise            
        except ckanapi.errors.CKANAPIError as err:
            if '504 Gateway Time-out' in err.extra_msg:
                print "Got a gateway timeout from the CKANs. Let's give her a minute to cool off"
                print "Sleeping for 3secs"
                time.sleep(3)
                print "Here we go again! "
                Dataset._no_srsly_create_or_update(**deets)
            else:
                raise
        return

    @staticmethod
    def rename(oldname, newname):
        pkg = ckan.action.package_show(id=oldname)
        pkg['title'] = newname
        ckan.action.package_update(**pkg)
        return

    @staticmethod
    def tag(dataset, tag):
        oldtags = dataset['tags']
        if len([t for t in oldtags if t['name'] == tag]) < 1:
            dataset['tags'] = oldtags + tags(tag)
            ckan.action.package_update(**dataset)
        return
    
if __name__ == '__main__':
    getattr(ckan.action, sys.argv[-2])(id=sys.argv[-1])

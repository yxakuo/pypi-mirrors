#!/usr/bin/env python
import datetime
import socket
import urllib2
import os
import time
import json

try:
    import cPickle as pickle
except ImportError:
    import pickle

import redis
from pypimirrors import mirror_statuses
from jinja2 import Environment, PackageLoader

from config import load_config
from iploc import get_city

env = Environment(loader=PackageLoader('pypi_mirrors', 'templates'))
CONFIG = load_config()
ROOT = os.path.abspath(os.path.dirname(__file__))
# Used to absolute-ify relative paths
path = lambda x: os.path.abspath(os.path.join(ROOT, x))

# Add non-official mirrors here
UNOFFICIAL_MIRRORS = [
     'pypi.crate.io',
]

STATUSES = {'Green':'<span class="label label-success">Fresh</span>',
            'Yellow':'<span class="label label-warning">Oldish</span>',
            'Red':'<span class="label label-important">Old</span>'}


def find_status(status):
    """ Find the status give the status code"""
    return STATUSES.get(status, 'Unavailable')


def cache_key(token, value):
    """ build a cache key """
    return "{0}_{1}".format(token, value)


def get_connection():
    """ Get the connection to Redis"""
    return redis.StrictRedis(host=CONFIG.get('host'),
                          port=CONFIG.get('port'),
                          db=CONFIG.get('db'),
                          password=CONFIG.get('password'))


def ping_ip2loc(ip):
    """ get the location info for the ip
    you need to register for an API key here. http://ipinfodb.com/register.php
    
    and set it as an envirornment variable called
    PYPI_MIRRORS_API_KEY
    
    """
    api_key = os.getenv('PYPI_MIRRORS_API_KEY')
    if not api_key:
        return None
    return get_city(api_key, ip)


def get_location_for_mirror(mirror):
    """ get the location for the mirror """
    conn = get_connection()
    loc_key = cache_key('IPLOC', mirror)
    value = conn.get(loc_key)
    if value:
        return pickle.loads(value)

    ip = socket.gethostbyname(mirror)
    location = ping_ip2loc(ip)
    if location:
        #print(location)
        conn.setex(loc_key, 86400, pickle.dumps(location)) # 1 day cache
        return location
    # if we get here, no good, return None
    return None


def location_name(location):
    """ build out the location name given the location data """
    if not location:
        return "N/A"
    city = location.get('City', None)
    region = location.get('RegionName', None)
    country = location.get('CountryName', None)
    country_code = location.get('CountryCode', None) 

    # If we have everything return everything but only use country_code
    if city and region and country_code:
        return "{0}, {1} {2}".format(city, region, country_code)

    # if we just have country, then only return country
    if not city and not region and country:
        return country

    # whatever else we have build it out by dynamically
    name = ""
    if city:
        name += city
    if city and region:
        name += ", "
    if region:
        name += region + " "
    if country:
        name += country
    return name

def generate_page(results, time_now, format='html'):
    """ generate the page from the resutls """
    template = env.get_template('index.html')

    print template.render(date_now=time_now, data=results)

def process_results(results):
    """ process the results and gather data """

    conn = get_connection()
    new_results = []
    for d in results:
        mirror = d.get('mirror')
        resp_time = d.get('response_time')
        age = int(round(d.get('time_diff').total_seconds())) # need to round
        #print("resp: {0} ; age: {1}".format(resp_time, age))
        conn.rpush(cache_key('RESPTIME', mirror), resp_time )
        conn.rpush(cache_key('AGE', mirror), age)
        resp_list = conn.lrange(cache_key('RESPTIME', mirror), -240, 240)
        age_list = conn.lrange(cache_key('AGE', mirror), -240, 240)
        location = get_location_for_mirror(mirror)
        d['location'] = location_name(location)
        d['resp_list'] = ",".join(resp_list)
        d['age_list'] = ",".join(age_list)
        d['status'] = find_status(d.get('status', None))
        new_results.append(d)
    return new_results


def run():
    """ run everything """
    results = mirror_statuses(unofficial_mirrors=UNOFFICIAL_MIRRORS)
    if results:
        time_now = results[0].get('time_now', None)
    data = process_results(results)
    
    generate_page(data, time_now)


if __name__ == '__main__':
    run()

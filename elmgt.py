#!/usr/bin/env python

import argparse, pycurl, io, json, os

elastic_actions = { 
                   'nodes': '_cat/nodes', 
                   'shards': '_cat/shards', 
                   'indices': '_cat/indices',
                   'recovery': '_cat/recovery',
                   'health': '_cluster/health', 
                   'state': '_cluster/state', 
                   'stats': '_cluster/state', 
                   'drain': '_cluster/settings', 
                   'undrain': '_cluster/settings', 
                  }

parser = argparse.ArgumentParser(description='ELastic ManaGmenT')
parser.add_argument('-p', '--pretty', action='store_true',help='do ?v')
parser.add_argument('-o', '--host', help='host to query')
parser.add_argument('action', help='what we doin. must be any of {}'.format(elastic_actions.keys()))
parser.add_argument('target', nargs='?', help='host to target. for drain, host to drain, for state and stats host to gather from')

args=parser.parse_args()

DEFAULT_HOST='elk1.talpas.dev'
API_KEY = os.environ.get('ELASTIC_API_KEY') 
ACTION=args.action

AUGMENTS={
          'nodes': '?v&pretty', 
          'shards': '?v&pretty', 
          'indices': '?v&pretty',
          'recovery': '?v&pretty',
          'health': '?pretty', 
          'state': '?pretty', 
          'stats': '?pretty', 
          'drain': '', 
          'undrain': '', 
         }

if args.host:
    EL_HOST = args.host
else:
    EL_HOST = DEFAULT_HOST

if ACTION not in elastic_actions.keys():
    print ('action \'{}\' not a valid action'.format(ACTION))
else: 
    if args.pretty:
        AUGMENT=AUGMENTS[ACTION]
    else: 
        AUGMENT=''

    response = io.BytesIO()
    c = pycurl.Curl()

    if ACTION in ('drain', 'undrain'):
        if ACTION == 'undrain':
            args.target = ''
        data = json.dumps({ "persistent": { "cluster.routing.allocation.exclude._name": args.target } })
        c.setopt(pycurl.CUSTOMREQUEST, "PUT")
        c.setopt(pycurl.POSTFIELDS, data)

    c.setopt(pycurl.SSL_VERIFYPEER, 0)
    c.setopt(pycurl.SSL_VERIFYHOST, 0)
    c.setopt(c.HTTPHEADER, ['Content-Type: application/json', 'Authorization: ApiKey {}'.format(API_KEY)])
    c.setopt(c.URL, 'https://{}:9200/{}{}'.format(EL_HOST,elastic_actions[ACTION],AUGMENT))
    c.setopt(c.WRITEFUNCTION, response.write)

    c.perform()
    c.close()
    print(response.getvalue().decode())
    response.close()

